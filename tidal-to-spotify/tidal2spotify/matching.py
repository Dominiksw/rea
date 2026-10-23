"""Decide whether a Spotify search result is the same recording as a Tidal item.

Tracks are matched by ISRC first (the recording's international ID, shared by both
services). Without an ISRC hit, title/artist searches are scored on title, artists,
duration and version markers such as "live" or "remix".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import Album, Artist, SpotifyAlbum, SpotifyArtist, SpotifyTrack, Track

ACCEPT = 0.75  # auto-accept a search hit from this score on
SUGGEST = 0.5  # below ACCEPT but at least this: reported as a suggestion

# Words that mark a different recording or arrangement. "Remastered", "Mono" or
# "Album Version" are deliberately absent: they are the same song for a listener.
VERSION_MARKERS = frozenset(
    {
        "acapella", "acoustic", "bootleg", "cappella", "cover", "demo", "dub",
        "edit", "extended", "instrumental", "karaoke", "live", "mashup",
        "orchestral", "rehearsal", "remix", "reprise", "rework", "slowed",
        "sped", "unplugged", "vip",
    }
)  # fmt: skip

# A " - ..." part only decorates a title when it describes the release or version
# ("- Remastered 2011", "- Live at Wembley"); "Rosé - Intro" is a different song.
DECORATION_WORDS = VERSION_MARKERS | frozenset(
    {
        "album", "anniversary", "bonus", "deluxe", "edition", "feat", "featuring",
        "from", "ft", "mix", "mixed", "mono", "original", "radio", "recorded",
        "remaster", "remastered", "single", "soundtrack", "stereo", "version", "with",
    }
)  # fmt: skip

_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_DASH = re.compile(r"\s+[-–—]\s+")
_YEAR = re.compile(r"\b(19|20)\d\d\b")
_FEAT_SUFFIX = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w]+")


def normalize(text: str) -> str:
    """Lower-case, strip accents and punctuation: 'Beyoncé & JAY-Z' -> 'beyonce and jay z'."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ").replace("'", "").replace("’", "")
    return " ".join(_NON_WORD.sub(" ", text).split())


def strip_decorations(title: str) -> str:
    """Remove '(feat. X)', '[Remastered]', ' - Live' style additions from a title."""
    head, *tails = _DASH.split(_BRACKETS.sub(" ", title))
    core = " - ".join([head, *(t for t in tails if not _is_decoration(t))])
    core = _FEAT_SUFFIX.sub("", core)
    core = " ".join(core.split())
    return core or title


def _is_decoration(part: str) -> bool:
    return bool(set(normalize(part).split()) & DECORATION_WORDS) or bool(_YEAR.search(part))


def core_title(title: str) -> str:
    return normalize(strip_decorations(title)) or normalize(title)


def version_markers(*texts: str | None) -> frozenset[str]:
    words: set[str] = set()
    for text in texts:
        if text:
            words.update(normalize(text).split())
    return frozenset(words & VERSION_MARKERS)


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def artist_score(wanted: Iterable[str], found: Iterable[str]) -> float:
    """1.0 when the primary artist and all featured artists appear in the result."""
    wanted_n = [normalize(a) for a in wanted if a and normalize(a)]
    found_n = [normalize(a) for a in found if a and normalize(a)]
    if not wanted_n:
        return 0.5
    if not found_n:
        return 0.0
    joined = " " + " ".join(found_n) + " "

    def present(name: str) -> bool:
        return f" {name} " in joined or any(similarity(name, f) >= 0.85 for f in found_n)

    primary = 1.0 if present(wanted_n[0]) else 0.0
    share = sum(present(name) for name in wanted_n) / len(wanted_n)
    return 0.6 * primary + 0.4 * share


def duration_score(seconds: int | None, duration_ms: int | None) -> float:
    if not seconds or not duration_ms:
        return 0.6
    diff = abs(seconds - duration_ms / 1000)
    if diff <= 2:
        return 1.0
    if diff >= 20:
        return 0.0
    return 1.0 - (diff - 2) / 18


def score_track(track: Track, candidate: SpotifyTrack) -> float:
    title = similarity(core_title(track.title), core_title(candidate.name))
    artists = artist_score(track.artists, candidate.artist_names)
    duration = duration_score(track.duration, candidate.duration_ms)
    mismatched = version_markers(track.title, track.version) ^ version_markers(candidate.name)
    # Multiplicative, so a matching artist and length cannot make up for another title.
    score = title * (0.6 + 0.4 * artists) * (0.7 + 0.3 * duration) - 0.3 * len(mismatched)
    if track.album and candidate.album and similarity(normalize(track.album), normalize(candidate.album)) >= 0.8:
        score += 0.05
    return max(0.0, min(1.0, score))


@dataclass(frozen=True)
class TrackMatch:
    uri: str | None
    method: str  # "isrc", "search", "manual" or "none"
    score: float = 0.0
    candidate: SpotifyTrack | None = None  # the accepted result
    suggestion: SpotifyTrack | None = None  # best rejected result, for the report


def _query_text(text: str) -> str:
    return " ".join(text.replace('"', " ").split())


def track_queries(track: Track) -> list[str]:
    title = _query_text(strip_decorations(track.title))
    artist = _query_text(track.artists[0]) if track.artists else ""
    extra = " ".join(sorted(version_markers(track.title, track.version)))
    queries = []
    if artist:
        queries.append(f'track:"{title}" artist:"{artist}"')
    queries.append(" ".join(part for part in (title, extra, artist) if part))
    return queries


def find_track(track: Track, search: Callable[[str], list[SpotifyTrack]]) -> TrackMatch:
    best: tuple[float, SpotifyTrack] | None = None

    if track.isrc:
        isrc = track.isrc.upper()
        hits = [c for c in search(f"isrc:{isrc}") if not c.isrc or c.isrc.upper() == isrc]
        scored = sorted(((score_track(track, c), c) for c in hits), key=lambda s: -s[0])
        # The ISRC already identifies the recording; the score only guards against
        # mislabelled catalogue data.
        if scored and scored[0][0] >= SUGGEST:
            return TrackMatch(scored[0][1].uri, "isrc", scored[0][0], candidate=scored[0][1])
        if scored:
            best = scored[0]

    for query in track_queries(track):
        for candidate in search(query):
            score = score_track(track, candidate)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best and best[0] >= ACCEPT:
            return TrackMatch(best[1].uri, "search", best[0], candidate=best[1])

    if best and best[0] >= SUGGEST:
        return TrackMatch(None, "none", best[0], suggestion=best[1])
    return TrackMatch(None, "none", best[0] if best else 0.0)


def score_album(album: Album, candidate: SpotifyAlbum) -> float:
    title = similarity(core_title(album.title), core_title(candidate.name))
    artists = artist_score(album.artists, candidate.artists)
    tracks = 0.6
    if album.num_tracks and candidate.total_tracks:
        tracks = 1.0 if album.num_tracks == candidate.total_tracks else 0.3
    return title * (0.6 + 0.4 * artists) * (0.85 + 0.15 * tracks)


def find_album(album: Album, search: Callable[[str], list[SpotifyAlbum]]) -> tuple[str | None, float]:
    best: tuple[float, SpotifyAlbum] | None = None
    queries = []
    if album.upc:
        queries.append(f"upc:{album.upc}")
    title = _query_text(strip_decorations(album.title))
    artist = _query_text(album.artists[0]) if album.artists else ""
    queries.append(f'album:"{title}" artist:"{artist}"' if artist else f'album:"{title}"')
    for query in queries:
        # A UPC identifies the release, like an ISRC identifies a recording.
        threshold = SUGGEST if query.startswith("upc:") else ACCEPT
        for candidate in search(query):
            score = score_album(album, candidate)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best and best[0] >= threshold:
            return best[1].uri, best[0]
    return None, best[0] if best else 0.0


def find_artist(
    artist: Artist,
    search: Callable[[str], list[SpotifyArtist]],
    known: dict[str, str],
) -> str | None:
    """`known` maps normalized artist names to URIs seen on already matched tracks,
    which disambiguates artists that share a name."""
    wanted = normalize(artist.name)
    if wanted in known:
        return known[wanted]
    results = search(f'artist:"{_query_text(artist.name)}"')
    for candidate in results:
        if normalize(candidate.name) == wanted:
            return candidate.uri
    # Only near-identical spellings: "Nirvana" must not become "Nirvana Tribute Band".
    for candidate in results:
        if similarity(normalize(candidate.name), wanted) >= 0.9:
            return candidate.uri
    return None
