"""A single exception type for user-facing failures.

Anything the CLI catches and prints as `Error: ...` must be a TaxcalcError --
a condition the user caused and can fix (bad input, bad config, a broken
rates file). Anything else is a bug and crashes with a full traceback.
"""

from __future__ import annotations


class TaxcalcError(Exception):
    """A user-facing error: bad input, bad config, or similar -- not a bug."""
