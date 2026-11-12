"""Structured telemetry for one RAG request (PRD §32).

A `Tracer` records a tree of spans: what ran, when it started (milliseconds
from the start of the request, on the monotonic clock), how long it took,
whether it completed, was skipped or failed (with the error code), a short
human detail and a small data payload. `export()` flattens the tree into
rows in pre-order, each naming its parent's ordinal, which is how runs store
it; `build_tree()` turns stored rows back into the nested shape the API
returns.

Tracing is diagnostic and must never cost the user an answer:

* every tracer method swallows its own errors, logs the first one and turns
  the tracer inert (spans it hands out afterwards are detached and ignored);
* a span scope never suppresses the exception of the code it wraps — it only
  records it, closing the span (and any span still open inside it) as failed
  with the error's code;
* payloads are bounded: at most `MAX_SPANS` spans per trace (the rest are
  counted on the root as `dropped_spans`), `MAX_DATA_BYTES` of JSON data per
  span, and short strings.
"""
import json
import logging
import math
import numbers
import time

from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_SPANS = 100
MAX_DATA_BYTES = 2048
MAX_DATA_ITEMS = 20
MAX_STRING_CHARS = 200
MAX_NAME_CHARS = 64
MAX_LABEL_CHARS = 200
MAX_DETAIL_CHARS = 255
MAX_ERROR_CODE_CHARS = 80

COMPLETED = "completed"
SKIPPED = "skipped"
FAILED = "failed"
STATUSES = (COMPLETED, SKIPPED, FAILED)


def error_code_for(error):
    """The stable code recorded for a failure: an exception or a code string."""
    if isinstance(error, str):
        return error[:MAX_ERROR_CODE_CHARS] or "internal_error"
    if isinstance(error, GeneratorExit):
        return "stream_interrupted"  # the consumer stopped reading
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code[:MAX_ERROR_CODE_CHARS]
    return "internal_error"


def _clip(text, limit):
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def bounded(value, depth=0):
    """A JSON-safe copy of `value` with short strings and short collections."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        number = float(value)
        return round(number, 6) if math.isfinite(number) else None
    if isinstance(value, str):
        return _clip(value, MAX_STRING_CHARS)
    if depth < 2 and isinstance(value, dict):
        return {_clip(key, MAX_NAME_CHARS): bounded(item, depth + 1) for key, item in list(value.items())[:MAX_DATA_ITEMS]}
    if depth < 2 and isinstance(value, (list, tuple)):
        return [bounded(item, depth + 1) for item in list(value)[:MAX_DATA_ITEMS]]
    return _clip(value, MAX_STRING_CHARS)


def bounded_data(data):
    """`data` bounded item by item, keeping keys only while the JSON fits."""
    result, size = {}, 2
    for key, value in list((data or {}).items())[:MAX_DATA_ITEMS]:
        key, value = _clip(key, MAX_NAME_CHARS), bounded(value)
        cost = len(json.dumps({key: value}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size + cost > MAX_DATA_BYTES:
            result["truncated"] = True
            break
        result[key] = value
        size += cost
    return result


class Span:
    """One timed step. Its methods only assign; they cannot fail."""

    __slots__ = ("name", "label", "start_ms", "duration_ms", "status", "detail", "error_code", "data", "children")

    def __init__(self, name, label="", start_ms=0.0, data=None):
        self.name = name
        self.label = label
        self.start_ms = start_ms
        self.duration_ms = None
        self.status = None
        self.detail = ""
        self.error_code = ""
        self.data = dict(data or {})
        self.children = []

    def set(self, **data):
        """Adds to the span's data payload."""
        self.data.update(data)
        return self

    def describe(self, detail):
        self.detail = detail
        return self

    def fail(self, code, detail=None):
        """Marks a step that failed without raising (e.g. a recovered fallback)."""
        self.status = FAILED
        self.error_code = str(code)[:MAX_ERROR_CODE_CHARS]
        if detail is not None:
            self.detail = detail
        return self

    def skip(self, detail=None):
        """Marks the step as skipped; the status sticks when the span closes."""
        self.status = SKIPPED
        if detail is not None:
            self.detail = detail
        return self


class _Scope:
    __slots__ = ("tracer", "span")

    def __init__(self, tracer, span):
        self.tracer = tracer
        self.span = span

    def __enter__(self):
        return self.span

    def __exit__(self, exc_type, exc, tb):
        # Record, never suppress: the wrapped code's exception (including
        # GeneratorExit from a disconnected stream) carries on unchanged.
        self.tracer.finish(self.span, error=exc)
        return False


class Tracer:
    """A tree of spans under one root, timed from `origin` (monotonic seconds)."""

    def __init__(self, name, label="", *, origin=None, clock=time.monotonic):
        self._clock = clock
        self.origin = clock() if origin is None else origin
        self.started_at = timezone.now()
        self.root = Span(_clip(name, MAX_NAME_CHARS), _clip(label, MAX_LABEL_CHARS), 0.0)
        self._open = [self.root]
        self._count = 1
        self.dropped = 0
        self.broken = False

    # ── Internal ────────────────────────────────────────────────────────────
    def _now_ms(self):
        return (self._clock() - self.origin) * 1000.0

    def _break(self):
        if not self.broken:
            logger.warning("Tracing failed; the request continues without a trace", exc_info=True)
        self.broken = True
        self._open = []

    def _close(self, span, now, status=None, error=None, detail=None):
        span.duration_ms = max(0.0, now - span.start_ms)
        if error is not None:
            span.status = FAILED
            span.error_code = error_code_for(error)
        elif status is not None:
            span.status = status
        elif span.status is None:
            span.status = COMPLETED
        if detail is not None:
            span.detail = detail

    # ── Public API: every method is guarded ─────────────────────────────────
    def start(self, name, label="", **data):
        """Opens a child of the innermost open span; close it with finish()."""
        try:
            if self.broken:
                return Span(name, label)
            span = Span(_clip(name, MAX_NAME_CHARS), _clip(label, MAX_LABEL_CHARS), self._now_ms(), data)
            if self._count >= MAX_SPANS:
                self.dropped += 1
                return span  # timed by nobody, recorded nowhere
            self._count += 1
            (self._open[-1] if self._open else self.root).children.append(span)
            self._open.append(span)
            return span
        except Exception:
            self._break()
            return Span(name, label)

    def finish(self, span, *, status=None, error=None, detail=None):
        """Closes `span` and any span still open inside it.

        With `error` (an exception or a code) they all close as failed.
        Closing a span twice, or a span this tracer did not record, does nothing.
        """
        try:
            if self.broken or span is None or span.duration_ms is not None:
                return
            if not any(item is span for item in self._open):
                return
            now = self._now_ms()
            while self._open:
                current = self._open.pop()
                if current is span:
                    break
                self._close(current, now, status=FAILED if error is not None else None, error=error)
            self._close(span, now, status=status, error=error, detail=detail)
        except Exception:
            self._break()

    def span(self, name, label="", **data):
        """`with tracer.span("search", "Vector search") as span: …`"""
        return _Scope(self, self.start(name, label, **data))

    def close(self, *, status=None, error=None, detail=None):
        """Closes the root and everything still open."""
        self.finish(self.root, status=status, error=error, detail=detail)

    def elapsed_ms(self):
        try:
            return self._now_ms()
        except Exception:
            self._break()
            return None

    def export(self):
        """Flat rows in pre-order (see module doc); [] once the tracer broke."""
        try:
            if self.broken:
                return []
            if self.root.duration_ms is None:
                self.close()
            rows = []

            def walk(span, parent_ordinal, depth):
                ordinal = len(rows)
                data = dict(span.data)
                if ordinal == 0 and self.dropped:
                    data["dropped_spans"] = self.dropped
                rows.append({
                    "ordinal": ordinal,
                    "parent_ordinal": parent_ordinal,
                    "depth": depth,
                    "name": span.name,
                    "label": span.label,
                    "status": span.status if span.status in STATUSES else COMPLETED,
                    "start_ms": round(span.start_ms, 3),
                    "duration_ms": round(span.duration_ms, 3) if span.duration_ms is not None else None,
                    "detail": _clip(span.detail, MAX_DETAIL_CHARS),
                    "error_code": span.error_code,
                    "data": bounded_data(data),
                })
                for child in span.children:
                    walk(child, ordinal, depth + 1)

            walk(self.root, None, 0)
            return rows
        except Exception:
            self._break()
            return []


class NullTracer(Tracer):
    """A tracer that records nothing, for callers that were not given one."""

    def __init__(self):
        super().__init__("null")
        self.broken = True
        self._open = []


def new_tracer(name, label="", *, origin=None):
    try:
        return Tracer(name, label, origin=origin)
    except Exception:
        logger.warning("Could not start a trace", exc_info=True)
        return NullTracer()


def build_tree(rows):
    """Nested spans from stored rows (dicts with ordinal and parent_ordinal)."""
    nodes, roots = {}, []
    for row in sorted(rows, key=lambda item: item["ordinal"]):
        node = {key: value for key, value in row.items() if key not in ("ordinal", "parent_ordinal", "depth")}
        node["children"] = []
        nodes[row["ordinal"]] = node
        parent = nodes.get(row["parent_ordinal"]) if row["parent_ordinal"] is not None else None
        (parent["children"] if parent is not None else roots).append(node)
    return roots
