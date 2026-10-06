from django.contrib import admin

from .models import CodeReview, GitHubCommit, GitHubRepository, PullRequest, WebhookDelivery

for m in (GitHubRepository, WebhookDelivery, GitHubCommit, PullRequest, CodeReview):
    admin.site.register(m)
