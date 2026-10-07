"""Narrow Hedera testnet HBAR transfer adapter for the local demo account."""

from __future__ import annotations

import re


ENTITY_ID_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
DEMO_PAYMENT_HBAR = "0.1"
DEMO_PAYMENT_TINYBARS = 10_000_000


class HederaPaymentConfigurationError(Exception):
    """The local testnet signer or destination is not configured safely."""


class HederaPaymentSubmissionError(Exception):
    """A testnet transfer was rejected or its final outcome is uncertain."""

    def __init__(self, code, *, outcome_unknown):
        self.code = code
        self.outcome_unknown = outcome_unknown
        super().__init__(code)


def validate_testnet_payment_config(*, network, operator_id, private_key, recipient_id):
    if network != "testnet":
        raise HederaPaymentConfigurationError("HEDERA_TESTNET_ONLY")
    if not operator_id or not private_key or not recipient_id:
        raise HederaPaymentConfigurationError("HEDERA_TESTNET_SIGNER_NOT_CONFIGURED")
    if not ENTITY_ID_PATTERN.fullmatch(operator_id) or not ENTITY_ID_PATTERN.fullmatch(recipient_id):
        raise HederaPaymentConfigurationError("HEDERA_TESTNET_ACCOUNT_ID_INVALID")
    if operator_id == recipient_id:
        raise HederaPaymentConfigurationError("HEDERA_TESTNET_ACCOUNTS_MUST_DIFFER")
    normalized_key = private_key.removeprefix("0x")
    if len(normalized_key) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", normalized_key):
        raise HederaPaymentConfigurationError("HEDERA_TESTNET_ECDSA_KEY_INVALID")
    return normalized_key


def submit_testnet_hbar_transfer(*, operator_id, private_key, recipient_id):
    """Sign and submit exactly 0.1 HBAR, returning its SDK transaction ID."""
    try:
        import grpc
        from hiero_sdk_python import AccountId, Client, Network, PrivateKey, ResponseCode, TransferTransaction
        from hiero_sdk_python.exceptions import MaxAttemptsError, PrecheckError, ReceiptStatusError
    except ImportError as exc:
        raise HederaPaymentConfigurationError("HEDERA_SDK_NOT_INSTALLED") from exc

    try:
        signer = PrivateKey.from_string_ecdsa(private_key)
        sender = AccountId.from_string(operator_id)
        recipient = AccountId.from_string(recipient_id)
    except ValueError as exc:
        raise HederaPaymentConfigurationError("HEDERA_TESTNET_SIGNER_INVALID") from exc

    client = Client(Network("testnet"))
    client.set_operator(sender, signer)
    try:
        receipt = (
            TransferTransaction()
            .add_hbar_transfer(sender, -DEMO_PAYMENT_TINYBARS)
            .add_hbar_transfer(recipient, DEMO_PAYMENT_TINYBARS)
            .freeze_with(client)
            .sign(signer)
            .execute(client)
        )
    except (PrecheckError, ReceiptStatusError) as exc:
        raise HederaPaymentSubmissionError("HEDERA_TESTNET_TRANSFER_REJECTED", outcome_unknown=False) from exc
    except (MaxAttemptsError, grpc.RpcError, TimeoutError, OSError) as exc:
        raise HederaPaymentSubmissionError("HEDERA_TESTNET_TRANSFER_OUTCOME_UNKNOWN", outcome_unknown=True) from exc
    finally:
        client.close()

    if receipt.status != ResponseCode.SUCCESS:
        raise HederaPaymentSubmissionError("HEDERA_TESTNET_TRANSFER_NOT_SUCCESSFUL", outcome_unknown=False)
    if receipt.transaction_id is None:
        raise HederaPaymentSubmissionError("HEDERA_TESTNET_TRANSACTION_ID_MISSING", outcome_unknown=True)
    return str(receipt.transaction_id)
