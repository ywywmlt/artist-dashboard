"""Tests for pipeline/step4_social_handles.py — handle extraction, URL classification."""

from __future__ import annotations

import pytest

from pipeline.step4_social_handles import extract_handle, classify_url, extract_image_url


# ── extract_handle ───────────────────────────────────────────────────────────


class TestExtractHandle:
    def test_instagram(self):
        assert extract_handle("https://www.instagram.com/theweeknd", "instagram") == "theweeknd"

    def test_youtube_at_sign(self):
        assert extract_handle("https://www.youtube.com/@TaylorSwift", "youtube") == "TaylorSwift"

    def test_youtube_channel(self):
        assert extract_handle("https://www.youtube.com/channel/UCIwFjwMjI0y7PDBVEO9-bkQ", "youtube") == "UCIwFjwMjI0y7PDBVEO9-bkQ"

    def test_tiktok(self):
        assert extract_handle("https://www.tiktok.com/@billieeilish", "tiktok") == "billieeilish"

    def test_twitter(self):
        assert extract_handle("https://twitter.com/Drake", "twitter") == "Drake"

    def test_x_com(self):
        assert extract_handle("https://x.com/Drake", "twitter") == "Drake"

    def test_noise_intent(self):
        assert extract_handle("https://twitter.com/intent", "twitter") is None

    def test_noise_share(self):
        assert extract_handle("https://twitter.com/share", "twitter") is None

    def test_noise_home(self):
        assert extract_handle("https://twitter.com/home", "twitter") is None

    def test_unknown_platform(self):
        assert extract_handle("https://facebook.com/someone", "facebook") is None


# ── classify_url ─────────────────────────────────────────────────────────────


class TestClassifyUrl:
    def test_instagram(self):
        result = classify_url("https://www.instagram.com/theweeknd")
        assert result == ("instagram", "theweeknd")

    def test_tiktok(self):
        result = classify_url("https://www.tiktok.com/@billieeilish")
        assert result == ("tiktok", "billieeilish")

    def test_twitter(self):
        result = classify_url("https://twitter.com/Drake")
        assert result == ("twitter", "Drake")

    def test_x_com(self):
        result = classify_url("https://x.com/badgalriri")
        assert result == ("twitter", "badgalriri")

    def test_youtube(self):
        result = classify_url("https://www.youtube.com/@TaylorSwift")
        assert result == ("youtube", "TaylorSwift")

    def test_unrecognised_url(self):
        assert classify_url("https://www.facebook.com/someone") is None

    def test_noise_url(self):
        assert classify_url("https://twitter.com/intent") is None


# ── extract_image_url ────────────────────────────────────────────────────────


class TestExtractImageUrl:
    def test_wikimedia_commons(self):
        rels = [
            {"type": "official homepage", "target": "https://example.com"},
            {"type": "other", "target": "https://commons.wikimedia.org/wiki/File:Artist.jpg"},
        ]
        result = extract_image_url(rels)
        assert result == "https://commons.wikimedia.org/wiki/File:Artist.jpg"

    def test_image_relation_type(self):
        rels = [{"type": "image", "target": "https://example.com/photo.jpg"}]
        assert extract_image_url(rels) == "https://example.com/photo.jpg"

    def test_no_image(self):
        rels = [
            {"type": "official homepage", "target": "https://example.com"},
            {"type": "social network", "target": "https://instagram.com/someone"},
        ]
        assert extract_image_url(rels) is None

    def test_empty_rels(self):
        assert extract_image_url([]) is None
