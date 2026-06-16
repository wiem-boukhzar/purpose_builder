# Text normalization utilities shared by ontology_loader (while building indexes) and
# disease_linker (while matching user terms to MONDO labels).
from __future__ import annotations

import re
import unicodedata


# Handle patterns like "cancer of liver" -> "liver cancer" for better alignment.
_CANCER_OF_PATTERN = re.compile(r"\bcancer of ([a-z0-9\s]+)\b")


def normalize(value: str) -> str:
    """Normalize free-text disease labels for fuzzy matching."""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKD", value.lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text)

    def _swap(match: re.Match[str]) -> str:
        swapped = match.group(1).strip()
        return f"{swapped} cancer" if swapped else "cancer"

    text = _CANCER_OF_PATTERN.sub(_swap, text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
