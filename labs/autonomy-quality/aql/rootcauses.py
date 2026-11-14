"""What the lab knows about each root cause: a title, the expected behaviour,
a suggested correction and regression acceptance criteria.

The classifier (``classify.py``) decides WHICH root cause a failure belongs
to from the observed behaviour. This file only describes them. A root cause
with no entry here is still reported, with its witness trace, as not yet
analysed.

Suggestions point at behaviour, not at lines: the backend is Agent 1's, and
the lab reads it only through its API.
"""
from __future__ import annotations

from typing import Any, Dict

KNOWLEDGE: Dict[str, Dict[str, Any]] = {}
