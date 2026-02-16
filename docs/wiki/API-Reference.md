# API Reference

Base URL:

`https://staysense.vanityontour.de/api`

## GET /health

System- und Datenquellenstatus.

Beispiel:

```bash
curl -s https://staysense.vanityontour.de/api/health
```

## GET /spot/score

Query:
- `lat` (float)
- `lon` (float)
- `at` (ISO-8601, z. B. `2026-02-16T22:30:00Z`)

Antwort enthält u. a.:
- `score` (0-100)
- `ampel` (`green|yellow|red`)
- `reasons`
- `factors`
- `explanation.factors` (transparente Details)
- `explanation.spot_context` (Umfeld-Distanzen)
- `meta.quality` (Datenqualität)

Beispiel:

```bash
curl -s "https://staysense.vanityontour.de/api/spot/score?lat=51.10893&lon=6.90460&at=2026-02-16T22:30:00Z"
```

## POST /spot/signal

Body:
- `spot_id`
- `signal_type` (`calm|noise|knock|police`)
- `device_token`
- `timestamp` (ISO-8601)

Beispiel:

```bash
curl -s -X POST https://staysense.vanityontour.de/api/spot/signal \
  -H "Content-Type: application/json" \
  -d '{
    "spot_id":"2a227634-683d-54e9-8a4b-32d434251380",
    "signal_type":"noise",
    "device_token":"550e8400-e29b-41d4-a716-446655440000",
    "timestamp":"2026-02-16T22:35:00Z"
  }'
```

Hinweis:
- Cooldown aktiv (pro Spot/Device nur 1 Signal pro 24h); bei Verstoß: `429`.

## GET /geocode/search

Query:
- `q` (Suchtext)

Beispiel:

```bash
curl -s "https://staysense.vanityontour.de/api/geocode/search?q=Hilden"
```

## GET /map/tile/{z}/{x}/{y}.png

Proxy für OSM-Tiles (für die Web-Karte).
