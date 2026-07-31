"use strict";

const state = {
  csrf: null,
  selectedRun: null,
  runs: [],
  events: [],
  source: null,
  reconnectDelay: 1000,
  lastEventId: 0,
  plan: null,
  blocker: null,
  runStatus: null,
};

const terminalStatuses = new Set([
  "completed",
  "completed_best_effort",
  "failed",
  "cancelled",
  "interrupted",
  "paused",
  "waiting_for_approval",
  "waiting_for_input",
]);

const byId = (id) => document.getElementById(id);

function toast(message) {
  const element = byId("toast");
  element.textContent = message;
  element.hidden = false;
  window.setTimeout(() => { element.hidden = true; }, 3500);
}

function setConnection(label, mode) {
  byId("connection-label").textContent = label;
  byId("connection-dot").className = `connection-dot ${mode || ""}`;
}

async function api(path, options = {}) {
  const headers = {Accept: "application/json", ...(options.headers || {})};
  if (options.method && options.method !== "GET" && state.csrf) {
    headers["X-CSRF-Token"] = state.csrf;
  }
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {...options, headers, credentials: "same-origin"});
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || `HTTP ${response.status}`);
  }
  return payload.data;
}

async function bootstrap() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get("token");
  if (token) {
    history.replaceState(null, "", `${location.pathname}${location.search}`);
    const data = await api("/api/bootstrap", {
      method: "POST",
      body: JSON.stringify({token}),
    });
    state.csrf = data.csrf_token;
  }
}

function renderRuns() {
  const list = byId("run-list");
  list.replaceChildren();
  state.runs.forEach((run) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `run-item ${run.run_id === state.selectedRun ? "active" : ""}`;
    const name = document.createElement("strong");
    name.textContent = run.run_id;
    const meta = document.createElement("span");
    meta.textContent = `${run.status} · ${new Date(run.updated_at).toLocaleString()}`;
    button.append(name, meta);
    button.addEventListener("click", () => selectRun(run.run_id));
    list.append(button);
  });
}

async function loadRuns() {
  const data = await api("/api/runs?limit=200");
  state.runs = data.runs;
  renderRuns();
  const requested = new URLSearchParams(location.search).get("run");
  if (!state.selectedRun && (requested || state.runs[0]?.run_id)) {
    await selectRun(requested || state.runs[0].run_id);
  }
}

function statusBadge(status) {
  const span = document.createElement("span");
  span.className = `badge ${status}`;
  span.textContent = status;
  return span;
}

function renderPlan(status) {
  const waves = byId("waves");
  waves.replaceChildren();
  (state.plan?.waves || []).forEach((items, index) => {
    const wave = document.createElement("div");
    wave.className = "wave";
    const label = document.createElement("small");
    label.textContent = `Волна ${index + 1}`;
    wave.append(label);
    items.forEach((item) => {
      const code = document.createElement("code");
      code.textContent = item;
      wave.append(code);
    });
    waves.append(wave);
  });

  const steps = byId("steps");
  steps.replaceChildren();
  const agentMap = state.plan?.agents || {};
  const planSteps = Object.fromEntries((state.plan?.steps || []).map((item) => [item.name, item]));
  Object.entries(status.steps || {}).forEach(([name, stepState]) => {
    const rootName = name.split("@iteration-")[0];
    const planStep = planSteps[rootName] || {};
    const agent = agentMap[planStep.agent] || {};
    const row = document.createElement("div");
    row.className = "step";
    const description = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = name;
    const meta = document.createElement("span");
    const skills = (agent.skills || []).map((skill) => skill.reference).join(", ");
    meta.textContent = `${agent.model || "runtime"} · ${agent.permissions || "controller"} · attempt ${stepState.attempt}${skills ? ` · Skills: ${skills}` : ""}`;
    description.append(title, meta);
    row.append(description, statusBadge(stepState.status));
    steps.append(row);
  });
  byId("metric-steps").textContent = `${Object.keys(status.steps || {}).length}`;
}

function renderEvents() {
  const list = byId("events");
  list.replaceChildren();
  state.events.slice(-200).reverse().forEach((event) => {
    const item = document.createElement("li");
    const type = document.createElement("strong");
    type.textContent = `${event.event_id} · ${event.type}`;
    const time = document.createElement("time");
    time.dateTime = event.timestamp;
    time.textContent = new Date(event.timestamp).toLocaleString();
    item.append(type, time);
    list.append(item);
  });
  byId("event-count").textContent = String(state.events.length);
  const latest = state.events.at(-1);
  byId("metric-event").textContent = latest ? latest.type : "нет событий";
}

async function renderArtifacts() {
  const data = await api(`/api/runs/${state.selectedRun}/artifacts?limit=100`);
  const list = byId("artifacts");
  list.replaceChildren();
  data.artifacts.forEach((artifact) => {
    const item = document.createElement("li");
    item.textContent = `${artifact.relative_path} · ${artifact.mime_type} · ${artifact.size_bytes} B`;
    list.append(item);
  });
  if (!data.artifacts.length) {
    const item = document.createElement("li");
    item.textContent = "Артефактов пока нет.";
    list.append(item);
  }
}

function renderBlocker(status) {
  const panel = byId("blocker-panel");
  const approval = byId("approval-form");
  const input = byId("input-form");
  panel.hidden = !["waiting_for_approval", "waiting_for_input"].includes(status.status);
  approval.hidden = status.status !== "waiting_for_approval";
  input.hidden = status.status !== "waiting_for_input";
  if (status.status === "waiting_for_approval") {
    byId("blocker-message").textContent = "Сценарий ожидает подтверждения точного плана.";
    byId("approval-hash").value = status.plan_hash;
  } else if (status.status === "waiting_for_input") {
    byId("blocker-message").textContent = status.blocker?.prompt || "Сценарий ожидает структурированный ввод.";
  }
  state.blocker = status.blocker;
}

async function refreshRun() {
  if (!state.selectedRun) return;
  const [status, plan, result] = await Promise.all([
    api(`/api/runs/${state.selectedRun}`),
    api(`/api/runs/${state.selectedRun}/plan`),
    api(`/api/runs/${state.selectedRun}/result`),
  ]);
  state.plan = plan;
  state.runStatus = status.status;
  byId("run-title").textContent = plan.scenario_title || state.selectedRun;
  byId("run-subtitle").textContent = state.selectedRun;
  byId("metric-status").textContent = status.status;
  byId("metric-activity").textContent = status.activity?.status || "нет процесса";
  byId("result-output").textContent = result.result ? JSON.stringify(result.result, null, 2) : "Результат ещё не сформирован.";
  renderPlan(status);
  renderBlocker(status);
  await renderArtifacts();
}

function connectEvents() {
  if (state.source) state.source.close();
  if (!state.selectedRun) return;
  setConnection("Подключено", "online");
  const source = new EventSource(`/api/runs/${state.selectedRun}/stream?cursor=${state.lastEventId}`);
  state.source = source;
  source.addEventListener("runtime", (message) => {
    const event = JSON.parse(message.data);
    state.lastEventId = Number(message.lastEventId || event.event_id);
    if (!state.events.some((known) => known.event_id === event.event_id)) {
      state.events.push(event);
      renderEvents();
    }
    state.reconnectDelay = 1000;
    refreshRun().catch((error) => toast(error.message));
  });
  source.addEventListener("heartbeat", () => setConnection("Подключено", "online"));
  source.onerror = () => {
    source.close();
    if (state.source !== source) return;
    if (terminalStatuses.has(state.runStatus)) {
      setConnection("Запуск завершён", "online");
      return;
    }
    setConnection("Нет связи с runtime", "offline");
    const delay = state.reconnectDelay;
    state.reconnectDelay = Math.min(15000, delay * 2);
    window.setTimeout(connectEvents, delay);
  };
}

async function selectRun(runId) {
  state.selectedRun = runId;
  state.events = [];
  state.lastEventId = 0;
  byId("empty-state").hidden = true;
  byId("dashboard").hidden = false;
  byId("controls").hidden = false;
  renderRuns();
  const eventPage = await api(`/api/runs/${runId}/events?limit=200`);
  state.events = eventPage.events;
  state.lastEventId = eventPage.next_cursor;
  renderEvents();
  await refreshRun();
  connectEvents();
}

async function control(action, body = {}) {
  if (!state.selectedRun) return;
  const data = await api(`/api/runs/${state.selectedRun}/${action}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  toast(`${action}: принято`);
  await refreshRun();
  return data;
}

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => control(button.dataset.action).catch((error) => toast(error.message)));
  });
  byId("refresh-runs").addEventListener("click", () => loadRuns().catch((error) => toast(error.message)));
  byId("approve-button").addEventListener("click", async () => {
    await control("approve", {plan_hash: byId("approval-hash").value, gate: "full_access"});
    await control("resume");
  });
  byId("input-form").addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      const value = JSON.parse(byId("input-value").value);
      control("input", {gate_id: state.blocker?.gate_id || "", value}).catch((error) => toast(error.message));
    } catch (_error) {
      toast("Введите корректный JSON.");
    }
  });
  try {
    await bootstrap();
    await loadRuns();
    setConnection("Подключено", "online");
  } catch (error) {
    setConnection("Runtime недоступен", "offline");
    toast(error.message);
  }
});
