"""Load recorded pre-06 modules without editing the active checkout."""

import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pytest

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / "backend"))
for name, path in (
    ("app.core.config", "backend/app/core/config.py"),
    ("app.prompts.semantic", "backend/app/prompts/semantic.py"),
    ("app.services.turn_stream_service", "backend/app/services/turn_stream_service.py"),
):
    module = ModuleType(name)
    module.__file__ = str(root / path)
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    setattr(import_module(module.__package__), name.rpartition(".")[2], module)
    source = Path(__file__).parent / "before" / path
    exec(compile(source.read_text(encoding="utf-8"), module.__file__, "exec"), module.__dict__)

raise SystemExit(pytest.main(sys.argv[1:]))
