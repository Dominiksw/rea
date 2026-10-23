from tidal2spotify.spotify_target import SpotifyTarget


class FakeSpotipy:
    """Answers like the Web API after the February 2026 changes."""

    def __init__(self):
        self.calls = []

    def playlist_items(self, playlist_id, limit, offset, additional_types):
        self.calls.append(("playlist_items", offset))
        pages = {
            0: {
                "items": [
                    {"item": {"uri": "spotify:track:new-style"}, "track": True},
                    {"track": {"uri": "spotify:track:old-style"}},
                    {"item": None},  # unavailable / removed
                ],
                "next": "more",
            },
            50: {"items": [{"item": {"uri": "spotify:local:file"}}], "next": None},
        }
        return pages[offset]

    def current_user_playlists(self, limit, offset):
        return {
            "items": [
                {"id": "a", "name": "Mine", "owner": {"id": "me"}, "items": {"total": 3}},
                {"id": "b", "name": "Old", "owner": {"id": "x"}, "tracks": {"total": 7}},
            ],
            "next": None,
        }

    def current_user_saved_tracks(self, limit, offset):
        return {"items": [{"track": {"uri": "spotify:track:1"}}], "next": None}

    def current_user_followed_artists(self, limit, after):
        self.calls.append(("followed", after))
        if after is None:
            return {"artists": {"items": [{"uri": "spotify:artist:1"}], "cursors": {"after": "c1"}, "next": "n"}}
        return {"artists": {"items": [{"uri": "spotify:artist:2"}], "cursors": {"after": None}, "next": None}}

    def search(self, q, limit, type, market=None):
        self.calls.append(("search", q, limit, type, market))
        return {
            "tracks": {
                "items": [
                    None,
                    {
                        "uri": "spotify:track:s",
                        "name": "Song",
                        "artists": [{"name": "A", "uri": "spotify:artist:a"}],
                        "album": {"name": "Album"},
                        "duration_ms": 1000,
                        "external_ids": {"isrc": "X1"},
                    },
                ]
            }
        }

    def current_user_saved_tracks_add(self, uris):
        self.calls.append(("save", len(uris)))

    def playlist_add_items(self, playlist_id, uris):
        self.calls.append(("add", len(uris)))

    def current_user_playlist_create(self, name, public, description):
        self.calls.append(("create", name, public, description))
        return {"id": "new"}


def test_reads_both_item_and_legacy_track_fields():
    target = SpotifyTarget(FakeSpotipy())
    assert target.playlist_track_uris("p") == [
        "spotify:track:new-style",
        "spotify:track:old-style",
        "spotify:local:file",
    ]
    assert [(p.id, p.owner_id, p.total) for p in target.playlists()] == [("a", "me", 3), ("b", "x", 7)]
    assert target.saved_track_uris() == {"spotify:track:1"}
    assert target.followed_artist_uris() == {"spotify:artist:1", "spotify:artist:2"}


def test_search_respects_new_limit_and_skips_empty_results():
    fake = FakeSpotipy()
    (track,) = SpotifyTarget(fake).search_tracks("isrc:X1")
    assert (track.uri, track.isrc, track.artists, track.album) == (
        "spotify:track:s",
        "X1",
        (("A", "spotify:artist:a"),),
        "Album",
    )
    assert fake.calls[-1] == ("search", "isrc:X1", 10, "track", "from_token")


def test_writes_are_batched_within_api_limits():
    fake = FakeSpotipy()
    target = SpotifyTarget(fake)
    target.save_tracks([f"spotify:track:{i}" for i in range(85)])
    target.add_to_playlist("p", [f"spotify:track:{i}" for i in range(250)])
    assert [c for c in fake.calls if c[0] == "save"] == [("save", 40), ("save", 40), ("save", 5)]
    assert [c for c in fake.calls if c[0] == "add"] == [("add", 100), ("add", 100), ("add", 50)]


def test_create_playlist_cleans_description():
    fake = FakeSpotipy()
    assert SpotifyTarget(fake).create_playlist("N" * 120, "Zeile 1\nZeile 2  " + "x" * 400, False) == "new"
    _, name, public, description = fake.calls[-1]
    assert len(name) == 100 and public is False
    assert "\n" not in description and len(description) == 300
