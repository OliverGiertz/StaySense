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
