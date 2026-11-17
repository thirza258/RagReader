"""Evaluation datasets: CRUD, versions, items, import/export, drafts from chat (PRD §26, §42)."""
import json
import os

from django.http import HttpResponse
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from lab import serializers
from lab.models import EvaluationDataset
from lab.services import datasets as ds
from lab.views.base import LabView, invalid
from workspace.views.base import parse_id


def _base_version(data):
    value = data.get("base_version") if hasattr(data, "get") else None
    if value in (None, ""):
        return None
    number = parse_id(value)
    if number is None:
        raise invalid({"base_version": ["Expected a version number."]})
    return number


def _version(dataset, raw):
    if raw in (None, ""):
        return ds.latest_version(dataset)
    number = parse_id(raw)
    version = dataset.versions.filter(number=number).first() if number else None
    if version is None:
        raise invalid({"version": [f"The dataset has no version {raw}."]})
    return version


class DatasetListView(LabView):
    def get(self, request):
        workspace = self.resolve_workspace(request.query_params.get("workspace_id"))
        datasets = EvaluationDataset.objects.filter(workspace=workspace).order_by("-updated_at", "-id")
        return Response({"results": [serializers.dataset_payload(dataset) for dataset in datasets]})

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        workspace = self.resolve_workspace(data.get("workspace_id"))
        name = ds.clean_name(data.get("name"), required=True)
        description = ds.clean_description(data.get("description"))
        items = data.get("items")
        if items is not None and not isinstance(items, list):
            raise invalid({"items": ["Expected a list of items."]})
        dataset, version = ds.create_dataset(workspace, name=name, description=description,
                                             document_ids=data.get("document_ids"), raw_items=items)
        return Response(serializers.dataset_payload(dataset, version=version), status=201)


class DatasetImportNewView(LabView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request):
        data = request.data
        workspace = self.resolve_workspace(data.get("workspace_id") if hasattr(data, "get") else None)
        raw_items, ignored, meta = ds.read_import(data, request.FILES)
        upload = request.FILES.get("file")
        fallback = ((meta.get("dataset") or {}).get("name") if isinstance(meta, dict) else None) or (
            os.path.splitext(upload.name)[0] if upload is not None else None) or "Imported dataset"
        name = ds.clean_name(data.get("name") if hasattr(data, "get") else None, required=False) or \
            ds.clean_name(fallback, required=True)
        description = ((meta.get("dataset") or {}).get("description") if isinstance(meta, dict) else "") or ""
        dataset, version = ds.create_dataset(workspace, name=name, description=ds.clean_description(description[:2000]),
                                             raw_items=raw_items, note=f"Imported {len(raw_items)} items")
        return Response({"dataset": serializers.dataset_payload(dataset, version=version),
                         "imported": version.item_count, "ignored_columns": ignored}, status=201)


class DatasetDetailView(LabView):
    def get(self, request, dataset_id):
        return Response(serializers.dataset_payload(self.get_dataset(dataset_id)))

    def patch(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        data = request.data if isinstance(request.data, dict) else {}
        changed = False
        if "name" in data:
            dataset.name = ds.clean_name(data.get("name"), required=True)
            changed = True
        if "description" in data:
            dataset.description = ds.clean_description(data.get("description"))
            changed = True
        if changed:
            dataset.save(update_fields=["name", "description", "updated_at"])
        created = False
        if "items" in data or "document_ids" in data:
            items = data.get("items")
            if items is not None and not isinstance(items, list):
                raise invalid({"items": ["Expected a list of items."]})
            _version_row, created = ds.replace_content(
                dataset, raw_items=items, document_ids=data.get("document_ids") if "document_ids" in data else None,
                base_version=_base_version(data),
            )
        dataset.refresh_from_db()
        return Response({**serializers.dataset_payload(dataset), "version_created": created})

    def delete(self, request, dataset_id):
        self.get_dataset(dataset_id).delete()
        return Response(status=204)


class DatasetVersionsView(LabView):
    def get(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        return Response({"dataset_id": dataset.pk,
                         "results": [serializers.version_payload(version) for version in dataset.versions.order_by("-number")]})


class DatasetItemsView(LabView):
    def get(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        version = _version(dataset, request.query_params.get("version"))
        return Response({"dataset_id": dataset.pk, "version": serializers.version_payload(version),
                         "results": serializers.items_payload(dataset, version)})

    def post(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        data = request.data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            raw = data["items"]
        elif isinstance(data, dict) and "question" in data:
            raw = [{key: value for key, value in data.items() if key != "base_version"}]
        else:
            raise invalid({"items": ["Send an item, or {\"items\": [...]}."]})
        version, _created, added = ds.add_items(dataset, raw, base_version=_base_version(data))
        resolver = ds.DocumentResolver(dataset.workspace)
        offset = version.item_count - len(added)
        return Response({
            "version": serializers.version_payload(version),
            "items": [ds.output_item(item, offset + position, resolver) for position, item in enumerate(added, 1)],
        }, status=201)


class DatasetItemDetailView(LabView):
    def patch(self, request, dataset_id, item_id):
        dataset = self.get_dataset(dataset_id)
        data = request.data if isinstance(request.data, dict) else None
        if data is None:
            raise invalid({"item": ["Expected an object."]})
        version, _created, item = ds.update_item(dataset, item_id, data, base_version=_base_version(data))
        resolver = ds.DocumentResolver(dataset.workspace)
        position = next((index for index, row in enumerate(ds.version_items(version), 1)
                         if row["item_id"] == item["item_id"]), None)
        return Response({"version": serializers.version_payload(version),
                         "item": ds.output_item(item, position, resolver)})

    def delete(self, request, dataset_id, item_id):
        dataset = self.get_dataset(dataset_id)
        version = ds.delete_item(dataset, item_id, base_version=_base_version(request.data))
        return Response({"version": serializers.version_payload(version)})


class DatasetImportView(LabView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        data = request.data
        mode = (data.get("mode") if hasattr(data, "get") else None) or "append"
        if mode not in ("append", "replace"):
            raise invalid({"mode": ["Choose append or replace."]})
        raw_items, ignored, _meta = ds.read_import(data, request.FILES)
        version, _created, count = ds.import_items(dataset, raw_items, mode=mode, base_version=_base_version(data))
        return Response({"version": serializers.version_payload(version), "imported": count,
                         "ignored_columns": ignored}, status=201)


class _FormatIsAFileType(DefaultContentNegotiation):
    """`?format=csv` names the export's file type here, not a DRF renderer
    (DRF would answer an unknown renderer format with 404). Errors still
    render as JSON."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class DatasetExportView(LabView):
    content_negotiation_class = _FormatIsAFileType

    def get(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        fmt = (request.query_params.get("format") or "json").lower()
        if fmt not in ("json", "csv"):
            raise invalid({"format": ["Choose json or csv."]})
        version = _version(dataset, request.query_params.get("version"))
        if fmt == "csv":
            body, content_type = ds.export_csv(dataset, version), "text/csv; charset=utf-8"
        else:
            body = json.dumps(ds.export_json(dataset, version), ensure_ascii=False, indent=2)
            content_type = "application/json; charset=utf-8"
        response = HttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="dataset-{dataset.pk}-v{version.number}.{fmt}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response


class DatasetDraftView(LabView):
    def get(self, request, dataset_id):
        dataset = self.get_dataset(dataset_id)
        return Response(ds.draft_from_message(dataset.workspace, request.user, request.query_params.get("message_id")))
