# StaySense Deployment Guide (Linux + Nginx)

## 1. Voraussetzungen

- Ubuntu/Debian Server mit sudo
- Domain (optional, empfohlen)
- Python 3.10+
- Nginx
- systemd

Install:

```bash
sudo apt update
sudo apt install -y python3 nginx
sudo useradd --system --create-home --shell /usr/sbin/nologin staysense || true
```

## 2. Code bereitstellen

```bash
sudo mkdir -p /opt/staysense
sudo chown -R $USER:$USER /opt/staysense
git clone <REPO_URL> /opt/staysense
sudo mkdir -p /opt/staysense/data
sudo chown -R staysense:staysense /opt/staysense/data
sudo chmod 2775 /opt/staysense/data
```

## 3. Initialisierung

```bash
cd /opt/staysense/backend
python3 -c "from db import init_db; init_db()"
python3 import_osm_overpass.py
python3 run_import_jobs.py --config ../docs/open_data_sources.json --prune-legacy
```

## 4. API als Service starten

1. Service-Datei kopieren:

```bash
sudo cp /opt/staysense/deploy/systemd/staysense-api.service /etc/systemd/system/
```

2. Secret setzen (Datei anpassen):

```bash
sudo nano /etc/systemd/system/staysense-api.service
# STAYSENSE_SERVER_SALT=... setzen
```

3. Aktivieren:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now staysense-api.service
sudo systemctl status staysense-api.service
```

## 5. Import-Timer aktivieren

```bash
sudo cp /opt/staysense/deploy/systemd/staysense-import.service /etc/systemd/system/
sudo cp /opt/staysense/deploy/systemd/staysense-import.timer /etc/systemd/system/
sudo cp /opt/staysense/deploy/systemd/staysense-watchdog.service /etc/systemd/system/
sudo cp /opt/staysense/deploy/systemd/staysense-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now staysense-import.timer
sudo systemctl enable --now staysense-watchdog.timer
sudo systemctl list-timers | grep staysense
```

## 6. Nginx konfigurieren

```bash
sudo cp /opt/staysense/deploy/nginx/staysense.conf /etc/nginx/sites-available/staysense
sudo ln -s /etc/nginx/sites-available/staysense /etc/nginx/sites-enabled/staysense
sudo nginx -t
sudo systemctl reload nginx
```

## 7. API-Route im Frontend anpassen

Fuer Reverse Proxy `/api` kann in `src/index.html` vor `app.js` gesetzt werden:

```html
<script>
  window.STAYSENSE_API_BASE = "/api";
</script>
```

Danach Nginx reloaden.

## 8. HTTPS (empfohlen)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d staysense.example.com
```

## 9. Betrieb / Checks

```bash
curl -s http://127.0.0.1:8787/health
sudo journalctl -u staysense-api.service -f
sudo journalctl -u staysense-import.service -n 100
sudo journalctl -u staysense-watchdog.service -n 50
```
