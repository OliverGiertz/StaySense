# StaySense Roadmap 30/60/90

Stand: 2026-02-16

## Priorisierung

Top-3 mit direktem Nutzwert fuer die WebApp:

1. Transparente Score-Erklaerung (Faktoren + Spot-Kontext)
2. Datenqualitaetsindikator je Score
3. Karten-UX: Standort per verschiebbarem Pin auswaehlen

## Umsetzung Top-3 (abgeschlossen)

- [x] Transparente Score-Erklaerung
  - API liefert jetzt `explanation.factors` und `explanation.spot_context`
  - Frontend zeigt Faktorenliste und Distanz-Kontext (Polizei/Feuerwehr/Krankenhaus)
- [x] Datenqualitaetsindikator
  - API liefert `meta.quality` mit `level`, `label`, `score`, `reasons`
  - Frontend zeigt Badge `hoch/mittel/niedrig`
- [x] Karten-UX verbessert
  - Marker als verschiebbarer Pin (drag & drop)
  - Koordinatenfeld wird beim Verschieben sofort aktualisiert

## 0-30 Tage

- Monitoring fuer API/Import (Uptime, Error-Rate, Alarmierung)
- Score-Engine Observability:
  - Logging fuer degradierte Scores und Fallback-Nutzung
- Admin UX:
  - Filter fuer Events/Signals nach Zeitraum
  - Bessere Fehlermeldungen je API-Error

## 31-60 Tage

- "Alternativen in der Naehe" (ruhigere Spots im Radius)
- Community-Signale erweitern:
  - optionale Strukturfelder (z. B. Intensitaet, Dauer)
- Opendata-Quellen NRW ausbauen:
  - weitere Kommunen fuer Events/Baustellen

## 61-90 Tage

- Persistenter Betrieb auf PostgreSQL (optional PostGIS)
- Anomalie-Erkennung gegen Signal-Missbrauch
- Exportierbare API-Doku (OpenAPI) und versionierte API (`/v1`)

