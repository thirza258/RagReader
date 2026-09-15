"""Eligibility for the optional stages on follow-up analysis runs."""
from common.constant import build_variants
from django.db.models import Prefetch
from router.models import AnalysisBatch, AnalysisResult


def has_completed_analysis(conversation_id):
    if not conversation_id:
        return False
    batches = AnalysisBatch.objects.filter(conversation_id=conversation_id).only("id", "config").prefetch_related(
        Prefetch("results", queryset=AnalysisResult.objects.only("batch_id", "method", "ai_model")),
    )
    for batch in batches:
        expected = {(v["method"], v["model"]) for v in build_variants(batch.config)}
        completed = {(r.method, r.ai_model) for r in batch.results.all()}
        if expected.issubset(completed):
            return True
    return False
