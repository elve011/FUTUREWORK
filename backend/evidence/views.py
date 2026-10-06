from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Avg, Count
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError
from domain.canonical import content_digest
from . import services
from .contract import build_contract
from .models import Evidence, EvidenceVerification


def _get(evidence_id) -> Evidence:
    ev = Evidence.objects.filter(evidence_id=evidence_id).first()
    if not ev:
        raise ApiError("EVIDENCE_NOT_FOUND", f"{evidence_id} not found", 404)
    return ev


class ManualEvidenceIn(serializers.Serializer):  # FR-E-12 (Could)
    projectId = serializers.CharField(max_length=32)
    milestoneId = serializers.CharField(max_length=32, required=False, allow_null=True)
    title = serializers.CharField(max_length=300)
    author = serializers.CharField(max_length=100)
    content = serializers.CharField()


class EvidenceListCreate(APIView):
    def get(self, request):
        qs = Evidence.objects.all()
        for param, field in (("projectId", "project_id"), ("milestoneId", "milestone_id"), ("status", "status"),
                             ("source", "source")):
            if (v := request.query_params.get(param)):
                qs = qs.filter(**{field: v})
        if request.query_params.get("unattached") == "1":
            qs = qs.filter(milestone_id__isnull=True)
        return Response([e.to_api() for e in qs.select_related("proof")[:200]])

    def post(self, request):
        s = ManualEvidenceIn(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        digest = content_digest(d["content"])
        n = {"source": "MANUAL", "source_ref": f"manual:{digest[7:23]}", "author": d["author"], "title": d["title"],
             "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "content_digest": digest,
             "milestone_id": (d.get("milestoneId") or "").upper() or None, "milestone_source": "manual",
             "metadata": {"message_ok": len(d["title"]) >= 10, "reviewed_or_merged": False}}
        ev, created = services.collect(d["projectId"], n)
        return Response(ev.to_api(detail=True), status=201 if created else 200)


class EvidenceDetail(APIView):
    def get(self, request, evidence_id):
        from hcs.models import HCSEvent
        ev = _get(evidence_id)
        out = ev.to_api(detail=True)
        out["hcsEvents"] = [e.to_api() for e in HCSEvent.objects.filter(evidence_id=ev.evidence_id)]
        return Response(out)


class VerifyView(APIView):
    def post(self, request, evidence_id):
        ev = services.process(_get(evidence_id))
        return Response(ev.to_api(detail=True))


class AttachView(APIView):
    def post(self, request, evidence_id):
        ms = request.data.get("milestoneId")
        if not ms:
            raise ApiError("VALIDATION_ERROR", "milestoneId is required", 400)
        ev = services.attach(_get(evidence_id), ms)
        if settings.AUTO_VERIFY:
            ev = services.process(ev)
        return Response(ev.to_api(detail=True))


class ContractView(APIView):
    def get(self, request, milestone_id):
        return Response(build_contract(milestone_id, request.query_params.get("projectId")))


class OverviewView(APIView):
    """Dashboard: Evidence Overview section."""

    def get(self, request):
        qs = Evidence.objects.all()
        if (p := request.query_params.get("projectId")):
            qs = qs.filter(project_id=p)
        by_status = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}
        scores = EvidenceVerification.objects.filter(evidence__in=qs).aggregate(avg=Avg("score"))["avg"]
        return Response({"total": qs.count(), "byStatus": by_status, "unattached": qs.filter(milestone_id__isnull=True).count(),
                         "averageScore": round(scores, 1) if scores is not None else None})
