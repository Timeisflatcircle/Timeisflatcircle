"""Cheap deterministic corporate-risk pre-screening for small/micro-caps.

The scanner intentionally treats missing exchange data as UNKNOWN rather than safe.
It is designed to run before expensive Gemini analysis.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping


@dataclass
class CorporateRiskResult:
    hard_fail: bool = False
    risk_flags: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    risk_score: int = 0

    @property
    def governance_grade(self) -> str:
        if self.hard_fail or self.risk_score >= 50:
            return "D"
        if self.risk_score >= 30:
            return "C"
        if self.risk_score >= 15:
            return "B"
        return "A"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def _keywords(text: str, terms: Iterable[str]) -> bool:
    text = text.lower()
    return any(term.lower() in text for term in terms)


def _announcement_risk(subject: str, details: str) -> tuple[int, list[str], bool]:
    text = f"{subject} {details}".lower()
    score = 0
    flags: list[str] = []
    hard_fail = False

    hard_patterns = {
        "auditor resignation": 35,
        "resignation of auditor": 35,
        "qualified opinion": 40,
        "adverse opinion": 50,
        "disclaimer of opinion": 50,
        "fraud": 50,
        "forensic audit": 40,
        "default": 35,
        "insolvency": 50,
        "delisting": 50,
    }
    medium_patterns = {
        "change in auditor": 20,
        "related party": 15,
        "preferential": 15,
        "preferential allotment": 20,
        "warrant": 15,
        "convertible": 15,
        "qip": 8,
        "fund raising": 5,
        "promoter sale": 15,
        "promoter pledge": 20,
        "pledge": 15,
        "resignation of director": 10,
        "regulatory order": 20,
        "sebi": 10,
        "stock exchange fine": 15,
    }

    for term, points in hard_patterns.items():
        if term in text:
            flags.append(f"Corporate filing: {term}")
            score += points
            if points >= 40:
                hard_fail = True
    for term, points in medium_patterns.items():
        if term in text and not any(term in flag.lower() for flag in flags):
            flags.append(f"Corporate filing: {term}")
            score += points

    return min(score, 100), flags, hard_fail


def assess_corporate_risk(
    *,
    promoter_holding_pct: Any = None,
    promoter_pledge_pct: Any = None,
    promoter_change_pct: Any = None,
    auditor_status: str | None = None,
    related_party_risk: str | None = None,
    announcements: Iterable[Mapping[str, Any]] | None = None,
) -> CorporateRiskResult:
    """Evaluate mechanical governance signals before AI analysis.

    Expected announcement keys: ``subject``, ``details`` and optionally ``date``.
    """
    result = CorporateRiskResult()

    pledge = _num(promoter_pledge_pct)
    if pledge is None:
        result.data_gaps.append("Promoter pledge data unavailable")
    elif pledge > 20:
        result.risk_score += 35
        result.risk_flags.append(f"High promoter pledge: {pledge:.2f}%")
        result.hard_fail = True
    elif pledge > 5:
        result.risk_score += 20
        result.risk_flags.append(f"Promoter pledge above threshold: {pledge:.2f}%")
    else:
        result.positive_signals.append("Promoter pledge <= 5%")

    promoter = _num(promoter_holding_pct)
    if promoter is None:
        result.data_gaps.append("Promoter holding data unavailable")
    elif promoter < 25:
        result.risk_score += 10
        result.risk_flags.append(f"Low promoter holding: {promoter:.2f}%")
    else:
        result.positive_signals.append("Promoter holding >= 25%")

    change = _num(promoter_change_pct)
    if change is None:
        result.data_gaps.append("Promoter holding change unavailable")
    elif change < -5:
        result.risk_score += 20
        result.risk_flags.append(f"Sharp promoter holding decline: {change:.2f} pp")
    elif change > 2:
        result.positive_signals.append(f"Promoter holding increased {change:.2f} pp")

    auditor = _text(auditor_status)
    if not auditor:
        result.data_gaps.append("Auditor change/status unavailable")
    elif _keywords(auditor, ["resign", "qualified", "adverse", "disclaimer"]):
        result.risk_score += 30
        result.risk_flags.append(f"Auditor concern: {auditor_status}")
        result.hard_fail = True
    else:
        result.positive_signals.append("No mechanical auditor red flag")

    rtp = _text(related_party_risk)
    if not rtp:
        result.data_gaps.append("Related-party risk unavailable")
    elif rtp in {"high", "very high", "critical"}:
        result.risk_score += 30
        result.risk_flags.append(f"High related-party risk: {related_party_risk}")
        result.hard_fail = True
    elif rtp in {"medium", "moderate"}:
        result.risk_score += 15
        result.risk_flags.append(f"Moderate related-party risk: {related_party_risk}")
    else:
        result.positive_signals.append("Related-party risk not elevated")

    for announcement in announcements or []:
        points, flags, hard = _announcement_risk(
            _text(announcement.get("subject")),
            _text(announcement.get("details")),
        )
        result.risk_score += points
        result.risk_flags.extend(flags)
        result.hard_fail = result.hard_fail or hard

    result.risk_score = min(result.risk_score, 100)
    return result


def extract_announcements_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Normalize exchange announcement rows for the risk engine."""
    normalized = []
    for row in rows:
        normalized.append(
            {
                "subject": str(row.get("subject") or row.get("SUBJECT") or ""),
                "details": str(row.get("details") or row.get("DETAILS") or ""),
                "date": str(row.get("date") or row.get("BROADCAST_DATE") or ""),
            }
        )
    return normalized
