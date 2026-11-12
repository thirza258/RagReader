"""The request tracer (PRD §32): span tree, timings, failures, bounds, and never failing."""
import json
from unittest import mock

from django.test import SimpleTestCase

from common.errors import PipelineError
from workspace.services import tracing
from workspace.services.tracing import Tracer, build_tree, error_code_for


class Clock:
    """A monotonic clock the test moves by hand (seconds)."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms / 1000.0


def tracer_with_clock():
    clock = Clock()
    return Tracer("request", "Request", origin=clock(), clock=clock), clock


class TracerTests(SimpleTestCase):
    def test_nested_spans_have_offsets_durations_and_a_preorder_export(self):
        tracer, clock = tracer_with_clock()
        clock.advance(5)
        with tracer.span("retrieve", "Retrieval", documents=2) as outer:
            clock.advance(10)
            with tracer.span("embed", "Query embedding") as inner:
                inner.set(dimensions=7)
                clock.advance(20)
            clock.advance(3)
            outer.set(candidates=4)
        clock.advance(2)
        with tracer.span("generate", "Generation") as generate:
            first = tracer.start("generate.first_token")
            clock.advance(8)
            tracer.finish(first)
            clock.advance(12)
        tracer.close()

        rows = tracer.export()
        self.assertEqual([(row["ordinal"], row["parent_ordinal"], row["depth"], row["name"]) for row in rows], [
            (0, None, 0, "request"), (1, 0, 1, "retrieve"), (2, 1, 2, "embed"),
            (3, 0, 1, "generate"), (4, 3, 2, "generate.first_token"),
        ])
        timing = {row["name"]: (row["start_ms"], row["duration_ms"]) for row in rows}
        self.assertEqual(timing["request"], (0.0, 60.0))
        self.assertEqual(timing["retrieve"], (5.0, 33.0))
        self.assertEqual(timing["embed"], (15.0, 20.0))
        self.assertEqual(timing["generate"], (40.0, 20.0))
        self.assertEqual(timing["generate.first_token"], (40.0, 8.0))
        self.assertTrue(all(row["status"] == "completed" for row in rows))
        self.assertEqual(rows[1]["data"], {"documents": 2, "candidates": 4})
        self.assertEqual(rows[2]["label"], "Query embedding")
        self.assertIs(generate.status, "completed")

        tree = build_tree(rows)
        self.assertEqual(len(tree), 1)
        self.assertEqual([child["name"] for child in tree[0]["children"]], ["retrieve", "generate"])
        self.assertEqual(tree[0]["children"][1]["children"][0]["name"], "generate.first_token")
        self.assertNotIn("ordinal", tree[0])

    def test_a_failure_closes_the_active_span_and_everything_inside_it(self):
        tracer, clock = tracer_with_clock()
        with self.assertRaises(PipelineError):
            with tracer.span("generate"):
                tracer.start("generate.first_token")
                clock.advance(4)
                raise PipelineError("provider_timeout", "timed out")
        tracer.close(error="provider_timeout")
        rows = {row["name"]: row for row in tracer.export()}
        for name in ("generate", "generate.first_token", "request"):
            self.assertEqual((rows[name]["status"], rows[name]["error_code"]), ("failed", "provider_timeout"), name)
        self.assertEqual(rows["generate.first_token"]["duration_ms"], 4.0)

    def test_unexpected_errors_and_disconnects_get_stable_codes(self):
        self.assertEqual(error_code_for(RuntimeError("PRIVATE")), "internal_error")
        self.assertEqual(error_code_for(GeneratorExit()), "stream_interrupted")
        self.assertEqual(error_code_for(PipelineError("index_unavailable", "x")), "index_unavailable")
        self.assertEqual(error_code_for("rewrite_failed"), "rewrite_failed")

        tracer, _clock = tracer_with_clock()
        with self.assertRaises(GeneratorExit):
            with tracer.span("generate"):
                raise GeneratorExit
        row = tracer.export()[1]
        self.assertEqual((row["status"], row["error_code"]), ("failed", "stream_interrupted"))

    def test_skipped_and_recovered_failures_keep_their_status(self):
        tracer, _clock = tracer_with_clock()
        with tracer.span("rewrite") as span:
            span.skip("First question")
        with tracer.span("rewrite.retry") as span:
            span.fail("rewrite_failed", "Fell back to the question")
        rows = tracer.export()
        self.assertEqual((rows[1]["status"], rows[1]["detail"]), ("skipped", "First question"))
        self.assertEqual((rows[2]["status"], rows[2]["error_code"]), ("failed", "rewrite_failed"))
        self.assertEqual(rows[0]["status"], "completed")

    def test_finishing_twice_or_a_foreign_span_does_nothing(self):
        tracer, clock = tracer_with_clock()
        span = tracer.start("a")
        clock.advance(3)
        tracer.finish(span)
        clock.advance(3)
        tracer.finish(span, error="late")
        tracer.finish(tracing.Span("stranger"))
        tracer.finish(None)
        row = tracer.export()[1]
        self.assertEqual((row["duration_ms"], row["status"]), (3.0, "completed"))

    def test_payloads_and_span_counts_are_bounded(self):
        tracer, _clock = tracer_with_clock()
        with tracer.span("big") as span:
            span.set(text="x" * 5000, items=list(range(100)), nested={"deep": {"deeper": {"deepest": 1}}})
            span.describe("d" * 1000)
        with tracer.span("huge") as span:
            span.set(**{f"key{index}": "y" * 190 for index in range(15)})
        for index in range(tracing.MAX_SPANS + 10):
            tracer.finish(tracer.start(f"s{index}"))
        rows = tracer.export()
        self.assertEqual(len(rows), tracing.MAX_SPANS)
        self.assertEqual(rows[0]["data"]["dropped_spans"], 13)  # 3 + 97 recorded, 13 not
        big = rows[1]
        self.assertEqual(len(big["data"]["text"]), tracing.MAX_STRING_CHARS)
        self.assertEqual(len(big["data"]["items"]), tracing.MAX_DATA_ITEMS)
        self.assertIsInstance(big["data"]["nested"]["deep"]["deeper"], str)  # flattened below two levels
        self.assertEqual(len(big["detail"]), tracing.MAX_DETAIL_CHARS)
        huge = rows[2]["data"]
        self.assertTrue(huge["truncated"])
        self.assertLessEqual(len(json.dumps(huge).encode()), tracing.MAX_DATA_BYTES + 32)

    def test_numpy_and_odd_values_become_json(self):
        import numpy as np
        data = tracing.bounded_data({"f": np.float32(0.5), "i": np.int64(3), "nan": float("nan"), "obj": object(), "flag": True})
        self.assertEqual((data["f"], data["i"], data["nan"], data["flag"]), (0.5, 3, None, True))
        self.assertIsInstance(data["obj"], str)

    def test_an_internal_failure_makes_the_tracer_inert_without_raising(self):
        tracer, _clock = tracer_with_clock()
        with mock.patch.object(Tracer, "_now_ms", side_effect=RuntimeError("clock broken")):
            with self.assertLogs("workspace.services.tracing", "WARNING") as logs:
                with tracer.span("a") as span:
                    span.set(ok=True)
                    tracer.finish(tracer.start("b"))
                tracer.close()
        self.assertEqual(len(logs.records), 1)  # logged once
        self.assertTrue(tracer.broken)
        self.assertEqual(tracer.export(), [])

    def test_a_span_scope_never_swallows_the_wrapped_exception(self):
        for broken in (False, True):
            with self.subTest(broken=broken):
                tracer, _clock = tracer_with_clock()
                tracer.broken = broken
                with self.assertRaises(ValueError):
                    with tracer.span("a"):
                        raise ValueError("the real error")

    def test_null_tracer_records_nothing(self):
        tracer = tracing.NullTracer()
        with tracer.span("a") as span:
            span.set(x=1)
        tracer.close()
        self.assertEqual(tracer.export(), [])
