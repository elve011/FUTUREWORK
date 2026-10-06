"""Opt-in Testnet smoke test; this creates a real token and spends test HBAR."""

import os
import unittest

from django.test import SimpleTestCase

from .hedera_service import create_fungible_token


@unittest.skipUnless(
    os.getenv("RUN_HEDERA_TESTNET_TESTS") == "1",
    "Set RUN_HEDERA_TESTNET_TESTS=1 to submit a real Testnet token creation.",
)
class HederaTestnetTokenCreationTests(SimpleTestCase):
    def test_creates_fungible_token_with_expected_supply(self):
        result = create_fungible_token(
            name="FutureWork Dev 1 Smoke Test",
            symbol="FWTEST",
            total_units=3,
        )
        self.assertRegex(result["token_id"], r"^0\.0\.\d+$")
        self.assertEqual(result["total_supply"], 3)
        self.assertEqual(result["decimals"], 0)
        self.assertTrue(result["transaction_id"])
