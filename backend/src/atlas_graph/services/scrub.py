"""Secret scrubbing for Flight Recorder payloads.

Run-recording brings in raw stdout, env dumps, tracebacks, and the agent's
own scratch text — any of which can carry an API key, a JWT, or a DB
connection string. Scrub at *ingestion*, never at push, so the raw
secret never persists to the DAG.

Conservative-by-design: a few false-positive masks are fine; a single
leaked key is not. The high-entropy heuristic deliberately skips pure-hex
tokens so we don't redact git SHAs and content hashes (which would damage
the captured trajectory).

Ported from ``journal/useless/backend/blackbox/privacy/redact.py``.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_PLACEHOLDER = "«redacted:{label}»"

# (label, compiled pattern). Order matters: more specific first.
_BUILTIN: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    )),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("atlas-key", re.compile(r"(?:thk|osk)_[A-Za-z0-9._\-]{16,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("stripe-key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
    )),
    ("bearer", re.compile(r"(?i)\b(authorization:\s*bearer\s+)\S+")),
    # DB / broker connection strings - mask the password between : and @
    ("conn-string", re.compile(
        r"(?i)\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|rediss|amqp)"
        r"://[^\s:@/]+:)([^\s@/]+)(@)"
    )),
    # KEY: "value with spaces"  /  KEY = 'value' - mask the whole quoted value
    ("env-secret-quoted", re.compile(
        r"(?im)([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|"
        r"ACCESS_?KEY|PRIVATE|CREDENTIAL)[A-Z0-9_]*"
        r"\s*[:=]\s*)([\"'])(.*?)(\2)"
    )),
    # KEY=value (unquoted) - mask to first whitespace/comment
    ("env-secret", re.compile(
        r"(?im)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|"
        r"ACCESS_?KEY|PRIVATE|CREDENTIAL)[A-Z0-9_]*)"
        r"\s*[:=]\s*[\"']?([^\s\"'#]+)"
    )),
]

# value-group index for patterns that keep a prefix and mask one capture group
_VALUE_GROUP = {
    "env-secret": 2,
    "bearer": 1,
    "env-secret-quoted": 3,
    "conn-string": 2,
}

# A high-entropy token candidate: long, base64/hex-ish, no whitespace.
_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{28,}")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_secret(token: str) -> bool:
    """Heuristic for a prefix-less credential, tuned to avoid eating data.

    Requires mixed character classes (api keys look random) and skips
    pure-hex strings - git SHAs and content hashes are high-entropy but
    NOT secrets, and redacting them would damage the captured trajectory.
    """
    if re.fullmatch(r"[0-9a-fA-F]+", token):
        return False
    has_lower = any(c.islower() for c in token)
    has_upper = any(c.isupper() for c in token)
    has_digit = any(c.isdigit() for c in token)
    has_b64 = any(c in "+/=" for c in token)
    classes = sum([has_lower, has_upper, has_digit, has_b64])
    return classes >= 3 and _shannon_entropy(token) >= 4.0


class Scrubber:
    def __init__(
        self,
        extra_patterns: list[str] | None = None,
        entropy: bool = True,
    ) -> None:
        self.patterns = list(_BUILTIN)
        self.entropy = entropy
        for i, raw in enumerate(extra_patterns or []):
            try:
                self.patterns.append((f"custom-{i}", re.compile(raw)))
            except re.error:
                continue

    def scrub_text(self, text: str) -> tuple[str, int]:
        """Return ``(clean_text, num_redactions)``."""
        if not text:
            return text, 0
        count = 0
        for label, pat in self.patterns:
            grp = _VALUE_GROUP.get(label)
            if grp is not None:
                def _sub(m: re.Match[str], _label=label, _grp=grp) -> str:
                    nonlocal count
                    count += 1
                    prefix = m.group(0)[: m.start(_grp) - m.start(0)]
                    suffix = m.group(0)[m.end(_grp) - m.start(0):]
                    return prefix + _PLACEHOLDER.format(label=_label) + suffix

                text = pat.sub(_sub, text)
            else:
                def _sub(m: re.Match[str], _label=label) -> str:
                    nonlocal count
                    count += 1
                    return _PLACEHOLDER.format(label=_label)

                text = pat.sub(_sub, text)

        if self.entropy:
            def _ent_sub(m: re.Match[str]) -> str:
                nonlocal count
                tok = m.group(0)
                if _looks_secret(tok):
                    count += 1
                    return _PLACEHOLDER.format(label="high-entropy")
                return tok

            text = _TOKEN.sub(_ent_sub, text)
        return text, count

    def scrub_payload(self, payload: Any) -> tuple[Any, int]:
        """Recursively scrub all string values in a nested payload.

        Walks dicts and lists. Leaves non-string scalars alone (ints,
        floats, bools, None) so config blobs and metrics aren't damaged.
        """
        total = 0

        def walk(obj: Any) -> Any:
            nonlocal total
            if isinstance(obj, str):
                clean, n = self.scrub_text(obj)
                total += n
                return clean
            if isinstance(obj, dict):
                return {k: walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [walk(v) for v in obj]
            return obj

        return walk(payload), total


# Process-wide default; cheap to construct repeatedly but pointless.
_DEFAULT = Scrubber()


def scrub_text(text: str) -> tuple[str, int]:
    """Module-level convenience: scrub with the default ruleset."""
    return _DEFAULT.scrub_text(text)


def scrub_payload(payload: Any) -> tuple[Any, int]:
    """Module-level convenience: scrub with the default ruleset."""
    return _DEFAULT.scrub_payload(payload)
