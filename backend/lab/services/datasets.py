"""Evaluation datasets: validation, immutable versions, import/export, drafts (PRD §26, §42).

A dataset's content lives in immutable versions. Every change that alters
the content hash adds version n + 1 with its own copies of the items (a
change that reproduces the latest hash adds nothing), so an experiment that
names a version names exact questions and expected sources. Items keep a
stable `item_id` across versions, which is what comparisons pair on.

The CSV format is shared with the web client (frontend
`features/evaluation/lib/datasetCsv.ts`); see docs/prd-implementation.md.
"""
import csv
import hashlib
import io
import json
import re

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from common.constant import CHAT_HISTORY_MESSAGES
from lab.models import DatasetItem, DatasetVersion, EvaluationDataset
from router.models import Document
from workspace.errors import ApiError
from workspace.models import ChatMessage

MAX_ITEMS = 2000
MAX_SOURCES = 20
MAX_QUESTION_CHARS = 4000
MAX_ANSWER_CHARS = 20000
MAX_SOURCE_TEXT_CHARS = 1000
MAX_HISTORY_TURNS = CHAT_HISTORY_MESSAGES
MAX_HISTORY_CHARS = 4000
MAX_TAGS = 20
MAX_TAG_CHARS = 50
MAX_METADATA_BYTES = 8192
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_NAME_CHARS = 120
MAX_DESCRIPTION_CHARS = 2000
MAX_CHECK_IDS = 50
MAX_ID = 2 ** 63 - 1

ITEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
SOURCE_KEYS = ("document_id", "chunk_id", "index_version_id", "char_start", "char_end", "page", "page_end", "text")
INPUT_SOURCE_KEYS = frozenset(SOURCE_KEYS) | {"document_title"}
ITEM_KEYS = ("item_id", "question", "expected_answer", "expected_sources", "history", "tags", "metadata")
# `position` is accepted (exports carry it) and ignored: order is list order.
INPUT_ITEM_KEYS = frozenset(ITEM_KEYS) | {"position"}
CSV_COLUMNS = ("item_id", "question", "expected_answer", "expected_sources", "tags", "metadata", "history")
INVALID = "The request contains invalid or missing fields."
EXPORT_FORMAT = "ragreader-dataset"


def invalid(details, message=INVALID):
    return ApiError("invalid_request", message, details=details)


# ── Documents a dataset may name ─────────────────────────────────────────────

class DocumentResolver:
    """The documents of one workspace, by id and by exact title."""

    def __init__(self, workspace):
        self.workspace = workspace
        documents = list(Document.objects.filter(workspace=workspace, user=workspace.user).only("id", "name"))
        self.by_id = {document.pk: document for document in documents}
        self.by_title = {}
        for document in documents:
            self.by_title.setdefault(document.name, []).append(document)

    def resolve(self, document_id, title):
        """The document's id, or None. Ids win; a title must name exactly one document."""
        if document_id is not None and document_id in self.by_id:
            return document_id
        if isinstance(title, str) and title.strip():
            matches = self.by_title.get(title.strip()) or self.by_title.get(title) or []
            if len(matches) == 1:
                return matches[0].pk
        return None

    def title(self, document_id):
        document = self.by_id.get(document_id)
        return document.name if document is not None else None


def not_in_workspace(value):
    return f"Document {value} is not in this workspace."


# ── Item validation ──────────────────────────────────────────────────────────

def _int_value(value, *, minimum=0):
    """An int ≥ minimum from an int or a digit string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if minimum <= number <= MAX_ID else None


def _text(value):
    return value.strip() if isinstance(value, str) else None


def normalize_source(raw, resolver, errors, key):
    """The stored form of one expected source (every key present), or None."""
    if not isinstance(raw, dict):
        errors.setdefault(key, []).append("Expected an object with at least a document_id.")
        return None
    unknown = sorted(str(name) for name in raw if name not in INPUT_SOURCE_KEYS)
    if unknown:
        errors.setdefault(key, []).append(f"Unknown keys: {', '.join(unknown)}.")
        return None
    problems = []
    raw_id = raw.get("document_id")
    document_id = _int_value(raw_id, minimum=1) if raw_id is not None else None
    if raw_id is not None and document_id is None:
        problems.append("document_id must be a positive whole number.")
    title = raw.get("document_title")
    resolved = resolver.resolve(document_id, title)
    if resolved is None and not problems:
        if raw_id is None and title in (None, ""):
            problems.append("Name the document with document_id (or document_title).")
        else:
            problems.append(not_in_workspace(raw_id if raw_id is not None else f"“{title}”"))
    source = {name: None for name in SOURCE_KEYS}
    source["document_id"] = resolved
    source["text"] = ""
    for name in ("chunk_id", "index_version_id"):
        value = raw.get(name)
        if value is not None:
            number = _int_value(value, minimum=1)
            if number is None:
                problems.append(f"{name} must be a positive whole number or null.")
            source[name] = number
    start, end = raw.get("char_start"), raw.get("char_end")
    if (start is None) != (end is None):
        problems.append("Give both char_start and char_end, or neither.")
    elif start is not None:
        start_value, end_value = _int_value(start), _int_value(end)
        if start_value is None or end_value is None or start_value >= end_value:
            problems.append("char_start and char_end must be whole numbers with char_start < char_end.")
        source["char_start"], source["char_end"] = start_value, end_value
    page, page_end = raw.get("page"), raw.get("page_end")
    if page is not None:
        page_value = _int_value(page, minimum=1)
        if page_value is None:
            problems.append("page must be a whole number from 1.")
        source["page"] = page_value
        if page_end is not None:
            end_value = _int_value(page_end, minimum=1)
            if end_value is None or page_value is None or end_value < page_value:
                problems.append("page_end must be a whole number not below page.")
            source["page_end"] = end_value
        else:
            source["page_end"] = page_value
    elif page_end is not None:
        problems.append("page_end needs page.")
    text = raw.get("text")
    if text is not None:
        if not isinstance(text, str):
            problems.append("text must be a string.")
        elif len(text) > MAX_SOURCE_TEXT_CHARS:
            problems.append(f"text must be at most {MAX_SOURCE_TEXT_CHARS} characters.")
        else:
            source["text"] = text
    if problems:
        errors.setdefault(key, []).extend(problems)
        return None
    return source


def _history(raw, errors, key):
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors[key] = ["Expected a list of {role, content} turns."]
        return []
    if len(raw) > MAX_HISTORY_TURNS:
        errors[key] = [f"At most {MAX_HISTORY_TURNS} turns."]
        return []
    turns = []
    for turn in raw:
        if not isinstance(turn, dict) or set(turn) - {"role", "content"}:
            errors[key] = ["Each turn is {\"role\": \"user\" | \"assistant\", \"content\": …}."]
            return []
        role, content = turn.get("role"), turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip() \
                or len(content) > MAX_HISTORY_CHARS:
            errors[key] = [f"Each turn needs role user or assistant and 1–{MAX_HISTORY_CHARS} characters of content."]
            return []
        turns.append({"role": role, "content": content.strip()})
    return turns


def _tags(raw, errors, key):
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors[key] = ["Expected a list of strings."]
        return []
    tags = []
    for tag in raw:
        value = _text(tag)
        if not value or len(value) > MAX_TAG_CHARS:
            errors[key] = [f"Each tag is 1–{MAX_TAG_CHARS} characters."]
            return []
        if value not in tags:
            tags.append(value)
    if len(tags) > MAX_TAGS:
        errors[key] = [f"At most {MAX_TAGS} tags."]
        return []
    return tags


def _metadata(raw, errors, key):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        errors[key] = ["Expected a JSON object."]
        return {}
    try:
        size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        errors[key] = ["Expected a JSON object."]
        return {}
    if size > MAX_METADATA_BYTES:
        errors[key] = [f"At most {MAX_METADATA_BYTES} bytes of JSON."]
        return {}
    return raw


def normalize_item(raw, resolver, errors, prefix=""):
    """The stored form of one item (item_id may still be None), or None."""
    def key(name):
        return f"{prefix}.{name}" if prefix else name

    if not isinstance(raw, dict):
        errors[prefix or "item"] = ["Expected an object."]
        return None
    before = len(errors)
    unknown = sorted(str(name) for name in raw if name not in INPUT_ITEM_KEYS)
    if unknown:
        errors[key("keys")] = [f"Unknown keys: {', '.join(unknown)}."]
    item_id = raw.get("item_id")
    if item_id in (None, ""):
        item_id = None
    elif not isinstance(item_id, str) or not ITEM_ID_PATTERN.match(item_id.strip()):
        errors[key("item_id")] = ["Use 1–64 letters, digits, '_', '.', ':' or '-', starting with a letter or digit."]
    else:
        item_id = item_id.strip()
    question = _text(raw.get("question"))
    if not question:
        errors[key("question")] = ["This field may not be blank."]
    elif len(question) > MAX_QUESTION_CHARS:
        errors[key("question")] = [f"Ensure this field has no more than {MAX_QUESTION_CHARS} characters."]
    expected_answer = raw.get("expected_answer")
    if expected_answer is None:
        expected_answer = ""
    elif not isinstance(expected_answer, str):
        errors[key("expected_answer")] = ["Expected a string."]
        expected_answer = ""
    else:
        expected_answer = expected_answer.strip()
        if len(expected_answer) > MAX_ANSWER_CHARS:
            errors[key("expected_answer")] = [f"Ensure this field has no more than {MAX_ANSWER_CHARS} characters."]
    sources = []
    raw_sources = raw.get("expected_sources")
    if raw_sources is None:
        raw_sources = []
    if not isinstance(raw_sources, list):
        errors[key("expected_sources")] = ["Expected a list of sources."]
    elif len(raw_sources) > MAX_SOURCES:
        errors[key("expected_sources")] = [f"At most {MAX_SOURCES} expected sources."]
    else:
        for position, source in enumerate(raw_sources):
            normalized = normalize_source(source, resolver, errors, f"{key('expected_sources')}[{position}]")
            if normalized is not None:
                sources.append(normalized)
    item = {
        "item_id": item_id,
        "question": question or "",
        "expected_answer": expected_answer,
        "expected_sources": sources,
        "history": _history(raw.get("history"), errors, key("history")),
        "tags": _tags(raw.get("tags"), errors, key("tags")),
        "metadata": _metadata(raw.get("metadata"), errors, key("metadata")),
    }
    return item if len(errors) == before else None


def normalize_items(raw_items, resolver, *, prefix="items"):
    """(items, errors) for a submitted list; errors keyed `items[i].field`."""
    if not isinstance(raw_items, list):
        return [], {prefix: ["Expected a list of items."]}
    if len(raw_items) > MAX_ITEMS:
        return [], {prefix: [f"At most {MAX_ITEMS} items."]}
    errors, items = {}, []
    for index, raw in enumerate(raw_items):
        item = normalize_item(raw, resolver, errors, f"{prefix}[{index}]")
        items.append(item)
    return items, errors


def assign_item_ids(items, taken=(), *, prefix="items", offset=0):
    """Give items without an id the first free `q<n>`; refuse repeated ids.

    `taken` are ids already in the version the items join. Returns errors.
    """
    errors, seen = {}, set(taken)
    for index, item in enumerate(items):
        if item is None or item["item_id"] is None:
            continue
        if item["item_id"] in seen:
            errors[f"{prefix}[{index + offset}].item_id"] = [f"Item id “{item['item_id']}” is used twice."]
        seen.add(item["item_id"])
    number = len(seen) + 1
    for item in items:
        if item is None or item["item_id"] is not None:
            continue
        while f"q{number}" in seen:
            number += 1
        item["item_id"] = f"q{number}"
        seen.add(item["item_id"])
    return errors


def canonical_item(item):
    return {key: item[key] for key in ITEM_KEYS}


def content_hash(document_ids, items):
    """sha256 of the canonical JSON (sorted keys, no whitespace) of the version's content."""
    payload = {"document_ids": sorted(document_ids or []), "items": [canonical_item(item) for item in items]}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def item_record(row):
    """A DatasetItem row as a plain item dict (stored form)."""
    return {
        "item_id": row.item_id, "question": row.question, "expected_answer": row.expected_answer,
        "expected_sources": list(row.expected_sources or []), "history": list(row.history or []),
        "tags": list(row.tags or []), "metadata": dict(row.metadata or {}),
    }


def version_items(version):
    return [item_record(row) for row in version.items.order_by("position")]


def clean_name(value, *, required, limit=MAX_NAME_CHARS, field="name"):
    name = " ".join(str(value or "").split())
    if not name:
        if required:
            raise invalid({field: ["This field may not be blank."]})
        return None
    if len(name) > limit:
        raise invalid({field: [f"Ensure this field has no more than {limit} characters."]})
    return name


def clean_description(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise invalid({"description": ["Expected a string."]})
    value = value.strip()
    if len(value) > MAX_DESCRIPTION_CHARS:
        raise invalid({"description": [f"Ensure this field has no more than {MAX_DESCRIPTION_CHARS} characters."]})
    return value


def clean_document_ids(workspace, value, field="document_ids"):
    """Sorted unique ids of documents in `workspace` (400 for anything else)."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise invalid({field: ["Expected a list of at most 200 document ids."]})
    ids = []
    for raw in value:
        number = _int_value(raw, minimum=1)
        if number is None:
            raise invalid({field: ["Expected document ids (positive whole numbers)."]})
        if number not in ids:
            ids.append(number)
    found = set(Document.objects.filter(pk__in=ids, workspace=workspace, user=workspace.user).values_list("pk", flat=True))
    missing = [number for number in ids if number not in found]
    if missing:
        raise invalid({field: [not_in_workspace(number) for number in missing]})
    return sorted(ids)


# ── Versions ─────────────────────────────────────────────────────────────────

def latest_version(dataset):
    return dataset.versions.order_by("-number").first()


def _write_version(dataset, items, document_ids, note):
    number = (dataset.versions.aggregate(top=Max("number"))["top"] or 0) + 1
    version = DatasetVersion.objects.create(
        dataset=dataset, number=number, document_ids=sorted(document_ids or []),
        content_hash=content_hash(document_ids, items), item_count=len(items), note=(note or "")[:200],
    )
    DatasetItem.objects.bulk_create([
        DatasetItem(version=version, position=position, **canonical_item(item))
        for position, item in enumerate(items, 1)
    ], batch_size=500)
    return version


def commit_version(dataset, build, *, base_version=None):
    """(version, created): apply `build(latest items, latest document ids)` as version n + 1.

    `build` returns (items, document_ids, note). Runs under the dataset's
    row lock, so concurrent edits get consecutive numbers; `base_version`
    (a number) must be the latest or the edit is refused with 409.
    """
    with transaction.atomic():
        locked = EvaluationDataset.objects.select_for_update().get(pk=dataset.pk)
        latest = latest_version(locked)
        if base_version is not None and (latest is None or latest.number != base_version):
            raise ApiError(
                "version_conflict",
                f"The dataset changed since version {base_version}; reload it (latest is v{latest.number if latest else 0}) and try again.",
                status=409,
            )
        current_items = version_items(latest) if latest is not None else []
        current_ids = list(latest.document_ids or []) if latest is not None else []
        items, document_ids, note = build(current_items, current_ids)
        if len(items) > MAX_ITEMS:
            raise invalid({"items": [f"A version holds at most {MAX_ITEMS} items."]})
        if latest is not None and content_hash(document_ids, items) == latest.content_hash:
            return latest, False
        version = _write_version(locked, items, document_ids, note)
        EvaluationDataset.objects.filter(pk=locked.pk).update(updated_at=timezone.now())
    return version, True


def _validated(raw_items, resolver, taken=(), *, prefix="items", offset=0):
    items, errors = normalize_items(raw_items, resolver, prefix=prefix)
    errors.update(assign_item_ids(items, taken, prefix=prefix, offset=offset))
    if errors:
        raise invalid(errors)
    return items


def _plural(count, noun):
    return f"{count} {noun}{'' if count == 1 else 's'}"


def create_dataset(workspace, *, name, description="", document_ids=None, raw_items=None, note=None):
    resolver = DocumentResolver(workspace)
    items = _validated(raw_items or [], resolver)
    document_ids = clean_document_ids(workspace, document_ids)
    with transaction.atomic():
        dataset = EvaluationDataset.objects.create(workspace=workspace, name=name, description=description or "")
        version = _write_version(dataset, items, document_ids,
                                 note or (f"Created with {_plural(len(items), 'item')}" if items else "Created"))
    return dataset, version


def replace_content(dataset, *, raw_items=None, document_ids=None, base_version=None):
    """PATCH: a new item list and/or corpus (None keeps the current one)."""
    workspace = dataset.workspace
    items = _validated(raw_items, DocumentResolver(workspace)) if raw_items is not None else None
    ids = clean_document_ids(workspace, document_ids) if document_ids is not None else None

    def build(current_items, current_ids):
        notes = []
        if items is not None:
            notes.append(f"Replaced the items ({_plural(len(items), 'item')})")
        if ids is not None and ids != sorted(current_ids):
            notes.append("Changed the documents")
        return (items if items is not None else current_items,
                ids if ids is not None else current_ids, "; ".join(notes) or "Edited")

    return commit_version(dataset, build, base_version=base_version)


def add_items(dataset, raw_items, *, base_version=None, note=None):
    resolver = DocumentResolver(dataset.workspace)
    added = []

    def build(current_items, current_ids):
        taken = [item["item_id"] for item in current_items]
        added[:] = _validated(raw_items, resolver, taken)
        return current_items + added, current_ids, note or f"Added {_plural(len(added), 'item')}"

    version, created = commit_version(dataset, build, base_version=base_version)
    return version, created, added


def update_item(dataset, item_id, changes, *, base_version=None):
    if not isinstance(changes, dict):
        raise invalid({"item": ["Expected an object."]})
    resolver = DocumentResolver(dataset.workspace)
    updated = {}

    def build(current_items, current_ids):
        position = next((index for index, item in enumerate(current_items) if item["item_id"] == item_id), None)
        if position is None:
            raise ApiError("not_found", "Item not found.", status=404)
        current = current_items[position]
        merged = {**current, **{key: value for key, value in changes.items() if key not in ("base_version",)}}
        if merged.get("item_id") in (None, ""):
            merged["item_id"] = item_id
        errors = {}
        item = normalize_item(merged, resolver, errors)
        if errors:
            raise invalid(errors)
        others = [other["item_id"] for index, other in enumerate(current_items) if index != position]
        if item["item_id"] in others:
            raise invalid({"item_id": [f"Item id “{item['item_id']}” is used twice."]})
        updated.update(item)
        items = list(current_items)
        items[position] = item
        return items, current_ids, f"Edited {item_id}"

    version, created = commit_version(dataset, build, base_version=base_version)
    return version, created, updated


def delete_item(dataset, item_id, *, base_version=None):
    def build(current_items, current_ids):
        items = [item for item in current_items if item["item_id"] != item_id]
        if len(items) == len(current_items):
            raise ApiError("not_found", "Item not found.", status=404)
        return items, current_ids, f"Deleted {item_id}"

    version, _created = commit_version(dataset, build, base_version=base_version)
    return version


def import_items(dataset, raw_items, *, mode="append", base_version=None):
    """Append to (or replace) the latest version's items with imported ones."""
    resolver = DocumentResolver(dataset.workspace)
    imported = []

    def build(current_items, current_ids):
        taken = [] if mode == "replace" else [item["item_id"] for item in current_items]
        imported[:] = _validated(raw_items, resolver, taken)
        items = imported if mode == "replace" else current_items + imported
        verb = "Replaced the items with" if mode == "replace" else "Imported"
        return items, current_ids, f"{verb} {_plural(len(imported), 'item')}"

    version, created = commit_version(dataset, build, base_version=base_version)
    return version, created, len(imported)


# ── Checks (dataset problems that need no run) ───────────────────────────────

def normalized_question(text):
    """Questions compared for duplicates: case, whitespace and punctuation ignored."""
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def duplicate_groups(items):
    """[[item_id, …], …] of items whose questions are the same once normalised."""
    groups = {}
    for item in items:
        groups.setdefault(normalized_question(item["question"]), []).append(item["item_id"])
    return [ids for key, ids in groups.items() if key and len(ids) > 1]


def version_checks(version, items=None, workspace_document_ids=None):
    items = version_items(version) if items is None else items
    if workspace_document_ids is None:
        workspace = version.dataset.workspace
        workspace_document_ids = set(
            Document.objects.filter(workspace=workspace, user=workspace.user).values_list("pk", flat=True)
        )
    corpus = set(version.document_ids or []) or set(workspace_document_ids)
    without = [item["item_id"] for item in items if not item["expected_sources"]]
    missing = [
        item["item_id"] for item in items
        if any(source.get("document_id") not in corpus for source in item["expected_sources"])
    ]
    return {
        "items_without_sources": without[:MAX_CHECK_IDS],
        "duplicate_questions": duplicate_groups(items)[:MAX_CHECK_IDS],
        "missing_documents": missing[:MAX_CHECK_IDS],
    }


# ── Import parsing ───────────────────────────────────────────────────────────

COMPACT_PAGE = re.compile(r"[pP](\d+)(?:-(\d+))?")
COMPACT_CHUNK = re.compile(r"[cC](\d+)")
COMPACT_RANGE = re.compile(r"(\d+)-(\d+)")


def parse_compact_sources(cell):
    """`12#p4; 14#c345,10234-10746` → sources. Raises ValueError with a message."""
    sources = []
    for part in cell.split(";"):
        part = part.strip()
        if not part:
            continue
        document, _hash, selectors = part.partition("#")
        document = document.strip()
        if not document.isdigit():
            raise ValueError(f"“{part}” must start with a document id.")
        source = {"document_id": int(document)}
        for selector in (selectors.split(",") if selectors.strip() else []):
            selector = selector.strip()
            if match := COMPACT_PAGE.fullmatch(selector):
                if "page" in source:
                    raise ValueError(f"“{part}” names a page twice.")
                source["page"] = int(match.group(1))
                if match.group(2):
                    source["page_end"] = int(match.group(2))
            elif match := COMPACT_CHUNK.fullmatch(selector):
                if "chunk_id" in source:
                    raise ValueError(f"“{part}” names a chunk twice.")
                source["chunk_id"] = int(match.group(1))
            elif match := COMPACT_RANGE.fullmatch(selector):
                if "char_start" in source:
                    raise ValueError(f"“{part}” names a character range twice.")
                source["char_start"], source["char_end"] = int(match.group(1)), int(match.group(2))
            else:
                raise ValueError(f"“{selector}” is not p<page>, p<page>-<page>, c<chunk id> or <start>-<end>.")
        sources.append(source)
    return sources


def _json_cell(cell, expected, label):
    value = json.loads(cell)
    if not isinstance(value, expected):
        raise ValueError(f"{label} must be a JSON {'array' if expected is list else 'object'}.")
    return value


def parse_csv(text):
    """(raw items, ignored columns); raises ApiError(invalid_request) for malformed input."""
    if text.startswith("﻿"):
        text = text[1:]
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise invalid({"content": [f"The CSV could not be read: {exc}."]}) from exc
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise invalid({"content": ["The CSV has no header row."]})
    header = [cell.strip().lower() for cell in rows[0]]
    if "question" not in header:
        raise invalid({"content": ["The CSV needs a question column."]})
    columns = {name: header.index(name) for name in CSV_COLUMNS if name in header}
    ignored = [rows[0][index].strip() for index, name in enumerate(header) if name not in CSV_COLUMNS]
    items, errors = [], {}
    for index, row in enumerate(rows[1:]):
        def cell(name):
            position = columns.get(name)
            return row[position].strip() if position is not None and position < len(row) else ""

        prefix = f"items[{index}]"
        item = {"question": cell("question")}
        if cell("item_id"):
            item["item_id"] = cell("item_id")
        if cell("expected_answer"):
            item["expected_answer"] = cell("expected_answer")
        sources = cell("expected_sources")
        try:
            if sources.startswith("["):
                item["expected_sources"] = _json_cell(sources, list, "expected_sources")
            elif sources:
                item["expected_sources"] = parse_compact_sources(sources)
        except ValueError as exc:
            errors[f"{prefix}.expected_sources"] = [str(exc) if not isinstance(exc, json.JSONDecodeError) else "Invalid JSON."]
        tags = cell("tags")
        if tags:
            item["tags"] = [tag.strip() for tag in tags.split(";") if tag.strip()]
        for name, expected in (("metadata", dict), ("history", list)):
            value = cell(name)
            if value:
                try:
                    item[name] = _json_cell(value, expected, name)
                except ValueError as exc:
                    errors[f"{prefix}.{name}"] = [str(exc) if not isinstance(exc, json.JSONDecodeError) else "Invalid JSON."]
        items.append(item)
    if errors:
        raise invalid(errors)
    return items, ignored


def parse_json(text):
    """(raw items, export metadata or {}) from a JSON export or a bare list."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise invalid({"content": ["The file is not valid JSON."]}) from exc
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"], data
    raise invalid({"content": ["Expected a list of items or a dataset export with an \"items\" list."]})


def read_import(data, files=None):
    """(raw items, ignored columns, export metadata) from an import request body.

    Accepts JSON `{"items": [...]}`, JSON `{"format": "json" | "csv", "content": "…"}`
    or a multipart upload `file` (CSV by extension or content, else JSON).
    """
    upload = files.get("file") if files else None
    if upload is not None:
        if upload.size is not None and upload.size > MAX_IMPORT_BYTES:
            raise ApiError("file_too_large", f"Import files are limited to {MAX_IMPORT_BYTES // (1024 * 1024)} MB.", status=413)
        raw = upload.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise ApiError("file_too_large", f"Import files are limited to {MAX_IMPORT_BYTES // (1024 * 1024)} MB.", status=413)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise invalid({"file": ["The file must be UTF-8 text (CSV or JSON)."]}) from exc
        name = (upload.name or "").lower()
        fmt = (data.get("format") or "").lower() if hasattr(data, "get") else ""
        if not fmt:
            fmt = "csv" if name.endswith(".csv") else "json" if name.endswith(".json") else (
                "json" if text.lstrip().startswith(("[", "{")) else "csv")
    elif isinstance(data, dict) and "items" in data and "content" not in data:
        return data["items"], [], {}
    else:
        fmt = str(data.get("format") or "").lower() if hasattr(data, "get") else ""
        text = data.get("content") if hasattr(data, "get") else None
        if not isinstance(text, str) or not text.strip():
            raise invalid({"content": ["Send items, or content with a format (json or csv), or a file."]})
        if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ApiError("file_too_large", f"Imports are limited to {MAX_IMPORT_BYTES // (1024 * 1024)} MB.", status=413)
    if fmt not in ("json", "csv"):
        raise invalid({"format": ["Choose json or csv."]})
    if fmt == "csv":
        items, ignored = parse_csv(text)
        return items, ignored, {}
    items, meta = parse_json(text)
    return items, [], meta


# ── Export ───────────────────────────────────────────────────────────────────

def output_source(source, resolver):
    return {**{key: source.get(key) for key in SOURCE_KEYS}, "document_title": resolver.title(source.get("document_id"))}


def output_item(item, position, resolver):
    return {
        "item_id": item["item_id"], "position": position, "question": item["question"],
        "expected_answer": item["expected_answer"],
        "expected_sources": [output_source(source, resolver) for source in item["expected_sources"]],
        "history": item["history"], "tags": item["tags"], "metadata": item["metadata"],
    }


def export_json(dataset, version):
    resolver = DocumentResolver(dataset.workspace)
    return {
        "format": EXPORT_FORMAT, "schema_version": 1,
        "dataset": {"id": dataset.pk, "name": dataset.name, "description": dataset.description},
        "version": {"number": version.number, "content_hash": version.content_hash,
                    "document_ids": list(version.document_ids or []), "created_at": version.created_at.isoformat()},
        "items": [output_item(item, position, resolver) for position, item in enumerate(version_items(version), 1)],
    }


def export_csv(dataset, version):
    resolver = DocumentResolver(dataset.workspace)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for item in version_items(version):
        sources = [output_source(source, resolver) for source in item["expected_sources"]]
        writer.writerow([
            item["item_id"], item["question"], item["expected_answer"],
            json.dumps(sources, ensure_ascii=False) if sources else "",
            "; ".join(item["tags"]),
            json.dumps(item["metadata"], ensure_ascii=False) if item["metadata"] else "",
            json.dumps(item["history"], ensure_ascii=False) if item["history"] else "",
        ])
    return buffer.getvalue()


# ── Drafts from chat answers ─────────────────────────────────────────────────

def draft_from_message(workspace, user, message_id):
    """A dataset item proposed from a chat answer; nothing is written.

    The question is the user message the answer replied to; the expected
    sources are the evidence the answer cited (for the user to confirm);
    the expected answer is left empty — prefilling it with the model's own
    answer would make answer correctness circular.
    """
    def refused():
        return invalid({"message_id": [f"Message {message_id} is not a completed answer in this workspace."]})

    number = _int_value(message_id, minimum=1)
    if number is None:
        raise invalid({"message_id": ["A valid integer is required."]})
    message = (
        ChatMessage.objects.select_related("session")
        .filter(pk=number, session__user=user, session__workspace=workspace,
                role=ChatMessage.Role.ASSISTANT, status=ChatMessage.Status.COMPLETE)
        .first()
    )
    if message is None:
        raise refused()
    earlier = message.session.messages.filter(created_at__lte=message.created_at).exclude(pk=message.pk)
    asked = earlier.filter(role=ChatMessage.Role.USER, pk__lt=message.pk).order_by("-created_at", "-id").first()
    question = (asked.content if asked is not None else "") or ((message.retrieval or {}).get("query") or {}).get("original") or ""
    history = []
    if asked is not None:
        rows = list(
            message.session.messages.filter(status=ChatMessage.Status.COMPLETE, pk__lt=asked.pk)
            .order_by("-created_at", "-id")[:MAX_HISTORY_TURNS]
        )
        rows.reverse()
        history = [{"role": row.role, "content": row.content[:MAX_HISTORY_CHARS]} for row in rows if row.content.strip()]
    resolver = DocumentResolver(workspace)
    sources, expected = [], []
    for evidence in message.citations or []:
        available = evidence.get("document_id") in resolver.by_id
        suggested = bool(evidence.get("cited")) and available
        sources.append({**evidence, "suggested": suggested, "document_available": available})
        if suggested:
            expected.append(evidence_source(evidence, resolver))
    retrieval = message.retrieval or {}
    return {
        "draft": {
            "item_id": None, "position": None, "question": question[:MAX_QUESTION_CHARS].strip(),
            "expected_answer": "", "expected_sources": expected, "history": history, "tags": [],
            "metadata": {"source": {"message_id": message.pk, "conversation_id": message.session_id,
                                    "run_id": retrieval.get("run_id")}},
        },
        "sources": sources,
        "message_id": message.pk,
        "conversation_id": message.session_id,
    }


def evidence_source(evidence, resolver=None):
    """An Evidence object (PRD §14) as an expected source."""
    def number(value, minimum=0):
        return _int_value(value, minimum=minimum) if value is not None else None

    source = {
        "document_id": evidence.get("document_id"),
        "chunk_id": number(evidence.get("chunk_id"), 1),
        "index_version_id": number(evidence.get("index_version_id"), 1),
        "char_start": number(evidence.get("char_start")),
        "char_end": number(evidence.get("char_end")),
        "page": number(evidence.get("page_number"), 1),
        "page_end": number(evidence.get("page_end"), 1),
        "text": (evidence.get("text") or "")[:MAX_SOURCE_TEXT_CHARS],
    }
    if source["char_start"] is None or source["char_end"] is None or source["char_start"] >= source["char_end"]:
        source["char_start"] = source["char_end"] = None
    if source["page"] is None:
        source["page_end"] = None
    elif source["page_end"] is None or source["page_end"] < source["page"]:
        source["page_end"] = source["page"]
    if resolver is not None:
        source["document_title"] = resolver.title(source["document_id"])
    return source
