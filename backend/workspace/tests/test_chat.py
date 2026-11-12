"""Persistent conversations and the streamed, cited chat turn (PRD §13–16)."""
import os
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from router.models import Conversation, Document
from workspace.models import ChatMessage, ChatSession
from workspace.tests.helpers import WorkspaceTestCase, make_user, parse_sse

LETTERS = (
    "Alpha is the first letter of the Greek alphabet.\n\n"
    "Gamma is the third letter, used for radiation.\n\n"
    "Delta is the fourth letter and means change."
)
MESSAGE_KEYS = {"id", "conversation_id", "role", "content", "status", "citations", "retrieval",
                "token_usage", "latency_ms", "error", "analysis_turn", "created_at"}
EVIDENCE_KEYS = {"citation_id", "document_id", "document_title", "index_version_id", "chunk_id", "page_number",
                 "page_end", "char_start", "char_end", "text", "retrieval_score", "rerank_score", "cited"}
CONVERSATION_KEYS = {"id", "workspace_id", "title", "document_ids", "message_count", "last_message_preview",
                     "created_at", "updated_at"}


class ChatTestCase(WorkspaceTestCase):
    def conversation(self, **payload):
        response = self.post("/api/v1/conversations/", payload)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def ask(self, conversation_id, content, **payload):
        response = self.post(f"/api/v1/conversations/{conversation_id}/messages/", {"content": content, **payload})
        self.assertEqual(response.status_code, 200, getattr(response, "content", b""))
        self.assertTrue(response.streaming)
        return response, parse_sse(b"".join(response.streaming_content))

    @staticmethod
    def event(events, name):
        return [data for event, data in events if event == name]


class StreamingTurnTests(ChatTestCase):
    def test_event_order_persistence_and_citations(self):
        document = self.ready_text_document(LETTERS, title="Greek letters")
        conversation = self.conversation()
        self.chat.answer = "Alpha comes first [1]. Gamma is third [2, 9]."
        response, events = self.ask(conversation["id"], "Which letter is alpha?")

        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        names = [name for name, _ in events]
        tokens = names.count("token")
        self.assertGreater(tokens, 1)
        self.assertEqual(names, ["message.created", "stage", "stage", "stage", "retrieval", "stage"]
                         + ["token"] * tokens + ["stage", "message.completed"])
        stages = [(data["id"], data["status"]) for name, data in events if name == "stage"]
        self.assertEqual(stages, [("rewrite", "skipped"), ("retrieve", "running"), ("retrieve", "completed"),
                                  ("generate", "running"), ("generate", "completed")])

        created = events[0][1]
        self.assertEqual(set(created["user_message"]), MESSAGE_KEYS)
        self.assertEqual((created["user_message"]["role"], created["user_message"]["status"]), ("user", "complete"))
        self.assertEqual((created["assistant_message"]["role"], created["assistant_message"]["status"]), ("assistant", "streaming"))

        retrieval = self.event(events, "retrieval")[0]
        self.assertEqual((retrieval["candidate_count"], retrieval["context_count"]), (3, 3))
        self.assertTrue(all(source["cited"] is False for source in retrieval["citations"]))
        first = retrieval["citations"][0]
        self.assertEqual(set(first), EVIDENCE_KEYS)
        self.assertEqual((first["citation_id"], first["document_id"], first["document_title"]), (1, document["id"], "Greek letters"))
        self.assertEqual(first["text"], "Alpha is the first letter of the Greek alphabet.")
        self.assertIsNone(first["page_number"])  # not a PDF
        text = self.get(f"/api/v1/documents/{document['id']}/text/").json()["text"]
        self.assertEqual(text[first["char_start"]:first["char_end"]], first["text"])
        self.assertEqual(first["index_version_id"], Document.objects.get(pk=document["id"]).current_index_id)

        self.assertEqual("".join(data["delta"] for data in self.event(events, "token")), self.chat.answer)
        message = self.event(events, "message.completed")[0]["message"]
        self.assertEqual((message["status"], message["content"], message["error"]), ("complete", self.chat.answer, None))
        self.assertEqual([source["cited"] for source in message["citations"]], [True, True, False])
        self.assertEqual(message["token_usage"]["prompt_tokens"], 50)
        self.assertIsInstance(message["latency_ms"], int)
        meta = message["retrieval"]
        self.assertEqual((meta["candidate_count"], meta["context_count"], meta["cited_count"]), (3, 3, 2))
        self.assertEqual(meta["pipeline"], {
            "strategy": "dense", "embedding_model": "openai/text-embedding-3-small",
            "generation_model": "openai/gpt-4o-mini", "temperature": 0.0, "candidate_k": 20, "top_k": 5,
            "prompt_version": "chat-cited-v1",
        })
        self.assertEqual(meta["query"], {"original": "Which letter is alpha?", "rewritten": "Which letter is alpha?", "rewrite_applied": False})
        self.assertEqual(meta["documents"], [{"document_id": document["id"], "index_version_id": first["index_version_id"]}])
        self.assertEqual([candidate["rank"] for candidate in meta["candidates"]], [1, 2, 3])
        self.assertEqual(set(meta["timings_ms"]), {"rewrite", "embed_query", "search", "first_token", "generation", "total"})

        stored = list(ChatMessage.objects.filter(session_id=conversation["id"]).order_by("created_at", "id"))
        self.assertEqual([(row.role, row.status) for row in stored], [("user", "complete"), ("assistant", "complete")])
        listed = self.get(f"/api/v1/conversations/{conversation['id']}/messages/").json()["results"]
        self.assertEqual([row["id"] for row in listed], [row.id for row in stored])
        self.assertEqual(listed[1]["citations"], message["citations"])
        thread = self.get(f"/api/v1/conversations/{conversation['id']}/").json()
        self.assertEqual((thread["title"], thread["message_count"]), ("Which letter is alpha?", 2))
        self.assertEqual(thread["last_message_preview"], self.chat.answer)

        # Single-document scope: linked to a legacy turn for Deep analysis.
        turn = Conversation.objects.get(pk=message["analysis_turn"]["conversation_id"])
        self.assertEqual(message["analysis_turn"]["document_id"], document["id"])
        self.assertEqual((turn.document_id, turn.query, turn.response), (document["id"], "Which letter is alpha?", self.chat.answer))
        started = self.post("/api/v1/start-analysis/", {"conversation_id": turn.pk})
        self.assertEqual(started.status_code, 202)

    def test_stream_zero_returns_both_messages_as_json(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/?stream=0", {"content": "Alpha?"})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), {"user_message", "assistant_message"})
        self.assertEqual((body["user_message"]["content"], body["assistant_message"]["status"]), ("Alpha?", "complete"))
        self.assertEqual(body["assistant_message"]["content"], self.chat.answer)

    def test_multi_document_candidates_are_merged_by_score(self):
        first = self.ready_text_document(
            "Alpha only paragraph about the first letter here.\n\nGamma only paragraph about the third letter here.",
            title="First")
        second = self.ready_text_document(
            "Alpha and beta paragraph mixing two letters here.\n\nDelta only paragraph about the fourth letter here.",
            title="Second")
        conversation = self.conversation(document_ids=[first["id"], second["id"]])
        _, events = self.ask(conversation["id"], "alpha")
        message = self.event(events, "message.completed")[0]["message"]
        candidates = message["retrieval"]["candidates"]
        self.assertEqual([c["document_id"] for c in candidates], [first["id"], second["id"], first["id"], second["id"]])
        scores = [c["retrieval_score"] for c in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertAlmostEqual(scores[0], 1.0, places=5)
        self.assertEqual({d["document_id"] for d in message["retrieval"]["documents"]}, {first["id"], second["id"]})
        self.assertEqual([c["document_title"] for c in message["citations"][:2]], ["First", "Second"])
        prompt = self.chat.stream_calls[-1]["messages"][-1]["content"]
        self.assertIn("[1] First\nAlpha only paragraph", prompt)
        self.assertIn("[2] Second\nAlpha and beta paragraph", prompt)
        self.assertIsNone(message["analysis_turn"])  # two documents in scope

    def test_identical_passages_are_deduplicated_across_documents(self):
        shared = "Epsilon paragraph that both documents contain verbatim."
        self.ready_text_document(shared, title="One")
        self.ready_text_document(shared, title="Two")
        conversation = self.conversation()
        _, events = self.ask(conversation["id"], "epsilon")
        message = self.event(events, "message.completed")[0]["message"]
        self.assertEqual(message["retrieval"]["candidate_count"], 1)
        self.assertEqual(len(message["citations"]), 1)

    def test_scope_follows_the_conversation_then_the_message_override(self):
        first = self.ready_text_document("Alpha paragraph in the first document here.", title="First")
        second = self.ready_text_document("Beta paragraph in the second document here.", title="Second")
        conversation = self.conversation(document_ids=[first["id"]])
        _, events = self.ask(conversation["id"], "alpha")
        used = self.event(events, "message.completed")[0]["message"]["retrieval"]["documents"]
        self.assertEqual([d["document_id"] for d in used], [first["id"]])
        _, events = self.ask(conversation["id"], "beta", document_ids=[second["id"]])
        message = self.event(events, "message.completed")[0]["message"]
        self.assertEqual([d["document_id"] for d in message["retrieval"]["documents"]], [second["id"]])
        self.assertEqual(message["analysis_turn"]["document_id"], second["id"])


class HistoryAndRewriteTests(ChatTestCase):
    def setUp(self):
        super().setUp()
        self.ready_text_document(LETTERS)
        self.thread = self.conversation()
        self.chat.answer = "Alpha comes first [1]."
        self.ask(self.thread["id"], "Tell me about alpha")
        self.embeddings.calls.clear()

    def test_history_is_rewritten_and_sent_with_the_prompt(self):
        self.chat.rewrite = "gamma radiation letter"
        _, events = self.ask(self.thread["id"], "And the one used for radiation?")
        rewrite = [data for name, data in events if name == "stage" and data["id"] == "rewrite"]
        self.assertEqual([data["status"] for data in rewrite], ["running", "completed"])
        meta = self.event(events, "message.completed")[0]["message"]["retrieval"]
        self.assertEqual(meta["query"], {"original": "And the one used for radiation?", "rewritten": "gamma radiation letter", "rewrite_applied": True})
        self.assertEqual(self.embeddings.calls, [["gamma radiation letter"]])  # one query embedding
        self.assertIn("Tell me about alpha", self.chat.rewrite_calls[-1]["messages"][0]["content"])

        messages = self.chat.stream_calls[-1]["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[1]["content"], "Tell me about alpha")
        self.assertEqual(messages[2]["content"], "Alpha comes first.")  # old [n] markers stripped
        self.assertIn("Question: And the one used for radiation?", messages[3]["content"])
        # Only the first question names the thread.
        self.assertEqual(self.get(f"/api/v1/conversations/{self.thread['id']}/").json()["title"], "Tell me about alpha")

    def test_unusable_rewrites_fall_back_to_the_original_question(self):
        for rewrite in ("line one\nline two", "x" * 201, "   "):
            with self.subTest(rewrite=rewrite[:20]):
                self.chat.rewrite = rewrite
                self.embeddings.calls.clear()
                _, events = self.ask(self.thread["id"], "What about gamma?")
                meta = self.event(events, "message.completed")[0]["message"]["retrieval"]["query"]
                self.assertEqual((meta["rewritten"], meta["rewrite_applied"]), ("What about gamma?", False))
                self.assertEqual(self.embeddings.calls, [["What about gamma?"]])

    def test_a_failing_rewrite_falls_back_too(self):
        original_create = self.chat.create

        def create(**kwargs):
            if not kwargs.get("stream"):
                raise RuntimeError("rewrite model down")
            return original_create(**kwargs)

        with mock.patch.object(self.chat, "create", side_effect=create):
            _, events = self.ask(self.thread["id"], "What about gamma?")
        message = self.event(events, "message.completed")[0]["message"]
        self.assertEqual(message["status"], "complete")
        self.assertFalse(message["retrieval"]["query"]["rewrite_applied"])


class FailureTests(ChatTestCase):
    def test_no_ready_documents_is_a_json_409(self):
        self.add_text("Alpha still queued.")
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "Alpha?"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "no_ready_documents")
        self.assertFalse(ChatMessage.objects.exists())

    def test_an_unloadable_index_fails_the_turn_naming_the_document(self):
        document = self.ready_text_document(LETTERS, title="Lost index")
        os.remove(Document.objects.get(pk=document["id"]).current_index.vectorstore_location)
        conversation = self.conversation()
        _, events = self.ask(conversation["id"], "Alpha?")
        self.assertEqual([name for name, _ in events][-2:], ["stage", "error"])
        error = events[-1][1]
        self.assertEqual((error["error"]["code"], error["error"]["stage"]), ("index_unavailable", "retrieve"))
        self.assertIn("Lost index", error["error"]["message"])
        self.assertEqual((error["message"]["status"], error["message"]["error"]["code"]), ("failed", "index_unavailable"))
        self.assertEqual(self.chat.stream_calls, [])  # never reached generation
        self.assertEqual(ChatMessage.objects.get(role="assistant").status, "failed")

    def test_generation_failure_is_an_error_event_and_a_failed_message(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.chat.stream_error = RuntimeError("PRIVATE upstream detail")
        _, events = self.ask(conversation["id"], "Alpha?")
        names = [name for name, _ in events]
        self.assertIn("retrieval", names)
        self.assertEqual(names[-2:], ["stage", "error"])
        self.assertEqual(events[-2][1]["status"], "failed")
        error = events[-1][1]
        self.assertEqual((error["error"]["code"], error["error"]["stage"], error["error"]["retryable"]), ("provider_error", "generate", True))
        self.assertNotIn("PRIVATE", str(error))
        stored = ChatMessage.objects.get(role="assistant")
        self.assertEqual((stored.status, stored.error_code, stored.content), ("failed", "provider_error", ""))
        self.assertIsNotNone(stored.retrieval)  # retrieval had finished; kept for inspection

    def test_validation_errors_are_json_before_streaming(self):
        document = self.ready_text_document(LETTERS)
        conversation = self.conversation()
        for payload in ({}, {"content": ""}, {"content": "   "}, {"content": "x" * 4001},
                        {"content": "q", "document_ids": [999999]}, {"content": "q", "document_ids": "nope"}):
            with self.subTest(payload=str(payload)[:40]):
                response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
        other = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        foreign = self.post("/api/v1/conversations/", {"workspace_id": other["id"], "document_ids": [document["id"]]})
        self.assertEqual(foreign.status_code, 400)
        self.assertFalse(ChatMessage.objects.exists())

    def test_messages_left_streaming_by_a_dead_producer_are_failed_on_read(self):
        conversation = self.conversation()
        session = ChatSession.objects.get(pk=conversation["id"])
        stale = ChatMessage.objects.create(session=session, role="assistant", status="streaming")
        ChatMessage.objects.filter(pk=stale.pk).update(updated_at=timezone.now() - timedelta(minutes=11))
        fresh = ChatMessage.objects.create(session=session, role="assistant", status="streaming")
        listed = {row["id"]: row for row in self.get(f"/api/v1/conversations/{conversation['id']}/messages/").json()["results"]}
        self.assertEqual((listed[stale.pk]["status"], listed[stale.pk]["error"]["code"]), ("failed", "stream_interrupted"))
        self.assertEqual(listed[fresh.pk]["status"], "streaming")

    def test_a_client_that_stops_reading_leaves_a_failed_not_streaming_message(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "Alpha?"})
        stream = iter(response.streaming_content)
        next(stream)  # message.created only
        response.close()  # what the WSGI server does when the client goes away
        stored = ChatMessage.objects.get(role="assistant")
        self.assertEqual((stored.status, stored.error_code), ("failed", "stream_interrupted"))

    def test_leaving_after_the_last_token_keeps_the_finished_answer(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "Alpha?"})
        for frame in response.streaming_content:
            if b"event: stage" in frame and b'"id":"generate","status":"completed"' in frame:
                break  # message.completed not read yet
        response.close()
        stored = ChatMessage.objects.get(role="assistant")
        self.assertEqual((stored.status, stored.content), ("complete", self.chat.answer))


class ConversationCrudTests(ChatTestCase):
    def test_create_list_rename_rescope_and_delete(self):
        first = self.ready_text_document("Alpha paragraph in the first document here.")
        second = self.add_text("Beta paragraph in the second document here.")
        named = self.conversation(title="Retrieval methods", document_ids=[first["id"]])
        self.assertEqual(set(named), CONVERSATION_KEYS)
        self.assertEqual((named["title"], named["document_ids"], named["message_count"], named["last_message_preview"]),
                         ("Retrieval methods", [first["id"]], 0, ""))
        untitled = self.conversation()
        self.assertEqual(untitled["title"], "New conversation")

        # A named thread keeps its name after the first question.
        self.ask(named["id"], "Alpha?")
        self.assertEqual(self.get(f"/api/v1/conversations/{named['id']}/").json()["title"], "Retrieval methods")
        listed = [row["id"] for row in self.get("/api/v1/conversations/").json()["results"]]
        self.assertEqual(listed, [named["id"], untitled["id"]])  # most recently active first

        patched = self.patch(f"/api/v1/conversations/{untitled['id']}/", {"title": "Renamed", "document_ids": [first["id"], second["id"]]})
        self.assertEqual((patched.status_code, patched.json()["title"]), (200, "Renamed"))
        self.assertEqual(patched.json()["document_ids"], sorted([first["id"], second["id"]]))
        self.assertFalse(ChatSession.objects.get(pk=untitled["id"]).title_is_auto)
        cleared = self.patch(f"/api/v1/conversations/{untitled['id']}/", {"document_ids": []}).json()
        self.assertEqual(cleared["document_ids"], [])
        self.assertEqual(self.patch(f"/api/v1/conversations/{untitled['id']}/", {"title": " "}).status_code, 400)

        self.assertEqual(self.delete(f"/api/v1/conversations/{named['id']}/").status_code, 204)
        self.assertFalse(ChatMessage.objects.filter(session_id=named["id"]).exists())
        self.assertEqual(self.get(f"/api/v1/conversations/{named['id']}/").status_code, 404)

    def test_conversations_are_listed_per_workspace(self):
        self.get("/api/v1/workspaces/")  # creates the default, as the app does on load
        other = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        mine = self.conversation()
        theirs = self.conversation(workspace_id=other["id"])
        self.assertEqual([row["id"] for row in self.get("/api/v1/conversations/").json()["results"]], [mine["id"]])
        scoped = self.get(f"/api/v1/conversations/?workspace_id={other['id']}").json()["results"]
        self.assertEqual([row["id"] for row in scoped], [theirs["id"]])

    def test_deleting_a_document_keeps_answers_but_unlinks_the_turn(self):
        document = self.ready_text_document(LETTERS)
        conversation = self.conversation()
        self.ask(conversation["id"], "Alpha?")
        with self.captureOnCommitCallbacks(execute=True):
            self.delete(f"/api/v1/documents/{document['id']}/")
        answer = self.get(f"/api/v1/conversations/{conversation['id']}/messages/").json()["results"][1]
        self.assertEqual(answer["status"], "complete")
        self.assertIsNone(answer["analysis_turn"])


class AnotherUserTests(ChatTestCase):
    def test_a_conversation_never_reads_another_users_documents(self):
        self.ready_text_document(LETTERS)
        stranger = make_user("stranger")
        from workspace.tests.helpers import bearer
        auth = bearer(stranger)
        thread = self.client.post("/api/v1/conversations/", {}, content_type="application/json", **auth).json()
        response = self.client.post(f"/api/v1/conversations/{thread['id']}/messages/", {"content": "Alpha?"},
                                    content_type="application/json", **auth)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "no_ready_documents")
