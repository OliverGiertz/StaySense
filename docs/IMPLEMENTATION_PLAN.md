# StaySense Umsetzungsplan (MVP NRW)

## Ziel

Entscheidung in <10 Sekunden: Ist ein Spot heute Nacht (22-06) voraussichtlich ruhig?

## Scope

- Region: NRW, Pilot Kreis Mettmann
- Plattform im MVP: Web-App mit iOS-tauglichem Verhalten (Offline-Queue/Cache)
- Kein Account-System

## Architektur

- Frontend: Vanilla HTML/CSS/JS (`src/`)
- Backend: Python Standardbibliothek + SQLite (`backend/`)
- Daten: `data/staysense.db`

## API (MVP)

- `GET /spot/score?lat=..&lon=..&at=ISO8601`
  - liefert `score`, `ampel`, `reasons`, `night_window`, `meta`
- `POST /spot/signal`
  - Body: `spot_id`, `signal_type`, `device_token`, `timestamp`
  - erzwingt 1 Signal pro `(spot, device)` in 24h

## Datenpipeline

- OSM Import (Overpass):
  - Tabellen: `osm_poi`, `osm_zone`, `osm_road`
  - Script: `backend/import_osm_overpass.py`
- OpenData Connector Layer:
  - Script: `backend/open_data_connector.py`
  - Konfig: `docs/open_data_sources.json`
  - Formate: CSV + JSON
- Job Runner:
  - Script: `backend/run_import_jobs.py`
  - Modi: einmalig (`once`) oder periodisch (`daemon`)
  - Optionales Legacy-Pruning: `--prune-legacy`

## Datenmodell

- `spot`
  - Standortmetadaten inkl. OSM-Typ und Distanzmetriken
- `community_signal`
  - Signale mit `hashed_device`, ohne PII
- `open_data_event`
  - lokale Risiko-Ereignisse mit Zeitfenster
- `data_source_state`
  - Importstand/Frische je Datenquelle

## Score Engine v0.1

- Startwert: `100`
- Modifikatoren:
  - Umgebungstyp (z. B. residential -10, industrial +10)
  - Distanz zu Polizei/Krankenhaus
  - Zeitlogik (Wochenende/Feiertag -10, Werktagnacht +5)
  - lokale Events (z. B. Muellabfuhr -20)
  - Community-Signale mit Zeit-Decay (`calm`, `noise`, `knock`, `police`)
- Ausgabe:
  - Score 0-100
  - Ampel
  - Top-2 bis Top-4 Gruende
  - Source-Health in `meta.health` (Freshness/Fallback-Info)

## Datenschutz / Sicherheit

- Local device token (UUIDv4) nur auf Client
- Backend speichert nur HMAC-Hash
- Kein Fingerprinting
- Kein Login
- HTTPS-only fuer Produktion

## Naechste Schritte

1. Monitoring/Alerting fuer API und Importjobs produktiv aufsetzen
2. "Ruhigere Alternativen im Umkreis" als Quick-Action integrieren
3. Opendata-Quellen in NRW pro Kommune schrittweise erweitern

Siehe auch: `docs/ROADMAP_30_60_90.md`
