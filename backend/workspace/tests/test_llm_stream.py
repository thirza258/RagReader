"""OpenRouterLLM.stream_chat, citation parsing and the cited chat prompt."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from ai_handler import llm as llm_module
from ai_handler.llm import OpenRouterLLM, StreamResult
from common.errors import PipelineError
from common.prompt_builder import cited_chat_messages, standalone_query_prompt
from workspace.services.citations import cited_ids, mark_cited
from workspace.tests.helpers import chunk

MESSAGES = [{"role": "user", "content": "question"}]


class CreditError(Exception):
    status_code = 402


def make_llm(create):
    with override_settings(OPENROUTER_API_KEY="test-key"):
        llm = OpenRouterLLM(model="openai/gpt-4o-mini")
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=mock.Mock(side_effect=create))))
    return llm


def collect(stream):
    deltas, results = [], []
    for item in stream:
        (results if isinstance(item, StreamResult) else deltas).append(item)
    return deltas, results


class StreamChatTests(SimpleTestCase):
    def test_streams_deltas_then_the_answering_model_and_usage(self):
        usage = SimpleNamespace(prompt_tokens=7, completion_tokens=2, total_tokens=9)
        llm = make_llm(lambda **kw: iter([chunk("Hello", "openai/gpt-4o-mini-2024-07-18"), chunk(" world", "openai/gpt-4o-mini-2024-07-18"),
                                          chunk(None, "openai/gpt-4o-mini-2024-07-18", usage)]))
        before = dict(llm.__dict__)
        deltas, results = collect(llm.stream_chat(MESSAGES))
        self.assertEqual(deltas, ["Hello", " world"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].model, "openai/gpt-4o-mini-2024-07-18")
        self.assertEqual(results[0].usage, {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9})
        call = llm.client.chat.completions.create.call_args.kwargs
        self.assertEqual((call["stream"], call["model"], call["messages"]), (True, "openai/gpt-4o-mini", MESSAGES))
        self.assertEqual(llm.__dict__, before)  # shared engines: no per-call state

    def test_credit_exhaustion_before_the_first_token_falls_back_to_a_free_model(self):
        def create(**kwargs):
            if kwargs["model"] == "openai/gpt-4o-mini":
                raise CreditError("402 Payment Required: insufficient credits")
            return iter([chunk("Free answer", kwargs["model"]), chunk(None, kwargs["model"])])

        llm = make_llm(create)
        with mock.patch.object(llm_module, "get_shuffled_free_models", return_value=["vendor/free-a:free", "vendor/free-b:free"]):
            deltas, results = collect(llm.stream_chat(MESSAGES))
        self.assertEqual((deltas, results[0].model), (["Free answer"], "vendor/free-a:free"))

    def test_a_credit_error_raised_while_opening_the_stream_iterator_also_falls_back(self):
        def failing_stream():
            raise CreditError("insufficient credits")
            yield  # pragma: no cover

        def create(**kwargs):
            if kwargs["model"] == "openai/gpt-4o-mini":
                return failing_stream()
            return iter([chunk("ok", kwargs["model"])])

        llm = make_llm(create)
        with mock.patch.object(llm_module, "get_shuffled_free_models", return_value=["vendor/free-a:free"]):
            deltas, results = collect(llm.stream_chat(MESSAGES))
        self.assertEqual((deltas, results[0].model), (["ok"], "vendor/free-a:free"))

    def test_free_models_are_tried_in_turn_and_exhaustion_reports_the_credit_error(self):
        def create(**kwargs):
            raise CreditError("insufficient credits")

        llm = make_llm(create)
        with mock.patch.object(llm_module, "get_shuffled_free_models", return_value=["vendor/a:free", "vendor/b:free"]):
            with self.assertRaises(PipelineError) as raised:
                collect(llm.stream_chat(MESSAGES))
        self.assertEqual(llm.client.chat.completions.create.call_count, 3)
        self.assertEqual(raised.exception.code, "provider_error")

    def test_no_fallback_once_text_has_been_sent(self):
        def stream():
            yield chunk("Partial")
            raise CreditError("insufficient credits")

        llm = make_llm(lambda **kw: stream())
        received = []
        with self.assertRaises(PipelineError):
            for item in llm.stream_chat(MESSAGES):
                received.append(item)
        self.assertEqual(received, ["Partial"])
        self.assertEqual(llm.client.chat.completions.create.call_count, 1)

    def test_other_errors_and_empty_answers_do_not_fall_back(self):
        for create, code in ((lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")), "provider_error"),
                             (lambda **kw: iter([chunk(None)]), "empty_model_response")):
            with self.subTest(code=code):
                llm = make_llm(create)
                with mock.patch.object(llm_module, "get_shuffled_free_models") as free:
                    with self.assertRaises(PipelineError) as raised:
                        collect(llm.stream_chat(MESSAGES))
                self.assertEqual(raised.exception.code, code)
                free.assert_not_called()


class CitationTests(SimpleTestCase):
    def test_marker_forms_and_out_of_range_numbers(self):
        answer = "One [1]. Two and three [2, 3]. Again [1][3]. Invented [9] and [0]. Not a marker [x]."
        self.assertEqual(cited_ids(answer, 3), [1, 2, 3])
        self.assertEqual(cited_ids(answer, 2), [1, 2])
        self.assertEqual(cited_ids("", 3), [])

    def test_mark_cited_copies_sources(self):
        sources = [{"citation_id": 1, "cited": False}, {"citation_id": 2, "cited": False}]
        marked = mark_cited(sources, "Only the second [2].")
        self.assertEqual([s["cited"] for s in marked], [False, True])
        self.assertEqual([s["cited"] for s in sources], [False, False])


class PromptTests(SimpleTestCase):
    def test_sources_are_numbered_and_history_markers_stripped(self):
        sources = [{"text": " Alpha text ", "document_title": "Paper A", "page_number": 4},
                   {"text": "Beta text", "document_title": "Paper B", "page_number": None}]
        history = [{"role": "user", "content": "Earlier question"},
                   {"role": "assistant", "content": "Earlier answer [1] with more [2, 3]."}]
        messages = cited_chat_messages("Now what?", sources, history)
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertIn("Never invent a citation number", messages[0]["content"])
        self.assertEqual(messages[2]["content"], "Earlier answer with more.")
        self.assertEqual(messages[3]["content"],
                         "Sources:\n\n[1] Paper A, page 4\nAlpha text\n\n[2] Paper B\nBeta text\n\nQuestion: Now what?")

    def test_no_sources_says_so(self):
        content = cited_chat_messages("Q?", [], [])[-1]["content"]
        self.assertIn("No passages were found", content)

    def test_rewrite_prompt_includes_the_conversation(self):
        prompt = standalone_query_prompt("And its limits?", [{"role": "user", "content": "Explain RAG"},
                                                             {"role": "assistant", "content": "RAG retrieves [1]."}])
        self.assertIn("User: Explain RAG", prompt)
        self.assertIn("Assistant: RAG retrieves.", prompt)
        self.assertIn("Latest question: And its limits?", prompt)
        self.assertIn("at most 200 characters", prompt)
