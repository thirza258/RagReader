"""Analysis-only progress, scoped to a run rather than a shared engine.

Context variables follow asgiref's sync/async bridges, including concurrent
Ragas calls. Ordinary chat and background jobs have no listener and do no work.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging

logger = logging.getLogger(__name__)
_reporter = ContextVar("analysis_progress", default=None)
STAGE_LABELS = {
    "question": "Document preparation", "search": "Search",
    "evidence": "Evidence refinement", "answer": "Answer generation",
    "evaluate": "Evaluation",
}


class ProgressReporter:
    def __init__(self, callback):
        self.callback = callback
        self.active_stage = None
        self.closed = False

    def emit(self, kind, identifier, status, detail="", **extra):
        if self.closed:
            return
        event = {"kind": kind, "id": identifier, "status": status,
                 "detail": detail, "stage": self.active_stage, **extra}
        try:
            self.callback(event)
        except Exception:
            # A lost progress listener must never discard an answer.
            logger.debug("Analysis progress listener unavailable", exc_info=True)

    def stage(self, identifier, detail, status="running"):
        if self.active_stage and self.active_stage != identifier:
            self.finish()
        self.active_stage = identifier
        self.emit("stage", identifier, status, detail)
        if status != "running":
            self.active_stage = None

    def finish(self, status="completed"):
        if self.active_stage:
            label = STAGE_LABELS[self.active_stage]
            detail = f"{label} finished." if status == "completed" else f"{label} failed. See the result error for details."
            self.emit("stage", self.active_stage, status, detail)
            self.active_stage = None


@contextmanager
def progress_scope(callback):
    reporter = ProgressReporter(callback)
    token = _reporter.set(reporter)
    try:
        yield reporter
    except BaseException:
        reporter.finish("failed")
        raise
    finally:
        reporter.closed = True
        _reporter.reset(token)


def progress_stage(identifier, detail, status="running"):
    reporter = _reporter.get()
    if reporter:
        reporter.stage(identifier, detail, status)


def report_progress(kind, identifier, status, detail="", **extra):
    reporter = _reporter.get()
    if reporter:
        reporter.emit(kind, identifier, status, detail, **extra)
