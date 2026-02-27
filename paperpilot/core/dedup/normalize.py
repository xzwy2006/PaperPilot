"""
Normalization utilities for deduplication.
"""
import re
import unicodedata


def normalize_title(text: str) -> str:
    """Unicode NFKC + lowercase + remove punctuation (keep \\w\\s) + collapse spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_author(text: str) -> str:
    """
    Lowercase + remove punctuation + collapse spaces.
    Returns the last name of the first author.
    Supports formats: "Last, First", "First Last", semicolon/and-separated lists.
    """
    if not text:
        return ""

    # Split by semicolon to get first author
    parts = re.split(r";", text)
    first_author = parts[0].strip()

    # Also split by ' and ' if no semicolon was present
    if len(parts) == 1:
        and_parts = re.split(r"\band\b", first_author, flags=re.IGNORECASE)
        if len(and_parts) > 1:
            first_author = and_parts[0].strip()

    # Extract last name
    # "Last, First Middle" format
    if "," in first_author:
        last_name = first_author.split(",")[0].strip()
    else:
        # "First [Middle] Last" format — take the last token
        tokens = first_author.strip().split()
        last_name = tokens[-1] if tokens else first_author

    last_name = last_name.lower()
    last_name = re.sub(r"[^\w\s]", " ", last_name)
    last_name = re.sub(r"\s+", " ", last_name).strip()
    return last_name


def normalize_doi(doi: str) -> str:
    """Lowercase + strip whitespace."""
    if not doi:
        return ""
    return doi.lower().strip()
