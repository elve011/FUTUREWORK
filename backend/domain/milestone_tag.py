"""Link activity to a milestone (FR-E-03). Priority: label > branch > title > message."""
import re

_TAG = re.compile(r"(?<![A-Za-z0-9])M-(?:DEMO-)?\d{3}(?!\d)", re.I)


def find_milestone(text):
    m = _TAG.search(text or "")
    return m.group(0).upper() if m else None


def resolve_milestone(*, labels=(), branch="", title="", message=""):
    """Returns (milestone_id | None, source | None)."""
    for label in labels or ():
        if (found := find_milestone(label)):
            return found, "label"
    for source, text in (("branch", branch), ("title", title), ("message", message)):
        if (found := find_milestone(text)):
            return found, source
    return None, None
