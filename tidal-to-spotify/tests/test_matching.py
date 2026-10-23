from dataclasses import replace

from tidal2spotify.matching import (
    ACCEPT,
    find_album,
    find_artist,
    find_track,
    normalize,
    score_track,
    strip_decorations,
    track_queries,
)
from tidal2spotify.models import Album, Artist, SpotifyAlbum, SpotifyArtist, Track

from .fakes import sp_track


def tidal(title, *artists, seconds=200, isrc=None, version=None, album=None):
    return Track("1", title, tuple(artists), album=album, duration=seconds, isrc=isrc, version=version)


def test_normalize_strips_accents_case_and_punctuation():
    assert normalize("Beyoncé & JAY-Z") == "beyonce and jay z"
    assert normalize("Don't Stop Me Now!") == "dont stop me now"


def test_isrc_hit_wins_even_when_spotify_titles_differ():
    wanted = tidal("Bohemian Rhapsody", "Queen", seconds=354, isrc="GBUM71029604")
    hit = sp_track("Bohemian Rhapsody - Remastered 2011", "Queen", seconds=355, isrc="GBUM71029604")
    other = sp_track("Bohemian Rhapsody", "Queen", seconds=354)
    match = find_track(wanted, lambda q: [hit] if q == "isrc:GBUM71029604" else [other])
    assert (match.uri, match.method) == (hit.uri, "isrc")


def test_isrc_hit_with_different_isrc_in_result_is_ignored():
    wanted = tidal("Song", "Artist", isrc="AAA111")
    wrong = sp_track("Song", "Artist", isrc="BBB222")
    queries = []

    def search(q):
        queries.append(q)
        return [wrong]

    match = find_track(wanted, search)
    assert match.method == "search"  # fell through to the title search
    assert len(queries) > 1


def test_remaster_and_featuring_decorations_still_match():
    wanted = tidal("Empire State of Mind", "JAY-Z", "Alicia Keys", seconds=276, version="feat. Alicia Keys")
    candidate = replace(
        sp_track("Empire State Of Mind (feat. Alicia Keys)", "JAY-Z", seconds=277),
        artists=(("JAY-Z", "a"), ("Alicia Keys", "b")),
    )
    assert score_track(wanted, candidate) >= ACCEPT


def test_live_version_is_not_taken_for_studio_recording():
    wanted = tidal("Wonderwall", "Oasis", seconds=258)
    live = sp_track("Wonderwall - Live at Knebworth", "Oasis", seconds=258)
    match = find_track(wanted, lambda q: [live])
    assert match.uri is None
    assert score_track(wanted, live) < ACCEPT


def test_wrong_artist_is_only_a_suggestion():
    wanted = tidal("Hurt", "Johnny Cash", seconds=218)
    cover_of_original = sp_track("Hurt", "Nine Inch Nails", seconds=373)
    match = find_track(wanted, lambda q: [cover_of_original])
    assert match.uri is None


def test_close_but_uncertain_result_is_reported_as_suggestion():
    wanted = tidal("Song Title", "Artist", seconds=200)
    near = sp_track("Song Title", "Someone Else", seconds=204)
    match = find_track(wanted, lambda q: [near])
    assert match.uri is None
    assert match.suggestion == near


def test_queries_use_core_title_primary_artist_and_version_markers():
    wanted = tidal('Say "Hello" (Remastered)', "Artist A", "Artist B", version="Live")
    assert track_queries(wanted) == ['track:"Say Hello" artist:"Artist A"', "Say Hello live Artist A"]


def test_album_by_upc_and_by_title():
    album = Album("9", "Abbey Road (Remastered)", ("The Beatles",), upc="0602567", num_tracks=17)
    found = SpotifyAlbum("spotify:album:x", "Abbey Road (Remastered)", ("The Beatles",), 17)
    uri, _ = find_album(album, lambda q: [found] if q == "upc:0602567" else [])
    assert uri == found.uri
    uri, _ = find_album(Album("9", "Abbey Road", ("The Beatles",)), lambda q: [found])
    assert uri == found.uri


def test_artist_prefers_uri_known_from_matched_tracks():
    artist = Artist("5", "Nirvana")
    search_hit = SpotifyArtist("spotify:artist:other-nirvana", "Nirvana")
    assert find_artist(artist, lambda q: [search_hit], {"nirvana": "spotify:artist:real"}) == "spotify:artist:real"
    assert find_artist(artist, lambda q: [search_hit], {}) == search_hit.uri
    assert find_artist(artist, lambda q: [SpotifyArtist("u", "Nirvana Tribute Band")], {}) is None


def test_dash_suffix_is_stripped_only_when_it_names_a_version():
    assert strip_decorations("Bohemian Rhapsody - Remastered 2011") == "Bohemian Rhapsody"
    assert strip_decorations("Heroes - 2017 Remaster") == "Heroes"
    assert strip_decorations("Rosé – Intro") == "Rosé - Intro"
    assert strip_decorations("(I Can't Get No) Satisfaction - Mono Version") == "Satisfaction"
    intro = tidal("Rosé – Intro", "X", seconds=100)
    assert score_track(intro, sp_track("Rose", "X", seconds=100)) < ACCEPT
