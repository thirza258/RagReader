from django.db import models
import uuid
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

class Job(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        READY = "READY"
        FAILED = "FAILED"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    progress = models.PositiveSmallIntegerField(default=0)
    user = models.ForeignKey(GuestUser, on_delete=models.CASCADE)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, null=True, blank=True) 
    vectorstore = models.ForeignKey(VectorStore, on_delete=models.CASCADE, null=True, blank=True)
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.id} - {self.status}"

    def mark_failed(self, message: str):
        self.status = self.Status.FAILED
        self.error_message = message
        self.save(update_fields=["status", "error_message", "updated_at"])


class Metadata(models.Model):
    llm_model = models.CharField(max_length=100, default="gpt-4o", help_text="LLM for answer generation")
    temperature = models.FloatField(default=0.0, help_text="LLM temperature (0.0 = deterministic)")
    embedding_model = models.CharField(max_length=100, default="text-embedding-3-small", help_text="OpenAI embedding model")
    top_k = models.IntegerField(default=5, help_text="Number of documents to retrieve")
    chunk_strategy = models.CharField(max_length=32, default="paragraph", help_text='Chunking strategy, e.g., "fixed", "paragraph", "semantic"')
    chunk_size = models.IntegerField(default=500, help_text="Max characters per chunk")
    overlap = models.IntegerField(default=50, help_text="Overlap for fixed chunking only")
    vector_store_path = models.TextField(default="./vector_stores", help_text="Path to store vector indices")
    max_retries = models.IntegerField(default=3, help_text="Max iterations for iterative search")
    reranker_model = models.CharField(max_length=200, default="cross-encoder/ms-marco-MiniLM-L-6-v2", help_text="Reranker model name")
    reranker_top_k = models.IntegerField(default=3, help_text="Top K for reranker")
    device = models.CharField(max_length=20, default="cuda", help_text="Device to use - 'cuda' or 'cpu'")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    