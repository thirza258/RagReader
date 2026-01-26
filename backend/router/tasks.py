from celery import shared_task
from .models import Job, AnalysisBatch, AnalysisResult
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

@shared_task(bind=True)
def run_single_analysis(batch_id, username, query, variant_config):
    try:
        engine = rag_registry.get_engine(variant_config["method"], variant_config["model"])
        response = engine.run(username, query) 
        
        metrics = [
            {"label": "Retrieval Score", "value": 0.85},
            {"label": "Faithfulness Score", "value": 0.66},
            {"label": "Answer Relevance", "value": 0.75},
        ]
        
        AnalysisResult.objects.create(
            batch_id=batch_id,
            method=variant_config["method"],
            ai_model=variant_config["model"],
            answer=response.get("data", {}).get("answer", ""),
            retrieved_chunks=[
                {"id": i, "label": f"Chunk {i}", "text": txt} 
                for i, txt in enumerate(response.get("data", {}).get("context", []), 1)
            ],
            model_agreement=[
                {"modelName": "OpenAI", "status": "AGREE"}, 
                {"modelName": "Claude", "status": "AGREE"}
            ],
            evaluation_metrics=metrics
        )
        return True
    except Exception as e:
        print(f"Error in analysis: {e}")
        return False