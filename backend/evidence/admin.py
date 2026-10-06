from django.contrib import admin

from .models import EmittedEvent, Evidence, EvidenceHash, EvidenceVerification

for m in (Evidence, EvidenceVerification, EvidenceHash, EmittedEvent):
    admin.site.register(m)
