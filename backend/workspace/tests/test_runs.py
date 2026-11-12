"""Retrieval runs: traced chat turns, provenance, the runs API and reliability (PRD §20–21, §32, §49)."""
import os
from datetime import datetime, timedelta
from unittest import mock

from django.contrib import admin
from django.db import DatabaseError
from django.test import SimpleTestCase
from django.utils import timezone

from ai_handler import llm as llm_module
from router.models import Document, Job
from workspace.models import (
    ChatMessage, ChatSession, RetrievalCandidate, RetrievalRun, RetrievalSpan, Workspace, default_workspace_for,
)
from workspace.services import runs as run_store
from workspace.services.runs import percentile
from workspace.services.tracing import Tracer
from workspace.tests.helpers import bearer, make_user
from workspace.tests.test_chat import LETTERS, ChatTestCase

RUN_KEYS = {"id", "workspace_id", "conversation_id", "message_id", "source", "status", "query", "error", "latency_ms",
            "token_usage", "candidate_count", "context_count", "cited_count", "strategy", "generation_model",
            "started_at", "created_at"}
DETAIL_KEYS = RUN_KEYS | {"provenance", "spans", "candidates"}
CANDIDATE_KEYS = {"rank", "document_id", "document_title", "document_available", "index_version_id", "chunk_id",
                  "page_number", "page_end", "char_start", "char_end", "text", "retrieval_score", "rerank_score",
                  "selected_for_context", "cited", "citation_id"}
SPAN_KEYS = {"name", "label", "status", "start_ms", "duration_ms", "detail", "error_code", "data", "children"}
EPSILON = 0.01  # ms; rounding of stored offsets


class CreditError(Exception):
    status_code = 402


def walk(spans):
    for span in spans:
        yield span
        yield from walk(span["children"])


def by_name(spans):
    return {span["name"]: span for span in walk(spans)}


class RunTestCase(ChatTestCase):
    def completed(self, events):
        return self.event(events, "message.completed")[0]

    def detail(self, run_id, auth=None):
        response = self.get(f"/api/v1/retrieval/runs/{run_id}/", auth=auth)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def make_run(self, workspace=None, user=None, **fields):
        user = user or self.user
        values = {"status": "completed", "source": "chat", "query_original": "q", "total_ms": 100}
        values.update(fields)
        return RetrievalRun.objects.create(user=user, workspace=workspace or default_workspace_for(user), **values)

    def ids(self, path, auth=None):
        response = self.get(path, auth=auth)
        self.assertEqual(response.status_code, 200, response.content)
        return [row["id"] for row in response.json()["results"]]


class TracedTurnTests(RunTestCase):
    def test_a_completed_turn_records_its_trace_spans_and_candidates(self):
        document = self.ready_text_document(LETTERS, title="Greek letters")
        conversation = self.conversation()
        self.chat.answer = "Alpha comes first [1]. Gamma is third [2, 9]."
        _, events = self.ask(conversation["id"], "Which letter is alpha?")
        completed = self.completed(events)
        message = completed["message"]
        run_id = message["retrieval"]["run_id"]
        self.assertIsInstance(run_id, int)
        self.assertEqual(completed["run_id"], run_id)
        stored = ChatMessage.objects.get(pk=message["id"])
        self.assertEqual(stored.retrieval["run_id"], run_id)  # persisted, not only sent

        run = RetrievalRun.objects.get(pk=run_id)
        self.assertEqual((run.status, run.source, run.user_id, run.conversation_id, run.message_id),
                         ("completed", "chat", self.user.pk, conversation["id"], message["id"]))
        self.assertEqual(run.workspace_id, conversation["workspace_id"])
        self.assertEqual((run.query_original, run.query_rewritten, run.rewrite_applied, run.rewrite_reason),
                         ("Which letter is alpha?", "Which letter is alpha?", False, "first_question"))
        timings = message["retrieval"]["timings_ms"]
        self.assertEqual(run.total_ms, message["latency_ms"])
        self.assertEqual((run.first_token_ms, run.generation_ms), (timings["first_token"], timings["generation"]))
        self.assertIsNotNone(run.retrieval_ms)
        self.assertIsNone(run.rewrite_ms)  # no rewrite ran
        self.assertIsNone(run.rerank_ms)
        self.assertEqual((run.prompt_tokens, run.completion_tokens), (50, message["token_usage"]["completion_tokens"]))
        self.assertEqual(run.total_tokens, message["token_usage"]["total_tokens"])
        self.assertEqual((run.candidate_count, run.context_count, run.cited_count), (3, 3, 2))
        self.assertEqual((run.error_code, run.error_stage), ("", ""))

        detail = self.detail(run_id)
        self.assertEqual(set(detail), DETAIL_KEYS)
        self.assertIsNone(detail["error"])
        self.assertEqual(detail["latency_ms"]["total"], message["latency_ms"])
        self.assertEqual(detail["query"]["rewrite_reason"], "first_question")

        # The §32 tree.
        self.assertEqual(len(detail["spans"]), 1)
        root = detail["spans"][0]
        self.assertEqual(set(root), SPAN_KEYS)
        self.assertEqual((root["name"], root["status"]), ("chat.turn", "completed"))
        self.assertEqual([child["name"] for child in root["children"]],
                         ["prepare", "rewrite", "retrieve", "generate", "citations", "persist"])
        spans = by_name(detail["spans"])
        self.assertEqual([child["name"] for child in spans["retrieve"]["children"]],
                         ["retrieve.load_indexes", "retrieve.embed_query", "retrieve.search", "retrieve.select"])
        self.assertEqual(spans["rewrite"]["status"], "skipped")
        loads = spans["retrieve.load_indexes"]["children"]
        self.assertEqual([load["name"] for load in loads], ["index.load"])
        self.assertEqual((loads[0]["data"]["cache"], loads[0]["data"]["document_id"]), ("miss", document["id"]))
        self.assertEqual(loads[0]["label"], "Load index: Greek letters")
        self.assertEqual(spans["retrieve.load_indexes"]["data"], {"documents": 1, "cache_hits": 0, "cache_misses": 1})
        self.assertEqual(spans["retrieve.select"]["data"], {"candidates": 3, "duplicates_skipped": 0, "context": 3})
        self.assertEqual(spans["retrieve.embed_query"]["data"]["model"], "openai/text-embedding-3-small")
        self.assertEqual([child["name"] for child in spans["generate"]["children"]], ["generate.first_token"])
        self.assertEqual(spans["generate"]["data"]["fallback"], False)
        self.assertEqual(spans["citations"]["data"], {"sources": 3, "cited": 2})
        self.assertTrue(all(span["status"] != "failed" for span in walk(detail["spans"])))

        # Offsets nest: children start after and end before their parent; siblings in order.
        def check(span):
            end = span["start_ms"] + span["duration_ms"]
            previous = span["start_ms"]
            for child in span["children"]:
                self.assertGreaterEqual(child["start_ms"] + EPSILON, previous, child["name"])
                self.assertLessEqual(child["start_ms"] + child["duration_ms"], end + EPSILON, child["name"])
                previous = child["start_ms"] + child["duration_ms"]
                check(child)
        check(root)
        self.assertEqual(root["start_ms"], 0.0)
        # The persisted answer is part of the trace, so the root outlasts `total`.
        self.assertGreaterEqual(root["duration_ms"] + 1, run.total_ms)

        candidates = detail["candidates"]
        self.assertEqual(set(candidates[0]), CANDIDATE_KEYS)
        self.assertEqual([c["rank"] for c in candidates], [1, 2, 3])
        self.assertEqual([c["selected_for_context"] for c in candidates], [True, True, True])
        self.assertEqual([c["cited"] for c in candidates], [True, True, False])
        self.assertEqual([c["citation_id"] for c in candidates], [1, 2, 3])
        self.assertEqual([c["chunk_id"] for c in candidates], [c["chunk_id"] for c in message["retrieval"]["candidates"]])
        self.assertIsNone(candidates[0]["rerank_score"])
        self.assertEqual(candidates[0]["document_title"], "Greek letters")
        self.assertTrue(candidates[0]["document_available"])
        self.assertEqual(candidates[0]["text"], "Alpha is the first letter of the Greek alphabet.")
        self.assertAlmostEqual(candidates[0]["retrieval_score"], message["citations"][0]["retrieval_score"], places=5)
        text = self.get(f"/api/v1/documents/{document['id']}/text/").json()["text"]
        for candidate in candidates:
            self.assertEqual(text[candidate["char_start"]:candidate["char_end"]], candidate["text"])

    def test_candidates_beyond_the_context_are_kept_but_not_selected(self):
        paragraphs = [
            "Alpha paragraph one about the first letter.",
            "Alpha paragraph two with beta mixed in.",
            "Alpha paragraph three with gamma mixed in.",
            "Alpha paragraph four with delta mixed in.",
            "Alpha paragraph five with epsilon mixed in.",
            "Alpha paragraph six with zeta mixed in.",
            "Alpha paragraph seven with beta and gamma.",
        ]
        self.ready_text_document("\n\n".join(paragraphs), title="Many")
        conversation = self.conversation()
        self.chat.answer = "Alpha appears often [1][4]."
        _, events = self.ask(conversation["id"], "alpha")
        run = RetrievalRun.objects.get(pk=self.completed(events)["run_id"])
        self.assertEqual((run.candidate_count, run.context_count, run.cited_count), (7, 5, 2))
        candidates = self.detail(run.pk)["candidates"]
        self.assertEqual([c["rank"] for c in candidates], list(range(1, 8)))
        self.assertEqual([c["citation_id"] for c in candidates], [1, 2, 3, 4, 5, None, None])
        self.assertEqual([c["selected_for_context"] for c in candidates], [True] * 5 + [False] * 2)
        self.assertEqual([c["cited"] for c in candidates], [True, False, False, True, False, False, False])
        for candidate in candidates[5:]:
            self.assertIsNotNone(candidate["char_start"])  # positions for every candidate, so the reader can open it
            self.assertIn("Alpha paragraph", candidate["text"])

    def test_a_second_turn_hits_the_index_cache_and_records_the_rewrite(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.ask(conversation["id"], "Tell me about alpha")
        self.chat.rewrite = "gamma radiation letter"
        _, events = self.ask(conversation["id"], "And the one for radiation?")
        run = RetrievalRun.objects.get(pk=self.completed(events)["run_id"])
        self.assertEqual((run.query_rewritten, run.rewrite_applied, run.rewrite_reason),
                         ("gamma radiation letter", True, "rewritten"))
        self.assertIsNotNone(run.rewrite_ms)
        spans = by_name(self.detail(run.pk)["spans"])
        self.assertEqual((spans["rewrite"]["status"], spans["rewrite"]["data"]["reason"]), ("completed", "rewritten"))
        self.assertEqual(spans["index.load"]["data"]["cache"], "hit")
        self.assertEqual(spans["retrieve.load_indexes"]["data"]["cache_hits"], 1)
        self.assertEqual(run.provenance["retrieval_parameters"]["history_messages"], 2)

    def test_a_failed_rewrite_is_shown_but_does_not_fail_the_turn(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.ask(conversation["id"], "Tell me about alpha")
        original = self.chat.create

        def create(**kwargs):
            if not kwargs.get("stream"):
                raise RuntimeError("rewrite model down")
            return original(**kwargs)

        with mock.patch.object(self.chat, "create", side_effect=create):
            _, events = self.ask(conversation["id"], "What about gamma?")
        run = RetrievalRun.objects.get(pk=self.completed(events)["run_id"])
        self.assertEqual((run.status, run.rewrite_reason, run.rewrite_applied), ("completed", "failed", False))
        rewrite = by_name(self.detail(run.pk)["spans"])["rewrite"]
        self.assertEqual((rewrite["status"], rewrite["error_code"]), ("failed", "rewrite_failed"))

    def test_provenance_records_models_parameters_and_index_versions(self):
        document = self.ready_text_document(LETTERS, title="Greek letters")
        vector = Document.objects.get(pk=document["id"]).current_index
        conversation = self.conversation()
        _, events = self.ask(conversation["id"], "Alpha?")
        provenance = self.detail(self.completed(events)["run_id"])["provenance"]
        self.assertEqual(provenance["strategy"], "dense")
        self.assertEqual(provenance["embedding_model"], "openai/text-embedding-3-small")
        self.assertIsNone(provenance["reranker"])
        self.assertEqual(provenance["retrieval_parameters"], {
            "candidate_k": 20, "context_k": 5, "similarity": "cosine", "deduplicate": True,
            "query_rewrite": False, "history_messages": 0, "history_limit": 6,
        })
        self.assertEqual((provenance["generation_model"], provenance["configured_generation_model"], provenance["fallback_used"]),
                         ("openai/gpt-4o-mini", "openai/gpt-4o-mini", False))
        self.assertEqual(provenance["generation_parameters"], {"temperature": 0.0, "stream": True})
        self.assertEqual(provenance["prompt_version"], "chat-cited-v1")
        self.assertEqual(provenance["index_versions"], [{
            "document_id": document["id"], "document_title": "Greek letters", "index_version_id": vector.pk,
            "method": "dense", "created_at": vector.created_at.isoformat(),
            "embedding_model": "openai/text-embedding-3-small", "loaded": True,
        }])
        self.assertEqual(provenance["index_version_count"], 1)
        stamped = datetime.fromisoformat(provenance["timestamp"])
        self.assertLess(abs((timezone.now() - stamped).total_seconds()), 60)

    def test_the_free_model_fallback_is_recorded_with_the_configured_model(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        original = self.chat.create

        def create(**kwargs):
            if kwargs.get("stream"):
                if kwargs["model"] == "openai/gpt-4o-mini":
                    raise CreditError("402 Payment Required: insufficient credits")
                self.chat.served_by = kwargs["model"]
            return original(**kwargs)

        with mock.patch.object(self.chat, "create", side_effect=create), \
                mock.patch.object(llm_module, "get_shuffled_free_models", return_value=["vendor/free-a:free"]):
            _, events = self.ask(conversation["id"], "Alpha?")
        message = self.completed(events)["message"]
        self.assertEqual(message["retrieval"]["pipeline"]["generation_model"], "vendor/free-a:free")
        detail = self.detail(message["retrieval"]["run_id"])
        provenance = detail["provenance"]
        self.assertEqual((provenance["generation_model"], provenance["configured_generation_model"], provenance["fallback_used"]),
                         ("vendor/free-a:free", "openai/gpt-4o-mini", True))
        self.assertEqual(detail["generation_model"], "vendor/free-a:free")
        self.assertTrue(by_name(detail["spans"])["generate"]["data"]["fallback"])

    def test_stream_zero_records_the_run_too(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        body = self.post(f"/api/v1/conversations/{conversation['id']}/messages/?stream=0", {"content": "Alpha?"}).json()
        run_id = body["assistant_message"]["retrieval"]["run_id"]
        self.assertEqual(RetrievalRun.objects.get(pk=run_id).message_id, body["assistant_message"]["id"])


class FailedTurnTests(RunTestCase):
    def test_a_retrieval_failure_records_a_failed_run(self):
        document = self.ready_text_document(LETTERS, title="Lost index")
        os.remove(Document.objects.get(pk=document["id"]).current_index.vectorstore_location)
        conversation = self.conversation()
        _, events = self.ask(conversation["id"], "Alpha?")
        error = events[-1][1]
        run = RetrievalRun.objects.get()
        self.assertEqual(error["run_id"], run.pk)
        self.assertEqual(error["message"]["retrieval"]["run_id"], run.pk)
        self.assertEqual(ChatMessage.objects.get(role="assistant").retrieval["run_id"], run.pk)
        self.assertEqual((run.status, run.error_stage, run.error_code), ("failed", "retrieve", "index_unavailable"))
        self.assertIn("Lost index", run.error_message)
        self.assertEqual(run.total_ms, error["message"]["latency_ms"])
        self.assertEqual((run.retrieval_ms, run.generation_ms, run.first_token_ms, run.total_tokens), (None, None, None, None))
        self.assertFalse(RetrievalCandidate.objects.exists())

        detail = self.detail(run.pk)
        self.assertEqual(detail["error"], {"code": "index_unavailable", "message": run.error_message, "stage": "retrieve"})
        root = detail["spans"][0]
        self.assertEqual((root["status"], root["error_code"]), ("failed", "index_unavailable"))
        self.assertEqual([child["name"] for child in root["children"]], ["prepare", "rewrite", "retrieve"])
        spans = by_name(detail["spans"])
        for name in ("retrieve", "retrieve.load_indexes", "index.load"):
            self.assertEqual((spans[name]["status"], spans[name]["error_code"]), ("failed", "index_unavailable"), name)
        self.assertEqual(spans["index.load"]["detail"], "Could not be loaded")
        self.assertEqual(detail["provenance"]["index_versions"][0]["loaded"], False)
        self.assertIsNone(detail["provenance"]["generation_model"])
        self.assertEqual(detail["provenance"]["configured_generation_model"], "openai/gpt-4o-mini")

    def test_a_generation_failure_records_a_failed_run_with_its_candidates(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.chat.stream_error = RuntimeError("PRIVATE upstream detail")
        _, events = self.ask(conversation["id"], "Alpha?")
        error = events[-1][1]
        run = RetrievalRun.objects.get(pk=error["run_id"])
        self.assertEqual((run.status, run.error_stage, run.error_code), ("failed", "generate", "provider_error"))
        self.assertNotIn("PRIVATE", run.error_message)
        self.assertIsNotNone(run.retrieval_ms)
        self.assertIsNone(run.generation_ms)
        self.assertEqual((run.candidate_count, run.context_count, run.cited_count), (3, 3, 0))
        detail = self.detail(run.pk)
        self.assertEqual([c["cited"] for c in detail["candidates"]], [False, False, False])
        self.assertEqual([c["selected_for_context"] for c in detail["candidates"]], [True, True, True])
        spans = by_name(detail["spans"])
        for name in ("generate", "generate.first_token", "chat.turn"):
            self.assertEqual((spans[name]["status"], spans[name]["error_code"]), ("failed", "provider_error"), name)
        self.assertEqual(spans["retrieve"]["status"], "completed")
        self.assertNotIn("citations", spans)

    def test_a_disconnected_stream_records_an_interrupted_run(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "Alpha?"})
        next(iter(response.streaming_content))  # message.created only
        response.close()
        run = RetrievalRun.objects.get()
        self.assertEqual((run.status, run.error_code), ("failed", "stream_interrupted"))
        self.assertEqual(ChatMessage.objects.get(role="assistant").retrieval["run_id"], run.pk)

    def test_leaving_after_the_last_token_keeps_the_completed_run(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "Alpha?"})
        for frame in response.streaming_content:
            if b'"id":"generate","status":"completed"' in frame:
                break
        response.close()
        run = RetrievalRun.objects.get()
        self.assertEqual(run.status, "completed")
        self.assertEqual(ChatMessage.objects.get(role="assistant").retrieval["run_id"], run.pk)


class TracingNeverBreaksTheTurnTests(RunTestCase):
    def test_a_database_error_while_storing_the_run_keeps_the_answer(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        with mock.patch.object(RetrievalCandidate.objects, "bulk_create", side_effect=DatabaseError("disk full")), \
                self.assertLogs("workspace.services.chat", "WARNING") as logs:
            _, events = self.ask(conversation["id"], "Alpha?")
        self.assertIn("Could not record the retrieval run", logs.output[0])
        completed = self.completed(events)
        self.assertEqual((completed["message"]["status"], completed["run_id"]), ("complete", None))
        self.assertIsNone(completed["message"]["retrieval"]["run_id"])
        self.assertFalse(RetrievalRun.objects.exists())  # the savepoint rolled back the partial run
        self.assertFalse(RetrievalSpan.objects.exists())
        # The connection is still usable afterwards.
        listed = self.get(f"/api/v1/conversations/{conversation['id']}/messages/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["results"][1]["status"], "complete")

    def test_a_storage_failure_on_a_failed_turn_still_reports_the_error(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.chat.stream_error = RuntimeError("down")
        with mock.patch.object(run_store, "save_run", side_effect=RuntimeError("bug")), \
                self.assertLogs("workspace.services.chat", "WARNING"):
            _, events = self.ask(conversation["id"], "Alpha?")
        self.assertEqual(events[-1][0], "error")
        self.assertIsNone(events[-1][1]["run_id"])
        self.assertEqual(ChatMessage.objects.get(role="assistant").status, "failed")

    def test_a_broken_tracer_does_not_break_the_turn(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        with mock.patch.object(Tracer, "_now_ms", side_effect=RuntimeError("clock broken")), \
                self.assertLogs("workspace.services.tracing", "WARNING") as logs:
            _, events = self.ask(conversation["id"], "Alpha?")
        self.assertEqual(len(logs.records), 1)
        completed = self.completed(events)
        self.assertEqual(completed["message"]["status"], "complete")
        self.assertEqual(completed["message"]["content"], self.chat.answer)
        # The run is still recorded from the turn's own measurements, without spans.
        run = RetrievalRun.objects.get(pk=completed["run_id"])
        self.assertEqual(run.total_ms, completed["message"]["latency_ms"])
        self.assertFalse(run.spans.exists())
        self.assertEqual(run.candidates.count(), 3)


class RunsApiTests(RunTestCase):
    def test_list_is_newest_first_bounded_and_filtered(self):
        now = timezone.now()
        workspace = default_workspace_for(self.user)
        other_workspace = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        thread = ChatSession.objects.create(user=self.user, workspace=workspace)
        old = self.make_run(started_at=now - timedelta(hours=3))
        failed = self.make_run(status="failed", error_stage="generate", error_code="provider_error",
                               started_at=now - timedelta(hours=2), conversation=thread)
        evaluation = self.make_run(source="evaluation", started_at=now - timedelta(hours=1))
        elsewhere = self.make_run(workspace=Workspace.objects.get(pk=other_workspace["id"]))

        self.assertEqual(self.ids("/api/v1/retrieval/runs/"), [evaluation.pk, failed.pk, old.pk])
        response = self.get("/api/v1/retrieval/runs/?limit=2").json()
        self.assertEqual(([row["id"] for row in response["results"]], response["has_more"]), ([evaluation.pk, failed.pk], True))
        self.assertFalse(self.get("/api/v1/retrieval/runs/?limit=3").json()["has_more"])
        self.assertEqual(self.ids("/api/v1/retrieval/runs/?status=failed"), [failed.pk])
        self.assertEqual(self.ids("/api/v1/retrieval/runs/?source=evaluation"), [evaluation.pk])
        self.assertEqual(self.ids(f"/api/v1/retrieval/runs/?conversation_id={thread.pk}"), [failed.pk])
        self.assertEqual(self.ids(f"/api/v1/retrieval/runs/?workspace_id={other_workspace['id']}"), [elsewhere.pk])
        self.assertEqual(self.ids(f"/api/v1/retrieval/runs/?workspace_id={other_workspace['id']}&conversation_id={thread.pk}"), [])

        row = self.get("/api/v1/retrieval/runs/?status=failed").json()["results"][0]
        self.assertEqual(set(row), RUN_KEYS)
        self.assertEqual(row["error"], {"code": "provider_error", "message": "The request failed.", "stage": "generate"})
        self.assertIsNone(row["token_usage"])

    def test_invalid_parameters_are_400(self):
        for query in ("status=bogus", "source=web", "limit=0", "limit=201", "limit=abc"):
            with self.subTest(query=query):
                response = self.get(f"/api/v1/retrieval/runs/?{query}")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
        for query in ("days=0", "days=366", "days=x", "source=web"):
            with self.subTest(query=query):
                response = self.get(f"/api/v1/retrieval/runs/summary/?{query}")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_another_users_runs_are_not_found(self):
        stranger = make_user("stranger")
        theirs = self.make_run(user=stranger)
        their_workspace = default_workspace_for(stranger)
        their_thread = ChatSession.objects.create(user=stranger, workspace=their_workspace)
        mine = self.make_run()
        self.assertEqual(self.ids("/api/v1/retrieval/runs/"), [mine.pk])
        for path in (f"/api/v1/retrieval/runs/{theirs.pk}/", "/api/v1/retrieval/runs/999999/",
                     f"/api/v1/retrieval/runs/?workspace_id={their_workspace.pk}",
                     f"/api/v1/retrieval/runs/?conversation_id={their_thread.pk}",
                     f"/api/v1/retrieval/runs/summary/?workspace_id={their_workspace.pk}"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")
        self.assertEqual(self.ids("/api/v1/retrieval/runs/", auth=bearer(stranger)), [theirs.pk])
        for path in ("/api/v1/retrieval/runs/", f"/api/v1/retrieval/runs/{mine.pk}/", "/api/v1/retrieval/runs/summary/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_candidates_keep_their_title_and_snippet_after_the_document_is_deleted(self):
        document = self.ready_text_document(LETTERS, title="Greek letters")
        conversation = self.conversation()
        _, events = self.ask(conversation["id"], "Alpha?")
        run_id = self.completed(events)["run_id"]
        with self.captureOnCommitCallbacks(execute=True):
            self.delete(f"/api/v1/documents/{document['id']}/")
        candidate = self.detail(run_id)["candidates"][0]
        self.assertEqual((candidate["document_id"], candidate["document_title"], candidate["document_available"]),
                         (None, "Greek letters", False))
        self.assertEqual(candidate["text"], "Alpha is the first letter of the Greek alphabet.")

    def test_deleting_the_conversation_deletes_its_runs(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.ask(conversation["id"], "Alpha?")
        self.assertTrue(RetrievalRun.objects.exists())
        self.delete(f"/api/v1/conversations/{conversation['id']}/")
        self.assertFalse(RetrievalRun.objects.exists())
        self.assertFalse(RetrievalSpan.objects.exists())

    def test_the_models_are_in_the_admin(self):
        for model in (RetrievalRun, RetrievalSpan, RetrievalCandidate):
            self.assertTrue(admin.site.is_registered(model), model)


class RetentionTests(RunTestCase):
    def test_stored_candidates_and_snippets_are_capped(self):
        workspace = default_workspace_for(self.user)
        candidates = [
            {"rank": rank, "document": None, "chunk_id": "not-a-number" if rank == 1 else rank,
             "index_version_id": True, "retrieval_score": float("nan") if rank == 2 else 0.5,
             "text": "z" * 5000, "position": {"page_start": "3", "char_start": -4}}
            for rank in range(1, 61)
        ]
        run = run_store.save_run(user=self.user, workspace=workspace, source="chat", status="completed",
                                 query_original="q", candidates=candidates, usage={"prompt_tokens": 4, "completion_tokens": 6})
        stored = list(run.candidates.order_by("rank"))
        self.assertEqual(len(stored), run_store.MAX_RUN_CANDIDATES)
        self.assertIsNone(stored[0].chunk_id)
        self.assertIsNone(stored[0].index_version_id)
        self.assertIsNone(stored[1].retrieval_score)
        self.assertEqual(len(stored[0].snippet), run_store.SNIPPET_CHARS)
        self.assertEqual((stored[0].page_start, stored[0].char_start), (3, None))
        self.assertEqual(run.total_tokens, 10)  # derived when the provider omits it


class PercentileTests(SimpleTestCase):
    def test_linear_interpolation_on_small_samples(self):
        self.assertIsNone(percentile([], 50))
        self.assertIsNone(percentile([None, None], 95))
        self.assertEqual(percentile([7], 50), 7.0)
        self.assertEqual(percentile([7], 95), 7.0)
        self.assertEqual(percentile([100, 300], 50), 200.0)
        self.assertEqual(percentile([100, 300], 95), 290.0)
        self.assertEqual(percentile([400, 100, None, 300, 200], 50), 250.0)
        self.assertEqual(percentile([100, 200, 300, 400], 95), 385.0)
        self.assertEqual(percentile([100, 200, 300, 400, 1000], 95), 880.0)
        self.assertEqual(percentile([5, 1, 9], 0), 1.0)
        self.assertEqual(percentile([5, 1, 9], 100), 9.0)
        with self.assertRaises(ValueError):
            percentile([1], 101)


class ReliabilitySummaryTests(RunTestCase):
    def test_summary_on_a_hand_made_dataset(self):
        workspace = default_workspace_for(self.user)
        now = timezone.now()
        for total, retrieval, generation, first, tokens in (
            (100, 10, 60, 40, 100), (200, 20, 150, 90, 200), (300, 30, 250, 120, None),
            (400, 40, 330, 200, 300), (1000, None, 900, 500, 400),
        ):
            self.make_run(total_ms=total, retrieval_ms=retrieval, generation_ms=generation, first_token_ms=first,
                          prompt_tokens=tokens and tokens - 10, completion_tokens=tokens and 10, total_tokens=tokens,
                          started_at=now - timedelta(days=1))
        self.make_run(status="failed", error_stage="retrieve", error_code="index_unavailable", total_ms=5)
        self.make_run(status="failed", error_stage="generate", error_code="provider_error", total_ms=50000, retrieval_ms=9000)
        self.make_run(status="failed", error_stage="rewrite", error_code="stream_interrupted", total_ms=1)
        # Outside the window, in another workspace, or someone else's: never counted.
        self.make_run(started_at=now - timedelta(days=40), total_ms=99999)
        other = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        self.make_run(workspace=Workspace.objects.get(pk=other["id"]), status="failed", error_stage="retrieve")
        self.make_run(user=make_user("stranger"), status="failed", error_stage="generate")

        def document(status, code=""):
            return Document.objects.create(user=self.user, workspace=workspace, name=status, source_type="text",
                                           status=status, error_code=code)
        ready_one, ready_two = document("READY"), document("READY")
        failed = document("FAILED", "embedding_failed")
        document("FAILED", "not_indexed")
        busy = document("EXTRACTING")
        for owner, status in ((ready_one, "READY"), (ready_two, "READY"), (failed, "FAILED"), (busy, "PROCESSING")):
            Job.objects.create(user=self.user, document=owner, kind="ingest", status=status)
        old_job = Job.objects.create(user=self.user, document=failed, kind="ingest", status="FAILED")
        Job.objects.filter(pk=old_job.pk).update(created_at=now - timedelta(days=40))

        response = self.get("/api/v1/retrieval/runs/summary/?days=30")
        self.assertEqual(response.status_code, 200, response.content)
        summary = response.json()
        self.assertEqual((summary["workspace_id"], summary["days"], summary["source"]), (workspace.pk, 30, None))
        self.assertEqual(summary["runs"], {"total": 8, "completed": 5, "failed": 3})
        self.assertEqual(summary["failure_rate"], 0.375)
        self.assertEqual(summary["failures_by_stage"], {
            "retrieval": {"count": 1, "rate": 0.125},
            "generation": {"count": 1, "rate": 0.125},
            "other": {"count": 1, "rate": 0.125},
        })
        latency = summary["latency_ms"]
        self.assertEqual(latency["sample_size"], 5)  # completed runs only
        self.assertEqual(latency["total"], {"p50": 300.0, "p95": 880.0, "count": 5})
        self.assertEqual(latency["retrieval"], {"p50": 25.0, "p95": 38.5, "count": 4})
        self.assertEqual(latency["generation"], {"p50": 250.0, "p95": 786.0, "count": 5})
        self.assertEqual(latency["first_token"], {"p50": 120.0, "p95": 440.0, "count": 5})
        self.assertEqual(summary["tokens"], {"prompt": 960, "completion": 40, "total": 1000,
                                             "runs_with_usage": 4, "average_per_run": 250.0})
        self.assertEqual(summary["ingestion"], {
            "documents": 5, "ready": 2, "failed": 1, "in_progress": 1, "not_indexed": 1,
            "success_rate": 0.6667, "failure_rate": 0.3333,
            "attempts": {"total": 4, "succeeded": 2, "failed": 1, "failure_rate": 0.3333},
        })

        narrow = self.get("/api/v1/retrieval/runs/summary/?days=30&source=evaluation").json()
        self.assertEqual(narrow["runs"]["total"], 0)
        wide = self.get("/api/v1/retrieval/runs/summary/?days=60").json()
        self.assertEqual(wide["runs"]["total"], 9)
        self.assertEqual(wide["ingestion"]["attempts"]["total"], 5)

    def test_an_empty_workspace_has_zeros_and_nulls(self):
        summary = self.get("/api/v1/retrieval/runs/summary/").json()
        self.assertEqual(summary["days"], 30)
        self.assertEqual(summary["runs"], {"total": 0, "completed": 0, "failed": 0})
        self.assertIsNone(summary["failure_rate"])
        self.assertEqual(summary["latency_ms"]["total"], {"p50": None, "p95": None, "count": 0})
        self.assertIsNone(summary["tokens"]["average_per_run"])
        self.assertIsNone(summary["ingestion"]["success_rate"])

    def test_a_real_turn_shows_up_in_the_summary(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.ask(conversation["id"], "Alpha?")
        summary = self.get("/api/v1/retrieval/runs/summary/").json()
        self.assertEqual((summary["runs"]["total"], summary["failure_rate"]), (1, 0.0))
        self.assertEqual(summary["latency_ms"]["total"]["count"], 1)
        self.assertEqual(summary["ingestion"]["ready"], 1)
        self.assertEqual(summary["ingestion"]["attempts"]["succeeded"], 1)
