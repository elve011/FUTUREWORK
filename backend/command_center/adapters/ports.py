from typing import Protocol


class ProjectDataSource(Protocol):
    def get_project_snapshot(self, project_id: str) -> dict: ...


class HederaObserver(Protocol):
    def get_activity(self, project_id: str) -> list[dict]: ...

    def get_transactions(self, project_id: str) -> list[dict]: ...


HederaDataSource = HederaObserver
