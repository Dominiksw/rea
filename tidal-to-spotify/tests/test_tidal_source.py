from types import SimpleNamespace as NS

import pytest

from tidal2spotify.tidal_source import TidalSource


def track(i, isrc=None):
    return NS(
        id=i,
        name=f"Song {i}",
        artists=[NS(name="Artist")],
        album=NS(name="Album"),
        duration=180,
        isrc=isrc,
        version=None,
    )


class FakeFavorites:
    def __init__(self, n_tracks):
        self.tracks_data = [track(i) for i in range(n_tracks)]
        self.calls = []

    def get_tracks_count(self):
        return len(self.tracks_data)

    def tracks(self, limit, offset, order, order_direction):
        self.calls.append((limit, offset, order.value, order_direction.value))
        return self.tracks_data[offset : offset + limit]

    def get_albums_count(self):
        return 1

    def albums(self, limit, offset, order, order_direction):
        album = NS(id=7, name="LP", artists=[NS(name="Artist")], universal_product_number="123", num_tracks=9)
        return [album][offset : offset + limit]

    def get_artists_count(self):
        return 0

    def artists(self, limit, offset, order, order_direction):
        return []


class FakePlaylist:
    def __init__(self, pid, name, creator_id, items):
        self.id, self.name, self.description = pid, name, None
        self.creator = NS(id=creator_id)
        self._items = items
        self.num_tracks, self.num_videos = len(items), 0

    def items(self, limit, offset):
        return self._items[offset : offset + limit]


def make_session(n_tracks=0, playlists=()):
    playlists = list(playlists)
    user = NS(id=42, favorites=FakeFavorites(n_tracks))
    user.playlist_and_favorite_playlists = lambda offset, limit: playlists[offset : offset + limit]
    return NS(user=user)


def test_favourites_are_paged_oldest_first():
    session = make_session(n_tracks=250)
    library = TidalSource(session).fetch({"songs"}, include_followed=False, progress=lambda _: None)
    assert [t.tidal_id for t in library.favorite_tracks] == [str(i) for i in range(250)]
    assert [c[1] for c in session.user.favorites.calls] == [0, 100, 200]
    assert session.user.favorites.calls[0][2:] == ("DATE", "ASC")


def test_followed_playlists_only_on_request_and_long_playlists_paged():
    own = FakePlaylist("p1", "Mine", 42, [track(i, isrc=f"I{i}") for i in range(130)])
    followed = FakePlaylist("p2", "Editorial", 1, [track(1)])
    session = make_session(playlists=[own, followed, own])

    library = TidalSource(session).fetch({"playlists"}, include_followed=False, progress=lambda _: None)
    assert [(p.tidal_id, p.owned, len(p.tracks)) for p in library.playlists] == [("p1", True, 130)]
    assert library.playlists[0].tracks[129].isrc == "I129"

    library = TidalSource(session).fetch({"playlists"}, include_followed=True, progress=lambda _: None)
    assert [(p.tidal_id, p.owned) for p in library.playlists] == [("p1", True), ("p2", False)]


def test_albums_keep_upc():
    library = TidalSource(make_session()).fetch({"albums"}, include_followed=False, progress=lambda _: None)
    assert [(a.tidal_id, a.title, a.upc, a.num_tracks) for a in library.albums] == [("7", "LP", "123", 9)]


def test_a_failing_page_aborts_instead_of_dropping_songs():
    session = make_session(n_tracks=150)

    def broken(limit, offset, order, order_direction):
        if offset == 100:
            raise ConnectionError("Tidal antwortet nicht")
        return session.user.favorites.tracks_data[offset : offset + limit]

    session.user.favorites.tracks = broken
    with pytest.raises(ConnectionError):
        TidalSource(session).fetch({"songs"}, include_followed=False, progress=lambda _: None)
