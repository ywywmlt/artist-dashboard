"""Dataclass definitions for the artist pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone


@dataclass
class ArtistSeed:
    """Raw artist data from kworb.net scrape."""
    rank: int
    name: str
    spotify_id: str
    monthly_listeners: int
    daily_change: Optional[int] = None
    peak_listeners: Optional[int] = None
    peak_listener_date: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TouringData:
    """Touring activity data from Bandsintown / setlist.fm."""
    spotify_id: str
    is_touring: bool = False
    recent_event_count: int = 0
    upcoming_event_count: int = 0
    last_event_date: Optional[str] = None
    next_event_date: Optional[str] = None
    touring_source: Optional[str] = None  # "bandsintown" or "setlistfm"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MusicBrainzData:
    """Genres, social handles, and country from MusicBrainz."""
    spotify_id: str
    genres: list[str] = field(default_factory=list)
    country: Optional[str] = None
    image_url: Optional[str] = None
    instagram: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    twitter: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpotifyData:
    """Artist data fetched directly from the Spotify API."""
    spotify_id: str
    popularity: Optional[int] = None           # 0-100
    spotify_genres: list[str] = field(default_factory=list)
    followers: Optional[int] = None
    image_url_spotify: Optional[str] = None
    top_tracks: list[dict] = field(default_factory=list)  # [{name, preview_url}]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArtistEnriched:
    """Final merged artist record for export."""
    rank: int
    name: str
    spotify_id: str
    spotify_url: Optional[str] = None
    monthly_listeners: int = 0
    daily_change: Optional[int] = None
    genres: str = ""  # comma-separated for CSV
    country: Optional[str] = None
    image_url: Optional[str] = None
    instagram: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    twitter: Optional[str] = None
    is_touring: bool = False
    recent_event_count: int = 0
    upcoming_event_count: int = 0
    last_event_date: Optional[str] = None
    next_event_date: Optional[str] = None
    touring_source: Optional[str] = None
    scraped_at: str = ""
    # Momentum (from listener history)
    momentum_7d: Optional[float] = None
    momentum_30d: Optional[float] = None
    # Spotify API enrichment
    popularity: Optional[int] = None
    followers: Optional[int] = None
    # Rostr intelligence
    management_company: Optional[str] = None
    booking_agency: Optional[str] = None
    record_label: Optional[str] = None
    publisher: Optional[str] = None
    rostr_profile_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NewsAlert:
    """A news article matched to one or more tracked artists."""
    title: str
    url: str
    source: str
    published: str  # ISO 8601
    matched_artists: list[str] = field(default_factory=list)
    matched_spotify_ids: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)
