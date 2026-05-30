"""Small tiktoken compatibility shim for generated harness smoke/eval runs.

Some generated harnesses use tiktoken only for rough context sizing. The real
package is optional for these benchmark adapters; when it is unavailable, this
shim provides a conservative character-based encoding API.
"""

from __future__ import annotations


class _SimpleEncoding:
    def encode(self, text: str, *args, **kwargs) -> list[int]:
        if text is None:
            return []
        # Approximate tokens at roughly four characters per token. The concrete
        # values are irrelevant to generated harnesses that only call len().
        s = str(text)
        return list(range(max(1, (len(s) + 3) // 4))) if s else []


def encoding_for_model(model_name: str) -> _SimpleEncoding:
    return _SimpleEncoding()


def get_encoding(name: str) -> _SimpleEncoding:
    return _SimpleEncoding()
