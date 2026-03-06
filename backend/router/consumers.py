import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from router.models import AnalysisBatch, AnalysisResult, GuestUser
from rag.rag_service import rag_registry
from common.constant import CONFIG_VARIANTS

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

            try:
                analysis_batch = await sync_to_async(AnalysisBatch.objects.get)(job_id=self.job_id)
            except ObjectDoesNotExist:
                await self.send(text_data=json.dumps({"error": "Batch record not found in DB"}))
                await self.close()
                return

            total_variants = len(CONFIG_VARIANTS)

            for index, config in enumerate(CONFIG_VARIANTS):
                try:
                    method = config["method"]
                    model = config["model"]
                    
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

                    answer_text = await sync_to_async(engine.run)(username, query)

                    await sync_to_async(AnalysisResult.objects.create)(
                        batch=analysis_batch,
                        method=method,
                        ai_model=model,
                        answer=answer_text,
                        query=query
                    )

                    progress = int(((index + 1) / total_variants) * 100)
                    
                    result_payload = {
                        "batch_id": self.job_id,
                        "query": query,
                        "method": method,
                        "aiModel": model,
                        "answer": answer_text,
                        "progress": progress
                    }

                    await self.send(text_data=json.dumps(result_payload))

                except Exception as e:
                    error_payload = {
                        "method": config.get("method", "Unknown"),
                        "error": str(e),
                        "progress": int(((index + 1) / total_variants) * 100)
                    }
                    await self.send(text_data=json.dumps(error_payload))
            
            await self.send(text_data=json.dumps({"status": "COMPLETE", "progress": 100}))
        except Exception as e:
            await self.send(text_data=json.dumps({"error": f"Pipeline error: {str(e)}"}))