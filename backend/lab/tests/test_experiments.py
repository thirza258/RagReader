"""Experiments end to end: run, metrics, runs, resume, cancel, failures (PRD §29, §31, §42)."""
import os
from datetime import timedelta
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from common.errors import PipelineError
from lab.models import Experiment, ExperimentItem
from lab.services import runner
from lab.tests.helpers import LabTestCase
from router.models import Document, GuestUser
from workspace.models import Pipeline, RetrievalRun, Workspace
from workspace.tests.helpers import bearer, make_user


class ExperimentRunTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.document, self.chunks = self.ready_letters()
        alpha, delta = self.chunks["alpha"], self.chunks["delta"]
        self.dataset = self.create_dataset([
            {"item_id": "q1", "question": "Which letter is alpha?", "expected_answer": "Alpha is the first letter.",
             "expected_sources": [{"document_id": self.document["id"], "chunk_id": alpha.pk}]},
            {"item_id": "q2", "question": "What does delta mean?",
             "expected_sources": [{"document_id": self.document["id"],
                                   "char_start": delta.metadata["char_start"], "char_end": delta.metadata["char_end"]}]},
            {"item_id": "q3", "question": "Which letter is gamma?"},
        ])

    def test_retrieval_only_scores_retrieval_and_makes_no_generation_call(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True, k_values=[1, 3])
        self.assertEqual(created["status"], "queued")
        self.experiment_delay.assert_called_once()
        self.assertTrue(self.run_queued(created["id"]))

        experiment = self.experiment(created["id"])
        self.assertEqual(experiment["status"], "completed")
        self.assertEqual(experiment["progress"], {"total": 3, "completed": 3, "failed": 0, "pending": 0})
        self.assertEqual(self.chat.stream_calls, [])
        self.judge.assert_not_called()
        retrieval = experiment["metrics"]["retrieval"]
        self.assertEqual(retrieval["recall@1"]["mean"], 1.0)  # alpha and delta rank first for their questions
        self.assertEqual(retrieval["mrr"]["count"], 2)
        self.assertEqual(retrieval["mrr"]["reasons"], {"no_expected_sources": 1})
        generation = experiment["metrics"]["generation"]["faithfulness"]
        self.assertEqual((generation["mean"], generation["reasons"]), (None, {"retrieval_only": 3}))
        self.assertIn("git_commit", experiment)  # null without a .git or GIT_COMMIT (as in this container)
        self.assertEqual(experiment["environment"]["models"]["judge"], None)
        self.assertEqual([entry["document_id"] for entry in experiment["index_versions"]], [self.document["id"]])

        items = self.items(created["id"])["results"]
        self.assertEqual([item["status"] for item in items], ["completed"] * 3)
        self.assertEqual(items[0]["matching"][0]["rule"], "chunk_id")
        self.assertEqual(items[1]["matching"][0]["rule"], "char_overlap")
        self.assertEqual([label["code"] for label in items[2]["failure_labels"]], ["ambiguous_question"])
        runs = RetrievalRun.objects.filter(source="evaluation")
        self.assertEqual(runs.count(), 3)
        self.assertTrue(all(run.provenance["evaluation"]["experiment_id"] == created["id"] for run in runs))

    def test_full_experiment_judges_answers_and_scores_citations(self):
        self.chat.answer = "Alpha comes first [1]."
        created = self.create_experiment(self.dataset["id"])
        self.assertTrue(self.run_queued(created["id"]))
        experiment = self.experiment(created["id"])
        self.assertEqual(experiment["status"], "completed")
        self.assertEqual(len(self.chat.stream_calls), 3)
        self.assertEqual(self.judge.call_count, 3)
        generation = experiment["metrics"]["generation"]
        self.assertEqual(generation["faithfulness"]["mean"], 0.9)
        self.assertEqual(generation["answer_relevance"]["mean"], 0.8)
        items = {item["item_id"]: item for item in self.items(created["id"])["results"]}
        # q1 cites [1], the alpha passage: every citation is expected evidence.
        self.assertEqual(items["q1"]["metrics"]["citation_correctness"], 1.0)
        self.assertEqual(items["q1"]["metrics"]["citation_completeness"], 1.0)
        # q2's answer cites [1], which for the delta question is the delta passage.
        self.assertEqual(items["q2"]["metric_reasons"].get("citation_correctness"), None)
        self.assertEqual(items["q3"]["metric_reasons"]["citation_correctness"], "no_expected_sources")
        self.assertEqual(items["q1"]["token_usage"]["prompt_tokens"], 50)
        self.assertIsNotNone(items["q1"]["latency_ms"]["generation"])
        run = RetrievalRun.objects.get(pk=items["q1"]["run_id"])
        self.assertEqual(run.source, "evaluation")
        span_names = [span.name for span in run.spans.order_by("ordinal")]
        for name in ("evaluation.item", "rewrite", "retrieve", "generate", "citations", "judge", "score"):
            self.assertIn(name, span_names)

    def test_evaluation_runs_are_left_out_of_the_chat_summary(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        self.run_queued(created["id"])
        default = self.get("/api/v1/retrieval/runs/summary/").json()
        self.assertEqual(default["runs"]["total"], 0)
        self.assertEqual(default["excluded_sources"], ["evaluation"])
        only = self.get("/api/v1/retrieval/runs/summary/?source=evaluation").json()
        self.assertEqual((only["runs"]["total"], only["excluded_sources"]), (3, []))

    def test_a_fatal_error_stops_the_run_and_resume_skips_completed_items(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        real = runner.chat.retrieve
        calls = []

        def flaky(engine, query, *args, **kwargs):
            calls.append(query)
            if len(calls) == 2:
                raise PipelineError("index_unavailable", "The index could not be loaded.", http_status=409)
            return real(engine, query, *args, **kwargs)

        with mock.patch.object(runner.chat, "retrieve", side_effect=flaky):
            self.assertFalse(self.run_queued(created["id"]))
        failed = self.experiment(created["id"])
        self.assertEqual((failed["status"], failed["error"]["code"]), ("failed", "index_unavailable"))
        self.assertEqual(failed["progress"], {"total": 3, "completed": 1, "failed": 0, "pending": 2})

        with self.captureOnCommitCallbacks(execute=True):
            restarted = self.post(f"/api/v1/experiments/{created['id']}/start/")
        self.assertEqual(restarted.status_code, 202, restarted.content)
        with mock.patch.object(runner.chat, "retrieve", side_effect=flaky):
            self.assertTrue(self.run_queued(created["id"]))
        # Two calls in the first run, then only the two remaining items.
        self.assertEqual(calls, ["Which letter is alpha?", "What does delta mean?",
                                 "What does delta mean?", "Which letter is gamma?"])
        done = self.experiment(created["id"])
        self.assertEqual(done["progress"]["completed"], 3)
        self.assertEqual(RetrievalRun.objects.filter(source="evaluation").count(), 3)

    def test_item_failures_are_recorded_and_three_in_a_row_fail_the_experiment(self):
        self.chat.stream_error = RuntimeError("model crashed")
        created = self.create_experiment(self.dataset["id"])
        self.assertFalse(self.run_queued(created["id"]))
        experiment = self.experiment(created["id"])
        self.assertEqual(experiment["status"], "failed")
        self.assertEqual(experiment["error"]["code"], "provider_error")
        items = self.items(created["id"], status="failed")["results"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["error"]["stage"], "generate")
        self.assertEqual(RetrievalRun.objects.filter(source="evaluation", status="failed").count(), 3)
        self.judge.assert_not_called()

    def test_cancel_stops_the_worker_at_its_next_heartbeat(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        original = runner.process_item

        def cancel_after_first(ctx, item):
            result = original(ctx, item)
            self.post(f"/api/v1/experiments/{created['id']}/cancel/")
            return result

        with mock.patch.object(runner, "process_item", side_effect=cancel_after_first):
            self.assertFalse(self.run_queued(created["id"]))
        cancelled = self.experiment(created["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["progress"]["pending"], 2)
        not_running = self.post(f"/api/v1/experiments/{created['id']}/cancel/")
        self.assertEqual((not_running.status_code, not_running.json()["error"]["code"]), (409, "experiment_not_running"))

    def test_a_duplicate_delivery_or_stale_token_does_nothing(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        token = Experiment.objects.get(pk=created["id"]).run_token
        self.assertTrue(runner.run_experiment(created["id"], token))
        self.assertFalse(runner.run_experiment(created["id"], token))
        self.assertFalse(runner.run_experiment(created["id"], "not-a-token"))
        self.assertEqual(RetrievalRun.objects.filter(source="evaluation").count(), 3)

    def test_draft_start_and_state_conflicts(self):
        draft = self.create_experiment(self.dataset["id"], draft=True)
        self.assertEqual(draft["status"], "draft")
        self.experiment_delay.assert_not_called()
        with self.captureOnCommitCallbacks(execute=True):
            started = self.post(f"/api/v1/experiments/{draft['id']}/start/")
        self.assertEqual(started.status_code, 202)
        again = self.post(f"/api/v1/experiments/{draft['id']}/start/")
        self.assertEqual((again.status_code, again.json()["error"]["code"]), (409, "experiment_in_progress"))
        self.run_queued(draft["id"])
        finished = self.post(f"/api/v1/experiments/{draft['id']}/start/")
        self.assertEqual(finished.json()["error"]["code"], "experiment_finished")

    def test_stalled_experiments_fail_on_read(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        Experiment.objects.filter(pk=created["id"]).update(heartbeat_at=timezone.now() - timedelta(minutes=40),
                                                          updated_at=timezone.now() - timedelta(minutes=40))
        stalled = self.experiment(created["id"])
        self.assertEqual((stalled["status"], stalled["error"]["code"]), ("failed", "experiment_stalled"))
        self.assertTrue(stalled["error"]["retryable"])

    def test_rerun_copies_the_configuration_and_reports_reproducibility(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True, seed=7)
        self.run_queued(created["id"])
        self.assertEqual(self.experiment(created["id"])["reproducibility"]["status"], "reproducible")
        # Editing the pipeline adds v2: the experiment's v1 still exists but is no longer latest.
        pipeline = Pipeline.objects.get(pk=created["pipeline"]["id"])
        self.patch(f"/api/v1/pipelines/{pipeline.pk}/", {"config": {"top_k": 3}})
        reproducibility = self.experiment(created["id"])["reproducibility"]
        self.assertEqual(reproducibility["status"], "changed")
        self.assertIn("pipeline_version_differs", [warning["code"] for warning in reproducibility["warnings"]])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(f"/api/v1/experiments/{created['id']}/rerun/")
        self.assertEqual(response.status_code, 202)
        copy = response.json()
        self.assertEqual((copy["rerun_of"], copy["seed"], copy["pipeline"]["version_id"]),
                         (created["id"], 7, created["pipeline"]["version_id"]))
        self.assertTrue(self.run_queued(copy["id"]))
        self.assertEqual(self.experiment(copy["id"])["progress"]["completed"], 3)

    def test_deleting_an_experiment_deletes_its_runs(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        self.run_queued(created["id"])
        self.assertEqual(self.delete(f"/api/v1/experiments/{created['id']}/").status_code, 204)
        self.assertFalse(RetrievalRun.objects.filter(source="evaluation").exists())
        self.assertFalse(ExperimentItem.objects.exists())

    def test_patch_records_the_conclusion(self):
        created = self.create_experiment(self.dataset["id"], draft=True)
        response = self.patch(f"/api/v1/experiments/{created['id']}/", {"conclusion": "Supported.", "name": "Renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["conclusion"], response.json()["name"]), ("Supported.", "Renamed"))

    def test_item_filters_by_failure_category_and_label(self):
        created = self.create_experiment(self.dataset["id"], retrieval_only=True)
        self.run_queued(created["id"])
        dataset_items = self.items(created["id"], category="dataset")
        self.assertEqual([item["item_id"] for item in dataset_items["results"]], ["q3"])
        self.assertEqual(self.items(created["id"], label="ambiguous_question")["count"], 1)
        bad = self.get(f"/api/v1/experiments/{created['id']}/items/?label=nope")
        self.assertEqual(bad.status_code, 400)


class ExperimentValidationTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.document, self.chunks = self.ready_letters()
        self.dataset = self.create_dataset([{"question": "Which letter is alpha?"}])

    def test_invalid_inputs_are_400_with_field_details(self):
        response = self.post("/api/v1/experiments/", {"dataset_id": self.dataset["id"], "k_values": [0, 99],
                                                      "seed": -1, "retrieval_only": "yes", "judge_model": "nope"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()["error"]["details"]), {"k_values", "seed", "retrieval_only", "judge_model"})

    def test_empty_dataset_and_unready_documents_are_409(self):
        empty = self.create_dataset([], name="Empty")
        response = self.post("/api/v1/experiments/", {"dataset_id": empty["id"]})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "dataset_empty"))
        Document.objects.filter(pk=self.document["id"]).update(status=Document.Status.EMBEDDING)
        response = self.post("/api/v1/experiments/", {"dataset_id": self.dataset["id"]})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "no_ready_documents"))

    def test_another_users_pipeline_version_is_refused(self):
        other = make_user("mallory")
        other_workspace = Workspace.objects.create(user=other, name="Theirs", is_default=True)
        from workspace.services import pipelines
        version = pipelines.latest_version(pipelines.default_pipeline_for(other_workspace))
        response = self.post("/api/v1/experiments/", {"dataset_id": self.dataset["id"], "pipeline_version_id": version.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("pipeline_version_id", response.json()["error"]["details"])


class ExperimentAccessTests(LabTestCase):
    def test_tokens_and_ownership(self):
        document, _chunks = self.ready_letters()
        dataset = self.create_dataset([{"question": "Which letter is alpha?"}])
        created = self.create_experiment(dataset["id"], draft=True)
        for path in ("/api/v1/experiments/", f"/api/v1/experiments/{created['id']}/",
                     f"/api/v1/experiments/{created['id']}/items/", "/api/v1/evaluations/datasets/",
                     f"/api/v1/evaluations/datasets/{dataset['id']}/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        mallory = bearer(make_user("mallory"))
        for path in (f"/api/v1/experiments/{created['id']}/", f"/api/v1/experiments/{created['id']}/items/",
                     f"/api/v1/evaluations/datasets/{dataset['id']}/",
                     f"/api/v1/evaluations/datasets/{dataset['id']}/items/",
                     f"/api/v1/experiments/compare/?ids={created['id']},{created['id'] + 1}"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, auth=mallory).status_code, 404)
        for path in (f"/api/v1/experiments/{created['id']}/start/", f"/api/v1/experiments/{created['id']}/cancel/",
                     f"/api/v1/experiments/{created['id']}/rerun/"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, auth=mallory).status_code, 404)
        stolen = self.post("/api/v1/experiments/", {"dataset_id": dataset["id"]}, auth=mallory)
        self.assertEqual(stolen.status_code, 404)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class QueueFailureTests(TransactionTestCase):
    def test_an_unreachable_worker_fails_the_experiment_with_503(self):
        user = GuestUser.objects.create(username="alice", email="alice@example.com")
        workspace = Workspace.objects.create(user=user, name="Mine", is_default=True)
        Document.objects.create(user=user, workspace=workspace, name="Ready", source_type="text",
                                status=Document.Status.READY, metadata={})
        from lab.services import datasets
        dataset, _version = datasets.create_dataset(workspace, name="QA", raw_items=[{"question": "Anything?"}])
        with mock.patch("lab.tasks.run_experiment_task.delay", side_effect=ConnectionError("no broker")):
            response = self.client.post("/api/v1/experiments/", {"dataset_id": dataset.pk},
                                        content_type="application/json", **bearer(user))
        self.assertEqual(response.status_code, 503, response.content)
        body = response.json()
        self.assertEqual(body["error"]["code"], "job_queue_unavailable")
        self.assertEqual(body["experiment"]["status"], "failed")
        self.assertTrue(body["experiment"]["error"]["retryable"])
        self.assertEqual(Experiment.objects.get().status, "failed")


class ComparisonApiTests(LabTestCase):
    def test_two_pipelines_compared_on_one_dataset(self):
        document, chunks = self.ready_letters()
        dataset = self.create_dataset([
            {"question": "Which letter is alpha?", "expected_sources": [{"document_id": document["id"], "chunk_id": chunks["alpha"].pk}]},
            {"question": "What does delta mean?", "expected_sources": [{"document_id": document["id"], "chunk_id": chunks["delta"].pk}]},
        ])
        bm25 = self.post("/api/v1/pipelines/", {"name": "Keywords", "config": {"strategy": "bm25"}})
        self.assertEqual(bm25.status_code, 201, bm25.content)
        dense = self.create_experiment(dataset["id"], retrieval_only=True)
        keyword = self.create_experiment(dataset["id"], retrieval_only=True, pipeline_id=bm25.json()["id"])
        self.assertTrue(self.run_queued(dense["id"]))
        self.assertTrue(self.run_queued(keyword["id"]))

        path = f"/api/v1/experiments/compare/?ids={dense['id']},{keyword['id']}"
        first = self.get(path)
        self.assertEqual(first.status_code, 200, first.content)
        body = first.json()
        self.assertEqual(body["baseline_id"], dense["id"])
        self.assertEqual(body["items"]["metric"], "recall@5")
        recall = next(row for row in body["metrics"] if row["key"] == "recall@5")
        self.assertEqual([cell["experiment_id"] for cell in recall["cells"]], [dense["id"], keyword["id"]])
        self.assertEqual(recall["cells"][1]["pairs"], 2)
        self.assertIn("strategy", [row["key"] for row in body["config_differences"]])
        self.assertEqual(self.get(path).json(), body)  # seeded: identical intervals every time

        swapped = self.get(path + f"&baseline={keyword['id']}&metric=mrr").json()
        self.assertEqual((swapped["baseline_id"], swapped["items"]["metric"]), (keyword["id"], "mrr"))
        self.assertEqual(self.get(f"/api/v1/experiments/compare/?ids={dense['id']}").status_code, 400)
        other = self.create_dataset([{"question": "Gamma?"}], name="Other")
        third = self.create_experiment(other["id"], retrieval_only=True, draft=True)
        mixed = self.get(f"/api/v1/experiments/compare/?ids={dense['id']},{third['id']}")
        self.assertEqual(mixed.status_code, 400)
        self.assertIn("ids", mixed.json()["error"]["details"])
