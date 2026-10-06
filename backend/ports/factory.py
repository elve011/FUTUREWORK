"""Port/Adapter switch. FW_MODE=mock|live globally, FW_MODE_<NAME> per source (spec FR-A-12 / section 11)."""
import os

from . import mock, real

_MOCK = {"project": mock.MockProject, "github": mock.MockGitHub, "hcs": mock.MockHcs, "mirror": mock.MockMirror,
         "events": mock.MockEvents, "llm": mock.MockLLM}
_REAL = {"project": real.RealProject, "github": real.RealGitHub, "hcs": real.RealHcs, "mirror": real.RealMirror,
         "events": real.RealEvents, "llm": real.RealLLM}


def mode_for(name: str) -> str:
    return os.getenv(f"FW_MODE_{name.upper()}") or os.getenv("FW_MODE", "mock")


def get_port(name: str):
    return (_REAL if mode_for(name) == "live" else _MOCK)[name]()
