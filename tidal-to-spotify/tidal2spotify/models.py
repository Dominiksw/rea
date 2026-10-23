"""Plain data types shared by the Tidal source, the Spotify target and the sync."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Track:
    tidal_id: str
    title: str
    artists: tuple[str, ...]
    album: str | None = None
    duration: int | None = None  # seconds
    isrc: str | None = None
    version: str | None = None

    @property
    def full_title(self) -> str:
        return f"{self.title} ({self.version})" if self.version else self.title

    @property
    def display(self) -> str:
        return f"{', '.join(self.artists) or '?'} – {self.full_title}"

    @property
    def tidal_url(self) -> str:
        return f"https://tidal.com/browse/track/{self.tidal_id}"


@dataclass(frozen=True)
class Album:
    tidal_id: str
    title: str
    artists: tuple[str, ...]
    upc: str | None = None
    num_tracks: int | None = None

    @property
    def display(self) -> str:
        return f"{', '.join(self.artists) or '?'} – {self.title}"

    @property
    def tidal_url(self) -> str:
        return f"https://tidal.com/browse/album/{self.tidal_id}"


@dataclass(frozen=True)
class Artist:
    tidal_id: str
    name: str

    @property
    def display(self) -> str:
        return self.name

    @property
    def tidal_url(self) -> str:
        return f"https://tidal.com/browse/artist/{self.tidal_id}"


@dataclass
class Playlist:
    tidal_id: str
    name: str
    description: str = ""
    owned: bool = True
    tracks: list[Track] = field(default_factory=list)
    skipped_videos: int = 0


@dataclass
class Library:
    """A snapshot of a Tidal account. Favourite tracks are ordered oldest first."""

    favorite_tracks: list[Track] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)
    albums: list[Album] = field(default_factory=list)
    artists: list[Artist] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"format": "tidal2spotify-library", "version": 1, **asdict(self)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Library:
        if data.get("format") != "tidal2spotify-library":
            raise ValueError("Die Datei ist kein tidal2spotify-Export.")

        def track(t: dict[str, Any]) -> Track:
            return Track(**{**t, "artists": tuple(t["artists"])})

        return cls(
            favorite_tracks=[track(t) for t in data["favorite_tracks"]],
            playlists=[
                Playlist(**{**p, "tracks": [track(t) for t in p["tracks"]]})
                for p in data["playlists"]
            ],
            albums=[Album(**{**a, "artists": tuple(a["artists"])}) for a in data["albums"]],
            artists=[Artist(**a) for a in data["artists"]],
        )


@dataclass(frozen=True)
class SpotifyTrack:
    uri: str
    name: str
    artists: tuple[tuple[str, str], ...]  # (name, uri)
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None

    @property
    def artist_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.artists)

    @property
    def display(self) -> str:
        return f"{', '.join(self.artist_names) or '?'} – {self.name}"


@dataclass(frozen=True)
class SpotifyAlbum:
    uri: str
    name: str
    artists: tuple[str, ...]
    total_tracks: int | None = None


@dataclass(frozen=True)
class SpotifyArtist:
    uri: str
    name: str


@dataclass(frozen=True)
class SpotifyPlaylist:
    id: str
    name: str
    owner_id: str
    total: int | None = None


def spotify_url(uri: str) -> str:
    """spotify:track:abc -> https://open.spotify.com/track/abc"""
    parts = uri.split(":")
    if len(parts) == 3 and parts[0] == "spotify":
        return f"https://open.spotify.com/{parts[1]}/{parts[2]}"
    return uri
