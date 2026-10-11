"""Where MTPLX keeps its files: the four XDG roots, or one legacy tree.

``MTPLX_HOME`` set -> a single tree under it holds config, state, cache and
data side by side (the old ``~/.mtplx`` layout). Otherwise each kind lives in
its XDG root under an ``mtplx`` folder. Nothing here touches the filesystem,
and nothing falls back to ``~/.mtplx`` implicitly.
"""

from __future__ import annotations

import os
from pathlib import Path

LEGACY_HOME_ENV = "MTPLX_HOME"
APP_DIR = "mtplx"


def _legacy_home() -> Path | None:
    raw = os.environ.get(LEGACY_HOME_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def _xdg_root(env_name: str, default: str) -> Path:
    # The XDG spec says to ignore a relative value.
    raw = os.environ.get(env_name, "").strip()
    if raw and os.path.isabs(raw):
        return Path(raw) / APP_DIR
    return Path.home() / default / APP_DIR


def config_dir() -> Path:
    """config.toml, api-key."""
    return _legacy_home() or _xdg_root("XDG_CONFIG_HOME", ".config")


def state_dir() -> Path:
    """logs/, metrics/, reports/, history, max-active.json, benchmarks/."""
    return _legacy_home() or _xdg_root("XDG_STATE_HOME", ".local/state")


def cache_dir() -> Path:
    """build-cache/, hf-cache/, session-bank/."""
    return _legacy_home() or _xdg_root("XDG_CACHE_HOME", ".cache")


def data_dir() -> Path:
    """models/, hf-upload/, bin/thermalforge, build/ThermalForge."""
    return _legacy_home() or _xdg_root("XDG_DATA_HOME", ".local/share")
