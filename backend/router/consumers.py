import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from router.models import AnalysisBatch, AnalysisResult, GuestUser
from rag.rag_service import rag_registry
from common.constant import CONFIG_VARIANTS

import logging

logger = logging.getLogger(__name__)

class AnalysisConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        try:
            self.job_id = self.scope['url_route']['kwargs']['job_id']
            self.group_name = f"analysis_{self.job_id}"

            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.accept()

            asyncio.create_task(self.run_rag_pipeline())
        except Exception as e:
            print(f"Error during WebSocket connection: {e}")
            await self.close()

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        except Exception as e:
            print(f"Error during disconnect: {e}")

    async def run_rag_pipeline(self):
        try:
            input_data = await sync_to_async(cache.get)(f"job_input_{self.job_id}")
            
            if not input_data:
                await self.send(text_data=json.dumps({"error": "Job cache expired or invalid"}))
                await self.close()
                return

            username = input_data['username']
            query = input_data['query']
            document_id = input_data.get('document_id')
            conversation_id = input_data.get('conversation_id')

            try:
                analysis_batch = await sync_to_async(AnalysisBatch.objects.get)(job_id=self.job_id)
            except ObjectDoesNotExist:
                await self.send(text_data=json.dumps({"error": "Batch record not found in DB"}))
                await self.close()
                return

            existing_results = await sync_to_async(
                lambda: list(AnalysisResult.objects.filter(batch=analysis_batch))
            )()

            completed_variants = {
                (r.method, r.ai_model) for r in existing_results
            }

            if len(completed_variants) >= len(CONFIG_VARIANTS):
                await self.send(text_data=json.dumps({"status": "REPLAYING"}))
                for result in existing_results:
                    await self.send(text_data=json.dumps({
                        "batch_id": str(self.job_id),
                        "query": result.query,
                        "method": result.method,
                        "aiModel": result.ai_model,
                        "answer": result.answer,
                        "context": result.retrieved_chunks or [],
                        "progress": 100,
                        "replayed": True
                    }))
                await self.send(text_data=json.dumps({"status": "COMPLETE", "progress": 100}))
                await self.close()
                return

            total_variants = len(CONFIG_VARIANTS)

            for index, config in enumerate(CONFIG_VARIANTS):
                method = config["method"]
                model = config["model"]
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
                            "progress": progress,
                            "replayed": True
                        }))
                        continue

                    engine = rag_registry.get_engine(method, model)
                    
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
                        {"id": doc["chunk_id"], "text": doc["text"], "score": doc.get("score")}
                        for doc in context
                    ]
                    
                    evaluation_with_retrieval = {
                        "chunk_evaluation": evaluation.get("chunk_evaluation", {}),
                        "response_evaluation": evaluation.get("response_evaluation", {}),
                        "retrieval_score": [
                            {"chunk_id": doc["chunk_id"], "score": doc.get("score")}
                            for doc in context
                        ]
                    }

                    metrics = [
                        {"name": key, "value": value}
                        for key, value in evaluation_with_retrieval.items()
                    ]

                    await sync_to_async(AnalysisResult.objects.create)(
                        batch=analysis_batch,
                        method=method,
                        ai_model=model,
                        answer=llm_answer,
                        query=query,
                        retrieved_chunks=retrieved_chunks,
                        evaluation_metrics=metrics
                    )

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
                    await self.send(text_data=json.dumps({
                        "method": method,
                        "error": str(e),
                        "progress": int(((index + 1) / total_variants) * 100)
                    }))

            await self.send(text_data=json.dumps({"status": "COMPLETE", "progress": 100}))
            await self.close()
        except Exception as e:
            await self.send(text_data=json.dumps({"error": f"Pipeline error: {str(e)}"}))
            await self.close()
