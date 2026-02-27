"""
paperpilot/core/screening/protocol.py
Load and manage screening protocols and exclusion-reason taxonomies.
"""
from __future__ import annotations

import importlib.resources
import json
import pathlib
from typing import Any

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:          # pragma: no cover
    _YAML_AVAILABLE = False


# ─────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────

def _assets_dir() -> pathlib.Path:
    """Return absolute path to paperpilot/assets/templates/."""
    here = pathlib.Path(__file__).resolve()          # .../core/screening/protocol.py
    return here.parents[2] / "assets" / "templates"


def _read_text(filename: str) -> str:
    """Read a template file and return its raw text content."""
    path = _assets_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Template not found: {path}. "
            "Make sure the paperpilot package is installed correctly."
        )
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────

def load_default_protocol() -> dict[str, Any]:
    """Load the default screening protocol from *protocol_default.json*.

    Returns
    -------
    dict
        Parsed protocol with keys such as ``inclusion_criteria``,
        ``exclusion_criteria``, ``must_exclude_terms``,
        ``soft_exclude_terms``, ``design_allowlist``, etc.
    """
    raw = _read_text("protocol_default.json")
    return json.loads(raw)


def load_reasons_taxonomy() -> dict[str, str]:
    """Load the exclusion-reason taxonomy from *reasons_taxonomy.yaml*.

    Returns
    -------
    dict
        Flat mapping from reason code (e.g. ``"TA006"``) to human-readable
        label (e.g. ``"Non-human subjects"``).

    Raises
    ------
    ImportError
        If PyYAML is not installed.
    """
    if not _YAML_AVAILABLE:
        raise ImportError(
            "PyYAML is required to load reasons_taxonomy.yaml. "
            "Install it with: pip install pyyaml"
        )
    raw = _read_text("reasons_taxonomy.yaml")
    data: dict = yaml.safe_load(raw)
    # The YAML has a top-level key "exclusion_reasons"
    return data.get("exclusion_reasons", data)
