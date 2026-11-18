"""Small, local safeguard for common credential patterns."""

import re


def strip_private(text: str) -> str:
    """Remove nested private blocks; an unclosed block hides the remaining text."""
    result, position, depth = [], 0, 0
    for match in re.finditer(r"</?private\s*>", text, re.I):
        closing = match.group().startswith("</")
        if not closing:
            if depth == 0:
                result.extend((text[position:match.start()], "[private]"))
            depth += 1
        elif depth:
            depth -= 1
        else:
            # An orphan closing tag may be the tail of a truncated private block.
            result = ["[private]"]
        position = match.end()
    if depth == 0:
        result.append(text[position:])
    return "".join(result)

PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.S),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"\bpassword\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", re.I),
)


def redact(text: str) -> str:
    text = strip_private(text)
    for pattern in PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text
