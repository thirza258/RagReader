"""Research tasks end to end with a scripted model (PRD §22–25, §47)."""
import json
import os
import re
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.test import SimpleTestCase
from django.utils import timezone

from research.models import ResearchTask
from research.services import engine, runner
from router.models import Document
from workspace.models import RetrievalRun
from workspace.tests.helpers import WorkspaceTestCase, bearer, make_user

LETTERS = (
    "Alpha is the first letter of the Greek alphabet.\n\n"
    "Gamma is the third letter, used for radiation.\n\n"
    "Delta is the fourth letter and means change."
)
RIVERS = (
    "Delta is a landform where a river meets the sea.\n\n"
    "Alpha was never the first letter in this fictional alphabet.\n\n"
    "Epsilon marks small quantities in mathematics."
)


class ScriptedChat:
    """`client.chat.completions` answering each prompt by its "Task: <name>." line."""

    def __init__(self):
        self.replies = {}
        self.calls = []

    def create(self, **kwargs):
        prompt = kwargs["messages"][-1]["content"]
        self.calls.append(prompt)
        match = re.search(r"Task: ([a-z -]+)\.", prompt)
        script = self.replies.get(match.group(1) if match else "")
        if callable(script):
            content = script(prompt)
        elif isinstance(script, list):
            content = script.pop(0) if script else ""
        else:
            content = script or ""
        content = content if isinstance(content, str) else json.dumps(content)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def count(self, name):
        return sum(1 for prompt in self.calls if f"Task: {name}." in prompt)


class ResearchTestCase(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.script = ScriptedChat()
        self.pipeline.llm.client = SimpleNamespace(chat=SimpleNamespace(completions=self.script))
        patch = mock.patch("research.tasks.run_research_task.delay")
        self.research_delay = patch.start()
        self.addCleanup(patch.stop)
        self.letters = self.ready_text_document(LETTERS, title="Greek letters")
        self.rivers = self.ready_text_document(RIVERS, title="Rivers and symbols")

    def create(self, **payload):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("/api/v1/research/tasks/", payload)
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()

    def run_task(self, task_id):
        token = ResearchTask.objects.get(pk=task_id).run_token
        return runner.run_task(task_id, token)

    def task(self, task_id):
        response = self.get(f"/api/v1/research/tasks/{task_id}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def run_kind(self, **payload):
        created = self.create(**payload)
        self.run_task(created["id"])
        return self.task(created["id"])


class VerdictTests(SimpleTestCase):
    def test_counts_to_verdicts(self):
        cases = {
            (0, 0): ("insufficient_evidence", "low"), (3, 0): ("supported", "high"), (2, 0): ("supported", "moderate"),
            (1, 0): ("supported", "low"), (3, 1): ("supported", "moderate"), (0, 3): ("contradicted", "high"),
            (1, 2): ("contradicted", "moderate"), (2, 2): ("mixed", "low"), (3, 2): ("mixed", "low"),
        }
        for (supporting, contradicting), expected in cases.items():
            with self.subTest(supporting=supporting, contradicting=contradicting):
                self.assertEqual(engine.verdict_for(supporting, contradicting), expected)

    def test_json_replies_tolerate_fences_but_not_garbage(self):
        self.assertEqual(engine.parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(engine.parse_json_object('Here it is: {"a": [1]} done'), {"a": [1]})
        for bad in ("no json", "[1, 2]", "{broken"):
            with self.subTest(bad=bad), self.assertRaises(engine.OutputInvalid):
                engine.parse_json_object(bad)

    def test_coercion_by_field_type(self):
        self.assertEqual(engine.coerce("1,200", "number"), (1200, True))
        self.assertEqual(engine.coerce("yes", "boolean"), (True, True))
        self.assertEqual(engine.coerce("a; b", "list"), (["a", "b"], True))
        self.assertEqual(engine.coerce("many", "number"), (None, False))


class VerifyClaimTests(ResearchTestCase):
    def test_stances_drive_the_verdict_and_the_evidence_is_cited(self):
        self.script.replies["counter-query"] = "alpha not first letter"
        self.script.replies["claim assessment"] = lambda prompt: {
            "assessments": [{"id": 1, "stance": "supports", "rationale": "States it."},
                            {"id": 2, "stance": "supports", "rationale": "Agrees."},
                            {"id": 3, "stance": "contradicts", "rationale": "Disagrees."},
                            {"id": 99, "stance": "supports"}],
            "conclusion": "Mostly supported [1], though one passage disagrees [3].",
        }
        task = self.run_kind(kind="verify_claim", claim="Alpha is the first letter", document_ids=[self.letters["id"], self.rivers["id"]])
        self.assertEqual(task["status"], "completed", task.get("error"))
        result = task["result"]
        self.assertEqual((result["verdict"], result["confidence"]), ("supported", "moderate"))
        self.assertEqual((result["supporting"], result["contradicting"]), ([1, 2], [3]))
        self.assertEqual(result["counter_query"], "alpha not first letter")
        evidence = task["evidence"]
        self.assertGreaterEqual(len(evidence), 3)
        self.assertEqual({item["citation_id"] for item in evidence if item["cited"]}, {1, 2, 3})
        self.assertEqual(set(evidence[0]) >= {"document_id", "document_title", "chunk_id", "text", "char_start"}, True)
        run = RetrievalRun.objects.get(pk=task["run_id"])
        self.assertEqual((run.source, run.status), ("research", "completed"))
        self.assertEqual(run.provenance["research"], {"task_id": task["id"], "kind": "verify_claim"})
        self.assertIn("generate", [span.name for span in run.spans.all()])

        exported = self.get(f"/api/v1/research/tasks/{task['id']}/export/?format=md")
        self.assertEqual(exported.status_code, 200)
        text = exported.content.decode()
        self.assertIn("**Verdict:** supported (moderate confidence)", text)
        self.assertIn("## References", text)

    def test_no_evidence_is_insufficient_without_asking_the_model(self):
        self.script.replies["counter-query"] = "alpha"
        with mock.patch.object(engine.Session, "search", return_value=[]):
            task = self.run_kind(kind="verify_claim", claim="Zeta is purple", document_ids=[self.letters["id"]])
        self.assertEqual(task["result"]["verdict"], "insufficient_evidence")
        self.assertEqual(self.script.count("claim assessment"), 0)

    def test_two_unreadable_replies_fail_the_task_retryably(self):
        self.script.replies["counter-query"] = "alpha"
        self.script.replies["claim assessment"] = ["not json", '{"assessments": "nope"}']
        task = self.run_kind(kind="verify_claim", claim="Alpha is first", document_ids=[self.letters["id"]])
        self.assertEqual(task["status"], "failed")
        self.assertEqual((task["error"]["code"], task["error"]["retryable"]), ("research_output_invalid", True))
        self.assertEqual(RetrievalRun.objects.get(pk=task["run_id"]).status, "failed")
        with self.captureOnCommitCallbacks(execute=True):
            retried = self.post(f"/api/v1/research/tasks/{task['id']}/retry/")
        self.assertEqual((retried.status_code, retried.json()["status"]), (202, "queued"))


class MultiDocumentTests(ResearchTestCase):
    def test_ask_answers_per_document_and_drops_uncited_answers(self):
        def reply(prompt):
            return {"per_document": [{"document_id": self.letters["id"], "answer": "Alpha is first [1]."},
                                     {"document_id": self.rivers["id"], "answer": "It says otherwise."}],
                    "comparison": "They disagree [1].", "synthesis": "Context matters."}
        self.script.replies["multi-document answer"] = reply
        task = self.run_kind(kind="ask", question="Which letter is first?")
        rows = {row["document_id"]: row for row in task["result"]["per_document"]}
        self.assertTrue(rows[self.letters["id"]]["found"])
        self.assertEqual(rows[self.letters["id"]]["citation_ids"], [1])
        self.assertEqual((rows[self.rivers["id"]]["found"], rows[self.rivers["id"]]["answer"]), (False, None))
        self.assertEqual(task["result"]["comparison"], "They disagree [1].")

    def test_compare_keeps_only_evidence_backed_findings(self):
        def reply(prompt):
            return {"dimensions": [{"name": "Methodology", "difference": "One is about letters [1].",
                                    "findings": [{"document_id": self.letters["id"], "finding": "Lists letters [1]."},
                                                 {"document_id": self.rivers["id"], "finding": "Describes rivers."}]}],
                    "summary": "Different topics."}
        self.script.replies["document comparison"] = reply
        task = self.run_kind(kind="compare", document_ids=[self.letters["id"], self.rivers["id"]],
                        dimensions=["methodology", "dataset"])
        rows = task["result"]["dimensions"]
        self.assertEqual([row["name"] for row in rows], ["methodology", "dataset"])
        cells = {cell["document_id"]: cell for cell in rows[0]["findings"]}
        self.assertEqual(cells[self.letters["id"]]["status"], "found")
        self.assertEqual((cells[self.rivers["id"]]["status"], cells[self.rivers["id"]]["finding"]), ("not_stated", None))
        self.assertTrue(all(cell["status"] == "not_stated" for cell in rows[1]["findings"]))
        md = self.get(f"/api/v1/research/tasks/{task['id']}/export/").content.decode()
        self.assertIn("| Dimension | Greek letters | Rivers and symbols | Difference |", md)

    def test_compare_needs_two_to_four_documents(self):
        response = self.post("/api/v1/research/tasks/", {"kind": "compare", "document_ids": [self.letters["id"]]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("document_ids", response.json()["error"]["details"])

    def test_contradictions_validate_pairs(self):
        def reply(prompt):
            return {"contradictions": [{"a": 1, "b": 2, "severity": "direct", "explanation": "Disagree."},
                                       {"a": 2, "b": 1, "severity": "direct"}, {"a": 1, "b": 1}, {"a": 1, "b": 99}],
                    "summary": "One conflict [1]."}
        self.script.replies["contradiction detection"] = reply
        task = self.run_kind(kind="contradictions", topic="alpha first letter")
        pairs = task["result"]["contradictions"]
        self.assertEqual(len(pairs), 1)
        self.assertEqual((pairs[0]["a"], pairs[0]["b"], pairs[0]["severity"]), (1, 2, "direct"))
        self.assertIn("cross_document", pairs[0])


class ExtractionAndReportTests(ResearchTestCase):
    def test_every_extracted_value_needs_a_citation(self):
        self.script.replies["evidence extraction"] = {"fields": {
            "letter_count": {"value": "3", "citations": [1]},
            "names": {"value": ["Alpha", "Gamma"], "citations": [1, 2]},
            "is_greek": {"value": "yes", "citations": []},
            "author": {"value": None, "citations": []},
            "year": {"value": "soon", "citations": [1]},
        }}
        task = self.run_kind(kind="extract", document_ids=[self.letters["id"]], fields=[
            {"name": "letter_count", "type": "number"}, {"name": "names", "type": "list"},
            {"name": "is_greek", "type": "boolean"}, "author", {"name": "year", "type": "number"},
        ])
        rows = {row["name"]: row for row in task["result"]["fields"]}
        self.assertEqual((rows["letter_count"]["value"], rows["letter_count"]["status"]), (3, "found"))
        self.assertEqual(rows["names"]["value"], ["Alpha", "Gamma"])
        self.assertEqual((rows["is_greek"]["value"], rows["is_greek"]["status"]), (None, "uncited"))
        self.assertEqual(rows["author"]["status"], "not_found")
        self.assertEqual(rows["year"]["status"], "invalid")
        self.assertEqual(task["result"]["data"], {"letter_count": 3, "names": ["Alpha", "Gamma"], "is_greek": None,
                                                  "author": None, "year": None})

    def test_report_falls_back_to_a_fixed_outline_when_the_plan_is_unreadable(self):
        self.script.replies["research plan"] = ["garbage", "still garbage"]
        self.script.replies["research report"] = {"title": "Letters", "summary": "Alpha leads [1].",
                                                  "sections": [{"heading": "Findings", "body": "Alpha first [1]."}],
                                                  "limitations": "Small corpus."}
        task = self.run_kind(kind="report", question="What do the documents say about alpha?")
        self.assertEqual(task["status"], "completed", task.get("error"))
        self.assertEqual(task["result"]["title"], "Letters")
        self.assertIn("Findings", self.script.calls[-1])  # the fallback outline reached the writer
        md = self.get(f"/api/v1/research/tasks/{task['id']}/export/?format=md").content.decode()
        self.assertIn("## Findings", md)
        self.assertIn("## Limitations", md)


class LifecycleAndAccessTests(ResearchTestCase):
    def test_validation_errors(self):
        cases = [({"kind": "verify_claim"}, "claim"), ({"kind": "nope"}, "kind"),
                 ({"kind": "extract", "fields": [{"name": "x", "type": "date"}]}, "fields[0]"),
                 ({"kind": "ask", "question": "q", "document_ids": ["a"]}, "document_ids")]
        for payload, field in cases:
            with self.subTest(payload=payload):
                response = self.post("/api/v1/research/tasks/", payload)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json()["error"]["details"])

    def test_documents_must_be_ready(self):
        Document.objects.filter(pk=self.rivers["id"]).update(status=Document.Status.EMBEDDING)
        response = self.post("/api/v1/research/tasks/", {"kind": "ask", "question": "q",
                                                         "document_ids": [self.letters["id"], self.rivers["id"]]})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "documents_not_ready"))

    def test_cancel_stale_token_and_stall(self):
        created = self.create(kind="ask", question="Which letter is first?")
        token = ResearchTask.objects.get(pk=created["id"]).run_token
        self.assertEqual(self.post(f"/api/v1/research/tasks/{created['id']}/cancel/").json()["status"], "cancelled")
        self.assertFalse(runner.run_task(created["id"], token))
        again = self.post(f"/api/v1/research/tasks/{created['id']}/cancel/")
        self.assertEqual((again.status_code, again.json()["error"]["code"]), (409, "task_not_running"))
        stalled = self.create(kind="ask", question="Which letter is first?")
        ResearchTask.objects.filter(pk=stalled["id"]).update(heartbeat_at=timezone.now() - timedelta(minutes=20),
                                                            updated_at=timezone.now() - timedelta(minutes=20))
        self.assertEqual(self.task(stalled["id"])["error"]["code"], "task_stalled")

    def test_tokens_and_ownership(self):
        created = self.create(kind="ask", question="Which letter is first?")
        for path in ("/api/v1/research/tasks/", f"/api/v1/research/tasks/{created['id']}/", "/api/v1/research/options/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        mallory = bearer(make_user("mallory"))
        for path in (f"/api/v1/research/tasks/{created['id']}/", f"/api/v1/research/tasks/{created['id']}/export/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, auth=mallory).status_code, 404)
        self.assertEqual(self.post(f"/api/v1/research/tasks/{created['id']}/cancel/", auth=mallory).status_code, 404)
        self.assertEqual(self.get("/api/v1/research/tasks/", auth=mallory).json()["results"], [])
        theirs = self.post("/api/v1/research/tasks/", {"kind": "ask", "question": "q",
                                                       "document_ids": [self.letters["id"]]}, auth=mallory)
        self.assertEqual(theirs.status_code, 409)  # not their document: their workspace has none READY

    def test_options_list_kinds_and_defaults(self):
        options = self.get("/api/v1/research/options/").json()
        self.assertEqual([kind["id"] for kind in options["kinds"]],
                         ["verify_claim", "ask", "compare", "extract", "contradictions", "report"])
        self.assertEqual(options["default_dimensions"][0], "methodology")

    def test_delete_removes_the_run_and_patch_keeps_notes(self):
        self.script.replies["multi-document answer"] = {"per_document": [], "comparison": "", "synthesis": ""}
        task = self.run_kind(kind="ask", question="Which letter is first?")
        patched = self.patch(f"/api/v1/research/tasks/{task['id']}/", {"notes": "Check the rivers paper.", "title": "Firsts"})
        self.assertEqual((patched.json()["notes"], patched.json()["title"]), ("Check the rivers paper.", "Firsts"))
        self.assertEqual(self.delete(f"/api/v1/research/tasks/{task['id']}/").status_code, 204)
        self.assertFalse(RetrievalRun.objects.filter(source="research").exists())


from django.test import TransactionTestCase, override_settings  # noqa: E402

from router.models import GuestUser  # noqa: E402
from workspace.models import Workspace  # noqa: E402


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class QueueFailureTests(TransactionTestCase):
    def test_an_unreachable_worker_fails_the_task_with_503(self):
        user = GuestUser.objects.create(username="alice", email="alice@example.com")
        workspace = Workspace.objects.create(user=user, name="Mine", is_default=True)
        Document.objects.create(user=user, workspace=workspace, name="Ready", source_type="text",
                                status=Document.Status.READY, metadata={})
        with mock.patch("research.tasks.run_research_task.delay", side_effect=ConnectionError("no broker")):
            response = self.client.post("/api/v1/research/tasks/", {"kind": "ask", "question": "Anything?"},
                                        content_type="application/json", **bearer(user))
        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(response.json()["error"]["code"], "job_queue_unavailable")
        self.assertEqual(response.json()["task"]["status"], "failed")
