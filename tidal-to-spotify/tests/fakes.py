"""In-memory Spotify account implementing the sync.Spotify protocol."""

from __future__ import annotations

import itertools

from tidal2spotify.matching import core_title, normalize
from tidal2spotify.models import SpotifyAlbum, SpotifyArtist, SpotifyPlaylist, SpotifyTrack

_ids = itertools.count(1)


def sp_track(
    name: str, artist: str, seconds: int = 200, isrc: str | None = None, album: str | None = None
) -> SpotifyTrack:
    n = next(_ids)
    return SpotifyTrack(
        uri=f"spotify:track:{n:022d}",
        name=name,
        artists=((artist, f"spotify:artist:{abs(hash(artist)) % 10**22:022d}"),),
        album=album,
        duration_ms=seconds * 1000,
        isrc=isrc,
    )


class FakeSpotify:
    def __init__(
        self,
        tracks: list[SpotifyTrack] = (),
        albums: list[SpotifyAlbum] = (),
        artists: list[SpotifyArtist] = (),
    ):
        self.catalog = list(tracks)
        self.album_catalog = list(albums)
        self.artist_catalog = list(artists)
        self.me = "me"
        self.saved_tracks: list[str] = []
        self.saved_albums: list[str] = []
        self.followed: list[str] = []
        self.lists: dict[str, SpotifyPlaylist] = {}
        self.list_items: dict[str, list[str]] = {}
        self.writes: list[tuple] = []
        self.searches: list[str] = []
        self.fail_add_to: str | None = None

    # reading
    def user_id(self) -> str:
        return self.me

    def display_name(self) -> str:
        return "Test"

    def search_tracks(self, query: str) -> list[SpotifyTrack]:
        self.searches.append(query)
        if query.startswith("isrc:"):
            return [t for t in self.catalog if t.isrc == query[5:]][:10]
        words = set(normalize(query.replace("track:", " ").replace("artist:", " ")).split())
        return [t for t in self.catalog if set(core_title(t.name).split()) <= words][:10]

    def search_albums(self, query: str) -> list[SpotifyAlbum]:
        words = set(normalize(query.replace("album:", " ").replace("artist:", " ")).split())
        return [a for a in self.album_catalog if set(normalize(a.name).split()) <= words][:10]

    def search_artists(self, query: str) -> list[SpotifyArtist]:
        words = set(normalize(query.replace("artist:", " ")).split())
        return [a for a in self.artist_catalog if set(normalize(a.name).split()) <= words][:10]

    def playlists(self) -> list[SpotifyPlaylist]:
        return list(self.lists.values())

    def playlist_track_uris(self, playlist_id: str) -> list[str]:
        return list(self.list_items[playlist_id])

    def saved_track_uris(self) -> set[str]:
        return set(self.saved_tracks)

    def saved_album_uris(self) -> set[str]:
        return set(self.saved_albums)

    def followed_artist_uris(self) -> set[str]:
        return set(self.followed)

    # writing
    def add_playlist(self, name: str, uris: list[str] = (), owner: str = "me") -> str:
        pid = f"pl{len(self.lists) + 1}"
        self.lists[pid] = SpotifyPlaylist(pid, name, owner, len(uris))
        self.list_items[pid] = list(uris)
        return pid

    def create_playlist(self, name: str, description: str, public: bool) -> str:
        pid = self.add_playlist(name)
        self.writes.append(("create", name, description, public))
        return pid

    def add_to_playlist(self, playlist_id: str, uris: list[str]) -> None:
        if playlist_id == self.fail_add_to:
            raise RuntimeError("network down")
        self.writes.append(("add", playlist_id, list(uris)))
        self.list_items[playlist_id].extend(uris)

    def save_tracks(self, uris: list[str]) -> None:
        self.writes.append(("save_tracks", list(uris)))
        self.saved_tracks.extend(uris)

    def save_albums(self, uris: list[str]) -> None:
        self.writes.append(("save_albums", list(uris)))
        self.saved_albums.extend(uris)

    def follow_artists(self, uris: list[str]) -> None:
        self.writes.append(("follow", list(uris)))
        self.followed.extend(uris)
