from django.db import models

# Create your models here.e

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
        choices=[("pdf", "PDF"), ("url", "URL"), ("text", "Text")]
    )
    file = models.TextField(null=True, blank=True)
    extracted_text_path = models.TextField(null=True, blank=True)
    source_path = models.TextField(null=True, blank=True)
    source_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.source_type}"

class VectorStore(models.Model):
    base_path = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.base_path or "VectorStore"

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
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="histories"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.conversation_id)