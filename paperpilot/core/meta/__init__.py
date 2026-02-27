"""
paperpilot/core/meta/__init__.py
Meta-analysis module: R runner + data preparation utilities.
"""

from .data_prep import prepare_meta_data, validate_meta_data
from .runner import MetaRunner

__all__ = [
    "MetaRunner",
    "prepare_meta_data",
    "validate_meta_data",
]
