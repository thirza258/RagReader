from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class AppUser(User):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.username

class GuestUser(models.Model):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.username

class Document(models.Model):
    user = models.ForeignKey(GuestUser, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    source_type = models.CharField(
        max_length=20,
        choices=[("pdf", "PDF"), ("url", "URL"), ("file", "File")]
    )
    file = models.FileField(upload_to="documents/", null=True, blank=True)
    source_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class VectorStore(models.Model):
    base_path = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.base_path

class DocumentVector(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="vectors"
    )
    vectorstore = models.ForeignKey(VectorStore, on_delete=models.CASCADE)
    vectorstore_location = models.TextField()
    document_location = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("ready", "Ready"),
            ("failed", "Failed"),
        ],
        default="pending"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Conversation(models.Model):
    query = models.TextField()
    response = models.TextField()
    context = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    

class ConversationHistory(models.Model):
    user = models.ForeignKey(GuestUser, on_delete=models.CASCADE)
    conversation_id = models.CharField(max_length=255)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.conversation_id

    