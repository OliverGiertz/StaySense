# StaySense (MVP NRW)

StaySense bewertet fuer die Nacht (22:00-06:00) die voraussichtliche Ruhe eines Spots in NRW (Pilot: Kreis Mettmann).

## MVP Status

Implementiert:
- Night Safety Score (0-100) mit Ampel (`green`, `yellow`, `red`)
- Begruendung mit Top-Faktoren (OSM-Typ, Distanz-POIs, Zeitlogik, Events, Community)
- API: `GET /spot/score`, `POST /spot/signal`
- Kartenwahl via OpenStreetMap (Leaflet), inkl. Klickauswahl und Ortssuche
- API: `GET /geocode/search` (Nominatim-Proxy), `GET /map/tile/{z}/{x}/{y}.png` (OSM-Tile-Proxy)
- Admin-Bereich (Setup/Login, geschuetzt per User/Passwort + Session-Token)
- Admin-API fuer Uebersicht und Event-Verwaltung (`/admin/*`)
- Anti-Spam ohne Account: lokaler Token + serverseitiger HMAC-Hash
- Quick Decision UI mit Signal-Buttons
- Offline-First im Frontend: Score-Cache + Signal-Queue
- Echter OSM-Import via Overpass (POIs, Landuse-Zonen, Highway-Typen)
- OpenData-Connectoren (CSV/JSON aus URL oder Datei)
- Automatischer Import-Job-Runner (`once` oder `daemon`)

Nicht im MVP:
- Accounts/Login
- Chat/Kommentare
- Stellplatz-Portal
- Routenplanung

## Start

1. Datenbank initialisieren:
   - `cd StaySense/backend`
   - `python3 -c "from db import init_db; init_db()"`
2. OSM importieren (Pilot-BBox Mettmann):
   - `python3 import_osm_overpass.py`
3. OpenData-Connectoren aus Konfig ausfuehren:
   - `python3 run_import_jobs.py --config ../docs/open_data_sources.json --prune-legacy`
4. Optional: periodische Imports (alle 6h) inkl. OSM:
   - `python3 run_import_jobs.py --config ../docs/open_data_sources.json --with-osm --prune-legacy --daemon --interval-seconds 21600`
5. API starten:
   - `python3 server.py`
6. Frontend starten (zweites Terminal):
   - `cd ../src`
   - `python3 -m http.server 8080`
7. App oeffnen:
   - `http://localhost:8080`

## OpenData Connector Config

Datei: `docs/open_data_sources.json`

- `enabled`: Quelle aktivieren/deaktivieren
- `format`: `csv` oder `json`
- `url` oder `file`: Quelle
- `field_map`: Mapping auf StaySense-Felder
- `event_type_map`: optionale Typ-Normalisierung
- `json_path`: Pfad auf Array bei JSON-Feeds
- Validierung aktiv:
  - Koordinaten muessen in DE-Bounds liegen
  - `start_datetime < end_datetime`
  - Event-Typ muss auf `market|waste|event|construction` normalisiert werden

## Tests

- Backend Unit-Tests:
  - `cd StaySense/backend`
  - `python3 -m unittest discover -s tests -p \"test_*.py\"`

## API Beispiele

Score holen:
- `curl "http://127.0.0.1:8787/spot/score?lat=51.25&lon=6.97&at=2026-02-15T20:00:00Z"`

Signal senden:
- `curl -X POST "http://127.0.0.1:8787/spot/signal" -H "Content-Type: application/json" -d '{"spot_id":"<ID>","signal_type":"noise","device_token":"<uuid-v4>","timestamp":"2026-02-15T20:15:00Z"}'`

Ortssuche:
- `curl "http://127.0.0.1:8787/geocode/search?q=Mettmann%20Bahnhof"`

Tile-Proxy:
- `curl -I "http://127.0.0.1:8787/map/tile/12/2149/1387.png"`

Admin-Setup (nur beim ersten Start):
- `curl -X POST "http://127.0.0.1:8787/admin/bootstrap" -H "Content-Type: application/json" -d '{"username":"admin","password":"<starkes-passwort>"}'`

## DSGVO-Hinweise im MVP

- Kein Login
- Keine IP-Speicherung in der Anwendung
- Kein Device Fingerprinting
- Missbrauchsschutz nur ueber `hashed_device = HMAC_SHA256(device_token, server_salt)`

## Produktion

- `STAYSENSE_SERVER_SALT` zwingend als geheimes Env setzen
- HTTPS-only bereitstellen
- OpenStreetMap-/Open-Data-Attribution in App verpflichtend sichtbar halten

## Doku Uebersicht

- Architektur / Umsetzung: `docs/IMPLEMENTATION_PLAN.md`
- Server-Deployment (Linux + Nginx + systemd): `docs/DEPLOYMENT.md`
- CloudPanel-Setup (Hetzner): `docs/CLOUDPANEL_SETUP.md`
- Betrieb / Runbook: `docs/OPERATIONS.md`
- GitHub Publish Ablauf: `docs/GITHUB_PUBLISH.md`
- Connector-Konfiguration: `docs/open_data_sources.json`
- Event-Template: `docs/open_data_events_template.csv`
