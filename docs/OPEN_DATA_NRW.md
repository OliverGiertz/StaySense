# OpenData NRW Quellen (StaySense)

Diese Datei beschreibt die aktuell integrierten externen OpenData-Quellen fuer den MVP.

## Aktiv integrierbare Quellen

1. Verkehrsbeeintraechtigungen Stadt Koeln (JSON / ArcGIS)
- Herkunft: Offene Daten Koeln / Open.NRW
- Lizenz: Datenlizenz Deutschland Zero 2.0
- Datensatzseite:
  - `https://offenedaten-koeln.de/dataset/verkehrsbeeintr%C3%A4chtigungen-stadt-k%C3%B6ln`
- API-Endpoint:
  - `https://geoportal.stadt-koeln.de/arcgis/rest/services/verkehr/verkehrskalender/MapServer/0/query?where=objectid%20is%20not%20null&outFields=*&returnGeometry=true&outSR=4326&f=pjson`

2. Baustellen Notfall Stadt Koeln (WFS / GeoJSON)
- Herkunft: Offene Daten Koeln / Open.NRW
- Lizenz: Datenlizenz Deutschland Zero 2.0
- Datensatzseite:
  - `https://offenedaten-koeln.de/dataset/baustellen-k%C3%B6ln`
- API-Endpoint:
  - `https://geoportal.stadt-koeln.de/wss/service/baustellen_wfs/guest?service=WFS&version=1.1.0&request=GetFeature&typeName=ms:notfall&outputFormat=application/json;%20subtype=geojson`

## Nutzung im Projekt

- Konfiguration:
  - `docs/open_data_sources_nrw_live.json`
- Import ausfuehren:
  - `cd StaySense/backend`
  - `python3 run_import_jobs.py --config ../docs/open_data_sources_nrw_live.json --prune-legacy`

## Technische Hinweise

- ArcGIS-Quellen liefern teils Datumswerte als Unix-Zeitstempel (Millisekunden). Der Connector normalisiert diese automatisch auf ISO8601 UTC.
- WFS-Baustellen liefern Koordinaten in EPSG:25832. Der Connector transformiert diese fuer StaySense auf WGS84 (lat/lon).
- Datumsbereich aus WFS (`Genehmigungs-Zeitraum`) wird per `date_range`-Mapping in Start/Ende aufgeteilt.
