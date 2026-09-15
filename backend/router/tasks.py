import logging

from celery import shared_task
from .models import Job, AnalysisBatch, AnalysisResult
from rag.rag_service import apply_retrieval_depth, rag_registry
from common.constant import normalize_analysis_config

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def initialize_rag_task(self, job_id, username, method, model_config):
    try:
        job = Job.objects.get(id=job_id)
        job.status = Job.Status.PROCESSING
        job.save()

        engine = rag_registry.get_engine(method, model_config)
      
        engine.init_job(username, job=job)

        job.status = Job.Status.READY
        job.progress = 100
        job.save()

        return True

    except Exception as e:
        if 'job' in locals():
            job.mark_failed(str(e))
            return False
        return False

@shared_task(bind=True)
def run_single_analysis(self, batch_id, username, query, variant_config, config=None):
    """Run one variant out of band.

    The stored batch configuration is authoritative. The optional argument is
    a fallback for legacy batches. The websocket consumer is the live path;
    this task is the queued equivalent.
    """
    try:
        batch = AnalysisBatch.objects.get(job_id=batch_id)
        config = normalize_analysis_config(batch.config or config)
        engine = rag_registry.get_engine(
            variant_config["method"], variant_config["model"], config
        )
        apply_retrieval_depth(engine, config["top_k"], config["child_top_k"])
        if config["modules"]:
            if not batch.conversation or not batch.conversation.document_id:
                raise ValueError("Module analysis requires a conversation document.")
            response = engine.run_analysis(batch.conversation.document_id, batch.conversation_id)
        else:
            response = engine.run(username, query)

        context = response.get("context", [])  
        retrieved_chunks = [
            {
                "id": doc["chunk_id"],
                "text": doc["text"],
                "score": doc.get("score")
            }
            for doc in context
        ]

        metrics = [
            {
                "name": "retrieval_score",
                "value": [
                    {"chunk_id": doc["chunk_id"], "score": doc.get("score")}
                    for doc in context
                ]
            }
        ]
        metrics.extend({"name": name, "value": value} for name, value in response.get("evaluation", {}).items())
        if response.get("module_trace"):
            metrics.append({"name": "module_trace", "value": response["module_trace"]})

        AnalysisResult.objects.create(
            query=query,
            batch=batch,
            method=variant_config["method"],
            ai_model=variant_config["model"],
            answer=response.get("answer", ""),
            retrieved_chunks=retrieved_chunks,
            evaluation_metrics=metrics
        )
        return True
    except Exception as e:
        logger.error(f"run_single_analysis failed for batch {batch_id}: {e}", exc_info=True)
        return False
