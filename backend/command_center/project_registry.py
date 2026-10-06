"""Validation helpers for explicitly reviewed local project records."""

import csv
import hashlib
import io
import json

from rest_framework import serializers

from .models import ProjectReference
from .serializers import ProjectInputSerializer


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 500


def extract_import_rows(request):
    uploaded = request.FILES.get("file")
    if uploaded is not None:
        if uploaded.size > MAX_IMPORT_BYTES:
            raise serializers.ValidationError({"file": "IMPORT_TOO_LARGE: maximum size is 2 MiB."})
        raw = uploaded.read()
        digest = hashlib.sha256(raw).hexdigest()
        file_name = uploaded.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255]
        try:
            if file_name.lower().endswith(".csv"):
                text = raw.decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise serializers.ValidationError({"file": "En-têtes CSV absents ou dupliqués."})
                rows = list(reader)
            elif file_name.lower().endswith(".json"):
                document = json.loads(raw.decode("utf-8-sig"))
                rows = document.get("projects") if isinstance(document, dict) else document
            else:
                raise serializers.ValidationError({"file": "Format accepté : .csv ou .json."})
        except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
            raise serializers.ValidationError({"file": "Fichier illisible ou encodage invalide."}) from exc
    else:
        rows = request.data.get("projects") if isinstance(request.data, dict) else None
        if not isinstance(rows, list):
            raise serializers.ValidationError({"projects": "Fournir une liste JSON 'projects' ou un fichier CSV/JSON."})
        raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_IMPORT_BYTES:
            raise serializers.ValidationError({"projects": "IMPORT_TOO_LARGE: maximum size is 2 MiB."})
        digest = hashlib.sha256(raw).hexdigest()
        file_name = ""

    if not isinstance(rows, list) or not rows:
        raise serializers.ValidationError({"projects": "Le fichier doit contenir au moins un projet."})
    if len(rows) > MAX_IMPORT_ROWS:
        raise serializers.ValidationError({"projects": f"Maximum {MAX_IMPORT_ROWS} projets par import."})
    return rows, digest, file_name


def validate_import_rows(rows):
    accepted = []
    rejected = []
    seen = set()
    for row_number, raw_row in enumerate(rows, start=1):
        serializer = ProjectInputSerializer(data=raw_row)
        if not serializer.is_valid():
            rejected.append({"row": row_number, "errors": serializer.errors})
            continue
        row = dict(serializer.validated_data)
        external_id = row["external_id"]
        if external_id in seen:
            rejected.append({"row": row_number, "external_id": external_id, "errors": {"external_id": ["Doublon dans le fichier."]}})
            continue
        seen.add(external_id)
        if ProjectReference.objects.filter(external_id=external_id).exists():
            rejected.append({"row": row_number, "external_id": external_id, "errors": {"external_id": ["Ce projet existe déjà dans le registre."]}})
            continue
        accepted.append(row)
    return accepted, rejected
