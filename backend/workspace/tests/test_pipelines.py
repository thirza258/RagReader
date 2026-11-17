"""Pipelines, immutable versions, conversation selection and index versions (PRD §17–20, §33)."""
from router.models import Document
from workspace.models import ChatSession, ImmutableVersionError, Pipeline, PipelineVersion, RetrievalRun, Workspace
from workspace.services import pipelines
from workspace.tests.helpers import bearer, make_user
from workspace.tests.test_chat import LETTERS
from workspace.tests.test_runs import RunTestCase

PIPELINE_KEYS = {"id", "workspace_id", "name", "is_default", "version", "version_count", "versions", "created_at", "updated_at"}
VERSION_KEYS = {"id", "pipeline_id", "number", "config", "config_hash", "created_at"}
INDEX_KEYS = {"id", "document_id", "document_title", "method", "status", "is_current", "embedding_model", "chunk_config",
              "chunk_count", "created_at", "updated_at"}
PHASE1_CONFIG = {
    "strategy": "dense", "fusion": "weighted", "hybrid_weight": 0.6, "rrf_k": 60, "candidate_k": 20, "top_k": 5,
    "reranker": None, "generation_model": "openai/gpt-4o-mini", "temperature": 0.0, "prompt_version": "chat-cited-v1",
    "embedding_model": "openai/text-embedding-3-small",
}


class PipelineTestCase(RunTestCase):
    def pipelines(self, auth=None, **params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        response = self.get(f"/api/v1/pipelines/{'?' + query if query else ''}", auth=auth)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def create(self, name="Hybrid", status=201, **config):
        response = self.post("/api/v1/pipelines/", {"name": name, "config": config})
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def edit(self, pipeline_id, status=200, **body):
        response = self.patch(f"/api/v1/pipelines/{pipeline_id}/", body)
        self.assertEqual(response.status_code, status, response.content)
        return response.json()


class DefaultPipelineTests(PipelineTestCase):
    def test_every_workspace_gets_a_phase1_default_on_first_use(self):
        rows = self.pipelines()
        self.assertEqual(len(rows), 1)
        default = rows[0]
        self.assertEqual(set(default), PIPELINE_KEYS)
        self.assertEqual((default["name"], default["is_default"], default["version_count"]), ("Default (dense)", True, 1))
        self.assertEqual(set(default["version"]), VERSION_KEYS)
        self.assertEqual((default["version"]["number"], default["version"]["config"]), (1, PHASE1_CONFIG))
        self.assertEqual(default["version"]["config_hash"], pipelines.config_hash(PHASE1_CONFIG))
        self.assertEqual(len(self.pipelines()), 1)  # created once
        other = self.post("/api/v1/workspaces/", {"name": "Second"}).json()
        self.assertFalse(other["is_default"])
        self.assertNotEqual(self.pipelines(workspace_id=other["id"])[0]["id"], default["id"])

    def test_the_default_cannot_be_deleted(self):
        default = self.pipelines()[0]
        response = self.delete(f"/api/v1/pipelines/{default['id']}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "default_pipeline")

    def test_options_describe_the_form(self):
        response = self.get("/api/v1/pipelines/options/")
        self.assertEqual(response.status_code, 200)
        options = response.json()
        self.assertEqual([item["id"] for item in options["strategies"]], ["dense", "bm25", "hybrid", "hybrid_rerank"])
        self.assertEqual([item["id"] for item in options["fusion_methods"]], ["weighted", "rrf"])
        self.assertEqual([item["id"] for item in options["reranker_providers"]], ["ollama", "llm"])
        self.assertIn("nomic-embed-text", [model["id"] for model in options["reranker_providers"][0]["models"]])
        self.assertEqual(options["ranges"]["candidate_k"], {"min": 1, "max": 50})
        self.assertEqual(options["ranges"]["top_k"], {"min": 1, "max": 20})
        self.assertEqual(options["ranges"]["hybrid_weight"], {"min": 0.0, "max": 1.0})
        self.assertEqual(options["defaults"], PHASE1_CONFIG)
        self.assertEqual(options["embedding_models"], ["openai/text-embedding-3-small"])


class ValidationTests(PipelineTestCase):
    def test_create_merges_onto_the_defaults(self):
        created = self.create("Hybrid RRF", strategy="hybrid", fusion="rrf", rrf_k=30, candidate_k=30, top_k=8)
        self.assertEqual(set(created), PIPELINE_KEYS)
        self.assertFalse(created["is_default"])
        self.assertEqual(created["version"]["config"], {**PHASE1_CONFIG, "strategy": "hybrid", "fusion": "rrf", "rrf_k": 30,
                                                       "candidate_k": 30, "top_k": 8})
        self.assertEqual(len(self.pipelines()), 2)

    def test_invalid_values_are_rejected_per_field(self):
        cases = [
            ({"strategy": "magic"}, "config.strategy"),
            ({"candidate_k": 0}, "config.candidate_k"),
            ({"candidate_k": 51}, "config.candidate_k"),
            ({"candidate_k": 2.5}, "config.candidate_k"),
            ({"top_k": 21}, "config.top_k"),
            ({"top_k": 10, "candidate_k": 5}, "config.top_k"),
            ({"hybrid_weight": 1.5}, "config.hybrid_weight"),
            ({"hybrid_weight": True}, "config.hybrid_weight"),
            ({"rrf_k": 0}, "config.rrf_k"),
            ({"temperature": 2.5}, "config.temperature"),
            ({"generation_model": "not a model"}, "config.generation_model"),
            ({"prompt_version": "v9"}, "config.prompt_version"),
            ({"fusion": "max"}, "config.fusion"),
            ({"colour": "blue"}, "config.colour"),
            ({"strategy": "dense", "reranker": {"provider": "ollama", "model": "nomic-embed-text"}}, "config.reranker"),
            ({"strategy": "hybrid_rerank", "reranker": None}, "config.reranker"),
            ({"strategy": "hybrid_rerank", "reranker": {"provider": "cohere", "model": "x"}}, "config.reranker"),
            ({"strategy": "hybrid_rerank", "reranker": {"provider": "ollama", "model": "unknown-model"}}, "config.reranker"),
            ({"strategy": "hybrid_rerank", "reranker": {"provider": "llm", "model": "no-slash"}}, "config.reranker"),
        ]
        for config, field in cases:
            body = self.create(status=400, **config)
            self.assertEqual(body["error"]["code"], "invalid_request", config)
            self.assertIn(field, body["error"]["details"], config)
        self.assertEqual(len(self.pipelines()), 1)  # nothing was created

    def test_an_embedding_model_other_than_the_index_model_is_rejected(self):
        body = self.create(status=400, embedding_model="google/gemini-embedding-001")
        self.assertEqual(body["error"]["code"], "invalid_request")
        message = body["error"]["details"]["config.embedding_model"][0]
        self.assertIn("openai/text-embedding-3-small", message)
        default = self.pipelines()[0]
        body = self.edit(default["id"], status=400, config={"embedding_model": "google/gemini-embedding-001"})
        self.assertIn("config.embedding_model", body["error"]["details"])

    def test_rerank_strategy_gets_the_default_reranker_and_other_strategies_drop_it(self):
        created = self.create("Rerank", strategy="hybrid_rerank")
        self.assertEqual(created["version"]["config"]["reranker"], {"provider": "ollama", "model": "nomic-embed-text"})
        llm = self.edit(created["id"], config={"reranker": {"provider": "llm", "model": "openai/gpt-4o-mini"}})
        self.assertEqual(llm["version"]["config"]["reranker"], {"provider": "llm", "model": "openai/gpt-4o-mini"})
        dense = self.edit(created["id"], config={"strategy": "dense"})
        self.assertIsNone(dense["version"]["config"]["reranker"])
        prefixed = self.create("Prefixed", strategy="hybrid_rerank", reranker={"provider": "ollama", "model": "ollama/bge-m3"})
        self.assertEqual(prefixed["version"]["config"]["reranker"]["model"], "bge-m3")

    def test_names_and_config_shapes(self):
        self.assertEqual(self.post("/api/v1/pipelines/", {"name": "   "}).status_code, 400)
        self.assertEqual(self.post("/api/v1/pipelines/", {"name": "x", "config": [1]}).status_code, 400)
        self.assertEqual(self.post("/api/v1/pipelines/", {"config": {}}).status_code, 400)


class VersioningTests(PipelineTestCase):
    def test_editing_adds_a_version_and_versions_never_change(self):
        created = self.create("Mine", strategy="hybrid")
        first = created["version"]
        edited = self.edit(created["id"], config={"hybrid_weight": 0.8, "top_k": 3})
        self.assertTrue(edited["version_created"])
        self.assertEqual((edited["version"]["number"], edited["version_count"]), (2, 2))
        self.assertEqual(edited["version"]["config"]["hybrid_weight"], 0.8)
        self.assertNotEqual(edited["version"]["config_hash"], first["config_hash"])
        # Version 1 is untouched.
        stored = PipelineVersion.objects.get(pk=first["id"])
        self.assertEqual((stored.config, stored.config_hash), (first["config"], first["config_hash"]))
        stored.config = {"strategy": "bm25"}
        with self.assertRaises(ImmutableVersionError):
            stored.save()
        self.assertEqual(PipelineVersion.objects.get(pk=first["id"]).config, first["config"])

        same = self.edit(created["id"], config={"hybrid_weight": 0.8})
        self.assertFalse(same["version_created"])
        renamed = self.edit(created["id"], name="Renamed")
        self.assertEqual((renamed["name"], renamed["version"]["number"], renamed["version_created"]), ("Renamed", 2, False))

        versions = self.get(f"/api/v1/pipelines/{created['id']}/versions/").json()
        self.assertEqual(versions["pipeline_id"], created["id"])
        self.assertEqual([row["number"] for row in versions["results"]], [2, 1])
        self.assertEqual(set(versions["results"][0]), VERSION_KEYS)
        self.assertEqual(versions["results"][1]["config"], first["config"])
        self.assertEqual([row["number"] for row in self.get(f"/api/v1/pipelines/{created['id']}/").json()["versions"]], [2, 1])

    def test_each_answer_records_the_version_it_ran_with(self):
        self.ready_text_document(LETTERS, title="Greek letters")
        created = self.create("Mine", strategy="dense", top_k=2)
        conversation = self.conversation(pipeline_id=created["id"])
        self.assertEqual(conversation["pipeline_id"], created["id"])
        _, events = self.ask(conversation["id"], "alpha")
        first = self.completed(events)["message"]
        v1 = created["version"]
        self.assertEqual(first["retrieval"]["pipeline_version_id"], v1["id"])
        self.assertEqual(first["retrieval"]["pipeline_version"], {"id": v1["id"], "pipeline_id": created["id"], "name": "Mine", "number": 1})
        self.assertEqual(first["retrieval"]["context_count"], 2)
        run = RetrievalRun.objects.get(pk=first["retrieval"]["run_id"])
        self.assertEqual(run.pipeline_version_id, v1["id"])
        self.assertEqual(run.provenance["pipeline"], {
            "pipeline_id": created["id"], "name": "Mine", "version_id": v1["id"], "version": 1,
            "config": v1["config"], "config_hash": v1["config_hash"],
        })
        detail = self.detail(run.pk)
        self.assertEqual(detail["pipeline_version_id"], v1["id"])
        self.assertEqual(detail["pipeline"], {"id": created["id"], "name": "Mine", "version": 1, "version_id": v1["id"]})

        # Edited between questions: the next answer uses the latest version.
        v2 = self.edit(created["id"], config={"top_k": 1})["version"]
        _, events = self.ask(conversation["id"], "gamma")
        second = self.completed(events)["message"]
        self.assertEqual((second["retrieval"]["pipeline_version_id"], second["retrieval"]["context_count"]), (v2["id"], 1))
        self.assertEqual(RetrievalRun.objects.get(pk=second["retrieval"]["run_id"]).pipeline_version_id, v2["id"])
        # The first answer still names version 1.
        stored = self.get(f"/api/v1/conversations/{conversation['id']}/messages/").json()["results"][1]
        self.assertEqual(stored["retrieval"]["pipeline_version_id"], v1["id"])

    def test_a_failed_turn_records_its_version_too(self):
        import os
        document = self.ready_text_document(LETTERS, title="Lost index")
        os.remove(Document.objects.get(pk=document["id"]).current_index.vectorstore_location)
        created = self.create("Mine", strategy="hybrid")
        conversation = self.conversation(pipeline_id=created["id"])
        _, events = self.ask(conversation["id"], "alpha")
        name, error = events[-1]
        self.assertEqual((name, error["error"]["code"]), ("error", "index_unavailable"))
        self.assertEqual(error["message"]["retrieval"]["pipeline_version_id"], created["version"]["id"])
        run = RetrievalRun.objects.get(pk=error["run_id"])
        self.assertEqual((run.status, run.pipeline_version_id), ("failed", created["version"]["id"]))
        self.assertEqual(run.provenance["pipeline"]["config"]["strategy"], "hybrid")

    def test_existing_conversations_follow_the_default_pipeline(self):
        self.ready_text_document(LETTERS)
        conversation = self.conversation()
        default = self.pipelines()[0]
        self.assertEqual(conversation["pipeline_id"], default["id"])
        self.assertIsNone(ChatSession.objects.get(pk=conversation["id"]).pipeline_id)
        _, events = self.ask(conversation["id"], "alpha")
        message = self.completed(events)["message"]
        self.assertEqual(message["retrieval"]["pipeline_version_id"], default["version"]["id"])
        self.assertEqual(message["retrieval"]["pipeline"]["strategy"], "dense")

    def test_deleting_a_pipeline_moves_its_conversations_to_the_default_and_keeps_run_provenance(self):
        self.ready_text_document(LETTERS)
        created = self.create("Temporary", strategy="bm25")
        conversation = self.conversation(pipeline_id=created["id"])
        _, events = self.ask(conversation["id"], "alpha")
        run_id = self.completed(events)["run_id"]
        self.assertEqual(self.delete(f"/api/v1/pipelines/{created['id']}/").status_code, 204)
        self.assertFalse(Pipeline.objects.filter(pk=created["id"]).exists())
        default = self.pipelines()[0]
        self.assertEqual(self.get(f"/api/v1/conversations/{conversation['id']}/").json()["pipeline_id"], default["id"])
        detail = self.detail(run_id)
        self.assertIsNone(detail["pipeline_version_id"])
        self.assertEqual(detail["pipeline"]["name"], "Temporary")
        self.assertEqual(detail["provenance"]["pipeline"]["config"]["strategy"], "bm25")


class ConversationSelectionTests(PipelineTestCase):
    def test_select_switch_and_reset_a_conversations_pipeline(self):
        first, second = self.create("One"), self.create("Two", strategy="bm25")
        conversation = self.conversation(pipeline_id=first["id"])
        patched = self.patch(f"/api/v1/conversations/{conversation['id']}/", {"pipeline_id": second["id"]})
        self.assertEqual((patched.status_code, patched.json()["pipeline_id"]), (200, second["id"]))
        reset = self.patch(f"/api/v1/conversations/{conversation['id']}/", {"pipeline_id": None}).json()
        self.assertEqual(reset["pipeline_id"], self.pipelines()[0]["id"])
        listed = self.get("/api/v1/conversations/").json()["results"]
        self.assertEqual(listed[0]["pipeline_id"], self.pipelines()[0]["id"])

    def test_pipelines_of_other_workspaces_and_users_are_invalid(self):
        self.pipelines()  # creates the default workspace first
        other_workspace = self.post("/api/v1/workspaces/", {"name": "Other"}).json()
        self.assertFalse(other_workspace["is_default"])
        elsewhere = self.post("/api/v1/pipelines/", {"name": "Elsewhere", "workspace_id": other_workspace["id"]}).json()
        bob = make_user("bob")
        bobs = self.post("/api/v1/pipelines/", {"name": "Bob's"}, auth=bearer(bob)).json()
        conversation = self.conversation()
        for pipeline_id in (elsewhere["id"], bobs["id"], 999999):
            created = self.post("/api/v1/conversations/", {"pipeline_id": pipeline_id})
            self.assertEqual(created.status_code, 400)
            self.assertIn("pipeline_id", created.json()["error"]["details"])
            patched = self.patch(f"/api/v1/conversations/{conversation['id']}/", {"pipeline_id": pipeline_id})
            self.assertEqual(patched.status_code, 400)
        # The two messages are identical, so ids cannot be probed.
        a = self.post("/api/v1/conversations/", {"pipeline_id": bobs["id"]}).json()["error"]["details"]["pipeline_id"][0]
        b = self.post("/api/v1/conversations/", {"pipeline_id": 999999}).json()["error"]["details"]["pipeline_id"][0]
        self.assertEqual(a.replace(str(bobs["id"]), "N"), b.replace("999999", "N"))

    def test_a_document_indexed_with_another_embedding_model_is_refused_before_streaming(self):
        document = self.ready_text_document(LETTERS, title="Old model")
        row = Document.objects.get(pk=document["id"])
        row.metadata = {**row.metadata, "embedding_model": "legacy/embedder"}
        row.save(update_fields=["metadata"])
        conversation = self.conversation()
        response = self.post(f"/api/v1/conversations/{conversation['id']}/messages/", {"content": "alpha"})
        self.assertEqual(response.status_code, 409)
        error = response.json()["error"]
        self.assertEqual(error["code"], "embedding_model_mismatch")
        self.assertIn("Old model", error["message"])
        self.assertIn("legacy/embedder", error["message"])
        # BM25 does not embed the question, so it can still search the document.
        bm25 = self.create("Keywords", strategy="bm25")
        self.patch(f"/api/v1/conversations/{conversation['id']}/", {"pipeline_id": bm25["id"]})
        _, events = self.ask(conversation["id"], "alpha")
        self.assertEqual(self.completed(events)["message"]["status"], "complete")

    def test_documents_without_a_recorded_model_are_let_through(self):
        document = self.ready_text_document(LETTERS)
        row = Document.objects.get(pk=document["id"])
        row.metadata = {key: value for key, value in row.metadata.items() if key != "embedding_model"}
        row.save(update_fields=["metadata"])
        conversation = self.conversation()
        _, events = self.ask(conversation["id"], "alpha")
        self.assertEqual(self.completed(events)["message"]["status"], "complete")


class RunFilterTests(PipelineTestCase):
    def test_runs_filter_by_pipeline_version(self):
        self.ready_text_document(LETTERS)
        created = self.create("Mine")
        default = self.pipelines()[0]
        mine = self.conversation(pipeline_id=created["id"])
        theirs = self.conversation()
        mine_run = self.completed(self.ask(mine["id"], "alpha")[1])["run_id"]
        default_run = self.completed(self.ask(theirs["id"], "alpha")[1])["run_id"]
        self.assertEqual(self.ids(f"/api/v1/retrieval/runs/?pipeline_version_id={created['version']['id']}"), [mine_run])
        self.assertEqual(self.ids(f"/api/v1/retrieval/runs/?pipeline_version_id={default['version']['id']}"), [default_run])
        listed = self.get("/api/v1/retrieval/runs/").json()["results"]
        self.assertEqual({row["pipeline_version_id"] for row in listed}, {created["version"]["id"], default["version"]["id"]})
        bad = self.get("/api/v1/retrieval/runs/?pipeline_version_id=abc")
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (400, "invalid_request"))
        bob = make_user("bob")
        bobs = self.post("/api/v1/pipelines/", {"name": "Bob's"}, auth=bearer(bob)).json()
        hidden = self.get(f"/api/v1/retrieval/runs/?pipeline_version_id={bobs['version']['id']}")
        self.assertEqual((hidden.status_code, hidden.json()["error"]["code"]), (404, "not_found"))


class OwnershipTests(PipelineTestCase):
    def test_another_users_pipelines_and_indexes_are_not_found(self):
        bob = make_user("bob")
        bob_auth = bearer(bob)
        bobs = self.post("/api/v1/pipelines/", {"name": "Bob's"}, auth=bob_auth).json()
        bob_document = self.ready_text_document(LETTERS, auth=bob_auth)
        bob_index = Document.objects.get(pk=bob_document["id"]).current_index_id
        for method, path in [
            ("get", f"/api/v1/pipelines/{bobs['id']}/"),
            ("patch", f"/api/v1/pipelines/{bobs['id']}/"),
            ("delete", f"/api/v1/pipelines/{bobs['id']}/"),
            ("get", f"/api/v1/pipelines/{bobs['id']}/versions/"),
            ("get", f"/api/v1/indexes/{bob_index}/"),
            ("get", f"/api/v1/indexes/?document_id={bob_document['id']}"),
            ("get", f"/api/v1/pipelines/?workspace_id={bobs['workspace_id']}"),
        ]:
            response = self.patch(path, {"name": "x"}) if method == "patch" else getattr(self, method)(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertEqual(response.json()["error"]["code"], "not_found", path)
        self.assertTrue(Pipeline.objects.filter(pk=bobs["id"], name="Bob's").exists())
        self.assertEqual(self.get("/api/v1/indexes/").json()["results"], [])

    def test_every_new_endpoint_requires_the_token(self):
        pipeline = self.pipelines()[0]
        for method, path in [
            ("get", "/api/v1/pipelines/"), ("post", "/api/v1/pipelines/"), ("get", "/api/v1/pipelines/options/"),
            ("get", f"/api/v1/pipelines/{pipeline['id']}/"), ("patch", f"/api/v1/pipelines/{pipeline['id']}/"),
            ("delete", f"/api/v1/pipelines/{pipeline['id']}/"), ("get", f"/api/v1/pipelines/{pipeline['id']}/versions/"),
            ("get", "/api/v1/indexes/"), ("get", "/api/v1/indexes/1/"),
        ]:
            for auth in ({}, {"HTTP_AUTHORIZATION": "Bearer rr_not-a-real-token"}):
                response = self.patch(path, {}, auth=auth) if method == "patch" else getattr(self, method)(path, auth=auth)
                self.assertEqual(response.status_code, 401, (method, path))
                self.assertEqual(response.json()["error"]["code"], "authentication_required")
                self.assertEqual(response["WWW-Authenticate"], "Bearer")
        self.assertTrue(Pipeline.objects.filter(pk=pipeline["id"]).exists())


class IndexVersionTests(PipelineTestCase):
    def test_a_documents_index_versions(self):
        document = self.ready_text_document(LETTERS, title="Greek letters")
        first_index = Document.objects.get(pk=document["id"]).current_index_id
        rows = self.get(f"/api/v1/indexes/?document_id={document['id']}").json()["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), INDEX_KEYS)
        self.assertEqual((rows[0]["id"], rows[0]["is_current"], rows[0]["method"], rows[0]["status"]), (first_index, True, "dense", "ready"))
        self.assertEqual((rows[0]["embedding_model"], rows[0]["chunk_count"]), ("openai/text-embedding-3-small", 3))
        self.assertEqual(rows[0]["chunk_config"], {"strategy": "paragraph", "chunk_size": 60, "overlap": 0})
        self.assertEqual(rows[0]["document_title"], "Greek letters")

        # A re-index adds a version; only the current one carries build settings.
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post(f"/api/v1/documents/{document['id']}/ingestion/").status_code, 202)
        self.assertTrue(self.ingest_last_queued())
        rows = self.get(f"/api/v1/indexes/?document_id={document['id']}").json()["results"]
        self.assertEqual(len(rows), 2)
        current = Document.objects.get(pk=document["id"]).current_index_id
        self.assertEqual([row["id"] for row in rows], [current, first_index])
        self.assertEqual([row["is_current"] for row in rows], [True, False])
        self.assertIsNone(rows[1]["embedding_model"])
        detail = self.get(f"/api/v1/indexes/{first_index}/").json()
        self.assertEqual((detail["id"], detail["is_current"]), (first_index, False))
        self.assertEqual(self.get("/api/v1/indexes/999999/").status_code, 404)
        self.assertEqual(self.get("/api/v1/indexes/?document_id=999999").status_code, 404)

    def test_without_a_document_every_index_of_the_workspace(self):
        first = self.ready_text_document(LETTERS, title="One")
        second = self.ready_text_document("Delta is the fourth letter and means change.", title="Two")
        rows = self.get("/api/v1/indexes/").json()["results"]
        self.assertEqual([row["document_id"] for row in rows], [second["id"], first["id"]])
        other = Workspace.objects.create(user=self.user, name="Empty")
        self.assertEqual(self.get(f"/api/v1/indexes/?workspace_id={other.pk}").json()["results"], [])
