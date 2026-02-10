import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

# Import your models
from router.models import AnalysisBatch, AnalysisResult, GuestUser
from rag.rag_service import rag_registry
from common.constant import CONFIG_VARIANTS

class AnalysisConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.group_name = f"analysis_{self.job_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        asyncio.create_task(self.run_rag_pipeline())

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def run_rag_pipeline(self):
        # 1. Retrieve Inputs from Cache (Faster/Safe way to get query params)
        input_data = await sync_to_async(cache.get)(f"job_input_{self.job_id}")
        
        if not input_data:
            await self.send(text_data=json.dumps({"error": "Job cache expired or invalid"}))
            await self.close()
            return

        username = input_data['username']
        query = input_data['query']

        # 2. Retrieve the Batch Object safely
        # We need this object to assign the Foreign Key for results
        try:
            analysis_batch = await sync_to_async(AnalysisBatch.objects.get)(job_id=self.job_id)
        except ObjectDoesNotExist:
            await self.send(text_data=json.dumps({"error": "Batch record not found in DB"}))
            await self.close()
            return

        total_variants = len(CONFIG_VARIANTS)

        # 3. Loop through configurations
        for index, config in enumerate(CONFIG_VARIANTS):
            try:
                method = config["method"]
                model = config["model"]

                # --- Run RAG Engine ---
                # Ensure your RAG engine returns a STRING. 
                # If it returns a dict/object, extract the text before saving.
                answer_text = await sync_to_async(rag_registry.get_engine(method, model).run)(username, query)

                # --- Save to Database ---
                # Use .create() for a cleaner implementation
                await sync_to_async(AnalysisResult.objects.create)(
                    batch=analysis_batch,
                    method=method,
                    ai_model=model,
                    answer=answer_text
                    
                )

                # --- Send to WebSocket ---
                progress = int(((index + 1) / total_variants) * 100)
                
                result_payload = {
                    "batch_id": self.job_id,
                    "method": method,
                    "aiModel": model,
                    "answer": answer_text,
                    "progress": progress
                }

                await self.send(text_data=json.dumps(result_payload))

            except Exception as e:
                # Handle specific failures so the whole batch doesn't die
                error_msg = str(e)
                error_payload = {
                    "method": config.get("method", "Unknown"),
                    "error": error_msg,
                    "progress": int(((index + 1) / total_variants) * 100)
                }
                
                await self.send(text_data=json.dumps(error_payload))
        
        # Done
        await self.send(text_data=json.dumps({"status": "COMPLETE", "progress": 100}))