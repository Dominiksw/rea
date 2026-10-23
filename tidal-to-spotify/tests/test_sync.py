import csv

import pytest

from tidal2spotify.models import Album, Artist, Library, Playlist, SpotifyAlbum, SpotifyArtist, Track
from tidal2spotify.report import write_reports
from tidal2spotify.store import Store
from tidal2spotify.sync import Matcher, apply_plan, build_plan

from .fakes import FakeSpotify, sp_track

ALL = {"songs", "playlists", "albums", "artists"}


def quiet(_):
    pass


def t(tid, title, artist, isrc=None, seconds=200):
    return Track(tid, title, (artist,), duration=seconds, isrc=isrc)


@pytest.fixture
def world(tmp_path):
    a = sp_track("Alpha", "Band", isrc="ISRC-A")
    b = sp_track("Beta", "Band", isrc="ISRC-B")
    c = sp_track("Gamma", "Band")
    spotify = FakeSpotify(
        [a, b, c],
        albums=[SpotifyAlbum("spotify:album:alb", "Greatest Hits", ("Band",), 12)],
        artists=[SpotifyArtist("spotify:artist:search", "Solo Artist")],
    )
    library = Library(
        favorite_tracks=[t("1", "Alpha", "Band", "ISRC-A"), t("2", "Beta", "Band", "ISRC-B")],
        playlists=[
            Playlist(
                "p1",
                "Road Trip",
                "Für lange Fahrten",
                tracks=[t("2", "Beta", "Band", "ISRC-B"), t("3", "Gamma", "Band"), t("2", "Beta", "Band", "ISRC-B")],
            ),
            Playlist("p2", "Rarities", tracks=[t("4", "Unreleased Demo", "Nobody")]),
        ],
        albums=[Album("al1", "Greatest Hits", ("Band",), num_tracks=12)],
        artists=[Artist("ar1", "Band"), Artist("ar2", "Solo Artist")],
    )
    store = Store(tmp_path / "data")
    return spotify, library, store, (a, b, c)


def plan_for(spotify, library, store, **kw):
    return build_plan(library, spotify, Matcher(spotify, store, **kw), ALL, quiet)


def test_compare_writes_nothing_and_counts_everything(world):
    spotify, library, store, (a, b, c) = world
    spotify.saved_tracks = [a.uri]
    plan = plan_for(spotify, library, store)

    assert spotify.writes == []
    songs, road, rarities, albums, artists = plan.sections
    assert (songs.total, songs.matched, songs.already, songs.to_add) == (2, 2, 1, [b.uri])
    assert road.creates_playlist and road.to_add == [b.uri, c.uri, b.uri]  # duplicates kept
    assert (rarities.total, rarities.missing) == (1, 1)
    assert albums.to_add == ["spotify:album:alb"]
    # "Band" comes from the matched tracks, "Solo Artist" from the artist search.
    assert set(artists.to_add) == {a.artists[0][1], "spotify:artist:search"}
    assert list(plan.missing) == [("song", "4")]


def test_transfer_then_rerun_adds_nothing(world):
    spotify, library, store, (a, b, c) = world
    apply_plan(plan_for(spotify, library, store), spotify, store, public=False, progress=quiet)

    assert spotify.saved_tracks == [a.uri, b.uri]  # Tidal order: oldest favourite first
    created = [w for w in spotify.writes if w[0] == "create"]
    assert created == [("create", "Road Trip", "Für lange Fahrten", False), ("create", "Rarities", "", False)]
    road_id = store.playlist_map["p1"]
    assert spotify.list_items[road_id] == [b.uri, c.uri, b.uri]

    writes = len(spotify.writes)
    searches = len(spotify.searches)
    again = plan_for(spotify, Library(**library.__dict__), Store(store.dir))
    assert not again.has_changes
    apply_plan(again, spotify, store, public=False, progress=quiet)
    assert len(spotify.writes) == writes
    assert len(spotify.searches) == searches  # served from the match cache


def test_new_tidal_songs_are_appended_to_the_existing_copy(world):
    spotify, library, store, (a, b, c) = world
    apply_plan(plan_for(spotify, library, store), spotify, store, public=False, progress=quiet)
    library.playlists[0].tracks.append(t("1", "Alpha", "Band", "ISRC-A"))

    plan = plan_for(spotify, library, store)
    road = plan.sections[1]
    assert road.spotify_id == store.playlist_map["p1"] and road.to_add == [a.uri]


def test_same_named_own_playlist_is_adopted_but_not_twice(world):
    spotify, library, store, (a, b, c) = world
    existing = spotify.add_playlist("Road Trip", [c.uri])
    spotify.add_playlist("Road Trip", [], owner="someone-else")
    library.playlists.append(Playlist("p3", "Road Trip", tracks=[t("1", "Alpha", "Band", "ISRC-A")]))

    sections = plan_for(spotify, library, store).sections
    first, second = sections[1], sections[3]
    assert first.spotify_id == existing and first.to_add == [b.uri, b.uri]
    assert second.creates_playlist


def test_mapping_is_saved_before_songs_are_added(world):
    spotify, library, store, _ = world
    plan = plan_for(spotify, library, store)
    spotify.fail_add_to = "pl1"
    with pytest.raises(RuntimeError):
        apply_plan(plan, spotify, store, public=False, progress=quiet)
    assert Store(store.dir).playlist_map == {"p1": "pl1"}

    spotify.fail_add_to = None
    apply_plan(plan_for(spotify, library, Store(store.dir)), spotify, store, public=False, progress=quiet)
    assert [w[1] for w in spotify.writes if w[0] == "create"] == ["Road Trip", "Rarities"]


def test_manual_match_and_not_found_report(world, tmp_path):
    spotify, library, store, (a, b, c) = world
    summary, missing = write_reports(plan_for(spotify, library, store), store.reports_dir, applied=False)
    with open(missing, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert [(r["typ"], r["tidal_id"], r["titel"], r["bereich"]) for r in rows] == [
        ("song", "4", "Unreleased Demo", "Playlist „Rarities“")
    ]
    assert "Unreleased Demo" in summary.read_text(encoding="utf-8")

    # The user copies the row into manuelle_zuordnung.csv and pastes a Spotify link.
    demo = sp_track("Demo (Bonus)", "Nobody")
    spotify.catalog.append(demo)
    with open(store.manual_path, "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh, delimiter=";").writerow(
            ["song", "4", f"https://open.spotify.com/intl-de/track/{demo.uri.split(':')[2]}?si=x"]
        )
    plan = plan_for(spotify, library, Store(store.dir))
    assert plan.sections[2].to_add == [demo.uri]
    assert plan.missing == {}


def test_invalid_manual_link_is_reported(tmp_path):
    store = Store(tmp_path)
    store.manual_path.write_text("typ;tidal_id;spotify_link\nsong;4;https://example.com/x\n", encoding="utf-8")
    store = Store(tmp_path)
    assert store.manual == {}
    assert "Zeile 2" in store.manual_errors[0]


def test_retry_not_found_searches_again(world):
    spotify, library, store, _ = world
    plan_for(spotify, library, store)
    before = len(spotify.searches)
    plan_for(spotify, library, Store(store.dir))
    assert len(spotify.searches) == before
    plan_for(spotify, library, Store(store.dir), retry_not_found=True)
    assert len(spotify.searches) > before


def test_playlist_filter(world):
    spotify, library, store, _ = world
    plan = build_plan(library, spotify, Matcher(spotify, store), {"playlists"}, quiet, ["rarities"])
    assert [s.title for s in plan.sections] == ["Playlist „Rarities“"]
