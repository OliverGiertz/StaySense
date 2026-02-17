# Deployment

Zielplattform aktuell: Hetzner + CloudPanel + Nginx + systemd.

## Komponenten

- App-Code: `/opt/staysense`
- API-Service: `staysense-api.service`
- Import-Timer: `staysense-import.timer`
- API-Watchdog: `staysense-watchdog.timer`
- Frontend-Root: `/home/staysense-site/htdocs/staysense.vanityontour.de/`

## Rollout (vereinfacht)

```bash
cd /opt/staysense
git pull --ff-only
rsync -a --delete /opt/staysense/src/ /home/staysense-site/htdocs/staysense.vanityontour.de/
systemctl restart staysense-api.service
nginx -t && systemctl reload nginx
systemctl restart staysense-watchdog.timer
```

## Pflichtchecks

```bash
systemctl is-active staysense-api.service
systemctl is-active staysense-watchdog.timer
curl -s -L https://staysense.vanityontour.de/api/health
```

## HTTPS

TLS-Zertifikate werden über CloudPanel verwaltet.
