"""Real-network preflight: operator balance -> create topic -> submit message -> Mirror Node readback."""
import json
import os
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ports.factory import get_port


class Command(BaseCommand):
    help = "Verify the live Hedera testnet chain end to end (uses a throwaway topic)"

    def handle(self, *args, **opts):
        os.environ["FW_MODE_HCS"] = os.environ["FW_MODE_MIRROR"] = "live"
        op = os.getenv("HEDERA_OPERATOR_ID")
        if not op or not os.getenv("HEDERA_OPERATOR_KEY"):
            raise CommandError("Set HEDERA_OPERATOR_ID and HEDERA_OPERATOR_KEY in backend/.env (free testnet account: portal.hedera.com)")

        r = requests.get(f"{settings.MIRROR_NODE_URL}/api/v1/accounts/{op}", timeout=15)
        if r.status_code != 200:
            raise CommandError(f"Mirror Node cannot see account {op} (HTTP {r.status_code})")
        hbar = r.json()["balance"]["balance"] / 1e8
        self.stdout.write(f"1/4 operator {op}: {hbar:.2f} HBAR")
        if hbar < 1:
            raise CommandError("Balance too low: top up from the testnet faucet at portal.hedera.com")

        t0 = time.time()
        topic_id = get_port("hcs").create_topic("fw-hedera-check")
        self.stdout.write(f"2/4 topic created {topic_id}  ({time.time() - t0:.1f}s)\n    https://hashscan.io/testnet/topic/{topic_id}")

        msg = json.dumps({"v": 1, "t": "HEDERA_CHECK", "ts": int(time.time())}, separators=(",", ":"))
        res = get_port("hcs").submit(topic_id, msg)
        self.stdout.write(f"3/4 message submitted, sequence #{res['sequenceNumber']}, tx {res['transactionId']}")

        mirror = get_port("mirror")
        for i in range(10):
            got = mirror.get_message(topic_id, res["sequenceNumber"])
            if got:
                ok = got["message"] == msg
                self.stdout.write(f"4/4 Mirror Node readback after ~{i * 2}s: consensus {got['consensusTimestamp']}, identical={ok}")
                if not ok:
                    raise CommandError("Readback mismatch")
                self.stdout.write(self.style.SUCCESS("Hedera chain OK: set FW_MODE_HCS=live and FW_MODE_MIRROR=live"))
                return
            time.sleep(2)
        raise CommandError("Message not visible on Mirror Node after 20s (retry; testnet mirror can lag)")
