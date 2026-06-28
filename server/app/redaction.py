"""Centralized sensitive data detection and redaction helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

REDACTION_PLACEHOLDER = "[REDACTED]"
VALID_REDACTION_MODES = frozenset({"audit_only", "redact_on_write", "block"})

_MAX_DEPTH = 12
_MAX_ITEMS = 500
_MAX_FINDINGS = 100
_MAX_STRING_SCAN = 10000

_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "id_token",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session_token",
    "token",
}


@dataclass(frozen=True)
class RedactionFinding:
    """A safe, non-reversible sensitive-data finding."""

    field_path: str
    rule_id: str
    severity: str
    action: str
    value_fingerprint: str


@dataclass(frozen=True)
class RedactionResult:
    """Redaction result with transformed payload and safe findings."""

    value: Any
    findings: list[RedactionFinding]


@dataclass(frozen=True)
class _PatternRule:
    id: str
    severity: str
    pattern: re.Pattern[str]
    replacement: str


_PATTERN_RULES = [
    _PatternRule(
        id="bearer_token",
        severity="high",
        pattern=re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"),
        replacement="Bearer [REDACTED]",
    ),
    _PatternRule(
        id="jwt",
        severity="high",
        pattern=re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        replacement=REDACTION_PLACEHOLDER,
    ),
    _PatternRule(
        id="credit_card",
        severity="critical",
        pattern=re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        replacement=REDACTION_PLACEHOLDER,
    ),
    _PatternRule(
        id="ssn",
        severity="critical",
        pattern=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        replacement=REDACTION_PLACEHOLDER,
    ),
    _PatternRule(
        id="email",
        severity="medium",
        pattern=re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        replacement=REDACTION_PLACEHOLDER,
    ),
    _PatternRule(
        id="phone",
        severity="low",
        pattern=re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        replacement=REDACTION_PLACEHOLDER,
    ),
]


def value_fingerprint(value: Any) -> str:
    """Return a short, non-reversible fingerprint for a sensitive value."""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:24]


def default_redaction_policy() -> dict[str, Any]:
    """Return the default project redaction policy payload."""
    return {
        "enabled": True,
        "mode": "audit_only",
        "rules": {
            "disabled_rule_ids": [],
            "sensitive_keys": sorted(_SENSITIVE_KEYS),
        },
    }


def normalize_redaction_mode(mode: str) -> str:
    """Normalize and validate a redaction policy mode."""
    normalized = str(mode).strip().lower()
    if normalized not in VALID_REDACTION_MODES:
        valid = ", ".join(sorted(VALID_REDACTION_MODES))
        raise ValueError(f"Invalid redaction mode. Expected one of: {valid}")
    return normalized


def _disabled_rule_ids(policy_rules: dict[str, Any] | None) -> set[str]:
    if not policy_rules:
        return set()
    raw_values = policy_rules.get("disabled_rule_ids") or []
    if not isinstance(raw_values, list):
        return set()
    return {str(value).strip() for value in raw_values if str(value).strip()}


def _policy_sensitive_keys(policy_rules: dict[str, Any] | None) -> set[str]:
    keys = set(_SENSITIVE_KEYS)
    if not policy_rules:
        return keys
    custom_keys = policy_rules.get("sensitive_keys")
    if isinstance(custom_keys, list):
        keys.update(str(key).strip().lower() for key in custom_keys if str(key).strip())
    return keys


def _key_path(parent_path: str, key: Any) -> str:
    safe_key = str(key).replace(".", "_")[:120]
    return f"{parent_path}.{safe_key}" if parent_path else safe_key


def _append_finding(
    findings: list[RedactionFinding],
    *,
    field_path: str,
    rule_id: str,
    severity: str,
    action: str,
    value: Any,
) -> None:
    if len(findings) >= _MAX_FINDINGS:
        return
    findings.append(
        RedactionFinding(
            field_path=field_path[:512],
            rule_id=rule_id,
            severity=severity,
            action=action,
            value_fingerprint=value_fingerprint(value),
        )
    )


def _redact_string(
    value: str,
    *,
    field_path: str,
    findings: list[RedactionFinding],
    disabled_rule_ids: set[str],
) -> str:
    if len(value) > _MAX_STRING_SCAN:
        scan_value = value[:_MAX_STRING_SCAN]
        suffix = value[_MAX_STRING_SCAN:]
    else:
        scan_value = value
        suffix = ""

    redacted = scan_value
    for rule in _PATTERN_RULES:
        if rule.id in disabled_rule_ids:
            continue
        matches = list(rule.pattern.finditer(redacted))
        if not matches:
            continue
        for match in matches[:5]:
            _append_finding(
                findings,
                field_path=field_path,
                rule_id=rule.id,
                severity=rule.severity,
                action="redact",
                value=match.group(0),
            )
        redacted = rule.pattern.sub(rule.replacement, redacted)

    return redacted + suffix


def scan_and_redact(
    value: Any,
    *,
    policy_rules: dict[str, Any] | None = None,
    field_path: str = "$",
) -> RedactionResult:
    """Scan and redact a JSON-like value according to centralized rules."""
    disabled_rule_ids = _disabled_rule_ids(policy_rules)
    sensitive_keys = _policy_sensitive_keys(policy_rules)
    findings: list[RedactionFinding] = []

    def visit(current: Any, path: str, depth: int) -> Any:
        if depth > _MAX_DEPTH:
            return current
        if isinstance(current, dict):
            redacted: dict[str, Any] = {}
            for index, (key, nested) in enumerate(current.items()):
                if index >= _MAX_ITEMS:
                    break
                nested_path = _key_path(path, key)
                normalized_key = str(key).strip().lower()
                if "sensitive_key" not in disabled_rule_ids and normalized_key in sensitive_keys:
                    _append_finding(
                        findings,
                        field_path=nested_path,
                        rule_id="sensitive_key",
                        severity="high",
                        action="redact",
                        value=nested,
                    )
                    redacted[key] = REDACTION_PLACEHOLDER
                else:
                    redacted[key] = visit(nested, nested_path, depth + 1)
            return redacted
        if isinstance(current, list):
            return [
                visit(item, f"{path}[{index}]", depth + 1)
                for index, item in enumerate(current[:_MAX_ITEMS])
            ]
        if isinstance(current, tuple):
            return [
                visit(item, f"{path}[{index}]", depth + 1)
                for index, item in enumerate(current[:_MAX_ITEMS])
            ]
        if isinstance(current, str):
            return _redact_string(
                current,
                field_path=path,
                findings=findings,
                disabled_rule_ids=disabled_rule_ids,
            )
        return current

    return RedactionResult(value=visit(value, field_path, 0), findings=findings)


def findings_to_dicts(findings: list[RedactionFinding]) -> list[dict[str, str]]:
    """Serialize redaction findings for API responses."""
    return [
        {
            "field_path": finding.field_path,
            "rule_id": finding.rule_id,
            "severity": finding.severity,
            "action": finding.action,
            "value_fingerprint": finding.value_fingerprint,
        }
        for finding in findings
    ]
