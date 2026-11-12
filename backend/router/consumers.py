"""Analysis streaming with durable outcomes and one owner per batch.

Authentication happens in-band so the token never appears in a URL or an
access log: after the socket opens, the client's first frame must be
`{"type": "auth", "token": "rr_…"}`. Until that token is valid and the batch
belongs to its user, nothing about the job is sent and the socket is not
subscribed to the batch's live updates. A missing, malformed or invalid auth
frame (or none within AUTH_TIMEOUT_SECONDS) closes the socket with 4401; a
batch that does not exist or belongs to someone else gets a `job_not_found`
error frame and close code 4404.
"""
import asyncio
import json
import logging
from uuid import UUID, uuid4

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from common.analysis_progress import progress_scope, progress_stage
from common.constant import build_variants
from common.errors import PipelineError, error_payload
from rag.rag_service import apply_retrieval_depth, engine_execution, rag_registry
from router.analysis import (
    HEARTBEAT_SECONDS, batch_snapshot, claim_batch, completion_frame,
    format_metrics, release_batch, renew_batch, result_frame, save_variant,
)
from router.models import AnalysisBatch
from workspace.auth import resolve_token

logger = logging.getLogger(__name__)
format_evaluation_metrics = format_metrics  # Historical import used by callers.
FOLLOW_INTERVAL_SECONDS = 1
AUTH_TIMEOUT_SECONDS = 10
CLOSE_UNAUTHENTICATED = 4401
CLOSE_NOT_FOUND = 4404
# Orchestration/heartbeats must not queue behind a long synchronous model call.
def db_call(function):
    return database_sync_to_async(function, thread_sensitive=False)


class AnalysisConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.stream_available = True
        self.group_available = False
        self.authenticated = False
        self.auth_started = False
        self.user = None
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        await self.accept()
        self.auth_deadline = asyncio.create_task(self.expire_unauthenticated())

    async def expire_unauthenticated(self):
        await asyncio.sleep(AUTH_TIMEOUT_SECONDS)
        if not self.authenticated and self.stream_available:
            await self.reject(CLOSE_UNAUTHENTICATED)

    async def reject(self, code):
        self.stream_available = False
        await self.close(code=code)

    async def receive(self, text_data=None, bytes_data=None):
        # Only the first frame means anything: it must authenticate.
        if self.auth_started or not self.stream_available:
            return
        self.auth_started = True
        self.auth_deadline.cancel()
        try:
            message = json.loads(text_data) if text_data else None
        except ValueError:
            message = None
        token = message.get("token") if isinstance(message, dict) and message.get("type") == "auth" else None
        record = await db_call(resolve_token)(token) if isinstance(token, str) else None
        if record is None:
            await self.reject(CLOSE_UNAUTHENTICATED)
            return
        self.user = record.user
        try:
            self.job_id = str(UUID(self.job_id))
        except (ValueError, TypeError, AttributeError):
            await self.send_frame({"status": "ERROR", **error_payload(PipelineError(
                "invalid_job_id", "Analysis job ID must be a valid UUID.", http_status=400)), "terminal": True})
            await self.reject(4400)
            return
        owned = await db_call(lambda: AnalysisBatch.objects.filter(job_id=self.job_id, user=self.user).exists())()
        if not owned:
            # The same answer for a batch that does not exist.
            await self.send_frame({"status": "ERROR", **error_payload(PipelineError(
                "job_not_found", "Analysis batch not found. Start a new analysis.", http_status=404)), "terminal": True})
            await self.reject(CLOSE_NOT_FOUND)
            return
        self.authenticated = True
        self.group_name = f"analysis_{self.job_id}"
        if self.channel_layer is not None:
            try:
                await self.channel_layer.group_add(self.group_name, self.channel_name)
                self.group_available = True
            except Exception:
                logger.warning("Live analysis fan-out unavailable; the direct stream remains usable.")
        self.pipeline_task = asyncio.create_task(self.run_rag_pipeline())

    async def disconnect(self, close_code):
        self.stream_available = False
        deadline = getattr(self, "auth_deadline", None)
        if deadline is not None:
            deadline.cancel()
        if self.group_available:
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.debug("Could not discard analysis subscription", exc_info=True)

    async def send_frame(self, payload, *, broadcast=False):
        payload = {"batch_id": str(self.job_id), **payload}
        if self.stream_available:
            try:
                await self.send(text_data=json.dumps(payload, allow_nan=False))
            except Exception:
                self.stream_available = False
        if broadcast and getattr(self, "group_available", False):
            try:
                await self.channel_layer.group_send(self.group_name, {
                    "type": "analysis.update", "payload": payload, "sender": self.channel_name,
                })
            except Exception:
                self.group_available = False
                logger.warning("Analysis subscribers will recover saved outcomes by polling.")

    async def analysis_update(self, event):
        if event["sender"] == self.channel_name or not self.stream_available or not self.authenticated:
            return
        await self.send_frame(event["payload"])
        if event["payload"].get("status") == "COMPLETE":
            self.stream_available = False
            await self.close()

    async def run_variant(self, method, model, config, username, document_id, conversation_id):
        loop = asyncio.get_running_loop()
        events = asyncio.Queue()
        attempt_id = str(uuid4())

        def publish(event):
            loop.call_soon_threadsafe(events.put_nowait, event)

        async def stream():
            sequence = 0
            while (event := await events.get()) is not None:
                sequence += 1
                await self.send_frame({
                    "status": "STAGE_PROGRESS", "method": method, "aiModel": model,
                    "attempt_id": attempt_id, "sequence": sequence, "event": event,
                }, broadcast=True)

        def analyze():
            with progress_scope(publish):
                progress_stage("question", "Preparing the document and retrieval index for this question.")
                engine = rag_registry.get_engine(method, model, config)
                with engine_execution(engine):
                    apply_retrieval_depth(engine, config["top_k"], child_top_k=config["child_top_k"])
                    # Real pipelines load the conversation's exact document in
                    # _run_analysis_core, rather than the user's latest upload.
                    return engine.run_analysis(document_id, conversation_id)

        sender = asyncio.create_task(stream())
        try:
            # Channels also uses its thread-sensitive executor for connection
            # cleanup. Keeping model calls there blocks other sockets opening.
            return await database_sync_to_async(analyze, thread_sensitive=False)()
        finally:
            loop.call_soon_threadsafe(events.put_nowait, None)
            await sender

    async def heartbeat(self, batch_id, token, stopped):
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                try:
                    if not await db_call(renew_batch)(batch_id, token):
                        return
                except Exception:
                    logger.warning("Could not renew analysis execution lease", exc_info=True)

    async def run_rag_pipeline(self):
        batch = None
        owner = False
        token = uuid4()
        heartbeat = None
        stopped = asyncio.Event()
        try:
            try:
                batch = await db_call(lambda: AnalysisBatch.objects.select_related(
                    "user", "conversation", "conversation__document",
                ).get(job_id=self.job_id, user=self.user))()
            except AnalysisBatch.DoesNotExist:
                raise PipelineError("job_not_found", "Analysis batch not found. Start a new analysis.", http_status=404)
            # Cached request data is optional and never overrides the DB binding.
            snapshot = await db_call(batch_snapshot)(batch)
            if snapshot["is_finished"]:
                await self.send_frame({"status": "REPLAYING"})
                for result in snapshot["results"]:
                    await self.send_frame({**result, "replayed": True})
                await self.send_frame(completion_frame(snapshot))
                await self.close()
                return
            if not batch.conversation or not batch.conversation.document_id:
                raise PipelineError("missing_document", "The analysis conversation has no document. Upload a document and start a new conversation.", http_status=400)
            if batch.conversation.user_id != batch.user_id or batch.conversation.document.user_id != batch.user_id:
                raise PipelineError("document_mismatch", "The analysis document does not belong to this conversation's user.", http_status=400)

            await self.send_frame({"status": "CONFIG", "config": snapshot["config"], "expected_count": snapshot["total"]})
            seen = set()
            waiting_sent = False
            while self.stream_available:
                snapshot = await db_call(batch_snapshot)(batch)
                for result in snapshot["results"]:
                    key = (result["method"], result["aiModel"])
                    if key not in seen:
                        seen.add(key)
                        await self.send_frame({**result, "replayed": True})
                if snapshot["is_finished"]:
                    await self.send_frame(completion_frame(snapshot))
                    await self.close()
                    return
                owner = await db_call(claim_batch)(batch.pk, token)
                if owner:
                    break
                if not waiting_sent:
                    await self.send_frame({"status": "WAITING", "message": "This batch is already running. Waiting for its current work; the job ID stays the same."})
                    waiting_sent = True
                await asyncio.sleep(FOLLOW_INTERVAL_SECONDS)
            if not owner:
                return
            heartbeat = asyncio.create_task(self.heartbeat(batch.pk, token, stopped))
            # Re-read after claiming: the previous owner may have just saved.
            snapshot = await db_call(batch_snapshot)(batch)
            for result in snapshot["results"]:
                if (result["method"], result["aiModel"]) not in seen:
                    await self.send_frame({**result, "replayed": True})
            existing = {(result["method"], result["aiModel"]) for result in snapshot["results"]}
            config = snapshot["config"]
            for variant in build_variants(config):
                if not self.stream_available:
                    return
                method, model = variant["method"], variant["model"]
                if (method, model) in existing:
                    continue
                response, failure = None, None
                try:
                    response = await self.run_variant(method, model, config, batch.user.username,
                                                      str(batch.conversation.document_id), str(batch.conversation_id))
                    if not isinstance(response, dict) or not isinstance(response.get("answer"), str) or not response["answer"].strip():
                        raise PipelineError("empty_model_response", "The answer model returned an empty response. Try again.", retryable=True, http_status=502)
                except Exception as exc:
                    logger.warning("Analysis variant failed: %s / %s", method, model, exc_info=True)
                    failure = error_payload(exc)
                if not await db_call(renew_batch)(batch.pk, token):
                    raise PipelineError("analysis_lease_lost", "This analysis was resumed by another worker. Reconnect to follow the same batch.", retryable=True, http_status=409)
                result = await db_call(save_variant)(batch, method, model, response, failure, token=token)
                frame = result_frame(batch, result)
                snapshot = await db_call(batch_snapshot)(batch)
                frame["progress"] = snapshot["progress"]
                await self.send_frame(frame, broadcast=True)
            snapshot = await db_call(batch_snapshot)(batch)
            await self.send_frame(completion_frame(snapshot), broadcast=True)
            if self.stream_available:
                await self.close()
        except Exception as exc:
            logger.warning("Analysis batch failed: %s", self.job_id, exc_info=True)
            await self.send_frame({"status": "ERROR", **error_payload(exc), "terminal": True})
            if self.stream_available:
                await self.close(code=4400)
        finally:
            stopped.set()
            if heartbeat:
                await heartbeat
            if owner and batch:
                try:
                    await db_call(release_batch)(batch.pk, token)
                except Exception:
                    logger.warning("Analysis lease will expire after a failed release", exc_info=True)
