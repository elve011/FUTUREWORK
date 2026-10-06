from django.urls import path
from rest_framework.schemas import get_schema_view

from . import views
from . import auth_views

urlpatterns = [
    path("api/auth/csrf", auth_views.csrf_token, name="auth-csrf"),
    path("api/auth/signup", auth_views.signup, name="auth-signup"),
    path("api/auth/login", auth_views.login_view, name="auth-login"),
    path("api/auth/logout", auth_views.logout_view, name="auth-logout"),
    path("api/auth/me", auth_views.me, name="auth-me"),
    path("api/freelancer/projects", views.freelancer_projects, name="freelancer-projects"),
    path("api/freelancer/projects/<str:project_id>", views.freelancer_project_detail, name="freelancer-project-detail"),
    path("api/freelancer/projects/<str:project_id>/members", views.freelancer_project_members, name="freelancer-project-members"),
    path("api/freelancer/projects/<str:project_id>/approvals", views.freelancer_project_approval, name="freelancer-project-approval"),
    path("api/freelancer/projects/<str:project_id>/milestones/<str:milestone_id>/complete", views.freelancer_complete_milestone, name="freelancer-project-milestone-complete"),
    path("api/freelancer/projects/<str:project_id>/evidence/test", views.freelancer_submit_test_evidence, name="freelancer-test-evidence"),
    path("api/freelancer/projects/<str:project_id>/evidence/github", views.freelancer_submit_github_evidence, name="freelancer-github-evidence"),
    path("api/freelancer/projects/<str:project_id>/hedera/testnet/config", views.freelancer_hedera_demo_config, name="freelancer-hedera-demo-config"),
    path("api/freelancer/projects/<str:project_id>/hedera/testnet/transfers", views.freelancer_hedera_demo_transfer, name="freelancer-hedera-demo-transfer"),
    path("api/freelancer/projects/<str:project_id>/policy-evaluations", views.freelancer_evaluate_policy, name="freelancer-policy-evaluate"),
    path("healthz", views.health, name="health"),
    path("api/agents", views.agents, name="agents"),
    path("api/agents/status", views.agent_status, name="agent-status"),
    path("api/agents/actions", views.agent_actions, name="agent-actions"),
    path("api/agents/<str:agent_id>/history", views.agent_history, name="agent-history"),
    path("api/settlements", views.settlements, name="settlements"),
    path("api/settlements/<str:settlement_id>", views.settlement_detail, name="settlement-detail"),
    path("api/events/ingest", views.ingest_event, name="event-ingest"),
    path("api/projects", views.project_registry, name="project-registry"),
    path("api/projects/import/preview", views.project_import_preview, name="project-import-preview"),
    path("api/projects/imports/<uuid:batch_id>/commit", views.project_import_commit, name="project-import-commit"),
    path("api/projects/<str:project_id>/activity", views.project_activity, name="project-activity"),
    path("api/projects/<str:project_id>/alerts", views.project_alerts, name="project-alerts"),
    path("api/projects/<str:project_id>/metrics", views.project_metrics, name="project-metrics"),
    path("api/projects/<str:project_id>/hedera/activity", views.hedera_activity, name="hedera-activity"),
    path("api/projects/<str:project_id>/hedera/transactions", views.hedera_transactions, name="hedera-transactions"),
    path("api/projects/<str:project_id>/dashboard", views.project_dashboard, name="project-dashboard"),
    path("api/openapi", get_schema_view(title="FUTUREWORK Dev 4 API", version="1.0.0"), name="openapi-schema"),
]
