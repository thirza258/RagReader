from celery import shared_task
from .models import Job
from rag.rag_service import rag_registry

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