import os

from hiero_sdk_python import (
    AccountId,
    Client,
    Network,
    PrivateKey,
    SupplyType,
    TokenCreateTransaction,
    TokenType,
)


def normalize_transaction_id(transaction_id):
    """Return the canonical hyphen-separated ID used by Mirror Node/HashScan."""
    value = str(transaction_id or "").strip()
    if "@" not in value:
        return value

    account_id, timestamp = value.split("@", 1)
    seconds, separator, nanos = timestamp.partition(".")
    if not separator or not account_id or not seconds or not nanos:
        return value

    return f"{account_id}-{seconds}-{nanos}"


def get_hedera_client():
    """Prepare a Hedera Testnet client using credentials from .env."""
    network_name = os.getenv("HEDERA_NETWORK", "testnet").strip().lower()

    if network_name != "testnet":
        raise ValueError("HEDERA_NETWORK doit être défini sur testnet.")

    account_id = os.getenv("HEDERA_ACCOUNT_ID")
    private_key = os.getenv("HEDERA_PRIVATE_KEY")

    if not account_id or not private_key:
        raise ValueError(
            "HEDERA_ACCOUNT_ID et HEDERA_PRIVATE_KEY doivent être définis dans .env."
        )

    try:
        operator_account = AccountId.from_string(account_id)
        # Hedera Portal provides the operator key as hex-encoded DER. Parse
        # that format directly; from_string_ecdsa expects only a raw 32-byte
        # scalar and rejects the portal's DER wrapper.
        operator_key = PrivateKey.from_string_der(private_key)
    except Exception as exc:
        raise ValueError(
            "Les identifiants Hedera dans .env ne sont pas valides."
        ) from exc

    client = Client(Network("testnet"))
    client.set_operator(operator_account, operator_key)

    return client, operator_account, operator_key


def create_fungible_token(name, symbol, total_units):
    """
    Create a fixed-supply fungible token on Hedera Testnet.

    Calling this function submits a real Testnet transaction and spends test HBAR.
    """
    if not name or not name.strip():
        raise ValueError("Le nom du token est obligatoire.")

    if not symbol or not symbol.strip():
        raise ValueError("Le symbole du token est obligatoire.")

    if not isinstance(total_units, int) or total_units <= 0:
        raise ValueError("total_units doit être un entier positif.")

    client, treasury_account, operator_key = get_hedera_client()

    transaction = (
        TokenCreateTransaction()
        .set_token_name(name.strip())
        .set_token_symbol(symbol.strip().upper())
        .set_token_type(TokenType.FUNGIBLE_COMMON)
        .set_supply_type(SupplyType.FINITE)
        .set_decimals(0)
        .set_initial_supply(total_units)
        .set_max_supply(total_units)
        .set_freeze_default(False)
        .set_treasury_account_id(treasury_account)
        .freeze_with(client)
    )

    transaction.sign(operator_key)

    # Dans ta version du SDK, execute() renvoie directement le reçu par défaut.
    receipt = transaction.execute(client)

    if receipt.token_id is None:
        raise RuntimeError("Hedera n’a pas retourné de Token ID.")

    return {
        "token_id": str(receipt.token_id),
        "transaction_id": normalize_transaction_id(
            transaction.transaction_id
        ),
        "total_supply": total_units,
        "decimals": 0,
    }
