"""Canonical concept key normalization.

This is the single source of truth for normalize_key(). Both
distill_manifest.py and buffer_manager.py should import from here.

Algorithm:
  1. Strip whitespace and lowercase
  2. Remove parenthetical content: "Wholeness (W)" -> "wholeness"
  3. Remove special characters (keep only a-z, 0-9, underscore, space)
  4. Replace spaces with underscores
  5. Truncate to 40 characters
"""

import re


def normalize_key(text: str) -> str:
    """Normalize a concept name to a marker key.

    >>> normalize_key('Wholeness (W)')
    'wholeness'
    >>> normalize_key('Degrees of life')
    'degrees_of_life'
    >>> normalize_key('Cross-metathesis')
    'crossmetathesis'
    >>> normalize_key('A' * 50)
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    """
    s = text.strip().lower()
    s = re.sub(r'\(.*?\)', '', s)           # strip parentheticals
    s = re.sub(r'[^a-z0-9\s_]', '', s)     # strip special chars
    s = re.sub(r'\s+', '_', s.strip())      # spaces to underscores
    return s[:40]
