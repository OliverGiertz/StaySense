const DEFAULT_API_BASE =
  window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8787"
    : "/api";
const API_BASE = window.STAYSENSE_API_BASE || DEFAULT_API_BASE;

const DEVICE_TOKEN_KEY = "staysense.device_token.v1";
const SETTINGS_KEY = "staysense.settings.v1";
const SCORE_CACHE_KEY = "staysense.score_cache.v1";
const SIGNAL_QUEUE_KEY = "staysense.signal_queue.v1";
const ADMIN_TOKEN_KEY = "staysense.admin_token.v1";
const MAX_CACHE_ITEMS = 50;

const latEl = document.getElementById("lat");
const lonEl = document.getElementById("lon");
const searchQueryEl = document.getElementById("search-query");
const searchLocationEl = document.getElementById("search-location");
const searchStatusEl = document.getElementById("search-status");
const searchResultsEl = document.getElementById("search-results");
const mapEl = document.getElementById("map");
const loadScoreEl = document.getElementById("load-score");
const useLocationEl = document.getElementById("use-location");

const scoreEl = document.getElementById("score");
const ampelEl = document.getElementById("ampel");
const reasonsEl = document.getElementById("reasons");
const nightWindowEl = document.getElementById("night-window");
const networkStatusEl = document.getElementById("network-status");
const dataStatusEl = document.getElementById("data-status");
const signalStatusEl = document.getElementById("signal-status");
const queueStatusEl = document.getElementById("queue-status");

const signalsEnabledEl = document.getElementById("signals-enabled");
const legalOutputEl = document.getElementById("legal-output");
const adminSetupEl = document.getElementById("admin-setup");
const adminLoginEl = document.getElementById("admin-login");
const adminContentEl = document.getElementById("admin-content");
const adminStatusEl = document.getElementById("admin-status");
const adminCountsEl = document.getElementById("admin-counts");
const adminEventsEl = document.getElementById("admin-events");
const adminSignalsEl = document.getElementById("admin-signals");
const adminSourcesEl = document.getElementById("admin-sources");
const adminSetupUserEl = document.getElementById("admin-setup-user");
const adminSetupPassEl = document.getElementById("admin-setup-pass");
const adminSetupSubmitEl = document.getElementById("admin-setup-submit");
const adminLoginUserEl = document.getElementById("admin-login-user");
const adminLoginPassEl = document.getElementById("admin-login-pass");
const adminLoginSubmitEl = document.getElementById("admin-login-submit");
const adminLogoutEl = document.getElementById("admin-logout");
const adminRefreshEl = document.getElementById("admin-refresh");
const adminEventCreateEl = document.getElementById("admin-event-create");
const adminEventDeleteEl = document.getElementById("admin-event-delete");
const adminEventIdEl = document.getElementById("admin-event-id");
const adminEventTypeEl = document.getElementById("admin-event-type");
const adminEventRiskEl = document.getElementById("admin-event-risk");
const adminEventLatEl = document.getElementById("admin-event-lat");
const adminEventLonEl = document.getElementById("admin-event-lon");
const adminEventStartEl = document.getElementById("admin-event-start");
const adminEventEndEl = document.getElementById("admin-event-end");
const adminEventSourceEl = document.getElementById("admin-event-source");

let currentSpot = null;
let scoreCache = loadJSON(SCORE_CACHE_KEY, []);
let signalQueue = loadJSON(SIGNAL_QUEUE_KEY, []);
let settings = loadJSON(SETTINGS_KEY, { signalsEnabled: true });
let apiOnline = false;
let lastHealthCheckAt = null;
let lastHealthLatencyMs = null;
let map = null;
let mapMarker = null;
let searchResults = [];
let selectedSearchIndex = -1;
let adminToken = localStorage.getItem(ADMIN_TOKEN_KEY) || "";

const deviceToken = ensureDeviceToken();
initialize();

function initialize() {
  signalsEnabledEl.checked = Boolean(settings.signalsEnabled);
  renderNetworkStatus();
  window.addEventListener("online", onNetworkHint);
  window.addEventListener("offline", onNetworkHint);

  signalsEnabledEl.addEventListener("change", () => {
    settings.signalsEnabled = signalsEnabledEl.checked;
    saveJSON(SETTINGS_KEY, settings);
  });

  useLocationEl.addEventListener("click", fillLocationFromDevice);
  loadScoreEl.addEventListener("click", loadScore);
  searchLocationEl.addEventListener("click", searchLocation);
  searchQueryEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchLocation();
    }
  });

  latEl.addEventListener("change", () => updateMapFromInputs(14));
  lonEl.addEventListener("change", () => updateMapFromInputs(14));

  document.querySelectorAll(".signal").forEach((btn) => {
    btn.addEventListener("click", () => sendSignal(btn.dataset.signal));
  });

  adminSetupSubmitEl.addEventListener("click", adminBootstrap);
  adminLoginSubmitEl.addEventListener("click", adminLogin);
  adminLogoutEl.addEventListener("click", adminLogout);
  adminRefreshEl.addEventListener("click", loadAdminOverview);
  adminEventCreateEl.addEventListener("click", saveAdminEvent);
  adminEventDeleteEl.addEventListener("click", deleteAdminEvent);
  adminEventsEl.addEventListener("click", onAdminEventListClick);

  // Pilotwert für Mettmann, falls noch keine Eingabe.
  if (!latEl.value && !lonEl.value) {
    latEl.value = "51.2500";
    lonEl.value = "6.9730";
  }

  initializeMap();
  updateMapFromInputs();
  flushSignalQueue();
  renderQueueStatus();
  checkApiHealth();
  setInterval(checkApiHealth, 30000);
  loadAdminBootstrapStatus();
}

function ensureDeviceToken() {
  let token = localStorage.getItem(DEVICE_TOKEN_KEY);
  if (!token) {
    token = crypto.randomUUID();
    localStorage.setItem(DEVICE_TOKEN_KEY, token);
  }
  return token;
}

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function saveJSON(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function renderNetworkStatus() {
  const checkedAt = lastHealthCheckAt ? toLocal(lastHealthCheckAt) : "-";
  const latency = Number.isFinite(lastHealthLatencyMs) ? `${lastHealthLatencyMs}ms` : "-";
  networkStatusEl.textContent = `API: ${apiOnline ? "Online" : "Offline"} | letzter Check: ${checkedAt} | Latenz: ${latency}`;
}

function onNetworkHint() {
  // Hint event from browser/OS network stack: trigger real check, do not trust onLine flag as truth.
  flushSignalQueue();
  checkApiHealth();
}

async function checkApiHealth() {
  const started = performance.now();
  try {
    const response = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("health_failed");
    }
    const payload = await response.json();
    apiOnline = true;
    lastHealthLatencyMs = Math.round(performance.now() - started);
    lastHealthCheckAt = new Date().toISOString();
    renderDataStatusFromHealth(payload && payload.health ? payload.health : null);
  } catch {
    apiOnline = false;
    lastHealthLatencyMs = null;
    lastHealthCheckAt = new Date().toISOString();
    dataStatusEl.textContent = "Datenstand: aktuell nicht abrufbar (API offline)";
  }
  renderNetworkStatus();
}

function renderDataStatusFromHealth(health) {
  if (!health || !health.has_data) {
    dataStatusEl.textContent = "Datenstand: keine Quellenmetadaten";
    return;
  }
  const freshness = `freshest ${health.freshest_age_hours}h, stalest ${health.stalest_age_hours}h`;
  const stale = health.stale_sources && health.stale_sources.length ? `, stale: ${health.stale_sources.join(", ")}` : "";
  dataStatusEl.textContent = `Datenstand: ${freshness}${stale}`;
}

function renderQueueStatus() {
  queueStatusEl.textContent = `Warteschlange: ${signalQueue.length} ausstehend`;
}

async function fillLocationFromDevice() {
  if (!navigator.geolocation) {
    alert("Geolocation wird auf diesem Gerät nicht unterstützt.");
    return;
  }

  useLocationEl.disabled = true;
  navigator.geolocation.getCurrentPosition(
    (position) => {
      selectedSearchIndex = -1;
      renderSearchResults();
      setCoordinates(position.coords.latitude, position.coords.longitude, { zoom: 16 });
      searchStatusEl.textContent = "Aktueller Standort übernommen.";
      useLocationEl.disabled = false;
    },
    () => {
      alert("Standort konnte nicht gelesen werden.");
      useLocationEl.disabled = false;
    },
    { enableHighAccuracy: true, maximumAge: 60000, timeout: 7000 }
  );
}

function initializeMap() {
  if (!mapEl || typeof L === "undefined") {
    searchStatusEl.textContent = "Karte konnte nicht geladen werden.";
    return;
  }

  map = L.map(mapEl, { zoomControl: true }).setView([51.2500, 6.9730], 12);
  L.tileLayer(`${API_BASE}/map/tile/{z}/{x}/{y}.png`, {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  map.on("click", (event) => {
    selectedSearchIndex = -1;
    renderSearchResults();
    setCoordinates(event.latlng.lat, event.latlng.lng, { fromMap: true });
    searchStatusEl.textContent = "Position aus Karte übernommen.";
  });
}

function setCoordinates(lat, lon, options = {}) {
  const zoom = options.zoom || null;
  latEl.value = Number(lat).toFixed(6);
  lonEl.value = Number(lon).toFixed(6);

  if (!map) {
    return;
  }

  const latLng = [Number(lat), Number(lon)];
  if (!mapMarker) {
    mapMarker = L.circleMarker(latLng, {
      radius: 8,
      color: "#006680",
      fillColor: "#1ca4c7",
      fillOpacity: 0.8,
      weight: 2,
    }).addTo(map);
  } else {
    mapMarker.setLatLng(latLng);
  }

  if (Number.isFinite(zoom)) {
    map.setView(latLng, zoom);
  } else if (options.fromMap) {
    map.panTo(latLng);
  }
}

function updateMapFromInputs(zoom = null) {
  const lat = Number(latEl.value);
  const lon = Number(lonEl.value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return;
  }
  setCoordinates(lat, lon, { zoom });
}

async function searchLocation() {
  const query = searchQueryEl.value.trim();
  if (!query) {
    searchStatusEl.textContent = "Bitte einen Suchbegriff eingeben.";
    return;
  }

  searchLocationEl.disabled = true;
  searchStatusEl.textContent = "Suche läuft ...";

  try {
    const response = await fetch(`${API_BASE}/geocode/search?q=${encodeURIComponent(query)}`);
    if (!response.ok) {
      throw new Error("search_failed");
    }

    const payload = await response.json();
    if (!payload.results || !payload.results.length) {
      searchResults = [];
      selectedSearchIndex = -1;
      renderSearchResults();
      searchStatusEl.textContent = "Keine Treffer gefunden.";
      return;
    }

    searchResults = payload.results;
    selectedSearchIndex = 0;
    renderSearchResults();
    const best = searchResults[0];
    setCoordinates(best.lat, best.lon, { zoom: 16 });
    searchStatusEl.textContent = `Treffer ausgewählt: ${best.display_name}`;
  } catch {
    searchResults = [];
    selectedSearchIndex = -1;
    renderSearchResults();
    searchStatusEl.textContent = "Suche fehlgeschlagen. Bitte später erneut versuchen.";
  } finally {
    searchLocationEl.disabled = false;
  }
}

async function loadAdminBootstrapStatus() {
  adminStatusEl.textContent = "Admin-Status wird geladen ...";
  try {
    const response = await fetch(`${API_BASE}/admin/bootstrap/status`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("bootstrap_status_failed");
    }
    const payload = await response.json();
    renderAdminMode(payload.initialized);
    if (!payload.initialized) {
      adminStatusEl.textContent = "Erst-Setup erforderlich: Bitte initialen Admin anlegen.";
      return;
    }
    adminStatusEl.textContent = adminToken
      ? "Admin bereit. Session wird geprüft ..."
      : "Admin bereit. Bitte anmelden.";
    if (adminToken) {
      await loadAdminOverview();
    }
  } catch {
    renderAdminMode(false);
    adminStatusEl.textContent = "Admin-Status konnte nicht geladen werden.";
  }
}

function renderAdminMode(initialized) {
  adminSetupEl.classList.toggle("hidden", initialized);
  adminLoginEl.classList.toggle("hidden", !initialized);
  if (!initialized) {
    adminContentEl.classList.add("hidden");
  }
}

function adminHeaders() {
  return adminToken ? { Authorization: `Bearer ${adminToken}` } : {};
}

async function adminBootstrap() {
  const username = adminSetupUserEl.value.trim();
  const password = adminSetupPassEl.value;
  if (username.length < 3 || password.length < 10) {
    adminStatusEl.textContent = "Setup fehlgeschlagen: User mind. 3 Zeichen, Passwort mind. 10 Zeichen.";
    return;
  }
  adminSetupSubmitEl.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/admin/bootstrap`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "setup_failed");
    }
    adminToken = payload.session.token;
    localStorage.setItem(ADMIN_TOKEN_KEY, adminToken);
    adminSetupPassEl.value = "";
    adminLoginUserEl.value = username;
    adminStatusEl.textContent = "Admin wurde angelegt und eingeloggt.";
    renderAdminMode(true);
    await loadAdminOverview();
  } catch (error) {
    adminStatusEl.textContent = `Setup fehlgeschlagen: ${String(error.message || "unbekannter Fehler")}`;
  } finally {
    adminSetupSubmitEl.disabled = false;
  }
}

async function adminLogin() {
  const username = adminLoginUserEl.value.trim();
  const password = adminLoginPassEl.value;
  if (!username || !password) {
    adminStatusEl.textContent = "Bitte User und Passwort eingeben.";
    return;
  }
  adminLoginSubmitEl.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "login_failed");
    }
    adminToken = payload.session.token;
    localStorage.setItem(ADMIN_TOKEN_KEY, adminToken);
    adminLoginPassEl.value = "";
    adminStatusEl.textContent = "Admin Login erfolgreich.";
    await loadAdminOverview();
  } catch (error) {
    adminStatusEl.textContent = `Login fehlgeschlagen: ${String(error.message || "unbekannter Fehler")}`;
  } finally {
    adminLoginSubmitEl.disabled = false;
  }
}

async function adminLogout() {
  try {
    await fetch(`${API_BASE}/admin/logout`, { method: "POST", headers: adminHeaders() });
  } catch {
    // ignore
  }
  adminToken = "";
  localStorage.removeItem(ADMIN_TOKEN_KEY);
  adminContentEl.classList.add("hidden");
  adminStatusEl.textContent = "Abgemeldet.";
}

function renderAdminList(target, rows, mapper) {
  target.innerHTML = "";
  if (!rows || !rows.length) {
    target.textContent = "Keine Daten.";
    return;
  }
  rows.forEach((row) => {
    const div = document.createElement("div");
    div.className = "admin-list-item";
    if (row && row.id) {
      div.dataset.eventId = row.id;
      div.title = "Klick setzt Event-ID";
    }
    div.textContent = mapper(row);
    target.appendChild(div);
  });
}

async function loadAdminOverview() {
  if (!adminToken) {
    adminStatusEl.textContent = "Nicht eingeloggt.";
    adminContentEl.classList.add("hidden");
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/admin/overview`, { headers: adminHeaders() });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      adminToken = "";
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      adminContentEl.classList.add("hidden");
      adminStatusEl.textContent = "Session abgelaufen. Bitte erneut anmelden.";
      return;
    }
    if (!response.ok) {
      throw new Error(payload.error || "admin_overview_failed");
    }
    adminContentEl.classList.remove("hidden");
    adminStatusEl.textContent = `Eingeloggt als ${payload.admin_user}.`;
    adminCountsEl.textContent = `Spots: ${payload.counts.spots} | Signale: ${payload.counts.signals} | Events: ${payload.counts.events} | Quellen: ${payload.counts.data_sources}`;
    renderAdminList(
      adminEventsEl,
      payload.latest_events,
      (row) =>
        `${row.id} | ${row.event_type} | ${Number(row.lat).toFixed(5)}, ${Number(row.lon).toFixed(5)} | ${row.start_datetime} -> ${row.end_datetime} | risk ${row.risk_modifier} | ${row.source}`
    );
    renderAdminList(
      adminSignalsEl,
      payload.latest_signals,
      (row) => `${row.timestamp} | ${row.signal_type} | spot ${row.spot_id}`
    );
    renderAdminList(
      adminSourcesEl,
      payload.data_sources,
      (row) => `${row.source_name} | ${row.record_count} records | ${row.imported_at} | ${row.notes}`
    );
  } catch (error) {
    adminStatusEl.textContent = `Admin-Daten konnten nicht geladen werden: ${String(error.message || "unbekannter Fehler")}`;
  }
}

function buildAdminEventPayload() {
  return {
    event_type: adminEventTypeEl.value,
    risk_modifier: Number(adminEventRiskEl.value),
    lat: Number(adminEventLatEl.value),
    lon: Number(adminEventLonEl.value),
    start_datetime: adminEventStartEl.value.trim(),
    end_datetime: adminEventEndEl.value.trim(),
    source: adminEventSourceEl.value.trim() || "admin_manual",
  };
}

async function saveAdminEvent() {
  if (!adminToken) {
    adminStatusEl.textContent = "Bitte zuerst anmelden.";
    return;
  }
  const eventId = adminEventIdEl.value.trim();
  const payload = buildAdminEventPayload();
  if (!Number.isFinite(payload.lat) || !Number.isFinite(payload.lon)) {
    adminStatusEl.textContent = "Ungültige Event-Koordinaten.";
    return;
  }
  const method = eventId ? "PUT" : "POST";
  const url = eventId ? `${API_BASE}/admin/events/${encodeURIComponent(eventId)}` : `${API_BASE}/admin/events`;
  adminEventCreateEl.disabled = true;
  try {
    const response = await fetch(url, {
      method,
      headers: { ...adminHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.error || "event_save_failed");
    }
    adminStatusEl.textContent = eventId ? `Event aktualisiert: ${eventId}` : `Event angelegt: ${body.id}`;
    if (!eventId && body.id) {
      adminEventIdEl.value = body.id;
    }
    await loadAdminOverview();
  } catch (error) {
    adminStatusEl.textContent = `Event konnte nicht gespeichert werden: ${String(error.message || "unbekannter Fehler")}`;
  } finally {
    adminEventCreateEl.disabled = false;
  }
}

async function deleteAdminEvent() {
  if (!adminToken) {
    adminStatusEl.textContent = "Bitte zuerst anmelden.";
    return;
  }
  const eventId = adminEventIdEl.value.trim();
  if (!eventId) {
    adminStatusEl.textContent = "Bitte Event-ID zum Löschen eingeben.";
    return;
  }
  adminEventDeleteEl.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/admin/events/${encodeURIComponent(eventId)}`, {
      method: "DELETE",
      headers: adminHeaders(),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.error || "event_delete_failed");
    }
    adminStatusEl.textContent = `Event gelöscht: ${eventId}`;
    adminEventIdEl.value = "";
    await loadAdminOverview();
  } catch (error) {
    adminStatusEl.textContent = `Event konnte nicht gelöscht werden: ${String(error.message || "unbekannter Fehler")}`;
  } finally {
    adminEventDeleteEl.disabled = false;
  }
}

function onAdminEventListClick(event) {
  const row = event.target.closest(".admin-list-item");
  if (!row) {
    return;
  }
  if (row.dataset.eventId) {
    adminEventIdEl.value = row.dataset.eventId;
    adminStatusEl.textContent = `Event-ID übernommen: ${row.dataset.eventId}`;
  }
}

function renderSearchResults() {
  searchResultsEl.innerHTML = "";
  searchResults.forEach((result, index) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result-btn";
    if (index === selectedSearchIndex) {
      button.classList.add("active");
    }
    button.textContent = result.display_name;
    button.addEventListener("click", () => {
      selectedSearchIndex = index;
      setCoordinates(result.lat, result.lon, { zoom: 16 });
      searchStatusEl.textContent = `Treffer ausgewählt: ${result.display_name}`;
      renderSearchResults();
    });
    li.appendChild(button);
    searchResultsEl.appendChild(li);
  });
}

function cacheKey(lat, lon) {
  return `${Number(lat).toFixed(4)}:${Number(lon).toFixed(4)}`;
}

function putScoreCache(entry) {
  scoreCache = [entry, ...scoreCache.filter((it) => it.key !== entry.key)].slice(0, MAX_CACHE_ITEMS);
  saveJSON(SCORE_CACHE_KEY, scoreCache);
}

function findCachedScore(lat, lon) {
  return scoreCache.find((it) => it.key === cacheKey(lat, lon));
}

async function loadScore() {
  const lat = Number(latEl.value);
  const lon = Number(lonEl.value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    alert("Bitte gültige Koordinaten eingeben.");
    return;
  }

  loadScoreEl.disabled = true;
  const at = new Date().toISOString();

  try {
    const response = await fetch(`${API_BASE}/spot/score?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&at=${encodeURIComponent(at)}`);
    if (!response.ok) {
      throw new Error("api_error");
    }

    const payload = await response.json();
    currentSpot = payload;
    renderScore(payload, false);

    putScoreCache({
      key: cacheKey(lat, lon),
      fetchedAt: new Date().toISOString(),
      payload,
    });
  } catch {
    const cached = findCachedScore(lat, lon);
    if (cached) {
      currentSpot = cached.payload;
      renderScore(cached.payload, true, cached.fetchedAt);
    } else {
      signalStatusEl.textContent = "Kein Live-Score und kein Cache für diesen Spot vorhanden.";
    }
  } finally {
    loadScoreEl.disabled = false;
  }
}

function renderScore(data, fromCache, cacheTime = "") {
  scoreEl.textContent = String(data.score);

  ampelEl.classList.remove("green", "yellow", "red");
  ampelEl.classList.add(data.ampel);
  ampelEl.textContent = data.ampel === "green" ? "Grün" : data.ampel === "yellow" ? "Gelb" : "Rot";

  nightWindowEl.textContent = `Bezug: ${toLocal(data.night_window.start)} bis ${toLocal(data.night_window.end)}`;

  reasonsEl.innerHTML = "";
  data.reasons.forEach((reason) => {
    const li = document.createElement("li");
    li.textContent = reason;
    reasonsEl.appendChild(li);
  });

  const health = (data.meta && data.meta.health) || {};
  if (health.has_data) {
    const freshness = `freshest ${health.freshest_age_hours}h, stalest ${health.stalest_age_hours}h`;
    const stale = health.stale_sources && health.stale_sources.length ? `, stale: ${health.stale_sources.join(", ")}` : "";
    const fallback = data.meta.used_fallback_pois ? ", Fallback-POI aktiv" : "";
    dataStatusEl.textContent = `Datenstand: ${freshness}${stale}${fallback}`;
  } else {
    dataStatusEl.textContent = "Datenstand: keine Quellenmetadaten";
  }

  if (fromCache) {
    signalStatusEl.textContent = `Cache verwendet (Stand: ${toLocal(cacheTime)}).`;
  } else {
    signalStatusEl.textContent = "Live-Score erfolgreich geladen.";
  }
}

function buildSignal(signalType) {
  if (!currentSpot || !currentSpot.spot_id) {
    return null;
  }

  return {
    spot_id: currentSpot.spot_id,
    signal_type: signalType,
    device_token: deviceToken,
    timestamp: new Date().toISOString(),
  };
}

async function sendSignal(signalType) {
  if (!settings.signalsEnabled) {
    signalStatusEl.textContent = "Community Signals sind in den Settings deaktiviert.";
    return;
  }

  const signal = buildSignal(signalType);
  if (!signal) {
    signalStatusEl.textContent = "Bitte zuerst einen Spot-Score laden.";
    return;
  }

  try {
    await submitSignal(signal);
    signalStatusEl.textContent = `Signal '${signalType}' wurde gespeichert.`;
  } catch (error) {
    if (error && String(error.message || "").startsWith("cooldown:")) {
      const nextAt = String(error.message).replace("cooldown:", "");
      signalStatusEl.textContent = `Signal gesperrt bis ${toLocal(nextAt)}.`;
      return;
    }
    signalQueue.push(signal);
    saveJSON(SIGNAL_QUEUE_KEY, signalQueue);
    signalStatusEl.textContent = `Offline/Fehler: Signal '${signalType}' zwischengespeichert.`;
    renderQueueStatus();
  }
}

async function submitSignal(signal) {
  const response = await fetch(`${API_BASE}/spot/signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(signal),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (payload && payload.error === "cooldown_active") {
      throw new Error(`cooldown:${payload.next_allowed_at || ""}`);
    }
    throw new Error("signal_failed");
  }
}

async function flushSignalQueue() {
  if (!signalQueue.length) {
    return;
  }

  const pending = [...signalQueue];
  const keep = [];

  for (const signal of pending) {
    try {
      await submitSignal(signal);
    } catch {
      keep.push(signal);
    }
  }

  signalQueue = keep;
  saveJSON(SIGNAL_QUEUE_KEY, signalQueue);
  renderQueueStatus();

  if (!keep.length && pending.length) {
    signalStatusEl.textContent = "Alle zwischengespeicherten Signale wurden synchronisiert.";
  }
}

function toLocal(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("de-DE", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
