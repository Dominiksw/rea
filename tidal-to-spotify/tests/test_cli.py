import json

from tidal2spotify import cli
from tidal2spotify.models import Library, Playlist, Track

from .fakes import FakeSpotify, sp_track


def export_file(tmp_path):
    library = Library(
        favorite_tracks=[Track("1", "Alpha", ("Band",), duration=200, isrc="ISRC-A")],
        playlists=[
            Playlist("p1", "Mine", tracks=[Track("1", "Alpha", ("Band",), duration=200, isrc="ISRC-A")]),
            Playlist("p2", "Tidal Mix", owned=False, tracks=[Track("9", "Nope", ("X",))]),
        ],
    )
    path = tmp_path / "export.json"
    path.write_text(json.dumps(library.to_json()), encoding="utf-8")
    return path


def test_compare_then_transfer_from_export(tmp_path, monkeypatch, capsys):
    spotify = FakeSpotify([sp_track("Alpha", "Band", isrc="ISRC-A")])
    monkeypatch.setattr(cli.SpotifyTarget, "connect", classmethod(lambda cls, *a: spotify))
    data = ["--data-dir", str(tmp_path / "data"), "--spotify-client-id", "cid"]
    path = export_file(tmp_path)

    assert cli.main([*data, "compare", "--from-export", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Playlist „Mine“ (neu)" in out and "Tidal Mix" not in out
    assert spotify.writes == []

    assert cli.main([*data, "transfer", "--from-export", str(path), "--yes"]) == 0
    assert [w[0] for w in spotify.writes] == ["save_tracks", "create", "add"]
    assert "Fertig" in capsys.readouterr().out

    assert cli.main([*data, "transfer", "--from-export", str(path), "--yes", "--with-followed-playlists"]) == 0
    assert "Tidal Mix" in capsys.readouterr().out
    assert [w[1] for w in spotify.writes if w[0] == "create"] == ["Mine", "Tidal Mix"]


def test_unknown_playlist_name_is_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.SpotifyTarget, "connect", classmethod(lambda cls, *a: FakeSpotify()))
    code = cli.main(
        ["--data-dir", str(tmp_path), "--spotify-client-id", "c", "compare", "--from-export",
         str(export_file(tmp_path)), "--playlist", "Gibt es nicht"]
    )  # fmt: skip
    assert code == 1
    assert "Gibt es nicht" in capsys.readouterr().out


def test_premium_error_is_explained(tmp_path, monkeypatch, capsys):
    from spotipy.exceptions import SpotifyException

    def refuse(cls, *a):
        raise SpotifyException(403, -1, "Active premium subscription required for the owner of the app.")

    monkeypatch.setattr(cli.SpotifyTarget, "connect", classmethod(refuse))
    data = ["--data-dir", str(tmp_path), "--spotify-client-id", "c"]
    code = cli.main([*data, "compare", "--from-export", str(export_file(tmp_path))])
    assert code == 1
    assert "Premium" in capsys.readouterr().out


class FakeTidal:
    def __init__(self, library):
        self.library = library
        self.fetches = []

    def account_name(self):
        return "tidal-user"

    def fetch(self, parts, include_followed, progress):
        self.fetches.append((parts, include_followed))
        return self.library


def test_assistant_backs_up_compares_and_transfers_after_confirmation(tmp_path, monkeypatch, capsys):
    library = Library.from_json(json.loads(export_file(tmp_path).read_text(encoding="utf-8")))
    spotify = FakeSpotify([sp_track("Alpha", "Band", isrc="ISRC-A")])
    tidal = FakeTidal(library)
    monkeypatch.setattr(cli.SpotifyTarget, "connect", classmethod(lambda cls, *a: spotify))
    monkeypatch.setattr(cli.TidalSource, "connect", classmethod(lambda cls, *a: tidal))
    answers = iter(["my-client-id", "n", ""])  # client id, followed playlists: no, transfer: default yes
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert cli.main(["--data-dir", str(tmp_path / "data")]) == 0

    out = capsys.readouterr().out
    assert "developer.spotify.com/dashboard" in out and "http://127.0.0.1:8888/callback" in out
    assert json.loads((tmp_path / "data" / "config.json").read_text())["spotify_client_id"] == "my-client-id"
    assert Library.from_json(json.loads((tmp_path / "data" / "tidal_bibliothek.json").read_text())) == library
    assert tidal.fetches == [({"songs", "playlists", "albums", "artists"}, True)]
    assert [w[1] for w in spotify.writes if w[0] == "create"] == ["Mine"]
    assert (tmp_path / "data" / "berichte" / "zusammenfassung.md").exists()
