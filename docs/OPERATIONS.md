# Operations Runbook

## Wichtige Befehle

API neu starten:

```bash
sudo systemctl restart staysense-api.service
```

Import manuell ausfuehren:

```bash
sudo systemctl start staysense-import.service
```

Service-Logs:

```bash
sudo journalctl -u staysense-api.service -f
sudo journalctl -u staysense-import.service -f
```

Fail2ban Status:

```bash
sudo fail2ban-client status
sudo fail2ban-client status nginx-staysense-limitreq
```

Health check:

```bash
curl -s http://127.0.0.1:8787/health
```

## Backup

```bash
cp /opt/staysense/data/staysense.db /opt/staysense/data/staysense.db.bak
```

## Restore

```bash
cp /opt/staysense/data/staysense.db.bak /opt/staysense/data/staysense.db
sudo systemctl restart staysense-api.service
```

## Hardening Snapshot

- API-Rate-Limit aktiv auf `/api/` (`limit_req zone=limit burst=20 nodelay`)
- Endpoint-spezifische Limits:
  - `/api/spot/score`: `zone=staysense_score`, `burst=25`
  - `/api/spot/signal`: `zone=staysense_signal`, `burst=3`
- Security Header aktiv im vHost (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`)
- Fail2ban Jail aktiv:
  - Name: `nginx-staysense-limitreq`
  - Log: `/home/staysense-site/logs/nginx/error.log`
  - Ban bei wiederholten Rate-Limit-Verstoessen
  - Alarm-Log: `/var/log/staysense-security.log`
