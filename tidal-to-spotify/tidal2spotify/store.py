"""Files in the data directory: login tokens, match cache, playlist mapping, manual matches."""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .matching import TrackMatch
from .models import SpotifyTrack

CACHE_VERSION = 1
CSV_DELIMITER = ";"  # what German Excel expects
MANUAL_HEADER = ["typ", "tidal_id", "spotify_link", "titel", "kuenstler"]

_SPOTIFY_REF = re.compile(r"(track|album|artist)[/:]([A-Za-z0-9]{22})")
_KINDS = {"song": "track", "album": "album", "kuenstler": "artist"}


def default_data_dir() -> Path:
    return Path(os.environ.get("TIDAL2SPOTIFY_DIR") or Path.home() / "tidal2spotify")


def spotify_uri(link: str, kind: str) -> str | None:
    """Accept 'https://open.spotify.com/intl-de/track/<id>?si=..' or 'spotify:track:<id>'."""
    found = _SPOTIFY_REF.search(link.strip())
    if not found or found.group(1) != kind:
        return None
    return f"spotify:{kind}:{found.group(2)}"


def write_json(path: Path, data: Any, private: bool = False) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _track_from_json(data: dict[str, Any] | None) -> SpotifyTrack | None:
    if not data:
        return None
    return SpotifyTrack(**{**data, "artists": tuple(tuple(a) for a in data["artists"])})


class Store:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = self.dir / "berichte"
        self.config_path = self.dir / "config.json"
        self.tidal_session_path = self.dir / "tidal-login.json"
        self.spotify_token_path = self.dir / "spotify-login.json"
        self.export_path = self.dir / "tidal_bibliothek.json"
        self.manual_path = self.dir / "manuelle_zuordnung.csv"
        self._cache_path = self.dir / "treffer-cache.json"
        self._state_path = self.dir / "playlist-zuordnung.json"

        self.config: dict[str, Any] = read_json(self.config_path, {})
        cache = read_json(self._cache_path, {})
        if cache.get("version") != CACHE_VERSION:
            cache = {}
        self._tracks: dict[str, dict[str, Any]] = cache.get("tracks", {})
        self._albums: dict[str, dict[str, Any]] = cache.get("albums", {})
        self._artists: dict[str, dict[str, Any]] = cache.get("artists", {})
        # Tidal playlist id -> Spotify playlist id of the copy this tool created or filled.
        self.playlist_map: dict[str, str] = read_json(self._state_path, {}).get("playlists", {})
        self.manual: dict[tuple[str, str], str] = {}
        self.manual_errors: list[str] = []
        self._load_manual()

    # -- config -----------------------------------------------------------------
    def save_config(self) -> None:
        write_json(self.config_path, self.config)

    # -- match cache ------------------------------------------------------------
    def cached_track(self, tidal_id: str) -> TrackMatch | None:
        entry = self._tracks.get(tidal_id)
        if entry is None:
            return None
        return TrackMatch(
            uri=entry["uri"],
            method=entry["method"],
            score=entry.get("score", 0.0),
            candidate=_track_from_json(entry.get("candidate")),
            suggestion=_track_from_json(entry.get("suggestion")),
        )

    def remember_track(self, tidal_id: str, match: TrackMatch) -> None:
        self._tracks[tidal_id] = {
            "uri": match.uri,
            "method": match.method,
            "score": round(match.score, 3),
            "candidate": asdict(match.candidate) if match.candidate else None,
            "suggestion": asdict(match.suggestion) if match.suggestion else None,
        }

    def cached_album(self, tidal_id: str) -> dict[str, Any] | None:
        return self._albums.get(tidal_id)

    def remember_album(self, tidal_id: str, uri: str | None, score: float) -> None:
        self._albums[tidal_id] = {"uri": uri, "score": round(score, 3)}

    def cached_artist(self, tidal_id: str) -> dict[str, Any] | None:
        return self._artists.get(tidal_id)

    def remember_artist(self, tidal_id: str, uri: str | None) -> None:
        self._artists[tidal_id] = {"uri": uri}

    def save_cache(self) -> None:
        write_json(
            self._cache_path,
            {
                "version": CACHE_VERSION,
                "tracks": self._tracks,
                "albums": self._albums,
                "artists": self._artists,
            },
        )

    def save_playlist_map(self) -> None:
        write_json(self._state_path, {"playlists": self.playlist_map})

    # -- manual matches ---------------------------------------------------------
    def _load_manual(self) -> None:
        if not self.manual_path.exists():
            with open(self.manual_path, "w", encoding="utf-8-sig", newline="") as fh:
                csv.writer(fh, delimiter=CSV_DELIMITER).writerow(MANUAL_HEADER)
            return
        with open(self.manual_path, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        first_line = text.splitlines()[0] if text else ""
        delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
        for line_no, row in enumerate(csv.DictReader(text.splitlines(), delimiter=delimiter), start=2):
            tidal_id = (row.get("tidal_id") or "").strip()
            link = (row.get("spotify_link") or "").strip()
            if not tidal_id or not link:
                continue
            typ = (row.get("typ") or "song").strip().lower()
            kind = _KINDS.get(typ)
            uri = spotify_uri(link, kind) if kind else None
            if kind is None or uri is None:
                self.manual_errors.append(
                    f"{self.manual_path.name}, Zeile {line_no}: '{link}' ist kein Spotify-Link für Typ '{typ}'."
                )
                continue
            self.manual[(kind, tidal_id)] = uri
