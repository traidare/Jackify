"""
Detects Creation Club / Anniversary Edition content missing errors in engine output.
"""

import re
from typing import Optional

# Matches CC content file names: ccXXXsse001-name.bsa/esm/esl/esp, ccXXXfo4001-name.ba2, etc.
# No leading \b — filenames often appear with a Data_ prefix (Data_ccbgssse019-...)
# where _ is a word char and would prevent \b from matching.
_CC_FILE_RE = re.compile(
    r'cc[a-z]{2,8}\d{3,4}[-\w]*\.(?:bsa|esm|esl|esp|ba2)',
    re.IGNORECASE
)

_ERROR_WORDS = frozenset((
    'missing', 'required', 'failed', 'unable', 'cannot', 'error', 'not found',
))


def is_cc_content_error(line: str) -> bool:
    """Return True if line indicates a missing CC/AE content file in an error context."""
    if not line:
        return False
    normalized = line.strip().lower()
    if not _CC_FILE_RE.search(normalized):
        return False
    return any(w in normalized for w in _ERROR_WORDS)


def extract_cc_filename(line: str) -> Optional[str]:
    """Return the CC filename from a line, or None if not found."""
    m = _CC_FILE_RE.search(line)
    return m.group(0) if m else None
