"""Console helpers.

On Windows the default console codepage (cp1252) mangles Hebrew when printing
politician names / bill titles (they show as ``?????``). The *data* is always
correct UTF-8 — this only affects what the terminal renders. Call
:func:`enable_utf8_console` at the top of any user-facing entry point so Hebrew
output is readable.
"""

from __future__ import annotations

import sys


def enable_utf8_console() -> None:
    """Best-effort: reconfigure stdout/stderr to UTF-8. No-op if unsupported."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                # Closed/redirected stream or a platform that refuses — ignore.
                pass
