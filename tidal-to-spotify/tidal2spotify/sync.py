"""Compare a Tidal library with a Spotify account and transfer what is missing.

Nothing on Spotify is ever removed or reordered: the transfer only creates playlists,
appends songs that are not there yet and adds to the library. Running it again only
adds what is still missing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from .matching import TrackMatch, find_album, find_artist, find_track, normalize
from .models import (
    Album,
    Artist,
    Library,
    Playlist,
    SpotifyAlbum,
    SpotifyArtist,
    SpotifyPlaylist,
    SpotifyTrack,
    Track,
)
from .store import Store

ALL_PARTS = ("songs", "playlists", "albums", "artists")
Progress = Callable[[str], None]


class Spotify(Protocol):
    def user_id(self) -> str: ...
    def search_tracks(self, query: str) -> list[SpotifyTrack]: ...
    def search_albums(self, query: str) -> list[SpotifyAlbum]: ...
    def search_artists(self, query: str) -> list[SpotifyArtist]: ...
    def playlists(self) -> list[SpotifyPlaylist]: ...
    def playlist_track_uris(self, playlist_id: str) -> list[str]: ...
    def saved_track_uris(self) -> set[str]: ...
    def saved_album_uris(self) -> set[str]: ...
    def followed_artist_uris(self) -> set[str]: ...
    def create_playlist(self, name: str, description: str, public: bool) -> str: ...
    def add_to_playlist(self, playlist_id: str, uris: list[str]) -> None: ...
    def save_tracks(self, uris: list[str]) -> None: ...
    def save_albums(self, uris: list[str]) -> None: ...
    def follow_artists(self, uris: list[str]) -> None: ...


@dataclass
class Missing:
    kind: str  # "song", "album", "kuenstler"
    item: Track | Album | Artist
    sections: list[str]
    suggestion: SpotifyTrack | None = None
    score: float = 0.0


@dataclass
class Section:
    kind: str  # "songs", "playlist", "albums", "artists"
    title: str
    total: int = 0
    matched: int = 0
    already: int = 0
    to_add: list[str] = field(default_factory=list)
    # playlists only
    tidal_id: str | None = None
    spotify_id: str | None = None
    name: str = ""
    description: str = ""

    @property
    def missing(self) -> int:
        return self.total - self.matched

    @property
    def creates_playlist(self) -> bool:
        return self.kind == "playlist" and self.spotify_id is None


@dataclass
class Plan:
    sections: list[Section] = field(default_factory=list)
    missing: dict[tuple[str, str], Missing] = field(default_factory=dict)

    def note_missing(
        self, kind: str, item: Track | Album | Artist, section: str, match: TrackMatch | None = None
    ) -> None:
        key = (kind, item.tidal_id)
        entry = self.missing.get(key)
        if entry is None:
            entry = self.missing[key] = Missing(kind, item, [])
            if match is not None:
                entry.suggestion, entry.score = match.suggestion, match.score
        if section not in entry.sections:
            entry.sections.append(section)

    @property
    def has_changes(self) -> bool:
        return any(s.to_add or s.creates_playlist for s in self.sections)


class Matcher:
    """Finds Spotify counterparts, using manual matches and the cache before searching."""

    def __init__(self, spotify: Spotify, store: Store, retry_not_found: bool = False):
        self.spotify = spotify
        self.store = store
        self.retry_not_found = retry_not_found
        self._looked_up: set[str] = set()

    def track(self, track: Track) -> TrackMatch:
        manual = self.store.manual.get(("track", track.tidal_id))
        if manual:
            return TrackMatch(manual, "manual", 1.0)
        cached = self.store.cached_track(track.tidal_id)
        if cached and (cached.uri or not self.retry_not_found or track.tidal_id in self._looked_up):
            return cached
        match = find_track(track, self.spotify.search_tracks)
        self._looked_up.add(track.tidal_id)
        self.store.remember_track(track.tidal_id, match)
        return match

    def tracks(self, tracks: Iterable[Track], progress: Progress) -> dict[str, TrackMatch]:
        unique = list({t.tidal_id: t for t in tracks}.values())
        results: dict[str, TrackMatch] = {}
        try:
            for done, track in enumerate(unique, start=1):
                results[track.tidal_id] = self.track(track)
                if done % 50 == 0 or done == len(unique):
                    progress(f"  Songs abgeglichen: {done}/{len(unique)}")
                    self.store.save_cache()
        finally:
            self.store.save_cache()
        return results

    def album(self, album: Album) -> str | None:
        manual = self.store.manual.get(("album", album.tidal_id))
        if manual:
            return manual
        cached = self.store.cached_album(album.tidal_id)
        if cached and (cached["uri"] or not self.retry_not_found):
            return cached["uri"]
        uri, score = find_album(album, self.spotify.search_albums)
        self.store.remember_album(album.tidal_id, uri, score)
        return uri

    def artist(self, artist: Artist, known: dict[str, str]) -> str | None:
        manual = self.store.manual.get(("artist", artist.tidal_id))
        if manual:
            return manual
        cached = self.store.cached_artist(artist.tidal_id)
        if cached and (cached["uri"] or not self.retry_not_found):
            return cached["uri"]
        uri = find_artist(artist, self.spotify.search_artists, known)
        self.store.remember_artist(artist.tidal_id, uri)
        return uri


def _playlist_title(playlist: Playlist) -> str:
    return f"Playlist „{playlist.name}“"


def build_plan(
    library: Library,
    spotify: Spotify,
    matcher: Matcher,
    parts: Iterable[str],
    progress: Progress,
    playlist_names: Iterable[str] = (),
) -> Plan:
    parts = set(parts)
    wanted_names = {normalize(n) for n in playlist_names}
    playlists = [
        p for p in library.playlists if not wanted_names or normalize(p.name) in wanted_names
    ] if "playlists" in parts else []
    plan = Plan()

    tracks = list(library.favorite_tracks) if "songs" in parts else []
    for playlist in playlists:
        tracks.extend(playlist.tracks)
    progress("Suche Songs auf Spotify …")
    matches = matcher.tracks(tracks, progress)

    if "songs" in parts:
        section = Section("songs", "Lieblingssongs")
        existing = spotify.saved_track_uris()
        queued: set[str] = set()
        for track in library.favorite_tracks:
            section.total += 1
            match = matches[track.tidal_id]
            if not match.uri:
                plan.note_missing("song", track, section.title, match)
                continue
            section.matched += 1
            if match.uri in existing or match.uri in queued:
                section.already += 1
            else:
                queued.add(match.uri)
                section.to_add.append(match.uri)
        plan.sections.append(section)

    if playlists:
        progress("Lese Spotify-Playlists …")
        me = spotify.user_id()
        own = {p.id: p for p in spotify.playlists() if p.owner_id == me}
        claimed = {sid for sid in matcher.store.playlist_map.values() if sid in own}
        for playlist in playlists:
            section = Section(
                "playlist",
                _playlist_title(playlist),
                tidal_id=playlist.tidal_id,
                name=playlist.name,
                description=playlist.description,
            )
            mapped = matcher.store.playlist_map.get(playlist.tidal_id)
            if mapped in own:
                section.spotify_id = mapped
            else:
                # Adopt an own Spotify playlist of the same name, e.g. from an earlier
                # run whose mapping was lost, unless it already mirrors another one.
                for candidate in own.values():
                    if candidate.id not in claimed and candidate.name == playlist.name:
                        section.spotify_id = candidate.id
                        claimed.add(candidate.id)
                        break
            remaining = Counter(spotify.playlist_track_uris(section.spotify_id) if section.spotify_id else [])
            for track in playlist.tracks:
                section.total += 1
                match = matches[track.tidal_id]
                if not match.uri:
                    plan.note_missing("song", track, section.title, match)
                    continue
                section.matched += 1
                if remaining[match.uri] > 0:
                    remaining[match.uri] -= 1
                    section.already += 1
                else:
                    section.to_add.append(match.uri)
            plan.sections.append(section)

    if "albums" in parts and library.albums:
        progress("Suche Alben auf Spotify …")
        section = Section("albums", "Alben")
        existing = spotify.saved_album_uris()
        try:
            for album in library.albums:
                section.total += 1
                uri = matcher.album(album)
                if not uri:
                    plan.note_missing("album", album, section.title)
                    continue
                section.matched += 1
                if uri in existing or uri in section.to_add:
                    section.already += 1
                else:
                    section.to_add.append(uri)
        finally:
            matcher.store.save_cache()
        plan.sections.append(section)

    if "artists" in parts and library.artists:
        progress("Suche Künstler auf Spotify …")
        known: dict[str, str] = {}
        for match in matches.values():
            if match.uri and match.candidate:
                for name, uri in match.candidate.artists:
                    known.setdefault(normalize(name), uri)
        section = Section("artists", "Künstler")
        existing = spotify.followed_artist_uris()
        try:
            for artist in library.artists:
                section.total += 1
                uri = matcher.artist(artist, known)
                if not uri:
                    plan.note_missing("kuenstler", artist, section.title)
                    continue
                section.matched += 1
                if uri in existing or uri in section.to_add:
                    section.already += 1
                else:
                    section.to_add.append(uri)
        finally:
            matcher.store.save_cache()
        plan.sections.append(section)

    return plan


def apply_plan(plan: Plan, spotify: Spotify, store: Store, public: bool, progress: Progress) -> None:
    for section in plan.sections:
        if section.kind == "songs" and section.to_add:
            progress(f"Speichere {len(section.to_add)} Lieblingssongs …")
            spotify.save_tracks(section.to_add)
        elif section.kind == "playlist":
            if section.spotify_id is None:
                progress(f"Erstelle {section.title} …")
                section.spotify_id = spotify.create_playlist(section.name, section.description, public)
            assert section.tidal_id is not None
            # Record the mapping before adding songs, so an interrupted run resumes
            # into the same playlist instead of creating a second copy.
            store.playlist_map[section.tidal_id] = section.spotify_id
            store.save_playlist_map()
            if section.to_add:
                progress(f"Füge {len(section.to_add)} Songs zu {section.title} hinzu …")
                spotify.add_to_playlist(section.spotify_id, section.to_add)
        elif section.kind == "albums" and section.to_add:
            progress(f"Speichere {len(section.to_add)} Alben …")
            spotify.save_albums(section.to_add)
        elif section.kind == "artists" and section.to_add:
            progress(f"Folge {len(section.to_add)} Künstlern …")
            spotify.follow_artists(section.to_add)
