# Admin API

Alle Admin-Endpunkte benötigen einen Bearer Token, außer Bootstrap Status/Login.

Base URL:

`https://staysense.vanityontour.de/api`

## Token erhalten

```bash
curl -s -X POST https://staysense.vanityontour.de/api/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"DEIN_USER","password":"DEIN_PASSWORT"}'
```

Token steht in `session.token`.

## Header für Folgeanfragen

`Authorization: Bearer <TOKEN>`

## Endpunkte

- `GET /admin/bootstrap/status`
- `POST /admin/bootstrap` (nur initial)
- `POST /admin/login`
- `POST /admin/logout`
- `GET /admin/overview`
- `GET /admin/events?limit=100`
- `POST /admin/events`
- `PUT /admin/events/{id}`
- `DELETE /admin/events/{id}`

## Beispiel: Overview

```bash
curl -s https://staysense.vanityontour.de/api/admin/overview \
  -H "Authorization: Bearer <TOKEN>"
```
