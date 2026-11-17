"""What each research task does (PRD §22–25, §47).

Every kind follows one pattern: gather evidence with the pipeline's own
retrieval (`workspace.services.retrieval.run_retrieval`), number it like chat
citations, ask the generation model for a strict JSON answer over those
numbered passages, then validate that answer against the evidence. Anything
the model claims without a valid citation is downgraded (a finding becomes
"not stated", an extracted value null) rather than shown as fact.

Verdicts for claims are not the model's: the model judges each passage
(supports / contradicts / neutral) and `verdict_for` turns the counts into a
verdict and a confidence, so the same stances always give the same verdict.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field

from common.errors import PipelineError
from workspace.services.citations import cited_ids, evidence as evidence_object
from workspace.services.retrieval import run_retrieval

logger = logging.getLogger(__name__)

PROMPT_VERSION = "research-v1"
MAX_EVIDENCE = 40
PASSAGE_CHARS = 1200
MAX_TEXT_CHARS = 4000
VERDICTS = ("supported", "contradicted", "mixed", "insufficient_evidence")
CONFIDENCE = ("low", "moderate", "high")
STANCES = ("supports", "contradicts", "neutral")
DEFAULT_DIMENSIONS = ["methodology", "dataset", "retrieval", "reranking", "evaluation", "limitations", "conclusions"]
DIMENSION_QUERIES = {
    "methodology": "methodology approach method design",
    "dataset": "dataset data corpus samples benchmark",
    "retrieval": "retrieval method retriever search embeddings",
    "reranking": "reranking reranker cross-encoder ranking",
    "evaluation": "evaluation metrics results benchmark scores",
    "limitations": "limitations weaknesses threats future work",
    "conclusions": "conclusion findings contribution summary",
}
FIELD_TYPES = ("text", "number", "list", "boolean")
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class OutputInvalid(ValueError):
    """The model's JSON did not have the required shape."""


def _ms(since):
    return int(round((time.monotonic() - since) * 1000))


# ── Evidence ─────────────────────────────────────────────────────────────────

@dataclass
class EvidenceBook:
    """Passages gathered for one task, numbered [1]… in the order first found."""
    items: list = field(default_factory=list)
    rows: list = field(default_factory=list)  # for the run record
    _keys: dict = field(default_factory=dict)

    def add(self, candidate):
        """The citation id of `candidate` (a retrieval Candidate), or None once the book is full."""
        key = (candidate.document.pk, candidate.chunk_id if candidate.chunk_id is not None else candidate.text)
        if key in self._keys:
            return self._keys[key]
        if len(self.items) >= MAX_EVIDENCE:
            return None
        number = len(self.items) + 1
        item = evidence_object(
            number, document=candidate.document, vector_id=candidate.index_version_id, chunk_id=candidate.chunk_id,
            text=candidate.text, score=candidate.retrieval_score, position=candidate.position_metadata,
        )
        item["rerank_score"] = round(float(candidate.rerank_score), 6) if candidate.rerank_score is not None else None
        self.items.append(item)
        self.rows.append({
            "rank": number, "retrieval_rank": number, "document": candidate.document,
            "index_version_id": candidate.index_version_id, "chunk_id": candidate.chunk_id,
            "retrieval_score": candidate.retrieval_score, "dense_score": candidate.dense_score,
            "bm25_score": candidate.bm25_score, "fused_score": candidate.fused_score,
            "rerank_score": candidate.rerank_score, "text": candidate.text, "position": candidate.position_metadata,
            "selected_for_context": True, "citation_id": number, "cited": False,
        })
        self._keys[key] = number
        return number

    def valid(self, values):
        """Integer citation ids in range, de-duplicated, in order."""
        seen = []
        for value in values if isinstance(values, list) else []:
            number = value if isinstance(value, int) and not isinstance(value, bool) else (
                int(value) if isinstance(value, str) and value.strip().isdigit() else None)
            if number is not None and 1 <= number <= len(self.items) and number not in seen:
                seen.append(number)
        return seen

    def cited_in(self, text):
        return cited_ids(text or "", len(self.items))

    def mark(self, cited):
        cited = set(cited)
        for item in self.items:
            item["cited"] = item["citation_id"] in cited
        for row in self.rows:
            row["cited"] = row["citation_id"] in cited

    def passages(self, ids=None):
        """The prompt block: `[n] (Title, p. 4) text`."""
        wanted = set(ids) if ids is not None else None
        lines = []
        for item in self.items:
            if wanted is not None and item["citation_id"] not in wanted:
                continue
            where = item["document_title"]
            if item.get("page_number"):
                where += f", p. {item['page_number']}"
            text = " ".join((item["text"] or "").split())[:PASSAGE_CHARS]
            lines.append(f"[{item['citation_id']}] ({where}) {text}")
        return "\n\n".join(lines) if lines else "(no passages were found)"


# ── Model output ─────────────────────────────────────────────────────────────

def parse_json_object(text):
    """The JSON object in a model reply (code fences and surrounding prose tolerated)."""
    raw = FENCE.sub("", (text or "").strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise OutputInvalid("The reply contains no JSON object.")
    try:
        value = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise OutputInvalid(f"The reply is not valid JSON ({exc.msg}).") from exc
    if not isinstance(value, dict):
        raise OutputInvalid("The reply is not a JSON object.")
    return value


def clip(text, limit=MAX_TEXT_CHARS):
    return " ".join(str(text).split())[:limit] if isinstance(text, str) and text.strip() else None


# ── Verdicts (§22) ───────────────────────────────────────────────────────────

def verdict_for(supporting, contradicting):
    """(verdict, confidence) from how many passages support and contradict a claim.

    Clearly one-sided evidence (at least twice as many passages on one side)
    gives that side's verdict; anything closer is `mixed`. Confidence is high
    only for three or more passages with nothing against them, moderate for
    at least two on the winning side, low otherwise.
    """
    if supporting == 0 and contradicting == 0:
        return "insufficient_evidence", "low"
    if contradicting == 0 or supporting >= 2 * contradicting:
        verdict = "supported"
    elif supporting == 0 or contradicting >= 2 * supporting:
        verdict = "contradicted"
    else:
        return "mixed", "low"
    majority, minority = max(supporting, contradicting), min(supporting, contradicting)
    if minority == 0 and majority >= 3:
        return verdict, "high"
    if majority >= 2:
        return verdict, "moderate"
    return verdict, "low"


# ── The run of one task ──────────────────────────────────────────────────────

@dataclass
class Session:
    """What a task's steps share: documents, pipeline, models, tracer, evidence."""
    documents: list
    config: dict
    engine: object
    llm: object
    tracer: object
    on_progress: object = None
    book: EvidenceBook = field(default_factory=EvidenceBook)
    indexes: list = field(default_factory=list)
    retrieval_ms: int = 0
    generation_ms: int = 0

    def progress(self, stage, detail):
        if self.on_progress is not None:
            self.on_progress(stage, detail)

    def document(self, document_id):
        return next((document for document in self.documents if document.pk == document_id), None)

    def search(self, query, documents, depth, label="Search"):
        """Citation ids of the top `depth` passages for `query` within `documents`."""
        config = {**self.config, "top_k": depth, "candidate_k": max(depth, int(self.config.get("candidate_k") or depth))}
        began = time.monotonic()
        with self.tracer.span("retrieve", label, query=query[:200], documents=len(documents)) as span:
            found = run_retrieval(query, documents, config, engine=self.engine, tracer=self.tracer, indexes=self.indexes)
            ids = [number for number in (self.book.add(candidate) for candidate in found.context) if number is not None]
            span.set(passages=len(ids))
        self.retrieval_ms += _ms(began)
        return ids

    def ask(self, name, prompt, validate):
        """The model's JSON answer to `prompt`, checked by `validate` (one retry on a bad reply)."""
        last_error = None
        for attempt in range(2):
            began = time.monotonic()
            with self.tracer.span("generate", name, attempt=attempt + 1) as span:
                text = self.llm.generate(prompt if attempt == 0 else (
                    f"{prompt}\n\nYour previous reply was rejected: {last_error} Reply with the JSON object only."))
                self.generation_ms += _ms(began)
                try:
                    return validate(parse_json_object(text))
                except OutputInvalid as exc:
                    last_error = str(exc)
                    span.fail("research_output_invalid", last_error[:200])
        raise PipelineError("research_output_invalid",
                            f"The model's answer could not be read twice in a row ({last_error}). Retry the task.",
                            retryable=True, http_status=502)

    def generate_line(self, name, prompt, limit=200):
        """One short line of model text (e.g. a search query), or None."""
        began = time.monotonic()
        with self.tracer.span("generate", name) as span:
            try:
                text = (self.llm.generate(prompt) or "").strip().strip("\"'`").strip()
            except Exception:
                logger.warning("Research helper call %s failed", name, exc_info=True)
                span.fail("helper_failed")
                return None
            finally:
                self.generation_ms += _ms(began)
        if not text or "\n" in text or len(text) > limit:
            return None
        return text


RULES = (
    "Use only the numbered passages. Cite every factual statement with its passage number in square brackets, "
    "e.g. [2] or [1, 3]. Never cite a number that is not listed. Reply with one JSON object and nothing else."
)


# ── Verify a claim (§22) ─────────────────────────────────────────────────────

def verify_claim(session, data):
    claim = data["claim"]
    session.progress("retrieve", "Searching for evidence about the claim")
    session.search(claim, session.documents, 6, "Evidence for the claim")
    counter = session.generate_line("Counter-query", (
        "Task: counter-query. Write one search query that would find passages contradicting or qualifying this "
        f"claim. Output only the query.\nClaim: {claim}"))
    if counter and counter.lower() != claim.lower():
        session.search(counter, session.documents, 4, "Evidence against the claim")
    book = session.book
    if not book.items:
        return {"claim": claim, "verdict": "insufficient_evidence", "confidence": "low", "counter_query": counter,
                "conclusion": "No passage in the selected documents addresses this claim.",
                "supporting": [], "contradicting": [], "neutral": [], "assessments": []}, []

    session.progress("analyze", f"Judging {len(book.items)} passages against the claim")

    def validate(raw):
        assessments = raw.get("assessments")
        if not isinstance(assessments, list):
            raise OutputInvalid('"assessments" must be a list.')
        stances = {}
        for entry in assessments:
            if not isinstance(entry, dict):
                continue
            ids = book.valid([entry.get("id")])
            stance = entry.get("stance")
            if ids and stance in STANCES and ids[0] not in stances:
                stances[ids[0]] = {"citation_id": ids[0], "stance": stance, "rationale": clip(entry.get("rationale"), 500)}
        conclusion = clip(raw.get("conclusion"))
        if conclusion is None:
            raise OutputInvalid('"conclusion" must be text.')
        return stances, conclusion

    stances, conclusion = session.ask("Claim assessment", (
        "Task: claim assessment. For every passage, decide whether it supports the claim, contradicts it, or is "
        "neutral (does not bear on it). Then write a short conclusion that cites the passages it relies on.\n"
        f"{RULES}\n"
        'JSON: {"assessments": [{"id": 1, "stance": "supports" | "contradicts" | "neutral", "rationale": "…"}], '
        '"conclusion": "…"}\n\n'
        f"Claim: {claim}\n\nPassages:\n{book.passages()}"), validate)
    assessments = [stances.get(item["citation_id"]) or {"citation_id": item["citation_id"], "stance": "neutral",
                                                       "rationale": None}
                   for item in book.items]
    supporting = [entry["citation_id"] for entry in assessments if entry["stance"] == "supports"]
    contradicting = [entry["citation_id"] for entry in assessments if entry["stance"] == "contradicts"]
    neutral = [entry["citation_id"] for entry in assessments if entry["stance"] == "neutral"]
    verdict, confidence = verdict_for(len(supporting), len(contradicting))
    return {"claim": claim, "verdict": verdict, "confidence": confidence, "counter_query": counter,
            "conclusion": conclusion, "supporting": supporting, "contradicting": contradicting, "neutral": neutral,
            "assessments": assessments}, supporting + contradicting + book.cited_in(conclusion)


# ── Ask across documents (§23) ───────────────────────────────────────────────

def ask(session, data):
    question = data["question"]
    per_document = {}
    for position, document in enumerate(session.documents, 1):
        session.progress("retrieve", f"Searching “{document.name}” ({position} of {len(session.documents)})")
        per_document[document.pk] = session.search(question, [document], 3, f"Evidence in {document.name}"[:200])
    book = session.book
    session.progress("analyze", "Answering per document and comparing")
    ids_text = "\n".join(f"- document_id {document.pk}: {document.name} (passages {per_document[document.pk] or 'none'})"
                         for document in session.documents)

    def validate(raw):
        entries = raw.get("per_document")
        if not isinstance(entries, list):
            raise OutputInvalid('"per_document" must be a list.')
        answers = {}
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("document_id"), int):
                answers[entry["document_id"]] = clip(entry.get("answer"))
        return answers, clip(raw.get("comparison")), clip(raw.get("synthesis"))

    answers, comparison, synthesis = session.ask("Multi-document answer", (
        "Task: multi-document answer. Answer the question separately for each document from its own passages "
        "(null when its passages do not answer it), then compare the documents and write a synthesis.\n"
        f"{RULES}\n"
        'JSON: {"per_document": [{"document_id": 12, "answer": "…" | null}], "comparison": "…", "synthesis": "…"}\n\n'
        f"Question: {question}\n\nDocuments:\n{ids_text}\n\nPassages:\n{book.passages()}"), validate)
    rows, cited = [], []
    for document in session.documents:
        answer = answers.get(document.pk)
        citations = book.cited_in(answer)
        found = bool(answer) and bool(citations)
        rows.append({"document_id": document.pk, "document_title": document.name,
                     "answer": answer if found else None, "found": found, "citation_ids": citations if found else []})
        cited += citations if found else []
    for text in (comparison, synthesis):
        cited += book.cited_in(text)
    return {"question": question, "per_document": rows, "comparison": comparison, "synthesis": synthesis}, cited


# ── Compare documents (§24) ──────────────────────────────────────────────────

def compare(session, data):
    dimensions = data["dimensions"]
    for dimension in dimensions:
        session.progress("retrieve", f"Searching every document for “{dimension}”")
        query = DIMENSION_QUERIES.get(dimension.lower(), dimension)
        for document in session.documents:
            session.search(query, [document], 2, f"{dimension}: {document.name}"[:200])
    book = session.book
    session.progress("analyze", f"Comparing {len(session.documents)} documents on {len(dimensions)} dimensions")
    docs_text = "\n".join(f"- document_id {document.pk}: {document.name}" for document in session.documents)

    def validate(raw):
        entries = raw.get("dimensions")
        if not isinstance(entries, list):
            raise OutputInvalid('"dimensions" must be a list.')
        by_name = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            findings = {}
            for finding in entry.get("findings") or []:
                if isinstance(finding, dict) and isinstance(finding.get("document_id"), int):
                    findings[finding["document_id"]] = clip(finding.get("finding"), 1500)
            by_name[entry["name"].strip().lower()] = (findings, clip(entry.get("difference"), 1500))
        return by_name, clip(raw.get("summary"))

    by_name, summary = session.ask("Document comparison", (
        "Task: document comparison. For each dimension, state what each document says (null when its passages "
        "do not say), then the key difference between the documents.\n"
        f"{RULES}\n"
        'JSON: {"dimensions": [{"name": "methodology", "findings": [{"document_id": 12, "finding": "…" | null}], '
        '"difference": "…"}], "summary": "…"}\n\n'
        f"Dimensions: {', '.join(dimensions)}\n\nDocuments:\n{docs_text}\n\nPassages:\n{book.passages()}"), validate)
    rows, cited = [], []
    for dimension in dimensions:
        findings, difference = by_name.get(dimension.lower(), ({}, None))
        cells = []
        for document in session.documents:
            text = findings.get(document.pk)
            citations = book.cited_in(text)
            # Evidence-backed only: an uncited finding is shown as not stated.
            status = "found" if text and citations else "not_stated"
            cells.append({"document_id": document.pk, "finding": text if status == "found" else None,
                          "citation_ids": citations if status == "found" else [], "status": status})
            cited += citations if status == "found" else []
        rows.append({"name": dimension, "findings": cells, "difference": difference})
        cited += book.cited_in(difference)
    cited += book.cited_in(summary)
    return {"documents": [{"id": document.pk, "title": document.name} for document in session.documents],
            "dimensions": rows, "summary": summary}, cited


# ── Extract fields (§25) ─────────────────────────────────────────────────────

def coerce(value, kind):
    """(value, ok) for one extracted value of type `kind`."""
    if value is None:
        return None, True
    if kind == "number":
        if isinstance(value, bool):
            return None, False
        if isinstance(value, (int, float)):
            return value, True
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            try:
                number = float(cleaned)
            except ValueError:
                return None, False
            return int(number) if number.is_integer() else number, True
        return None, False
    if kind == "boolean":
        if isinstance(value, bool):
            return value, True
        if isinstance(value, str) and value.strip().lower() in ("true", "yes", "false", "no"):
            return value.strip().lower() in ("true", "yes"), True
        return None, False
    if kind == "list":
        if isinstance(value, list):
            items = [clip(str(entry), 300) for entry in value if entry is not None and str(entry).strip()]
            return items, True
        if isinstance(value, str):
            return [clip(part, 300) for part in value.split(";") if part.strip()], True
        return None, False
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return clip(str(value), 1500), True
    return None, False


def extract(session, data):
    fields = data["fields"]
    for spec in fields:
        session.progress("retrieve", f"Searching for “{spec['name']}”")
        query = f"{spec['name'].replace('_', ' ')} {spec.get('description') or ''}".strip()
        session.search(query, session.documents, 3, f"Field {spec['name']}"[:200])
    book = session.book
    session.progress("analyze", f"Extracting {len(fields)} fields")
    spec_text = "\n".join(f"- {spec['name']} ({spec['type']}): {spec.get('description') or ''}".rstrip(": ")
                          for spec in fields)

    def validate(raw):
        values = raw.get("fields")
        if not isinstance(values, dict):
            raise OutputInvalid('"fields" must be an object keyed by field name.')
        return values

    values = session.ask("Evidence extraction", (
        "Task: evidence extraction. Extract each field from the passages. Give the value (null when the "
        "passages do not state it) and the passage numbers it comes from.\n"
        f"{RULES}\n"
        'JSON: {"fields": {"field_name": {"value": … | null, "citations": [1, 2]}}}\n'
        "Types: text = a string, number = a JSON number, list = an array of strings, boolean = true/false.\n\n"
        f"Fields:\n{spec_text}\n\nPassages:\n{book.passages()}"), validate)
    rows, cited, data_out = [], [], {}
    for spec in fields:
        entry = values.get(spec["name"]) if isinstance(values.get(spec["name"]), dict) else {}
        raw_value = entry.get("value")
        value, ok = coerce(raw_value, spec["type"])
        citations = book.valid(entry.get("citations"))
        if raw_value is None:
            status, value, citations = "not_found", None, []
        elif not ok:
            # A value of the wrong type ("soon" for a number) is shown as invalid, not as missing.
            status, value, citations = "invalid", None, []
        elif value in (None, [], ""):
            status, value, citations = "not_found", None, []
        elif not citations:
            # PRD §25: every extracted field has a source citation.
            status, value = "uncited", None
        else:
            status = "found"
        rows.append({"name": spec["name"], "type": spec["type"], "value": value, "citation_ids": citations,
                     "status": status})
        data_out[spec["name"]] = value
        cited += citations
    return {"fields": rows, "data": data_out}, cited


# ── Find contradictions ──────────────────────────────────────────────────────

def contradictions(session, data):
    topic = data["topic"]
    session.progress("retrieve", "Searching for passages on the topic")
    session.search(topic, session.documents, 8, "Passages on the topic")
    if len(session.documents) > 1:
        for document in session.documents:
            session.search(topic, [document], 3, f"Passages in {document.name}"[:200])
    book = session.book
    if len(book.items) < 2:
        return {"topic": topic, "contradictions": [], "summary": "Fewer than two passages address this topic."}, []
    session.progress("analyze", f"Looking for disagreements among {len(book.items)} passages")

    def validate(raw):
        pairs = raw.get("contradictions")
        if not isinstance(pairs, list):
            raise OutputInvalid('"contradictions" must be a list.')
        return pairs, clip(raw.get("summary"))

    pairs, summary = session.ask("Contradiction detection", (
        "Task: contradiction detection. Find pairs of passages that make incompatible statements about the topic "
        "(not merely different emphasis). Return an empty list when there are none.\n"
        f"{RULES}\n"
        'JSON: {"contradictions": [{"a": 1, "b": 4, "severity": "direct" | "partial", "explanation": "…"}], '
        '"summary": "…"}\n\n'
        f"Topic: {topic}\n\nPassages:\n{book.passages()}"), validate)
    rows, seen, cited = [], set(), []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        ids = book.valid([pair.get("a"), pair.get("b")])
        if len(ids) != 2:
            continue
        key = tuple(sorted(ids))
        if key in seen:
            continue
        seen.add(key)
        a, b = book.items[key[0] - 1], book.items[key[1] - 1]
        rows.append({"a": key[0], "b": key[1], "severity": pair.get("severity") if pair.get("severity") in ("direct", "partial") else "partial",
                     "explanation": clip(pair.get("explanation"), 1000),
                     "cross_document": a["document_id"] != b["document_id"]})
        cited += list(key)
    return {"topic": topic, "contradictions": rows, "summary": summary}, cited + book.cited_in(summary)


# ── Write a report ───────────────────────────────────────────────────────────

def plan_sections(session, question):
    def validate(raw):
        sections = raw.get("sections")
        if not isinstance(sections, list):
            raise OutputInvalid('"sections" must be a list.')
        planned = []
        for entry in sections[:6]:
            if isinstance(entry, dict) and clip(entry.get("heading"), 120) and clip(entry.get("query"), 200):
                planned.append({"heading": clip(entry["heading"], 120), "query": clip(entry["query"], 200)})
        if len(planned) < 2:
            raise OutputInvalid("Plan at least two sections.")
        return clip(raw.get("title"), 200), planned

    try:
        return session.ask("Report plan", (
            "Task: research plan. Plan a short evidence-based report answering the question: a title and 2–6 "
            "sections, each with a search query that would find its evidence. Reply with one JSON object.\n"
            'JSON: {"title": "…", "sections": [{"heading": "…", "query": "…"}]}\n\n'
            f"Question: {question}"), validate)
    except PipelineError:
        # A plan is a convenience: fall back to a fixed outline.
        return None, [{"heading": "Findings", "query": question},
                      {"heading": "Limitations and open questions", "query": f"{question} limitations"}]


def report(session, data):
    question = data["question"]
    session.progress("plan", "Planning the report")
    title, sections = plan_sections(session, question)
    for section in sections:
        session.progress("retrieve", f"Gathering evidence for “{section['heading']}”")
        section["ids"] = session.search(section["query"], session.documents, 4, f"Section {section['heading']}"[:200])
    book = session.book
    session.progress("analyze", "Writing the report")
    outline = "\n".join(f"- {section['heading']} (passages {section['ids'] or 'none'})" for section in sections)

    def validate(raw):
        written = raw.get("sections")
        if not isinstance(written, list):
            raise OutputInvalid('"sections" must be a list.')
        bodies = []
        for entry in written:
            if isinstance(entry, dict) and clip(entry.get("heading"), 120):
                bodies.append({"heading": clip(entry["heading"], 120), "body": clip(entry.get("body"), 6000)})
        summary = clip(raw.get("summary"), 2000)
        if summary is None or not bodies:
            raise OutputInvalid('A "summary" and at least one section are required.')
        return clip(raw.get("title"), 200), summary, bodies, clip(raw.get("limitations"), 2000)

    final_title, summary, bodies, limitations = session.ask("Research report", (
        "Task: research report. Write the report following the outline: an executive summary, one body per "
        "section, and the limitations of the evidence. Say plainly when the passages do not settle a point.\n"
        f"{RULES}\n"
        'JSON: {"title": "…", "summary": "…", "sections": [{"heading": "…", "body": "…"}], "limitations": "…"}\n\n'
        f"Question: {question}\n\nOutline:\n{outline}\n\nPassages:\n{book.passages()}"), validate)
    cited = book.cited_in(summary)
    for body in bodies:
        cited += book.cited_in(body["body"])
    cited += book.cited_in(limitations)
    return {"question": question, "title": final_title or title or question[:200], "summary": summary,
            "sections": bodies, "limitations": limitations}, cited


KINDS = {
    "verify_claim": verify_claim,
    "ask": ask,
    "compare": compare,
    "extract": extract,
    "contradictions": contradictions,
    "report": report,
}


def execute(session, kind, data):
    """(result, evidence) for one task; the evidence's `cited` flags are set."""
    result, cited = KINDS[kind](session, data)
    session.book.mark(cited)
    return result, session.book.items
