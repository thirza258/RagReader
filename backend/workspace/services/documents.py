"""Creating and deleting workspace documents."""
from django.db import transaction

from router.models import Document, DocumentVector
from workspace.services import index_cache
from workspace.services.ingestion import queue_ingestion
from workspace.services.uploads import delete_document_files


def create_document(*, user, workspace, name, source_type, **fields):
    """Create a QUEUED document plus its ingest job; enqueue after commit.

    Returns (document, queue failures). Nothing is parsed or embedded here:
    upload acknowledgement has to stay fast (PRD §40).
    """
    failures = []
    with transaction.atomic():
        document = Document.objects.create(
            user=user, workspace=workspace, name=name[:255], source_type=source_type,
            status=Document.Status.QUEUED, **fields,
        )
        queue_ingestion(document, failures)
    document.refresh_from_db()
    return document, failures


def delete_documents(documents):
    """Delete documents and, once that commits, their files and indexes.

    The cascade removes chunks, jobs, indexes rows and embedding checkpoints,
    but not what lives on disk; collect those locations first.
    """
    documents = list(documents)
    if not documents:
        return
    paths, index_files, vector_ids = [], [], []
    for document in documents:
        paths.extend(path for path in (document.source_path, document.extracted_text_path) if path)
    for vector in DocumentVector.objects.filter(document__in=documents).select_related("vectorstore"):
        index_files.append((vector.vectorstore_location, vector.vectorstore.base_path))
        vector_ids.append(vector.pk)
    Document.objects.filter(pk__in=[document.pk for document in documents]).delete()

    def cleanup():
        delete_document_files(paths, index_files)
        index_cache.discard(vector_ids)

    transaction.on_commit(cleanup)
