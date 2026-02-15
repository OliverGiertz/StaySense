# CloudPanel Setup (Hetzner)

## Ziel

StaySense unter `staysense.vanityontour.de` mit CloudPanel + Let's Encrypt + Reverse Proxy auf API.

## DNS

- `A`: `staysense.vanityontour.de -> 88.99.209.207`
- `AAAA`: `staysense.vanityontour.de -> 2a01:4f8:10a:3ae1::2`

## CloudPanel Eintraege

1. Site-Typ: `Static HTML`
2. Domain: `staysense.vanityontour.de`
3. Site User: z. B. `staysense-site`
4. SSL: `Let's Encrypt` aktivieren
5. Redirect HTTP->HTTPS aktivieren

## Webroot

CloudPanel legt typischerweise an:

- `/home/staysense-site/htdocs/staysense.vanityontour.de`

Frontend deployen:

```bash
rsync -a --delete /opt/staysense/src/ /home/staysense-site/htdocs/staysense.vanityontour.de/
chown -R staysense-site:staysense-site /home/staysense-site/htdocs/staysense.vanityontour.de
```

## Reverse Proxy fuer API

In die vHost-Config der Site aufnehmen:

```nginx
location /api/ {
  limit_req zone=limit burst=20 nodelay;
  proxy_pass http://127.0.0.1:8787/;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Security Header (empfohlen)

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(self)" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'" always;
```

## Backend Services

- `staysense-api.service` (API)
- `staysense-import.timer` + `staysense-import.service` (Datenimporte)

Status:

```bash
systemctl is-active staysense-api.service
systemctl is-active staysense-import.timer
```

## Health Checks

```bash
curl -s https://staysense.vanityontour.de/api/health
curl -I http://staysense.vanityontour.de
curl -I https://staysense.vanityontour.de
```
