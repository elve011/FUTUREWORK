from django.contrib import admin
from django.urls import path

from common.views import health
from evidence import views as ev
from githubint import views as gh
from hcs import views as hc

urlpatterns = [
    path("health", health),
    path("admin/", admin.site.urls),
    # GitHub
    path("api/evidence/github/connect", gh.ConnectView.as_view()),
    path("api/evidence/github/webhook", gh.WebhookView.as_view()),
    path("api/evidence/github/sync", gh.SyncView.as_view()),
    path("api/evidence/github/commits", gh.CommitList.as_view()),
    path("api/evidence/github/pulls", gh.PullList.as_view()),
    path("api/evidence/github/reviews", gh.ReviewList.as_view()),
    # Evidence (fixed paths BEFORE the <evidence_id> catch-all)
    path("api/evidence", ev.EvidenceListCreate.as_view()),
    path("api/evidence/overview", ev.OverviewView.as_view()),
    path("api/evidence/milestones/<str:milestone_id>/contract", ev.ContractView.as_view()),
    path("api/evidence/<str:evidence_id>", ev.EvidenceDetail.as_view()),
    path("api/evidence/<str:evidence_id>/verify", ev.VerifyView.as_view()),
    path("api/evidence/<str:evidence_id>/attach", ev.AttachView.as_view()),
    # HCS
    path("api/hcs/topics", hc.TopicView.as_view()),
    path("api/hcs/events", hc.EventListCreate.as_view()),
    path("api/hcs/timeline", hc.TimelineView.as_view()),
    path("api/hcs/sync", hc.SyncView.as_view()),
]
