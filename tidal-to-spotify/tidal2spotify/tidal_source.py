"""Read a Tidal account with tidalapi (device login via link.tidal.com).

Pagination is done here instead of with tidalapi's parallel helpers, which log and
drop failed pages: an incomplete library must fail loudly, not transfer silently.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .models import Album, Artist, Library, Playlist, Track

Progress = Callable[[str], None]

PLAYLIST_PAGE = 50
ITEM_PAGE = 100


def convert_track(t: Any) -> Track:
    artists = tuple(a.name for a in (getattr(t, "artists", None) or []) if getattr(a, "name", None))
    if not artists and getattr(getattr(t, "artist", None), "name", None):
        artists = (t.artist.name,)
    duration = getattr(t, "duration", None)
    return Track(
        tidal_id=str(t.id),
        title=getattr(t, "name", None) or "",
        artists=artists,
        album=getattr(getattr(t, "album", None), "name", None),
        duration=int(duration) if isinstance(duration, (int, float)) else None,
        isrc=getattr(t, "isrc", None) or None,
        version=getattr(t, "version", None) or None,
    )


def convert_album(a: Any) -> Album:
    artists = tuple(x.name for x in (getattr(a, "artists", None) or []) if getattr(x, "name", None))
    return Album(
        tidal_id=str(a.id),
        title=getattr(a, "name", None) or "",
        artists=artists,
        upc=getattr(a, "universal_product_number", None) or None,
        num_tracks=getattr(a, "num_tracks", None),
    )


def _pages(fetch: Callable[[int, int], list[Any]], page_size: int, total: int | None) -> Iterable[Any]:
    offset = 0
    while total is None or offset < total:
        page = fetch(page_size, offset)
        if not page:
            return
        yield from page
        if total is None and len(page) < page_size:
            return
        offset += page_size


class TidalSource:
    def __init__(self, session: Any):
        self.session = session

    @classmethod
    def connect(cls, session_file: Path, show: Progress) -> TidalSource:
        import tidalapi

        session = tidalapi.Session()
        if not session.login_session_file(session_file, do_pkce=False, fn_print=show):
            raise RuntimeError("Tidal-Anmeldung fehlgeschlagen.")
        if session_file.exists():
            os.chmod(session_file, 0o600)
        return cls(session)

    def account_name(self) -> str:
        user = self.session.user
        return getattr(user, "username", None) or getattr(user, "email", None) or str(user.id)

    def fetch(self, parts: set[str], include_followed: bool, progress: Progress) -> Library:
        from tidalapi.types import AlbumOrder, ArtistOrder, ItemOrder, OrderDirection

        user = self.session.user
        favorites = user.favorites
        library = Library()

        if "songs" in parts:
            total = favorites.get_tracks_count()
            for track in _pages(
                lambda limit, offset: favorites.tracks(
                    limit=limit, offset=offset, order=ItemOrder.Date, order_direction=OrderDirection.Ascending
                ),
                ITEM_PAGE,
                total,
            ):
                library.favorite_tracks.append(convert_track(track))
                if len(library.favorite_tracks) % 500 == 0:
                    progress(f"  Lieblingssongs: {len(library.favorite_tracks)}/{total}")
            progress(f"  Lieblingssongs: {len(library.favorite_tracks)}")

        if "playlists" in parts:
            seen: set[str] = set()
            for playlist in _pages(
                lambda limit, offset: user.playlist_and_favorite_playlists(offset=offset, limit=limit),
                PLAYLIST_PAGE,
                None,
            ):
                pid = str(playlist.id)
                if pid in seen:
                    continue
                seen.add(pid)
                owned = getattr(getattr(playlist, "creator", None), "id", None) == user.id
                if not owned and not include_followed:
                    continue
                library.playlists.append(self._playlist(playlist, owned))
                progress(f"  Playlist „{playlist.name}“: {len(library.playlists[-1].tracks)} Songs")

        if "albums" in parts:
            library.albums = [
                convert_album(a)
                for a in _pages(
                    lambda limit, offset: favorites.albums(
                        limit=limit,
                        offset=offset,
                        order=AlbumOrder.DateAdded,
                        order_direction=OrderDirection.Ascending,
                    ),
                    PLAYLIST_PAGE,
                    favorites.get_albums_count(),
                )
            ]
            progress(f"  Alben: {len(library.albums)}")

        if "artists" in parts:
            library.artists = [
                Artist(tidal_id=str(a.id), name=a.name)
                for a in _pages(
                    lambda limit, offset: favorites.artists(
                        limit=limit,
                        offset=offset,
                        order=ArtistOrder.DateAdded,
                        order_direction=OrderDirection.Ascending,
                    ),
                    PLAYLIST_PAGE,
                    favorites.get_artists_count(),
                )
            ]
            progress(f"  Künstler: {len(library.artists)}")

        return library

    def _playlist(self, playlist: Any, owned: bool) -> Playlist:
        import tidalapi

        total = (getattr(playlist, "num_tracks", 0) or 0) + (getattr(playlist, "num_videos", 0) or 0)
        result = Playlist(
            tidal_id=str(playlist.id),
            name=playlist.name or "Ohne Titel",
            description=getattr(playlist, "description", None) or "",
            owned=owned,
        )
        for item in _pages(lambda limit, offset: playlist.items(limit=limit, offset=offset), ITEM_PAGE, total):
            if isinstance(item, tidalapi.Video):
                result.skipped_videos += 1
            else:
                result.tracks.append(convert_track(item))
        return result
