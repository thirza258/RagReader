import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from router.models import AnalysisBatch, AnalysisResult, GuestUser
from rag.rag_service import apply_retrieval_depth, rag_registry
from common.constant import build_variants, normalize_analysis_config

import logging

logger = logging.getLogger(__name__)

def format_evaluation_metrics(metrics):
    if not metrics:
        return {}
    if isinstance(metrics, dict):
        return metrics
    if isinstance(metrics, list):
        out = {}
        for m in metrics:
            if isinstance(m, dict) and "name" in m and "value" in m:
                out[m["name"]] = m["value"]
            elif isinstance(m, dict):
                out.update(m)
        return out
    return {}

class AnalysisConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.job_id = self.scope['url_route']['kwargs']['job_id']
            self.group_name = f"analysis_{self.job_id}"

            await self.accept()

            if self.channel_layer is not None:
                try:
                    await self.channel_layer.group_add(
                        self.group_name,
                        self.channel_name
                    )
                except Exception as ce:
                    logger.warning(f"Failed to add to channel group: {ce}")

            asyncio.create_task(self.run_rag_pipeline())
        except Exception as e:
            logger.error(f"Error during WebSocket connection: {e}", exc_info=True)
            try:
                await self.accept()
                await self.send(text_data=json.dumps({"error": f"Connection error: {str(e)}"}))
            except Exception:
                pass
            await self.close()

    async def disconnect(self, close_code):
        try:
            if self.channel_layer is not None:
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )
        except Exception as e:
            logger.debug(f"Error during disconnect: {e}")

    async def run_rag_pipeline(self):
        try:
            analysis_batch = None
            try:
                analysis_batch = await sync_to_async(
                    lambda: AnalysisBatch.objects.select_related("user", "conversation", "conversation__document").get(job_id=self.job_id)
                )()
            except (ObjectDoesNotExist, ValueError):
                analysis_batch = None

            input_data = await sync_to_async(cache.get)(f"job_input_{self.job_id}")

            if not input_data and not analysis_batch:
                await self.send(text_data=json.dumps({"error": "Batch record not found in DB"}))
                await self.close()
                return

            if analysis_batch and not input_data:
                username = analysis_batch.user.username if analysis_batch.user else None
                query = analysis_batch.query
                conversation_id = str(analysis_batch.conversation_id) if analysis_batch.conversation_id else None
                document_id = (
                    str(analysis_batch.conversation.document_id)
                    if (analysis_batch.conversation and analysis_batch.conversation.document_id)
                    else None
                )
                config_data = analysis_batch.config
            else:
                username = input_data['username']
                query = input_data['query']
                document_id = input_data.get('document_id')
                conversation_id = input_data.get('conversation_id')
                config_data = input_data.get("config")
                if not analysis_batch:
                    try:
                        analysis_batch = await sync_to_async(AnalysisBatch.objects.get)(job_id=self.job_id)
                    except ObjectDoesNotExist:
                        await self.send(text_data=json.dumps({"error": "Batch record not found in DB"}))
                        await self.close()
                        return

            # The batch records the config chosen in the sidebar; batches
            # created before that field existed fall back to the full matrix.
            config = normalize_analysis_config(analysis_batch.config or config_data)
            variants = build_variants(config)
            top_k = config["top_k"]

            existing_results = await sync_to_async(
                lambda: list(AnalysisResult.objects.filter(batch=analysis_batch))
            )()

            completed_variants = {
                (r.method, r.ai_model) for r in existing_results
            }

            if len(completed_variants) >= len(variants):
                await self.send(text_data=json.dumps({"status": "REPLAYING"}))
                for result in existing_results:
                    await self.send(text_data=json.dumps({
                        "batch_id": str(self.job_id),
                        "query": result.query,
                        "method": result.method,
                        "aiModel": result.ai_model,
                        "answer": result.answer,
                        "context": result.retrieved_chunks or [],
                        "evaluation": format_evaluation_metrics(result.evaluation_metrics),
                        "progress": 100,
                        "replayed": True
                    }))
                await self.send(text_data=json.dumps({"status": "COMPLETE", "progress": 100}))
                await self.close()
                return

            total_variants = len(variants)

            await self.send(text_data=json.dumps({
                "status": "CONFIG",
                "config": config,
                "expected_count": total_variants,
            }))

            for index, variant in enumerate(variants):
                method = variant["method"]
                model = variant["model"]
                try:
                    if (method, model) in completed_variants:
                        existing = next(
                            r for r in existing_results
                            if r.method == method and r.ai_model == model
                        )
                        progress = int(((index + 1) / total_variants) * 100)
                        await self.send(text_data=json.dumps({
                            "batch_id": str(self.job_id),
                            "query": existing.query,
                            "method": existing.method,
                            "aiModel": existing.ai_model,
                            "answer": existing.answer,
                            "context": existing.retrieved_chunks or [],
                            "evaluation": format_evaluation_metrics(existing.evaluation_metrics),
                            "progress": progress,
                            "replayed": True
                        }))
                        continue

                    engine = rag_registry.get_engine(method, model)

                    # Engines are shared singletons — reapply the depth every
                    # variant so a previous run's Top-K never carries over.
                    apply_retrieval_depth(engine, top_k)

                    is_initialized = await sync_to_async(engine.is_initialized)(username)
                    
                    if not is_initialized:
                        await self.send(text_data=json.dumps({
                            "status": "INITIALIZING",
                            "method": method,
                            "aiModel": model,
                            "progress": int(((index + 0.5) / total_variants) * 100)
                        }))
                        await sync_to_async(engine.init)(username)

                    response = await sync_to_async(engine.run_analysis)(document_id, conversation_id)

                    llm_answer = response.get("answer", "")
                    context = response.get("context", [])
                    evaluation = response.get("evaluation", {})
                    
                    logger.info(f"Evaluation for method {method} and model {model}: {evaluation}")
                    
                    retrieved_chunks = [
                        {"id": doc.get("chunk_id") or doc.get("id"), "text": doc.get("text", ""), "score": doc.get("score")}
                        for doc in context
                    ]
                    
                    evaluation_with_retrieval = {
                        "chunk_evaluation": evaluation.get("chunk_evaluation", {}),
                        "response_evaluation": evaluation.get("response_evaluation", {}),
                        "retrieval_score": [
                            {"chunk_id": doc.get("chunk_id") or doc.get("id"), "score": doc.get("score")}
                            for doc in context
                        ]
                    }

                    metrics = [
                        {"name": key, "value": value}
                        for key, value in evaluation_with_retrieval.items()
                    ]

                    def save_result():
                        res, _ = AnalysisResult.objects.update_or_create(
                            batch=analysis_batch,
                            method=method,
                            ai_model=model,
                            defaults={
                                "answer": llm_answer,
                                "query": query,
                                "retrieved_chunks": retrieved_chunks,
                                "evaluation_metrics": metrics,
                            }
                        )
                        return res

                    await sync_to_async(save_result)()

                    progress = int(((index + 1) / total_variants) * 100)
                    await self.send(text_data=json.dumps({
                        "batch_id": str(self.job_id),
                        "query": query,
                        "method": method,
                        "aiModel": model,
                        "answer": llm_answer,
                        "context": context,
                        "evaluation": evaluation_with_retrieval,
                        "progress": progress
                    }))

                except Exception as e:
                    logger.error(f"Error running variant {method}/{model}: {e}", exc_info=True)
                    await self.send(text_data=json.dumps({
                        "method": method,
                        "error": str(e),
                        "progress": int(((index + 1) / total_variants) * 100)
                    }))

            await self.send(text_data=json.dumps({"status": "COMPLETE", "progress": 100}))
            await self.close()
        except Exception as e:
            logger.error(f"Pipeline error for job {self.job_id}: {e}", exc_info=True)
            await self.send(text_data=json.dumps({"error": f"Pipeline error: {str(e)}"}))
            await self.close()
