from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mtplx import paths
from mtplx.server import openai
from mtplx.server.flight_recorder import resolve_flight_recorder

REPO_ROOT = Path(__file__).resolve().parents[1]
XDG_VARS = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")

# Module-level defaults are read at import, so a child process with the
# environment under test is the only honest way to see them.
_CONSTANTS_PROBE = """
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
probes = {
    "config": ("mtplx.config", "DEFAULT_CONFIG_PATH"),
    "models": ("mtplx.hf_loader", "DEFAULT_MODEL_CACHE"),
    "session_bank": ("mtplx.cache_bank.reconcile", "DEFAULT_COLD_TIER_DIR"),
    "quickstart": ("mtplx.ui.onboarding", "STATE_PATH"),
    "trace_logs": ("mtplx.commands.trace", "LOGS_DIR"),
    "trace_metrics": ("mtplx.commands.trace", "METRICS_DIR"),
    "aime": ("mtplx.benchmarks.runners.aime", "DEFAULT_PERSIST_DIR"),
    "tuning": ("mtplx.commands.public", "TUNE_STATE_PATH"),
    "history": ("mtplx.commands.public", "CHAT_HISTORY_PATH"),
    "forge_models": ("mtplx.default_models", "_MODELS"),
}
print(json.dumps({k: str(getattr(importlib.import_module(m), a)) for k, (m, a) in probes.items()}))
"""


@pytest.fixture
def xdg_env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    roots = {name: tmp_path / name.lower() for name in XDG_VARS}
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(paths.LEGACY_HOME_ENV, raising=False)
    for name, root in roots.items():
        monkeypatch.setenv(name, str(root))
    return SimpleNamespace(home=home, roots=roots)


def _child_env(home: Path, **extra: str) -> dict[str, str]:
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    env.update(extra)
    return env


def _constants(home: Path, **extra: str) -> dict[str, Path]:
    result = subprocess.run(
        [sys.executable, "-I", "-c", _CONSTANTS_PROBE, str(REPO_ROOT)],
        env=_child_env(home, **extra),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return {key: Path(value) for key, value in json.loads(result.stdout).items()}


def test_xdg_roots_win_when_set(xdg_env):
    roots = xdg_env.roots
    assert paths.config_dir() == roots["XDG_CONFIG_HOME"] / "mtplx"
    assert paths.state_dir() == roots["XDG_STATE_HOME"] / "mtplx"
    assert paths.cache_dir() == roots["XDG_CACHE_HOME"] / "mtplx"
    assert paths.data_dir() == roots["XDG_DATA_HOME"] / "mtplx"


def test_xdg_defaults_apply_when_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(paths.LEGACY_HOME_ENV, raising=False)
    for name in XDG_VARS:
        monkeypatch.delenv(name, raising=False)
    assert paths.config_dir() == tmp_path / ".config" / "mtplx"
    assert paths.state_dir() == tmp_path / ".local" / "state" / "mtplx"
    assert paths.cache_dir() == tmp_path / ".cache" / "mtplx"
    assert paths.data_dir() == tmp_path / ".local" / "share" / "mtplx"


def test_relative_or_empty_xdg_values_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(paths.LEGACY_HOME_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/dir")
    monkeypatch.setenv("XDG_STATE_HOME", "")
    assert paths.config_dir() == tmp_path / ".config" / "mtplx"
    assert paths.state_dir() == tmp_path / ".local" / "state" / "mtplx"


def test_mtplx_home_collapses_all_four_roots_into_one_tree(xdg_env, monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    monkeypatch.setenv(paths.LEGACY_HOME_ENV, str(legacy))
    assert (
        paths.config_dir()
        == paths.state_dir()
        == paths.cache_dir()
        == paths.data_dir()
        == legacy
    )


def test_mtplx_home_expands_user(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(paths.LEGACY_HOME_ENV, "~/old")
    assert paths.config_dir() == tmp_path / "old"


def test_import_time_defaults_follow_xdg(xdg_env):
    roots = {name: root / "mtplx" for name, root in xdg_env.roots.items()}
    env = {name: str(root) for name, root in xdg_env.roots.items()}
    found = _constants(xdg_env.home, **env)

    config, state = roots["XDG_CONFIG_HOME"], roots["XDG_STATE_HOME"]
    cache, data = roots["XDG_CACHE_HOME"], roots["XDG_DATA_HOME"]
    assert found["config"] == config / "config.toml"
    assert found["models"] == data / "models"
    assert found["forge_models"] == data / "models"
    assert found["session_bank"] == cache / "session-bank"
    assert found["quickstart"] == state / "quickstart.json"
    assert found["trace_logs"] == state / "logs"
    assert found["trace_metrics"] == state / "metrics"
    assert found["aime"] == state / "benchmarks" / "aime"
    assert found["tuning"] == state / "tuning.json"
    assert found["history"] == state / "history"


def test_import_time_defaults_follow_mtplx_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    legacy = tmp_path / "legacy"
    found = _constants(home, MTPLX_HOME=str(legacy))

    assert found["config"] == legacy / "config.toml"
    assert found["models"] == legacy / "models"
    assert found["session_bank"] == legacy / "session-bank"
    assert found["quickstart"] == legacy / "quickstart.json"
    assert found["trace_logs"] == legacy / "logs"
    assert found["trace_metrics"] == legacy / "metrics"
    assert found["aime"] == legacy / "benchmarks" / "aime"
    assert found["tuning"] == legacy / "tuning.json"
    assert found["history"] == legacy / "history"


def test_cli_config_defaults_follow_xdg(xdg_env):
    from mtplx.cli import build_parser

    expected = str(xdg_env.roots["XDG_CONFIG_HOME"] / "mtplx" / "config.toml")
    parser = build_parser()
    assert parser.parse_args(["init"]).config == expected
    assert parser.parse_args(["setup"]).config == expected


def test_explicit_overrides_still_beat_the_defaults(xdg_env, monkeypatch, tmp_path):
    from mtplx.cli import build_parser

    args = build_parser().parse_args(["init", "--config", str(tmp_path / "mine.toml")])
    assert args.config == str(tmp_path / "mine.toml")

    mine = tmp_path / "mine.jsonl"
    monkeypatch.setenv("MTPLX_REQUEST_LOG_JSONL", str(mine))
    state = SimpleNamespace(args=SimpleNamespace(port=8000))
    assert openai._request_log_path(state) == str(mine)

    monkeypatch.setenv("MTPLX_FLIGHT_RECORDER", str(mine))
    assert resolve_flight_recorder(SimpleNamespace(port=8000)).path == str(mine)


def test_default_path_functions_never_create_a_dotdir_in_home(xdg_env, monkeypatch):
    from mtplx import thermal_sidecar
    from mtplx.commands import forge

    monkeypatch.delenv("MTPLX_REQUEST_LOG_JSONL", raising=False)
    monkeypatch.delenv("MTPLX_FLIGHT_RECORDER", raising=False)
    monkeypatch.delenv("MTPLX_FORGE_CANCEL_DIR", raising=False)
    monkeypatch.delenv("MTPLX_FORGE_MODEL_ROOT", raising=False)
    monkeypatch.delenv("MTPLX_MODEL_DIR", raising=False)
    roots = {name: root / "mtplx" for name, root in xdg_env.roots.items()}

    state = SimpleNamespace(args=SimpleNamespace(port=8123))
    request_log = Path(openai._request_log_path(state))
    flight = Path(resolve_flight_recorder(SimpleNamespace(port=8123)).path)

    assert request_log == roots["XDG_STATE_HOME"] / "logs" / "request-log-8123.jsonl"
    assert flight == roots["XDG_STATE_HOME"] / "metrics" / "flight-8123.jsonl"
    assert request_log.parent.is_dir() and flight.parent.is_dir()
    assert Path(thermal_sidecar._log_path()) == (
        roots["XDG_STATE_HOME"] / "logs" / "thermal-sidecar.log"
    )
    assert forge._cancel_marker("run1") == (
        roots["XDG_STATE_HOME"] / "forge-cancel" / "run1.json"
    )
    assert forge._default_model_root() == roots["XDG_DATA_HOME"] / "models"
    assert paths.config_dir() / "api-key" == roots["XDG_CONFIG_HOME"] / "api-key"

    assert not (xdg_env.home / ".mtplx").exists()
    assert list(xdg_env.home.iterdir()) == []


_LITERAL = re.compile(r"""(?<=["'/])\.mtplx(?![\w-])""")

# ThermalForge's binary and build dir, and the max-active marker, stay under
# the home dotdir: the macOS app and the sudoers rule pin those absolute paths.
_PINNED_FILES = {Path("mtplx/paths.py"), Path("mtplx/thermal.py")}
# The macOS app writes the failed-start report there, and `mtplx doctor` reads it.
_PINNED_LINES = ("last-failed-start", "bin/thermalforge")


def test_no_hardcoded_dotdir_literal_outside_the_pinned_paths():
    offenders = []
    for source in sorted((REPO_ROOT / "mtplx").rglob("*.py")):
        relative = source.relative_to(REPO_ROOT)
        if relative in _PINNED_FILES:
            continue
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if _LITERAL.search(line) and not any(tag in line for tag in _PINNED_LINES):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == []
