"""Read-only settlement observation port for later provider integration."""


class SettlementSourceUnavailable(NotImplementedError):
    pass


class UnavailableSettlementAdapter:
    source = "unavailable"

    def observe(self, settlement):
        raise SettlementSourceUnavailable("No settlement observation source is configured.")


def get_settlement_adapter(mode="local"):
    """Fail closed until a real observation provider is configured in integration."""
    if mode in {"local", "mock"}:
        return UnavailableSettlementAdapter()
    raise SettlementSourceUnavailable(f"Settlement source mode '{mode}' is not implemented.")
