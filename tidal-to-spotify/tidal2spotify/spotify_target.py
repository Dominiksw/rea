"""Spotify Web API access via spotipy.

Written against the Web API as changed in February 2026: playlist contents live under
/playlists/{id}/items (entries carry "item" instead of "track"), playlists are created
with POST /me/playlists, library writes go through PUT /me/library (max. 40 URIs) and
search returns at most 10 results per type.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from .models import SpotifyAlbum, SpotifyArtist, SpotifyPlaylist, SpotifyTrack

SCOPES = " ".join(
    [
        "playlist-read-private",
        "playlist-read-collaborative",
        "playlist-modify-private",
        "playlist-modify-public",
        "user-library-read",
        "user-library-modify",
        "user-follow-read",
        "user-follow-modify",
    ]
)
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

SEARCH_LIMIT = 10
PAGE_LIMIT = 50
PLAYLIST_ADD_BATCH = 100
LIBRARY_BATCH = 40


def chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _entry_object(entry: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    # Playlist entries renamed "track" to "item" in 2026, and "track" may now be a
    # boolean. Take the first key that holds an object.
    for key in keys:
        value = entry.get(key)
        if isinstance(value, dict):
            return value
    return None


def parse_track(data: dict[str, Any]) -> SpotifyTrack:
    return SpotifyTrack(
        uri=data["uri"],
        name=data.get("name") or "",
        artists=tuple((a.get("name") or "", a.get("uri") or "") for a in data.get("artists") or []),
        album=(data.get("album") or {}).get("name"),
        duration_ms=data.get("duration_ms"),
        isrc=(data.get("external_ids") or {}).get("isrc"),
    )


class SpotifyTarget:
    def __init__(self, client: Any):
        self.sp = client
        self._me: dict[str, Any] | None = None

    @classmethod
    def connect(cls, client_id: str, redirect_uri: str, token_path: Path) -> SpotifyTarget:
        import spotipy
        from spotipy.cache_handler import CacheFileHandler
        from spotipy.oauth2 import SpotifyPKCE

        auth = SpotifyPKCE(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=SCOPES,
            cache_handler=CacheFileHandler(cache_path=str(token_path)),
            open_browser=True,
        )
        # Generous retries: spotipy honours Retry-After on HTTP 429 (rate limit).
        client = spotipy.Spotify(
            auth_manager=auth, retries=10, status_retries=10, backoff_factor=0.5, requests_timeout=30
        )
        target = cls(client)
        target.me()  # triggers the browser login on first use
        return target

    # -- reading ----------------------------------------------------------------
    def me(self) -> dict[str, Any]:
        if self._me is None:
            self._me = self.sp.me()
        return self._me

    def user_id(self) -> str:
        return self.me()["id"]

    def display_name(self) -> str:
        me = self.me()
        return me.get("display_name") or me["id"]

    def search_tracks(self, query: str) -> list[SpotifyTrack]:
        result = self.sp.search(query, limit=SEARCH_LIMIT, type="track", market="from_token")
        items = (result.get("tracks") or {}).get("items") or []
        return [parse_track(item) for item in items if item and item.get("uri")]

    def search_albums(self, query: str) -> list[SpotifyAlbum]:
        result = self.sp.search(query, limit=SEARCH_LIMIT, type="album", market="from_token")
        items = (result.get("albums") or {}).get("items") or []
        return [
            SpotifyAlbum(
                uri=item["uri"],
                name=item.get("name") or "",
                artists=tuple(a.get("name") or "" for a in item.get("artists") or []),
                total_tracks=item.get("total_tracks"),
            )
            for item in items
            if item and item.get("uri")
        ]

    def search_artists(self, query: str) -> list[SpotifyArtist]:
        result = self.sp.search(query, limit=SEARCH_LIMIT, type="artist")
        items = (result.get("artists") or {}).get("items") or []
        return [SpotifyArtist(uri=i["uri"], name=i.get("name") or "") for i in items if i and i.get("uri")]

    def playlists(self) -> list[SpotifyPlaylist]:
        found: list[SpotifyPlaylist] = []
        offset = 0
        while True:
            page = self.sp.current_user_playlists(limit=PAGE_LIMIT, offset=offset)
            for item in page.get("items") or []:
                if not item:
                    continue
                contents = _entry_object(item, "items", "tracks") or {}
                found.append(
                    SpotifyPlaylist(
                        id=item["id"],
                        name=item.get("name") or "",
                        owner_id=(item.get("owner") or {}).get("id") or "",
                        total=contents.get("total"),
                    )
                )
            if not page.get("next"):
                return found
            offset += PAGE_LIMIT

    def playlist_track_uris(self, playlist_id: str) -> list[str]:
        uris: list[str] = []
        offset = 0
        while True:
            page = self.sp.playlist_items(
                playlist_id, limit=PAGE_LIMIT, offset=offset, additional_types=("track",)
            )
            for entry in page.get("items") or []:
                obj = _entry_object(entry or {}, "item", "track")
                if obj and obj.get("uri"):
                    uris.append(obj["uri"])
            if not page.get("next"):
                return uris
            offset += PAGE_LIMIT

    def saved_track_uris(self) -> set[str]:
        return self._paged_uris(self.sp.current_user_saved_tracks, "track", "item")

    def saved_album_uris(self) -> set[str]:
        return self._paged_uris(self.sp.current_user_saved_albums, "album", "item")

    def followed_artist_uris(self) -> set[str]:
        uris: set[str] = set()
        after = None
        while True:
            page = self.sp.current_user_followed_artists(limit=PAGE_LIMIT, after=after)["artists"]
            uris.update(a["uri"] for a in page.get("items") or [] if a and a.get("uri"))
            after = (page.get("cursors") or {}).get("after")
            if not page.get("next") or not after:
                return uris

    def _paged_uris(self, fetch: Any, *keys: str) -> set[str]:
        uris: set[str] = set()
        offset = 0
        while True:
            page = fetch(limit=PAGE_LIMIT, offset=offset)
            for entry in page.get("items") or []:
                obj = _entry_object(entry or {}, *keys)
                if obj and obj.get("uri"):
                    uris.add(obj["uri"])
            if not page.get("next"):
                return uris
            offset += PAGE_LIMIT

    # -- writing ----------------------------------------------------------------
    def create_playlist(self, name: str, description: str, public: bool) -> str:
        created = self.sp.current_user_playlist_create(
            name[:100], public=public, description=" ".join(description.split())[:300]
        )
        return created["id"]

    def add_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> None:
        for batch in chunks(uris, PLAYLIST_ADD_BATCH):
            self.sp.playlist_add_items(playlist_id, list(batch))

    def save_tracks(self, uris: Sequence[str]) -> None:
        for batch in chunks(uris, LIBRARY_BATCH):
            self.sp.current_user_saved_tracks_add(list(batch))

    def save_albums(self, uris: Sequence[str]) -> None:
        for batch in chunks(uris, LIBRARY_BATCH):
            self.sp.current_user_saved_albums_add(list(batch))

    def follow_artists(self, uris: Sequence[str]) -> None:
        for batch in chunks(uris, LIBRARY_BATCH):
            self.sp.user_follow_artists(list(batch))
