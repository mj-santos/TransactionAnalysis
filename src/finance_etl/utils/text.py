"""Text normalization utilities."""
import re


def normalize_description(raw: str) -> str:
    """Strip and collapse internal whitespace. Preserve casing."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def normalize_for_fingerprint(raw: str) -> str:
    """Uppercase + collapse whitespace for stable fingerprint hashing."""
    return re.sub(r"\s+", " ", raw.strip().upper())
