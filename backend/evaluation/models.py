from django.db import models
from router.models import Conversation, Document

# Create your models here.
class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    config_hash = models.CharField(max_length=32, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "text", "config_hash"],
                name="unique_chunk_per_config"
            )
        ]

    def __str__(self):
        return f"Chunk {self.id} of Document {self.document_id}"
    
class GroundTruthChunk(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manually selected"
        POOLED = "pooled", "Candidate pooling (RRF)"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="ground_truth_chunks")
    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.MANUAL,
        db_index=True,
        help_text="How this chunk was chosen as ground truth.",
    )
    rank = models.PositiveIntegerField(null=True, blank=True, help_text="1-based RRF rank (pooled only).")
    rrf_score = models.FloatField(null=True, blank=True, help_text="Fused RRF score (pooled only).")
    metadata = models.JSONField(default=dict, blank=True, help_text="Which pipelines contributed, and at what rank.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rank", "id"]

    def __str__(self):
        return f"GroundTruthChunk {self.id} of Conversation {self.conversation_id} ({self.source})"
    
class GroundTruthResponse(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="ground_truth_responses")
    response = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GroundTruthResponse {self.id} of Conversation {self.conversation_id}"