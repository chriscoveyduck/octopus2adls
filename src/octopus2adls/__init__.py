"""Compatibility facade package expected by tests.

The original implementation lives under ``octopusclient`` but the test
suite (and earlier code) import ``octopus2adls``.  We re-export the
public symbols here to avoid duplicating logic while keeping backwards
compatibility.
"""

from .client import OctopusClient  # noqa: F401
from .config import Meter, OctopusSettings, Settings  # noqa: F401
from .enrich import detect_missing_intervals, vectorized_rate_join  # noqa: F401
from .storage import DataLakeWriter, StateStore  # noqa: F401

__all__ = [
    'OctopusClient', 'Settings', 'OctopusSettings', 'Meter',
    'DataLakeWriter', 'StateStore', 'vectorized_rate_join', 'detect_missing_intervals'
]
