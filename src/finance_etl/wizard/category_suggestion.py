"""
Dynamic Category Generation — Clustering
=========================================

Clusters a list of transaction descriptions and returns suggested category
labels together with their representative keywords.

Two strategies are available:

1. **K-Means + TF-IDF** (preferred) — uses scikit-learn's TfidfVectorizer
   and KMeans.  Produces semantically meaningful clusters.

2. **Word-frequency fallback** — pure Python, no extra dependencies.
   Groups the most-common tokens into buckets.  Used automatically when
   scikit-learn is not installed.

Public function
---------------
suggest_categories(descriptions, n_clusters=8) -> dict[str, list[str]]

Returns
-------
{
    "Suggested Category 1": ["KEYWORD_A", "KEYWORD_B", ...],
    "Suggested Category 2": [...],
    ...
}
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from typing import Sequence


# ---------------------------------------------------------------------------
# Built-in stopword list (avoids requiring NLTK download)
# ---------------------------------------------------------------------------
_STOPWORDS: frozenset[str] = frozenset({
    # English function words
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "at", "by",
    "for", "with", "from", "is", "was", "are", "be", "been", "being",
    "it", "its", "this", "that", "as", "if", "do", "did", "have", "has",
    "had", "will", "would", "could", "should", "may", "might", "shall",
    # Generic transaction noise
    "purchase", "transaction", "payment", "pos", "debit", "credit",
    "card", "online", "store", "llc", "inc", "ltd", "co", "corp",
    "us", "ny", "ca", "tx", "fl", "wa", "uk", "gb",
    # Common abbreviations in bank feeds
    "sq", "pp", "wwwpaypal", "paypal",
})

_DEFAULT_N_CLUSTERS = 8


# ---------------------------------------------------------------------------
# Tokenisation helper (shared by both strategies)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """
    Normalise and tokenise a transaction description.

    Steps:
    1. Upper-case (most bank descriptions are already upper-case).
    2. Strip non-alphanumeric characters.
    3. Split on whitespace.
    4. Remove tokens that are stopwords, purely numeric, or ≤ 2 chars.
    """
    text = re.sub(r"[^A-Z0-9\s]", " ", text.upper())
    tokens = text.lower().split()
    return [
        t for t in tokens
        if len(t) > 2
        and t not in _STOPWORDS
        and not t.isdigit()
    ]


# ---------------------------------------------------------------------------
# Strategy 1 — K-Means + TF-IDF (scikit-learn)
# ---------------------------------------------------------------------------

def _sklearn_cluster(
    descriptions: list[str],
    n_clusters: int,
) -> dict[int, list[str]]:
    """
    Vectorise *descriptions* with TF-IDF (1- and 2-grams) and cluster with
    K-Means.  Returns {cluster_id: [top_keyword, …]}.

    Raises ImportError if scikit-learn is not available.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.cluster import KMeans                            # type: ignore

    # Pre-tokenise so TfidfVectorizer receives already-cleaned tokens.
    clean = [" ".join(_tokenize(d)) for d in descriptions]
    clean = [c for c in clean if c.strip()]

    if not clean:
        return {}

    # Guard: cannot have more clusters than samples.
    n_clusters = min(n_clusters, max(1, len(clean) // 2))

    vec = TfidfVectorizer(
        max_features=300,
        ngram_range=(1, 2),
        min_df=max(1, len(clean) // 50),   # at least ~2 % of docs
        stop_words=list(_STOPWORDS),
    )
    X = vec.fit_transform(clean)

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    km.fit(X)

    feature_names = vec.get_feature_names_out()
    cluster_keywords: dict[int, list[str]] = {}
    for cid, center in enumerate(km.cluster_centers_):
        top_indices = center.argsort()[-10:][::-1]
        cluster_keywords[cid] = [
            feature_names[i].upper() for i in top_indices
        ]
    return cluster_keywords


# ---------------------------------------------------------------------------
# Strategy 2 — Word-frequency fallback (pure Python)
# ---------------------------------------------------------------------------

def _fallback_cluster(
    descriptions: list[str],
    n_clusters: int,
) -> dict[int, list[str]]:
    """
    Group the most frequent tokens across all descriptions into *n_clusters*
    buckets of up to 5 keywords each.  No external dependencies needed.
    """
    all_tokens: list[str] = []
    for desc in descriptions:
        all_tokens.extend(_tokenize(desc))

    if not all_tokens:
        return {}

    top_tokens = [word for word, _ in Counter(all_tokens).most_common(n_clusters * 5)]

    groups: dict[int, list[str]] = {}
    tokens_per_group = max(1, len(top_tokens) // n_clusters)
    for group_idx in range(n_clusters):
        start = group_idx * tokens_per_group
        chunk = top_tokens[start: start + tokens_per_group]
        if chunk:
            groups[group_idx] = [t.upper() for t in chunk]

    return groups


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def suggest_categories(
    descriptions: Sequence[str],
    n_clusters: int = _DEFAULT_N_CLUSTERS,
) -> dict[str, list[str]]:
    """
    Cluster transaction *descriptions* and return a dict mapping suggested
    category names to their representative keywords.

    Attempts to use scikit-learn (K-Means + TF-IDF).  Automatically falls
    back to a pure-Python word-frequency grouper when sklearn is unavailable.

    Parameters
    ----------
    descriptions : sequence of str
        Raw transaction description strings (from the bank CSV).
    n_clusters : int
        Number of category groups to generate (default 8).

    Returns
    -------
    dict[str, list[str]]
        ``{"Suggested Category N": ["KEYWORD_A", "KEYWORD_B", …], …}``

        Keywords are upper-cased.  Present up to 10 keywords per category.
        The caller (wizard / UI) should let the user rename or merge groups.
    """
    descriptions = [d for d in descriptions if d and d.strip()]
    if not descriptions:
        return {}

    try:
        raw_clusters = _sklearn_cluster(list(descriptions), n_clusters)
        method = "K-Means (TF-IDF, scikit-learn)"
    except ImportError:
        print(
            "[wizard] scikit-learn not installed — using word-frequency fallback.",
            file=sys.stderr,
        )
        raw_clusters = _fallback_cluster(list(descriptions), n_clusters)
        method = "word-frequency (built-in fallback)"

    if not raw_clusters:
        return {}

    # Convert numeric cluster IDs to human-readable placeholder names.
    named: dict[str, list[str]] = {
        f"Suggested Category {cid + 1}": keywords
        for cid, keywords in raw_clusters.items()
    }

    _print_clusters(named, method)
    return named


# ---------------------------------------------------------------------------
# Pretty-print helper
# ---------------------------------------------------------------------------

def _print_clusters(clusters: dict[str, list[str]], method: str) -> None:
    print(f"\n=== Suggested Categories  [{method}] ===")
    for name, keywords in clusters.items():
        kw_str = ", ".join(keywords[:6])
        print(f"  {name}: {kw_str}")
    print("=" * 42)
