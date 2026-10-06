from django.contrib import admin

from .models import HCSEvent, HCSTopic

admin.site.register(HCSTopic)
admin.site.register(HCSEvent)
