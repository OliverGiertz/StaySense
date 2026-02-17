# Operations Runbook

## Health & Status

```bash
systemctl status staysense-api.service --no-pager
systemctl status staysense-import.timer --no-pager
systemctl status staysense-watchdog.timer --no-pager
curl -s https://staysense.vanityontour.de/api/health
```

## Logs

```bash
journalctl -u staysense-api.service --no-pager -n 120
journalctl -u staysense-import.service --no-pager -n 120
journalctl -u staysense-watchdog.service --no-pager -n 120
```

## Häufige Fehlerbilder

1. `Kein Live-Score` bei Nutzern
- API Health prüfen
- `/api/spot/score` direkt mit Testkoordinaten prüfen

2. DB readonly / Schreibfehler
- Datenverzeichnisrechte prüfen
- Service-User und Besitzrechte prüfen

```bash
chown -R staysense:staysense /opt/staysense/data
chmod 2775 /opt/staysense/data
systemctl restart staysense-api.service
```

3. Importdaten veraltet
- Timer-Status prüfen
- Import-Service manuell starten

```bash
systemctl start staysense-import.service
```
