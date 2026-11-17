"""Small, local safeguard for common credential patterns."""

import re

PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.S),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"\bpassword\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", re.I),
)


def redact(text: str) -> str:
    for pattern in PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text
