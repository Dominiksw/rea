# tidal2spotify – Umzug von Tidal zu Spotify

Gleicht deine Tidal-Bibliothek mit Spotify ab und überträgt alles, was auf Spotify noch fehlt:

| Tidal | → Spotify |
| --- | --- |
| Lieblingssongs (Meine Sammlung → Titel) | „Lieblingssongs“, in derselben Reihenfolge |
| eigene Playlists | neue (private) Playlists mit gleichem Namen, gleicher Reihenfolge und Beschreibung |
| Playlists, denen du folgst (optional) | Kopien als eigene Playlists |
| Lieblingsalben | gespeicherte Alben |
| Lieblingskünstler | gefolgte Künstler |

- **Abgleich statt Kopie:** Es wird nur hinzugefügt, was fehlt. Du kannst die App beliebig oft
  laufen lassen – z. B. nachdem du auf Tidal noch Songs hinzugefügt hast.
- **Löscht nie etwas** auf Spotify und ändert keine bestehende Reihenfolge.
- **Bericht** über alles, was nicht (sicher) gefunden wurde, inkl. Vorschlägen – und du kannst
  solche Songs per Spotify-Link selbst zuordnen.
- **Sicherung** deiner Tidal-Bibliothek als JSON-Datei. Damit kannst du auch nach der
  Tidal-Kündigung noch übertragen.

## Voraussetzungen

- **Python 3.10 oder neuer** ([python.org](https://www.python.org/downloads/); unter Windows bei
  der Installation „Add python.exe to PATH“ anhaken).
- **Spotify Premium.** Seit Februar 2026 funktionieren selbst angelegte Spotify-Apps nur, wenn
  der Besitzer der App ein aktives Premium-Abo hat.
- Dein **Tidal-Konto** muss beim ersten Lauf noch aktiv sein (oder du hast vorher exportiert).

## 1. Spotify-App anlegen (einmalig, ca. 3 Minuten)

Spotify lässt Programme nur über eine eigene „App“ auf dein Konto zugreifen. Die ist kostenlos:

1. Öffne <https://developer.spotify.com/dashboard> und melde dich mit deinem Spotify-Konto an
   (beim ersten Mal die Nutzungsbedingungen akzeptieren).
2. Klicke **Create app**:
   - *App name* / *App description*: beliebig, z. B. „Tidal Umzug“
   - *Redirect URIs*: genau `http://127.0.0.1:8888/callback` eintragen und **Add** klicken
   - bei *Which API/SDKs are you planning to use?* **Web API** ankreuzen
   - Bedingungen akzeptieren, **Save**
3. In der App unter **Settings** die **Client ID** kopieren. (Das Client Secret brauchst du nicht.)

Meldest du dich später mit einem *anderen* Spotify-Konto an als dem, mit dem du die App angelegt
hast, trage dieses Konto in der App unter **User Management** ein.

## 2. Installieren

Im Ordner `tidal-to-spotify` ein Terminal öffnen (Windows: „Eingabeaufforderung“ oder
„PowerShell“) und ausführen:

```bash
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install .
```

(Unter macOS/Linux ggf. `python3` statt `python`.) Bei späteren Starts nur die Zeile zum
Aktivieren wiederholen.

## 3. Starten

```bash
tidal2spotify
```

Der Assistent führt dich durch alles:

1. fragt einmalig nach deiner Spotify **Client ID**,
2. **Tidal-Anmeldung:** zeigt einen Link `link.tidal.com/…` – öffnen, bei Tidal anmelden,
   bestätigen; danach geht es automatisch weiter,
3. **Spotify-Anmeldung:** öffnet den Browser, dort „Zustimmen“ klicken,
4. liest deine Tidal-Bibliothek und **sichert** sie als `tidal_bibliothek.json`,
5. fragt, ob auch Playlists übernommen werden sollen, denen du auf Tidal nur folgst,
6. **gleicht ab** und zeigt eine Übersicht, z. B.:

   ```
   Bereich                    Tidal  gefunden  schon da  neu  fehlt
   -------------------------  -----  --------  --------  ---  -----
   Lieblingssongs              1243      1221         0  1221     22
   Playlist „Sommer“ (neu)       87        86         0    86      1
   Alben                         54        53         0    53      1
   Künstler                      71        71         0    71      0
   ```

7. fragt **„Jetzt zu Spotify übertragen?“** – erst dann wird etwas geändert.

Bei großen Bibliotheken dauert die Suche eine Weile (pro Song mindestens eine Anfrage an
Spotify). Meldet Spotify ein Anfrage-Limit, wartet die App automatisch und macht dann weiter. Du kannst jederzeit mit **Strg+C**
abbrechen: Bereits gefundene Songs sind gespeichert, der nächste Start macht dort weiter.

Die Anmeldungen werden gespeichert; beim nächsten Start musst du dich nicht erneut anmelden.

## Nicht gefundene Songs

Nach jedem Lauf liegen im Arbeitsordner (Standard: `tidal2spotify` in deinem Benutzerordner):

- `berichte/zusammenfassung.md` – Übersicht und Liste aller nicht gefundenen Einträge
- `berichte/nicht_gefunden.csv` – dieselbe Liste als Tabelle (öffnet sich in Excel),
  mit Tidal-Link und – falls vorhanden – einem **Vorschlag** von Spotify

So ordnest du einen Song selbst zu:

1. Song in Spotify suchen → „Teilen“ → „Link zum Song kopieren“.
2. `manuelle_zuordnung.csv` im Arbeitsordner öffnen, die Zeile des Songs aus
   `nicht_gefunden.csv` hineinkopieren (wichtig sind die Spalten `typ` und `tidal_id`) und den
   Link in die Spalte `spotify_link` einfügen. Passt der Vorschlag, kannst du auch einfach den
   Link aus der Spalte `vorschlag` übernehmen.
3. `tidal2spotify` erneut starten – es wird nur noch das Fehlende ergänzt.

Das funktioniert genauso für Alben (`typ` = `album`) und Künstler (`typ` = `kuenstler`).

## Einzelne Befehle

Für mehr Kontrolle statt des Assistenten:

| Befehl | Was passiert |
| --- | --- |
| `tidal2spotify login` | nur bei Tidal und Spotify anmelden |
| `tidal2spotify export` | Tidal-Bibliothek sichern (`--output DATEI` für einen anderen Ort) |
| `tidal2spotify compare` | abgleichen und Bericht schreiben, **ohne** etwas zu ändern |
| `tidal2spotify transfer` | abgleichen und nach Rückfrage übertragen |

Optionen für `compare` und `transfer`:

| Option | Bedeutung |
| --- | --- |
| `--only songs\|playlists\|albums\|artists` | nur diesen Bereich (mehrfach möglich) |
| `--playlist "Name"` | nur diese Playlist (mehrfach möglich) |
| `--with-followed-playlists` | auch Playlists, denen du auf Tidal nur folgst |
| `--from-export DATEI` | statt Tidal live eine Sicherung verwenden, z. B. nach der Kündigung |
| `--retry-not-found` | bisher nicht gefundene Songs erneut suchen |
| `--public` | (nur `transfer`) neue Playlists öffentlich anlegen |
| `-y`, `--yes` | (nur `transfer`) ohne Rückfrage übertragen |

Allgemein: `--data-dir ORDNER` wählt einen anderen Arbeitsordner (alternativ Umgebungsvariable
`TIDAL2SPOTIFY_DIR`), `--spotify-client-id ID` setzt die Client ID (alternativ
`SPOTIFY_CLIENT_ID`). Eine andere Redirect URI lässt sich mit `SPOTIFY_REDIRECT_URI` setzen.

Beispiel – nach der Tidal-Kündigung nur die Playlist „Sommer“ aus der Sicherung übertragen:

```bash
tidal2spotify transfer --from-export ~/tidal2spotify/tidal_bibliothek.json --playlist "Sommer"
```

## Wie werden Songs gefunden?

1. Über den **ISRC** – eine weltweit eindeutige Kennung jeder Aufnahme, die Tidal und Spotify
   gemeinsam haben. So wird genau dieselbe Aufnahme gefunden.
2. Sonst per Suche nach Titel und Künstler. Ein Treffer wird nur übernommen, wenn Titel,
   Künstler und Länge zusammenpassen. Live-, Remix-, Akustik- oder Instrumental-Versionen werden
   nicht mit der Studioversion verwechselt; „Remastered“ und Ähnliches zählt dagegen als derselbe
   Song.
3. Knappe Treffer werden nicht automatisch übernommen, sondern im Bericht als Vorschlag gezeigt.

Alben werden über ihren Barcode (UPC) bzw. Titel und Künstler gesucht, Künstler bevorzugt über
die Künstler der bereits gefundenen Songs (damit bei gleichnamigen Künstlern der richtige gewählt
wird).

## Dateien im Arbeitsordner

| Datei | Inhalt |
| --- | --- |
| `config.json` | deine Spotify Client ID |
| `tidal-login.json`, `spotify-login.json` | gespeicherte Anmeldungen – **nicht weitergeben** |
| `tidal_bibliothek.json` | Sicherung deiner Tidal-Bibliothek |
| `treffer-cache.json` | bereits gefundene Spotify-Treffer (macht erneute Läufe schnell) |
| `playlist-zuordnung.json` | welche Tidal-Playlist zu welcher Spotify-Playlist gehört |
| `manuelle_zuordnung.csv` | deine eigenen Zuordnungen |
| `berichte/` | Zusammenfassung und Liste der nicht gefundenen Einträge |

Zum Abmelden die beiden `…-login.json` löschen. Den Zugriff der App auf dein Spotify-Konto kannst
du außerdem unter <https://www.spotify.com/account/apps/> entziehen.

## Gut zu wissen

- **Videos** in Tidal-Playlists werden übersprungen (Spotify-Playlists enthalten keine Videos).
- **Tidal-Ordner** gibt es auf Spotify über die Schnittstelle nicht; alle Playlists landen
  einzeln in deiner Bibliothek.
- Gibt es auf Spotify schon eine **eigene Playlist mit exakt gleichem Namen**, wird sie
  ergänzt statt eine zweite anzulegen. Die Übersicht zeigt neue Playlists mit „(neu)“.
- Spotify sortiert „Lieblingssongs“ nach Hinzufügedatum. Die Songs werden in deiner
  Tidal-Reihenfolge übertragen, aber in Paketen zu je 40 – innerhalb eines Pakets kann die
  Reihenfolge leicht abweichen.
- Für Tidal wird die inoffizielle Bibliothek [`tidalapi`](https://github.com/EbbLabs/python-tidal)
  verwendet (Anmeldung über die offizielle Tidal-Geräteanmeldung).

## Für Entwickler

```bash
pip install -e ".[test]"
pytest
```
