import json

from django.conf import settings
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError
from ports.factory import get_port
from . import services
from .models import CodeReview, GitHubCommit, GitHubRepository, PullRequest
from .security import valid_signature


class ConnectIn(serializers.Serializer):
    projectId = serializers.CharField(max_length=32)
    repoFullName = serializers.RegexField(r"^[\w.-]+/[\w.-]+$")
    workerGithub = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    callbackUrl = serializers.URLField(required=False)  # public webhook URL (smee/ngrok); omit to configure manually


class ConnectView(APIView):
    def post(self, request):
        s = ConnectIn(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        repo, _ = GitHubRepository.objects.update_or_create(
            full_name=d["repoFullName"], defaults={"project_id": d["projectId"], "worker_github": d["workerGithub"]})
        if d.get("callbackUrl"):
            hook = get_port("github").ensure_webhook(repo.full_name, d["callbackUrl"])
            repo.webhook_id = hook.get("id")
            repo.save(update_fields=["webhook_id"])
        return Response(repo.to_api(), status=201)


class WebhookView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        body = request.body  # raw bytes: must be read for the HMAC (do not touch request.data)
        if not valid_signature(settings.GITHUB_WEBHOOK_SECRET, body, request.headers.get("X-Hub-Signature-256", "")):
            raise ApiError("INVALID_SIGNATURE", "Webhook signature verification failed", 401)
        delivery_id, event = request.headers.get("X-GitHub-Delivery"), request.headers.get("X-GitHub-Event")
        if not delivery_id or not event:
            raise ApiError("VALIDATION_ERROR", "X-GitHub-Delivery and X-GitHub-Event headers are required", 400)
        try:
            payload = json.loads(body)
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "Body is not valid JSON", 400)
        return Response(services.handle_delivery(delivery_id, event, payload), status=202)


class _List(APIView):
    model = None

    def get(self, request):
        qs = self.model.objects.select_related("repo")
        if (p := request.query_params.get("projectId")):
            qs = qs.filter(repo__project_id=p)
        if (m := request.query_params.get("milestoneId")):
            qs = qs.filter(milestone_id=m)
        return Response([o.to_api() for o in qs[:200]])


class CommitList(_List):
    model = GitHubCommit


class PullList(_List):
    model = PullRequest


class ReviewList(_List):
    model = CodeReview


class SyncView(APIView):
    """Backfill from the GitHub API (needs FW_MODE_GITHUB=live + GITHUB_TOKEN)."""

    def post(self, request):
        pid = request.data.get("projectId")
        if not pid:
            raise ApiError("VALIDATION_ERROR", "projectId is required", 400)
        return Response(services.backfill(pid))
