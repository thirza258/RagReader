from django.db import models

# Create your models here.
class ChatResponse(models.Model):
    model_name = models.CharField(max_length=100)
    human_message = models.TextField()
    tool_message = models.TextField()
    ai_message = models.TextField()
    
    def __str__(self):
        return self.model_name
    
class File(models.Model):
    file = models.FileField(upload_to="files/")
    
    def __str__(self):
        return self.file.name