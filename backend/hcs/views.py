from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError
from evidence import services as evidence_services
from evidence.models import Evidence
from . import services
from .models import HCSEvent, HCSTopic


class TopicIn(serializers.Serializer):
    projectId = serializers.CharField(max_length=32)


class TopicView(APIView):
    def get(self, request):
        return Response([t.to_api() for t in HCSTopic.objects.all()])

    def post(self, request):
        s = TopicIn(data=request.data)
        s.is_valid(raise_exception=True)
        existed = HCSTopic.objects.filter(project_id=s.validated_data["projectId"]).exists()
        topic = services.get_or_create_topic(s.validated_data["projectId"])
        return Response(topic.to_api(), status=200 if existed else 201)


class EventIn(serializers.Serializer):
    evidenceId = serializers.CharField(max_length=32)


class EventListCreate(APIView):
    def get(self, request):
        qs = HCSEvent.objects.select_related("topic")
        if (p := request.query_params.get("projectId")):
            qs = qs.filter(topic__project_id=p)
        if (st := request.query_params.get("status")):
            qs = qs.filter(status=st)
        return Response([e.to_api() for e in qs[:200]])

    def post(self, request):
        """Anchor a verified evidence on HCS (idempotent: same hash -> same event)."""
        s = EventIn(data=request.data)
        s.is_valid(raise_exception=True)
        ev = Evidence.objects.filter(evidence_id=s.validated_data["evidenceId"]).first()
        if not ev:
            raise ApiError("EVIDENCE_NOT_FOUND", "Unknown evidenceId", 404)
        if ev.status not in (Evidence.Status.VERIFIED, Evidence.Status.ANCHORED):
            raise ApiError("EVIDENCE_NOT_VERIFIED", "Only verified evidence can be anchored", 409,
                           {"status": ev.status})
        ev = evidence_services.process(ev)
        event = HCSEvent.objects.select_related("topic").get(evidence_id=ev.evidence_id)
        return Response(event.to_api(), status=201)


class TimelineView(APIView):
    """Consensus timeline (FR-E-10): ordered by sequence number (= consensus order within a topic)."""

    def get(self, request):
        qs = HCSEvent.objects.select_related("topic").exclude(sequence_number__isnull=True)
        if (p := request.query_params.get("projectId")):
            qs = qs.filter(topic__project_id=p)
        return Response([e.to_api() for e in qs.order_by("topic_id", "sequence_number")])


class SyncView(APIView):
    def post(self, request):
        res = services.sync()
        res["anchoredReconciled"] = evidence_services.reconcile_anchored()
        return Response(res)
