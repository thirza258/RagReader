"""The SSE transports, in particular the ASGI bridge.

Under Daphne a sync iterator would be buffered whole by Django, so the ASGI
path must deliver each event while the producer is still running. These
tests prove that with a producer that refuses to continue until the
consumer has received its first event.
"""
import asyncio
import json
import shutil
import tempfile
import threading
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import AsyncRequestFactory, RequestFactory, SimpleTestCase, TransactionTestCase, override_settings

import rag.rag_service as rag_service
from workspace.models import ChatMessage
from workspace.services import index_cache
from workspace.services.ingestion import run_ingestion
from workspace.services.sse import PING, async_stream, event_stream_response, format_event, sync_stream
from workspace.tests.helpers import make_chat_pipeline, make_user, parse_sse

WAIT = 5  # seconds; generous, only reached when the behaviour is wrong


async def take(stream, count):
    frames = []
    async for frame in stream:
        frames.append(frame)
        if len(frames) == count:
            break
    return frames


class AsyncBridgeTests(SimpleTestCase):
    def test_events_reach_the_consumer_while_the_producer_is_still_running(self):
        first_delivered = threading.Event()
        observed = {}

        def producer():
            yield "token", {"delta": "first"}
            # Only continues once the consumer holds the first frame; a
            # buffering transport would leave this waiting until the timeout.
            observed["incremental"] = first_delivered.wait(WAIT)
            yield "token", {"delta": "second"}

        async def consume():
            frames = []
            async for frame in async_stream(producer):
                frames.append(frame)
                if len(frames) == 1:
                    first_delivered.set()
            return frames

        frames = asyncio.run(consume())
        self.assertTrue(observed["incremental"])
        self.assertEqual([parse_sse(frame)[0][1]["delta"] for frame in frames], ["first", "second"])

    def test_the_producer_finishes_after_the_consumer_disconnects(self):
        finished = threading.Event()
        release = threading.Event()

        def producer():
            yield "message.created", {}
            release.wait(WAIT)
            for index in range(3):
                yield "token", {"delta": str(index)}
            finished.set()  # stands for "answer persisted"

        async def consume_one_then_disconnect():
            stream = async_stream(producer)
            frames = await take(stream, 1)
            await stream.aclose()
            release.set()
            return frames

        frames = asyncio.run(consume_one_then_disconnect())
        self.assertEqual(len(frames), 1)
        self.assertTrue(finished.wait(WAIT))

    def test_pings_are_sent_while_the_producer_is_quiet(self):
        proceed = threading.Event()

        def producer():
            proceed.wait(WAIT)
            yield "token", {"delta": "late"}

        async def consume():
            stream = async_stream(producer, ping_interval=0.01)
            frames = await take(stream, 1)
            proceed.set()
            frames += await take(stream, 1)
            await stream.aclose()
            return frames

        frames = asyncio.run(consume())
        self.assertEqual(frames[0], PING)
        self.assertEqual(parse_sse(b"".join(frames))[-1], ("token", {"delta": "late"}))

    def test_a_crashing_producer_ends_with_an_error_event(self):
        def producer():
            yield "token", {"delta": "a"}
            raise RuntimeError("PRIVATE")

        async def consume():
            return [frame async for frame in async_stream(producer)]

        events = parse_sse(b"".join(asyncio.run(consume())))
        self.assertEqual([name for name, _ in events], ["token", "error"])
        self.assertEqual(events[-1][1]["error"]["code"], "internal_error")
        self.assertNotIn("PRIVATE", json.dumps(events))

        sync_events = parse_sse(b"".join(sync_stream(producer)))
        self.assertEqual([name for name, _ in sync_events], ["token", "error"])

    def test_frame_format(self):
        self.assertEqual(format_event("token", {"delta": "é\n"}), 'event: token\ndata: {"delta":"é\\n"}\n\n'.encode("utf-8"))

    def test_transport_follows_the_request_type(self):
        def producer():
            yield "token", {"delta": "x"}

        asgi = event_stream_response(AsyncRequestFactory().post("/"), producer)
        wsgi = event_stream_response(RequestFactory().post("/"), producer)
        self.assertTrue(asgi.is_async)
        self.assertFalse(wsgi.is_async)
        for response in (asgi, wsgi):
            self.assertEqual((response["Content-Type"], response["Cache-Control"], response["X-Accel-Buffering"]),
                             ("text/event-stream", "no-cache", "no"))
        self.assertEqual(parse_sse(b"".join(wsgi.streaming_content)), [("token", {"delta": "x"})])


class AsgiEndToEndTests(TransactionTestCase):
    """POST /messages/ through Django's ASGI handler: the turn runs on the
    bridge's worker thread with its own DB connection and is persisted."""

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="ragreader-asgi-media-")
        self.vector_store = tempfile.mkdtemp(prefix="ragreader-asgi-vs-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.vector_store, ignore_errors=True)
        settings_patch = override_settings(MEDIA_ROOT=self.media)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        self.pipeline, self.embeddings, self.chat = make_chat_pipeline(self.vector_store)
        for patcher in (mock.patch.object(rag_service.rag_registry, "get_engine", return_value=self.pipeline),
                        mock.patch("workspace.tasks.ingest_document_task.delay")):
            self.delay = patcher.start()
            self.addCleanup(patcher.stop)
        index_cache.clear()
        self.addCleanup(index_cache.clear)

    def test_streamed_answer_is_delivered_and_persisted(self):
        from workspace.auth import issue_token
        user = make_user("asgi")
        token = issue_token(user)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.client.post("/api/v1/documents/", {"source_type": "text", "text": "Alpha is the first letter of the Greek alphabet."},
                         content_type="application/json", **auth)
        self.assertTrue(run_ingestion(self.delay.call_args.args[0]))
        thread = self.client.post("/api/v1/conversations/", {}, content_type="application/json", **auth).json()
        main_thread = threading.get_ident()
        producer_threads = []
        original = self.chat.create

        def create(**kwargs):
            producer_threads.append(threading.get_ident())
            return original(**kwargs)

        self.chat.create = create

        async def ask():
            response = await self.async_client.post(
                f"/api/v1/conversations/{thread['id']}/messages/", {"content": "Alpha?"},
                content_type="application/json", headers={"Authorization": f"Bearer {token}"},
            )
            self.assertTrue(response.is_async)
            return response, b"".join([chunk async for chunk in response.streaming_content])

        response, body = async_to_sync(ask)()
        self.assertEqual(response["Content-Type"], "text/event-stream")
        events = parse_sse(body)
        self.assertEqual(events[0][0], "message.created")
        self.assertEqual(events[-1][0], "message.completed")
        self.assertEqual(events[-1][1]["message"]["content"], self.chat.answer)
        self.assertTrue(producer_threads and all(ident != main_thread for ident in producer_threads))
        stored = ChatMessage.objects.get(session_id=thread["id"], role="assistant")
        self.assertEqual((stored.status, stored.content), ("complete", self.chat.answer))
