"""Command line: a guided assistant (no arguments) plus login/export/compare/transfer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .matching import normalize
from .models import Library
from .report import format_table, summary_rows, write_reports
from .spotify_target import DEFAULT_REDIRECT_URI, SpotifyTarget
from .store import Store, default_data_dir, read_json, write_json
from .sync import ALL_PARTS, Matcher, apply_plan, build_plan
from .tidal_source import TidalSource

DASHBOARD = "https://developer.spotify.com/dashboard"


def say(text: str = "") -> None:
    print(text, flush=True)


def ask_yes_no(question: str, default: bool = False) -> bool:
    hint = "[J/n]" if default else "[j/N]"
    while True:
        answer = input(f"{question} {hint} ").strip().lower()
        if not answer:
            return default
        if answer in ("j", "ja", "y", "yes"):
            return True
        if answer in ("n", "nein", "no"):
            return False


# -- connections ---------------------------------------------------------------


def spotify_client_id(store: Store, given: str | None, interactive: bool) -> str:
    client_id = given or os.environ.get("SPOTIFY_CLIENT_ID") or store.config.get("spotify_client_id")
    if client_id:
        if given and given != store.config.get("spotify_client_id"):
            store.config["spotify_client_id"] = given
            store.save_config()
        return client_id
    if not interactive:
        raise SystemExit(
            "Keine Spotify Client-ID. Übergib --spotify-client-id oder setze SPOTIFY_CLIENT_ID "
            "(Anleitung: README.md, Abschnitt „Spotify-App anlegen“)."
        )
    redirect = redirect_uri(store)
    say("Für den Zugriff auf Spotify brauchst du eine eigene (kostenlose) Spotify-App:")
    say(f"  1. Öffne {DASHBOARD} und melde dich mit deinem Spotify-Konto an.")
    say("  2. „Create app“: Name beliebig, bei „Redirect URIs“ genau diese Adresse eintragen:")
    say(f"       {redirect}")
    say("     und bei „Which API/SDKs are you planning to use?“ „Web API“ ankreuzen.")
    say("  3. Die „Client ID“ der App kopieren und hier einfügen.")
    while not client_id:
        client_id = input("Spotify Client ID: ").strip()
    store.config["spotify_client_id"] = client_id
    store.save_config()
    return client_id


def redirect_uri(store: Store) -> str:
    return os.environ.get("SPOTIFY_REDIRECT_URI") or store.config.get("spotify_redirect_uri") or DEFAULT_REDIRECT_URI


def connect_spotify(store: Store, client_id: str) -> SpotifyTarget:
    say("Spotify: Anmeldung im Browser (beim ersten Mal) …")
    target = SpotifyTarget.connect(client_id, redirect_uri(store), store.spotify_token_path)
    say(f"Spotify: angemeldet als {target.display_name()}")
    return target


def connect_tidal(store: Store) -> TidalSource:
    say("Tidal: Anmeldung …")

    def show(text: str) -> None:
        say(f"  {text}")
        if "link.tidal.com" in text:
            say("  Öffne den Link, melde dich bei Tidal an und bestätige. Danach geht es hier automatisch weiter.")

    source = TidalSource.connect(store.tidal_session_path, show)
    say(f"Tidal: angemeldet als {source.account_name()}")
    return source


# -- library -------------------------------------------------------------------


def load_export(path: Path) -> Library:
    try:
        return Library.from_json(read_json(path, None) or {})
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Export {path} kann nicht gelesen werden: {error}") from error


def fetch_library(source: TidalSource, parts: set[str], include_followed: bool) -> Library:
    say("Lese deine Tidal-Bibliothek …")
    return source.fetch(parts, include_followed, say)


def save_export(store: Store, library: Library) -> None:
    write_json(store.export_path, library.to_json())
    say(f"Sicherung der Tidal-Bibliothek: {store.export_path}")


def only_selected(library: Library, include_followed: bool) -> Library:
    return replace(library, playlists=[p for p in library.playlists if p.owned or include_followed])


def describe_library(library: Library) -> None:
    owned = sum(p.owned for p in library.playlists)
    say(
        f"Tidal: {len(library.favorite_tracks)} Lieblingssongs, {owned} eigene Playlists"
        + (f" (+{len(library.playlists) - owned} gefolgte)" if len(library.playlists) > owned else "")
        + f", {len(library.albums)} Alben, {len(library.artists)} Künstler"
    )
    videos = sum(p.skipped_videos for p in library.playlists)
    if videos:
        say(f"Hinweis: {videos} Videos in Playlists werden übersprungen (Spotify-Playlists enthalten keine Videos).")


# -- compare / transfer ----------------------------------------------------------


def compare_and_maybe_transfer(
    store: Store,
    spotify: SpotifyTarget,
    library: Library,
    parts: set[str],
    playlist_names: list[str],
    retry_not_found: bool,
    transfer: bool,
    confirm: bool,
    public: bool,
) -> int:
    if playlist_names:
        known = {normalize(p.name) for p in library.playlists}
        unknown = [n for n in playlist_names if normalize(n) not in known]
        if unknown:
            say("Diese Playlists gibt es in der Tidal-Bibliothek nicht: " + ", ".join(unknown))
            return 1
    for problem in store.manual_errors:
        say(f"Warnung: {problem}")

    matcher = Matcher(spotify, store, retry_not_found=retry_not_found)
    plan = build_plan(library, spotify, matcher, parts, say, playlist_names)
    say()
    say(format_table(summary_rows(plan)))
    say()
    summary, missing = write_reports(plan, store.reports_dir, applied=False)
    say(f"Bericht: {summary}")
    if plan.missing:
        say(f"Nicht gefunden ({len(plan.missing)}): {missing}")
        say(f"  Fehlende Songs kannst du in {store.manual_path} selbst zuordnen (siehe README).")

    if not transfer:
        return 0
    if not plan.has_changes:
        say("Spotify ist bereits auf dem Stand von Tidal – nichts zu übertragen.")
        return 0
    if confirm and not ask_yes_no("Jetzt zu Spotify übertragen? Es wird nichts gelöscht.", default=True):
        say("Nichts übertragen.")
        return 0
    apply_plan(plan, spotify, store, public, say)
    write_reports(plan, store.reports_dir, applied=True)
    say("Fertig! Alles Gefundene ist jetzt auf Spotify.")
    return 0


def assistant(store: Store, args: argparse.Namespace) -> int:
    say(f"tidal2spotify {__version__} – Umzug von Tidal zu Spotify")
    say(f"Arbeitsordner: {store.dir}")
    say()
    client_id = spotify_client_id(store, args.spotify_client_id, interactive=True)
    tidal = connect_tidal(store)
    spotify = connect_spotify(store, client_id)
    say()
    library = fetch_library(tidal, set(ALL_PARTS), include_followed=True)
    save_export(store, library)
    describe_library(library)
    followed = len(library.playlists) - sum(p.owned for p in library.playlists)
    include_followed = followed > 0 and ask_yes_no(
        f"Auch die {followed} Playlists übernehmen, denen du auf Tidal nur folgst (von Tidal/anderen erstellt)?"
    )
    say()
    return compare_and_maybe_transfer(
        store,
        spotify,
        only_selected(library, include_followed),
        set(ALL_PARTS),
        [],
        retry_not_found=False,
        transfer=True,
        confirm=True,
        public=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidal2spotify",
        description="Gleicht Lieblingssongs, Playlists, Alben und Künstler von Tidal mit Spotify ab "
        "und überträgt, was auf Spotify noch fehlt. Ohne Befehl startet ein Assistent.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="Arbeitsordner (Standard: ~/tidal2spotify)")
    parser.add_argument("--spotify-client-id", help="Client ID deiner Spotify-App (wird gespeichert)")
    sub = parser.add_subparsers(dest="command", metavar="BEFEHL")

    sub.add_parser("login", help="bei Tidal und Spotify anmelden")
    export = sub.add_parser("export", help="Tidal-Bibliothek als JSON sichern")
    export.add_argument("--output", type=Path, metavar="DATEI", help="Zieldatei (Standard: im Arbeitsordner)")

    for name, text in (
        ("compare", "abgleichen, ohne etwas zu ändern (schreibt einen Bericht)"),
        ("transfer", "abgleichen und Fehlendes zu Spotify übertragen"),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument(
            "--from-export", type=Path, metavar="DATEI", help="Tidal-Export statt Live-Daten von Tidal verwenden"
        )
        command.add_argument(
            "--only", action="append", choices=ALL_PARTS, help="nur diesen Bereich (mehrfach möglich)"
        )
        command.add_argument("--playlist", action="append", default=[], metavar="NAME", help="nur diese Playlist")
        command.add_argument(
            "--with-followed-playlists",
            action="store_true",
            help="auch Playlists, denen du auf Tidal nur folgst",
        )
        command.add_argument(
            "--retry-not-found", action="store_true", help="bisher nicht gefundene Songs erneut suchen"
        )
        if name == "transfer":
            command.add_argument("--public", action="store_true", help="neue Playlists öffentlich anlegen")
            command.add_argument("-y", "--yes", action="store_true", help="ohne Rückfrage übertragen")
    return parser


def run(args: argparse.Namespace) -> int:
    store = Store(args.data_dir or default_data_dir())
    interactive = sys.stdin.isatty()

    if args.command is None:
        return assistant(store, args)

    if args.command == "login":
        connect_tidal(store)
        connect_spotify(store, spotify_client_id(store, args.spotify_client_id, interactive))
        return 0

    if args.command == "export":
        library = fetch_library(connect_tidal(store), set(ALL_PARTS), include_followed=True)
        if args.output:
            write_json(args.output, library.to_json())
            say(f"Gespeichert: {args.output}")
        else:
            save_export(store, library)
        describe_library(library)
        return 0

    parts = set(args.only or ALL_PARTS)
    if args.playlist:
        parts.add("playlists")
    if args.from_export:
        library = load_export(args.from_export)
    else:
        library = fetch_library(connect_tidal(store), parts, args.with_followed_playlists)
    library = only_selected(library, args.with_followed_playlists)
    describe_library(library)
    spotify = connect_spotify(store, spotify_client_id(store, args.spotify_client_id, interactive))
    transfer = args.command == "transfer"
    return compare_and_maybe_transfer(
        store,
        spotify,
        library,
        parts,
        args.playlist,
        retry_not_found=args.retry_not_found,
        transfer=transfer,
        confirm=transfer and not args.yes,
        public=transfer and args.public,
    )


def explain_spotify_error(error: Exception) -> str:
    text = str(error)
    status = getattr(error, "http_status", None)
    if status == 403 and "premium" in text.lower():
        return (
            "Spotify verlangt seit 2026 ein aktives Premium-Abo für den Besitzer der Spotify-App "
            f"(das Konto, mit dem du sie unter {DASHBOARD} angelegt hast)."
        )
    if status == 403:
        return (
            "Spotify verweigert den Zugriff. Wenn du dich mit einem anderen Spotify-Konto anmeldest als dem, "
            f"das die App besitzt: trage es unter {DASHBOARD} → deine App → „User Management“ ein."
        )
    if "invalid_client" in text.lower() or "redirect uri" in text.lower():
        return f"Client ID oder Redirect URI stimmen nicht mit deiner App unter {DASHBOARD} überein."
    return text


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        say("\nAbgebrochen. Bereits gefundene Treffer sind gespeichert; ein neuer Lauf macht dort weiter.")
        return 130
    except Exception as error:  # noqa: BLE001 - show a readable message instead of a traceback
        from spotipy.exceptions import SpotifyBaseException

        if isinstance(error, SpotifyBaseException):
            say(f"Spotify-Fehler: {explain_spotify_error(error)}")
            return 1
        if os.environ.get("TIDAL2SPOTIFY_DEBUG"):
            raise
        say(f"Fehler: {error}")
        say("(Für Details: TIDAL2SPOTIFY_DEBUG=1 setzen und erneut starten.)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
