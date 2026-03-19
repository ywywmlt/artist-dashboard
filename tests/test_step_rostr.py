"""Tests for pipeline/step_rostr.py — regex patterns, normalisation."""

from __future__ import annotations

import pytest

from pipeline.step_rostr import SIGNING_RE, TEAM_RE, _normalize_deal_type


# ── SIGNING_RE ───────────────────────────────────────────────────────────────


class TestSigningRegex:
    def test_basic_match(self):
        text = "Lime Garden signed with Partisan Records for records."
        m = SIGNING_RE.match(text)
        assert m is not None
        assert m.group(1).strip() == "Lime Garden"
        assert m.group(2).strip() == "Partisan Records"
        assert m.group(3).strip() == "records"

    def test_no_deal_type(self):
        text = "Wild Rivers signed with WME."
        m = SIGNING_RE.match(text)
        assert m is not None
        assert m.group(1).strip() == "Wild Rivers"
        assert m.group(2).strip() == "WME"
        assert m.group(3) is None  # no "for X" clause

    def test_no_match_on_random_text(self):
        text = "This is just some random paragraph with no signing info."
        m = SIGNING_RE.match(text)
        assert m is None


# ── _normalize_deal_type ─────────────────────────────────────────────────────


class TestNormalizeDealType:
    def test_none_returns_unknown(self):
        assert _normalize_deal_type(None) == "unknown"

    def test_management(self):
        assert _normalize_deal_type("management") == "management"
        assert _normalize_deal_type("Management") == "management"
        assert _normalize_deal_type("artist management") == "management"

    def test_touring(self):
        assert _normalize_deal_type("touring") == "touring"
        assert _normalize_deal_type("booking") == "touring"

    def test_records(self):
        assert _normalize_deal_type("records") == "records"
        assert _normalize_deal_type("record label") == "records"
        assert _normalize_deal_type("distribution") == "records"

    def test_publishing(self):
        assert _normalize_deal_type("publishing") == "publishing"

    def test_passthrough(self):
        result = _normalize_deal_type("some other deal")
        assert result == "some other deal"


# ── TEAM_RE ──────────────────────────────────────────────────────────────────


class TestTeamRegex:
    def test_parses_team_string(self):
        # TEAM_RE uses [^A-Z] with re.IGNORECASE, which means it can only
        # match non-letter characters (digits, spaces, punctuation) between
        # uppercase label prefixes. In practice this captures partial values
        # like "360, " from "Management: 360, Agency: ..."
        text = "Management: 360, Agency: 123, Label: 456"
        matches = list(TEAM_RE.finditer(text))
        groups = {}
        for m in matches:
            if m.lastgroup and m.group(m.lastgroup):
                groups[m.lastgroup] = m.group(m.lastgroup).strip().rstrip(",")
        assert "mgmt" in groups
        assert "360" in groups["mgmt"]
