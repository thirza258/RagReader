"""Shared fixtures for the evaluation lab tests: a ready corpus, datasets, experiments."""
from unittest import mock

from evaluation.models import Chunk
from lab.models import Experiment
from lab.services import runner
from workspace.tests.helpers import WorkspaceTestCase

LETTERS = (
    "Alpha is the first letter of the Greek alphabet.\n\n"
    "Gamma is the third letter, used for radiation.\n\n"
    "Delta is the fourth letter and means change."
)


def judge_report(faithfulness=0.9, relevancy=0.8, correctness=0.7):
    """What evaluation.eval.evaluate_response returns (Ragas through OpenRouter)."""
    scores = {"faithfulness": faithfulness, "answer_relevancy": relevancy, "factual_correctness": correctness}
    return {"scores": scores,
            "details": {"metrics": {name: {"status": "completed"} for name in scores}}}


class LabTestCase(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch("lab.tasks.run_experiment_task.delay")
        self.experiment_delay = patch.start()
        self.addCleanup(patch.stop)
        judge = mock.patch("lab.services.judge.legacy_eval.evaluate_response", return_value=judge_report())
        self.judge = judge.start()
        self.addCleanup(judge.stop)

    # ── Corpus ──────────────────────────────────────────────────────────────
    def ready_letters(self, title="Greek letters"):
        document = self.ready_text_document(LETTERS, title=title)
        chunks = {row.text.split()[0].lower(): row for row in Chunk.objects.filter(document_id=document["id"])}
        return document, chunks

    # ── Datasets ────────────────────────────────────────────────────────────
    def create_dataset(self, items, name="Letters QA", **extra):
        response = self.post("/api/v1/evaluations/datasets/", {"name": name, "items": items, **extra})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    # ── Experiments ─────────────────────────────────────────────────────────
    def create_experiment(self, dataset_id, **payload):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("/api/v1/experiments/", {"dataset_id": dataset_id, **payload})
        self.assertIn(response.status_code, (201, 202), response.content)
        return response.json()

    def run_queued(self, experiment_id):
        """Run the experiment as the worker would, with the token it was queued with."""
        token = Experiment.objects.get(pk=experiment_id).run_token
        return runner.run_experiment(experiment_id, token)

    def experiment(self, experiment_id):
        response = self.get(f"/api/v1/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def items(self, experiment_id, **params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        response = self.get(f"/api/v1/experiments/{experiment_id}/items/?{query}")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()
