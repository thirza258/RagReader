from celery import shared_task

from workspace.services.ingestion import run_ingestion


@shared_task(bind=True, soft_time_limit=1800, time_limit=1860)
def ingest_document_task(self, job_id):
    """Run one document through EXTRACTING → … → READY (workspace.services.ingestion).

    Same limits as router.tasks.initialize_rag_task; a run cut off by them
    resumes from its committed embeddings when retried.
    """
    return run_ingestion(job_id)
