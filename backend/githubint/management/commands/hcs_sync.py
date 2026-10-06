from django.core.management.base import BaseCommand

from evidence.services import reconcile_anchored
from hcs.services import sync


class Command(BaseCommand):
    help = "Retry queued HCS submits and finish Mirror Node readbacks"

    def handle(self, *args, **opts):
        res = sync()
        res["anchoredReconciled"] = reconcile_anchored()
        self.stdout.write(str(res))
