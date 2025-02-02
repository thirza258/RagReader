from django.db import models

# Create your models here.
class ChatResponse(models.model):
    model_name = models.CharField(max_length=100)
    human_message = models.TextField()
    tool_message = models.TextField()
    ai_message = models.TextField()
    
    def __str__(self):
        return self.model_name