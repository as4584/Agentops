"""
Token-aware text chunking.
Vendored pattern from LightRAG (HKUDS/LightRAG, MIT License).
Falls back to character-based chunking if tiktoken is not installed.
"""

from __future__ import annotations

try:
    import tiktoken

    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False


def chunk_by_tokens(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
    encoding_name: str = "cl100k_base",
) -> list[str]:
    """Split text into overlapping token-bounded chunks.

    Uses tiktoken for accurate token counts. Falls back to a 4-chars-per-token
    approximation when tiktoken is unavailable.
    """
    if not text.strip():
        return []

    if not _HAS_TIKTOKEN:
        return _chunk_chars(text, chunk_size=max_tokens * 4, overlap=overlap_tokens * 4)

    enc = tiktoken.get_encoding(encoding_name)
    tokens = enc.encode(text)

    if len(tokens) <= max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + max_tokens)
        chunk_text = enc.decode(tokens[start:end])
        if chunk_text.strip():
            chunks.append(chunk_text)
        if end >= len(tokens):
            break
        start = end - overlap_tokens

    return chunks


def _chunk_chars(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Character-based chunking fallback."""
    clean = "\n".join(line.rstrip() for line in text.splitlines())
    if len(clean) <= chunk_size:
        return [clean]

    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        chunk = clean[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(clean):
            break
        start = max(0, end - overlap)
    return chunks
