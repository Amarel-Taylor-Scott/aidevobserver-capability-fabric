"""Stable local data paths independent of the caller's working directory."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("AIDEVOBSERVER_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "aidevobserver"
    return Path.home() / ".local" / "share" / "aidevobserver"


def default_db() -> Path:
    return data_dir() / "fabric.sqlite"
