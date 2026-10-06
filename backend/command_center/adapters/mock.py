"""Deterministic fixture adapters for a self-contained Dev 4 demo."""

import json
from functools import lru_cache
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@lru_cache(maxsize=8)
def _read_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class MockProjectAdapter:
    source = "mock"

    def get_project_snapshot(self, project_id):
        fixture = _read_fixture("project_fw_demo_001.json")
        if fixture["project_id"] != project_id:
            raise KeyError(f"Project fixture not found: {project_id}")
        return {**fixture, "source": self.source}


class MockHederaAdapter:
    source = "mock-mirror-node-fixture"

    def get_activity(self, project_id):
        fixture = _read_fixture("mirror_node_fw_demo_001.json")
        if fixture["project_id"] != project_id:
            raise KeyError(f"Hedera fixture not found for project: {project_id}")
        return [{**item, "source": self.source} for item in fixture["activity"]]

    def get_transactions(self, project_id):
        fixture = _read_fixture("mirror_node_fw_demo_001.json")
        if fixture["project_id"] != project_id:
            raise KeyError(f"Hedera fixture not found for project: {project_id}")
        return [{**item, "source": self.source} for item in fixture["transactions"]]


def get_project_adapter(mode):
    if mode == "mock":
        return MockProjectAdapter()
    raise NotImplementedError("Live Project Contract adapter is not implemented yet; refusing to label mock data as live.")


def get_hedera_adapter(mode):
    if mode == "mock":
        return MockHederaAdapter()
    if mode == "live":
        from .hedera import MirrorNodeObserver

        return MirrorNodeObserver()
    raise NotImplementedError(f"Unsupported Hedera source mode: {mode}")
