const DEFAULT_API_BASE =
  window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8787"
    : "/api";
const API_BASE = window.STAYSENSE_API_BASE || DEFAULT_API_BASE;

const DEVICE_TOKEN_KEY = "staysense.device_token.v1";
const SETTINGS_KEY = "staysense.settings.v1";
const SCORE_CACHE_KEY = "staysense.score_cache.v1";
const SIGNAL_QUEUE_KEY = "staysense.signal_queue.v1";
const MAX_CACHE_ITEMS = 50;

const latEl = document.getElementById("lat");
const lonEl = document.getElementById("lon");
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

let currentSpot = null;
let scoreCache = loadJSON(SCORE_CACHE_KEY, []);
let signalQueue = loadJSON(SIGNAL_QUEUE_KEY, []);
let settings = loadJSON(SETTINGS_KEY, { signalsEnabled: true });
let apiOnline = false;
let lastHealthCheckAt = null;
let lastHealthLatencyMs = null;

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

  document.querySelectorAll(".signal").forEach((btn) => {
    btn.addEventListener("click", () => sendSignal(btn.dataset.signal));
  });

  document.getElementById("show-attribution").addEventListener("click", (e) => {
    e.preventDefault();
    legalOutputEl.textContent = "Kartendaten: OpenStreetMap-Mitwirkende (ODbL). Open Data NRW: jeweilige Quellen mit Namensnennung.";
  });

  document.getElementById("show-privacy").addEventListener("click", (e) => {
    e.preventDefault();
    legalOutputEl.textContent = "Kein Login, keine IP-Speicherung, kein Fingerprinting. Missbrauchsschutz via gehashtem lokalem Zufallstoken (HMAC-SHA256).";
  });

  document.getElementById("show-imprint").addEventListener("click", (e) => {
    e.preventDefault();
    legalOutputEl.textContent = "MVP-Hinweis: Impressum im Produktionsbetrieb verpflichtend mit Anbieterkennzeichnung.";
  });

  // Pilotwert fuer Mettmann, falls noch keine Eingabe.
  if (!latEl.value && !lonEl.value) {
    latEl.value = "51.2500";
    lonEl.value = "6.9730";
  }

  flushSignalQueue();
  renderQueueStatus();
  checkApiHealth();
  setInterval(checkApiHealth, 30000);
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
    apiOnline = true;
    lastHealthLatencyMs = Math.round(performance.now() - started);
    lastHealthCheckAt = new Date().toISOString();
  } catch {
    apiOnline = false;
    lastHealthLatencyMs = null;
    lastHealthCheckAt = new Date().toISOString();
  }
  renderNetworkStatus();
}

function renderQueueStatus() {
  queueStatusEl.textContent = `Queue: ${signalQueue.length} ausstehend`;
}

async function fillLocationFromDevice() {
  if (!navigator.geolocation) {
    alert("Geolocation wird auf diesem Geraet nicht unterstuetzt.");
    return;
  }

  useLocationEl.disabled = true;
  navigator.geolocation.getCurrentPosition(
    (position) => {
      latEl.value = position.coords.latitude.toFixed(6);
      lonEl.value = position.coords.longitude.toFixed(6);
      useLocationEl.disabled = false;
    },
    () => {
      alert("Standort konnte nicht gelesen werden.");
      useLocationEl.disabled = false;
    },
    { enableHighAccuracy: true, maximumAge: 60000, timeout: 7000 }
  );
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
    alert("Bitte gueltige Koordinaten eingeben.");
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
      signalStatusEl.textContent = "Kein Live-Score und kein Cache fuer diesen Spot vorhanden.";
    }
  } finally {
    loadScoreEl.disabled = false;
  }
}

function renderScore(data, fromCache, cacheTime = "") {
  scoreEl.textContent = String(data.score);

  ampelEl.classList.remove("green", "yellow", "red");
  ampelEl.classList.add(data.ampel);
  ampelEl.textContent = data.ampel === "green" ? "Gruen" : data.ampel === "yellow" ? "Gelb" : "Rot";

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
    signalStatusEl.textContent = `Offline/Fehler: Signal '${signalType}' gequeued.`;
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
    signalStatusEl.textContent = "Alle gequeueten Signale wurden synchronisiert.";
  }
}

function toLocal(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("de-DE", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
