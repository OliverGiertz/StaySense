# StaySense Wiki

StaySense bewertet in weniger als 10 Sekunden, wie ruhig ein Spot in der Nacht (22:00-06:00) voraussichtlich ist.

## Produktstatus

- Region: NRW (Pilot: Kreis Mettmann)
- Plattform: WebApp / PWA (iOS-optimiert)
- API + Admin-Bereich: aktiv
- Offline-First: Score-Cache + Signal-Queue

## Schnellstart

1. API Health prüfen: `GET /api/health`
2. Score laden: `GET /api/spot/score?lat=...&lon=...&at=...`
3. Community-Signal senden: `POST /api/spot/signal`
4. Admin Login: `POST /api/admin/login`

## Dokumentation

- [API Reference](API-Reference)
- [Admin API](Admin-API)
- [Deployment](Deployment)
- [Operations Runbook](Operations-Runbook)
- [Roadmap 30-60-90](Roadmap-30-60-90)
- [Data Sources & Attribution](Data-Sources-and-Attribution)

## Wichtige Links

- WebApp: `https://staysense.vanityontour.de`
- API Base: `https://staysense.vanityontour.de/api`
- Repository: `https://github.com/OliverGiertz/StaySense`
