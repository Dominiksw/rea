"""Summary table and report files (Markdown summary, CSV of items not found)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .models import Album, Artist, Track, spotify_url
from .store import CSV_DELIMITER, MANUAL_HEADER
from .sync import Plan

NOT_FOUND_HEADER = [*MANUAL_HEADER, "album", "isrc", "bereich", "tidal_link", "vorschlag", "vorschlag_titel"]


def summary_rows(plan: Plan) -> list[list[str]]:
    rows = [["Bereich", "Tidal", "gefunden", "schon da", "neu", "fehlt"]]
    for s in plan.sections:
        title = s.title + (" (neu)" if s.creates_playlist else "")
        rows.append([title, str(s.total), str(s.matched), str(s.already), str(len(s.to_add)), str(s.missing)])
    return rows


def format_table(rows: list[list[str]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for n, row in enumerate(rows):
        cells = [row[0].ljust(widths[0])] + [cell.rjust(w) for cell, w in zip(row[1:], widths[1:], strict=True)]
        lines.append("  ".join(cells))
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _names(item: Track | Album | Artist) -> tuple[str, str, str, str]:
    """(titel, kuenstler, album, isrc)"""
    if isinstance(item, Track):
        return item.full_title, ", ".join(item.artists), item.album or "", item.isrc or ""
    if isinstance(item, Album):
        return item.title, ", ".join(item.artists), "", ""
    return "", item.name, "", ""


def write_reports(plan: Plan, reports_dir: Path, applied: bool) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "zusammenfassung.md"
    missing_path = reports_dir / "nicht_gefunden.csv"

    with open(missing_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=CSV_DELIMITER)
        writer.writerow(NOT_FOUND_HEADER)
        for (kind, tidal_id), entry in plan.missing.items():
            title, artists, album, isrc = _names(entry.item)
            suggestion = entry.suggestion
            writer.writerow(
                [
                    kind,
                    tidal_id,
                    "",  # spotify_link: filled in by the user in manuelle_zuordnung.csv
                    title,
                    artists,
                    album,
                    isrc,
                    " | ".join(entry.sections),
                    entry.item.tidal_url,
                    spotify_url(suggestion.uri) if suggestion else "",
                    f"{suggestion.display} ({entry.score:.0%})" if suggestion else "",
                ]
            )

    state = "übertragen" if applied else "nur abgeglichen, nichts geändert"
    lines = [
        "# Tidal → Spotify",
        "",
        f"Stand: {datetime.now():%d.%m.%Y %H:%M} ({state})",
        "",
        "```",
        format_table(summary_rows(plan)),
        "```",
        "",
        "- **gefunden**: auf Spotify gefunden",
        "- **schon da**: war bereits in deiner Spotify-Bibliothek bzw. Playlist",
        "- **neu**: " + ("wurde hinzugefügt" if applied else "wird bei der Übertragung hinzugefügt"),
        "- **fehlt**: nicht sicher gefunden, siehe `nicht_gefunden.csv`",
    ]
    by_section: dict[str, list[str]] = {}
    for entry in plan.missing.values():
        for section in entry.sections:
            line = f"- {entry.item.display}"
            if entry.suggestion:
                line += f" — Vorschlag: [{entry.suggestion.display}]({spotify_url(entry.suggestion.uri)})"
            by_section.setdefault(section, []).append(line)
    if by_section:
        lines += ["", "## Nicht gefunden"]
        for section, entries in by_section.items():
            lines += ["", f"### {section}", "", *entries]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path, missing_path
