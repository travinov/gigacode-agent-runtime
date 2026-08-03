"use strict";

const state = {
  csrf: null,
  catalog: null,
  kind: "config",
  current: null,
  original: null,
  isNew: false,
  preview: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const clone = (value) => JSON.parse(JSON.stringify(value));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast visible${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 4200);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (state.csrf && options.method && options.method !== "GET") {
    headers["X-CSRF-Token"] = state.csrf;
  }
  const response = await fetch(path, { ...options, headers });
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    throw new Error(`Studio вернул HTTP ${response.status}`);
  }
  if (!response.ok || payload.ok !== true) {
    const error = payload.error || {};
    const details = error.details && Object.keys(error.details).length
      ? ` · ${JSON.stringify(error.details)}`
      : "";
    throw new Error(`${error.code || "HTTP_ERROR"}: ${error.message || response.status}${details}`);
  }
  return payload.data;
}

function field(label, id, value, options = {}) {
  const type = options.type || "text";
  const wide = options.wide ? "field-wide" : "field";
  const hint = options.hint ? `<small>${escapeHtml(options.hint)}</small>` : "";
  const disabled = options.disabled ? " disabled" : "";
  const min = options.min !== undefined ? ` min="${options.min}"` : "";
  if (type === "textarea") {
    return `<div class="${wide}"><label for="${id}">${escapeHtml(label)}</label><textarea id="${id}"${disabled}>${escapeHtml(value)}</textarea>${hint}</div>`;
  }
  return `<div class="${wide}"><label for="${id}">${escapeHtml(label)}</label><input id="${id}" type="${type}" value="${escapeHtml(value)}"${min}${disabled}>${hint}</div>`;
}

function selectField(label, id, value, choices, options = {}) {
  const wide = options.wide ? "field-wide" : "field";
  const disabled = options.disabled ? " disabled" : "";
  const entries = choices.map((choice) => {
    const item = typeof choice === "string" ? { value: choice, label: choice } : choice;
    return `<option value="${escapeHtml(item.value)}"${item.value === value ? " selected" : ""}>${escapeHtml(item.label)}</option>`;
  }).join("");
  return `<div class="${wide}"><label for="${id}">${escapeHtml(label)}</label><select id="${id}"${disabled}>${entries}</select></div>`;
}

function section(title, description, body, action = "") {
  return `<section class="form-section"><div class="section-heading"><div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div>${action}</div><div class="section-body">${body}</div></section>`;
}

function markDirty() {
  const node = $("#dirty-state");
  node.textContent = "Есть изменения";
  node.classList.add("changed");
}

function markClean() {
  const node = $("#dirty-state");
  node.textContent = "Нет изменений";
  node.classList.remove("changed");
}

function currentItems() {
  if (!state.catalog) return [];
  if (state.kind === "config") {
    return [{ name: "runtime-config", description: "Эффективные настройки", source_level: "selected", writable: true }];
  }
  const key = state.kind === "scenario" ? "scenarios" : `${state.kind}s`;
  return state.catalog[key] || [];
}

const KIND_COPY = {
  config: { title: "Настройки", singular: "Настройки Runtime", icon: "CFG" },
  scenario: { title: "Маршруты", singular: "Маршрут", icon: "R" },
  agent: { title: "Агенты", singular: "Агент", icon: "A" },
  skill: { title: "Скиллы", singular: "Skill", icon: "S" },
};

function renderCatalog() {
  const query = $("#catalog-search").value.trim().toLowerCase();
  const items = currentItems().filter((item) => {
    const haystack = `${item.name} ${item.title || ""} ${item.description || ""}`.toLowerCase();
    return haystack.includes(query);
  });
  $("#catalog-title").textContent = KIND_COPY[state.kind].title;
  $("#new-resource").hidden = state.kind === "config";
  const activeName = state.current?.name || (state.kind === "config" ? "runtime-config" : null);
  $("#catalog-list").innerHTML = items.length ? items.map((item) => {
    const scope = item.source_level || "user";
    const label = item.title || item.name;
    const description = item.description || scope;
    const active = item.name === activeName && (state.kind !== "scenario" || scope === state.current?.scope);
    return `<button class="catalog-item${active ? " active" : ""}" data-name="${escapeHtml(item.name)}" data-scope="${escapeHtml(scope)}"><span class="catalog-icon">${KIND_COPY[state.kind].icon}</span><span class="catalog-copy"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(description)}</small></span>${item.writable === false ? '<span class="readonly-chip">READ ONLY</span>' : ""}</button>`;
  }).join("") : '<div class="empty-state">Ничего не найдено</div>';

  const roots = state.catalog.paths;
  const root = state.kind === "config" ? state.catalog.config.source_path
    : state.kind === "scenario" ? (roots.project_scenarios || roots.user_scenarios)
      : roots[`${state.kind}s`];
  $("#managed-root").textContent = root || "—";
}

function renderManagedPaths() {
  const labels = {
    data_dir: "Runtime data",
    user_scenarios: "User scenarios",
    project_scenarios: "Project scenarios",
    agents: "Agents",
    skills: "Skills",
    backups: "Backups",
  };
  $("#managed-paths").innerHTML = Object.entries(labels)
    .filter(([key]) => state.catalog.paths[key])
    .map(([key, label]) => `<div><dt>${label}</dt><dd>${escapeHtml(state.catalog.paths[key])}</dd></div>`)
    .join("");
}

async function loadCatalog() {
  state.catalog = await api("/api/studio/catalog");
  renderManagedPaths();
  renderCatalog();
}

async function selectResource(kind, scope, name = null) {
  state.kind = kind;
  state.isNew = false;
  const path = name
    ? `/api/studio/resources/${encodeURIComponent(kind)}/${encodeURIComponent(scope)}/${encodeURIComponent(name)}`
    : `/api/studio/resources/${encodeURIComponent(kind)}/${encodeURIComponent(scope)}`;
  const detail = await api(path);
  state.current = detail;
  state.original = clone(detail);
  renderEditor();
  renderCatalog();
}

function defaultScenario() {
  const model = state.catalog.choices.models[0] || "REPLACE_WITH_MODEL_ID";
  return {
    schema_version: "gigacode-agent-runtime/scenario-v1",
    kind: "Scenario",
    metadata: { name: "new-route", title: "Новый маршрут", description: "" },
    inputs: {},
    agents: {
      worker: { model, permissions: "read_only", system_prompt: "Выполни задачу и верни структурированный результат." },
    },
    steps: {
      work: { kind: "agent", agent: "worker", needs: [], prompt: { template: "Выполни задачу." }, output_schema: { type: "object" } },
    },
    result: { from: "${steps.work.output}" },
  };
}

function newResource() {
  state.isNew = true;
  if (state.kind === "scenario") {
    const scope = state.catalog.choices.scenario_scopes.includes("project") ? "project" : "user";
    state.current = { kind: "scenario", scope, name: "new-route", source_path: "Будет вычислен после Preview", writable: true, document: defaultScenario() };
  } else if (state.kind === "agent") {
    state.current = { kind: "agent", scope: "user", name: "new-agent", source_path: "~/.gigacode/agents/new-agent.md", writable: true, document: { name: "new-agent", description: "", model: state.catalog.choices.models[0] || "", approvalMode: "plan", tools: [], disallowedTools: [], system_prompt: "Опиши роль и правила работы агента." } };
  } else if (state.kind === "skill") {
    state.current = { kind: "skill", scope: "user", name: "new-skill", source_path: "~/.gigacode/skills/new-skill/SKILL.md", writable: true, document: { name: "new-skill", description: "", priority: 10, "user-invocable": true, "disable-model-invocation": false, paths: [], instructions: "# Инструкции\n\nОпиши пошаговый способ выполнения задачи." } };
  }
  state.original = clone(state.current);
  renderEditor();
  renderCatalog();
  markDirty();
}

function renderHeader() {
  const current = state.current;
  const title = state.kind === "config" ? "Настройки Runtime"
    : current.document?.metadata?.title || current.document?.name || current.name;
  $("#resource-kind").textContent = state.kind.toUpperCase();
  $("#resource-scope").textContent = current.scope;
  $("#resource-title").textContent = title;
  $("#resource-path").textContent = current.source_path || "Путь будет рассчитан на сервере";
  $("#preview-resource").disabled = current.writable === false;
  $("#activation-copy").textContent = state.kind === "config"
    ? "Настройки Runtime применятся после переподключения GigaCode к MCP."
    : "Сохранённый ресурс будет доступен новым планам после обновления справочника.";
}

function renderConfig(document) {
  const runtime = document.runtime;
  const gigacode = document.gigacode;
  const permissions = document.permissions;
  const web = document.web;
  const hashes = Object.entries(permissions.trusted_scenario_hashes || {}).map(([name, hash], index) => `<div class="repeat-card trust-row" data-index="${index}"><div class="field-grid"><div class="field"><label>Сценарий</label><input data-field="name" value="${escapeHtml(name)}"></div><div class="field"><label>SHA-256</label><input data-field="hash" value="${escapeHtml(hash)}"></div></div><button class="remove-button remove-repeat" data-group="trust" type="button">Удалить</button></div>`).join("");
  return [
    section("Runtime", "Лимиты параллельности, ожидания и выходных потоков", `<div class="field-grid three">${field("Data directory", "cfg-data-dir", runtime.data_dir, { wide: true, hint: "Абсолютный путь или путь внутри домашнего каталога" })}${field("Параллельных агентов", "cfg-max-parallel", runtime.max_parallel_agents, { type: "number", min: 1 })}${field("Timeout шага, сек.", "cfg-timeout", runtime.default_step_timeout_seconds, { type: "number", min: 1 })}${field("Graceful cancel, сек.", "cfg-cancel", runtime.graceful_cancel_seconds, { type: "number", min: 0 })}${field("Max stdout, байт", "cfg-stdout", runtime.max_stdout_bytes_per_step, { type: "number", min: 1 })}${field("Max stderr, байт", "cfg-stderr", runtime.max_stderr_bytes_per_step, { type: "number", min: 1 })}</div>`),
    section("GigaCode CLI", "Исполняемый файл, разрешённые модели и имена переменных окружения", `<div class="field-grid">${field("Executable", "cfg-executable", gigacode.executable, { wide: true })}${field("Model allowlist", "cfg-models", gigacode.model_allowlist.join("\n"), { type: "textarea", hint: "Одна модель на строку" })}${field("Environment allowlist", "cfg-environment", gigacode.environment_allowlist.join("\n"), { type: "textarea", hint: "Только имена; значения Studio не отображает" })}</div>`),
    section("Права", "Политика песочницы и защищённого full access", `<div class="field-grid three">${selectField("По умолчанию", "cfg-permission", permissions.default, state.catalog.choices.permissions)}${field("Full access одновременно", "cfg-full-parallel", permissions.max_parallel_full_access_agents, { type: "number", min: 1 })}${field("Итераций full access loop", "cfg-full-loop", permissions.max_full_access_loop_iterations, { type: "number", min: 1 })}<label class="check-field"><input id="cfg-allow-full" type="checkbox"${permissions.allow_full_access ? " checked" : ""}>Разрешить full access</label><label class="check-field"><input id="cfg-confirm-full" type="checkbox"${permissions.require_full_access_confirmation ? " checked" : ""}>Требовать подтверждение</label></div>`),
    section("Trusted scenario hashes", "Точные доверенные планы", `<div id="trust-list" class="repeat-list">${hashes}</div><button class="add-button" id="add-trust" type="button">+ Добавить доверенный хеш</button>`),
    section("Web UI", "Локальный сервер Dashboard и Studio", `<div class="field-grid three"><label class="check-field"><input id="cfg-web-enabled" type="checkbox"${web.enabled ? " checked" : ""}>Web UI включён</label>${field("Host", "cfg-web-host", web.host, { disabled: true })}${field("Port", "cfg-web-port", web.port, { hint: "auto или 1–65535" })}<label class="check-field"><input id="cfg-web-open" type="checkbox"${web.open_automatically ? " checked" : ""}>Открывать автоматически</label></div>`),
  ].join("");
}

function renderAgent(document, writable) {
  const readOnly = writable ? "" : '<div class="read-only-banner">Источник доступен только для чтения.</div>';
  return readOnly + section("Профиль агента", "Native Markdown agent с YAML front matter", `<div class="field-grid">${field("Имя", "agent-name", document.name, { disabled: !state.isNew })}${field("Описание", "agent-description", document.description || "")}${selectField("Модель", "agent-model", document.model || "", [{ value: "", label: "Без подсказки" }, ...state.catalog.choices.models])}${selectField("Approval mode", "agent-approval", document.approvalMode || "", [{ value: "", label: "По умолчанию" }, ...state.catalog.choices.approval_modes])}${field("Цвет", "agent-color", document.color || "")}${field("Разрешённые tools", "agent-tools", (document.tools || []).join("\n"), { type: "textarea", hint: "Один tool на строку" })}${field("Запрещённые tools", "agent-disallowed", (document.disallowedTools || []).join("\n"), { type: "textarea", hint: "Один tool на строку" })}${field("System prompt", "agent-prompt", document.system_prompt || "", { type: "textarea", wide: true, hint: "Тело .md; front matter сформирует Studio" })}</div>`);
}

function renderSkill(document, writable) {
  let banner = "";
  if (!writable) {
    banner = '<div class="read-only-banner"><span>Extension/bundled Skill доступен только для чтения.</span><button id="override-skill" type="button" class="button secondary">Создать user override</button></div>';
  } else if (state.current.override_from) {
    banner = `<div class="override-banner">User Skill перекроет источник: ${escapeHtml(state.current.override_from)}</div>`;
  }
  return banner + section("GigaCode Skill", "Инструкции и invocation metadata без ручного front matter", `<div class="field-grid">${field("Имя", "skill-name", document.name, { disabled: !state.isNew })}${field("Описание", "skill-description", document.description || "")}${field("Priority", "skill-priority", document.priority ?? "", { type: "number" })}${field("Paths", "skill-paths", (document.paths || []).join("\n"), { type: "textarea", hint: "Один glob на строку" })}<label class="check-field"><input id="skill-user" type="checkbox"${document["user-invocable"] === false ? "" : " checked"}>User invocable</label><label class="check-field"><input id="skill-model-disabled" type="checkbox"${document["disable-model-invocation"] ? " checked" : ""}>Запретить model invocation</label>${field("Инструкции Skill", "skill-instructions", document.instructions || "", { type: "textarea", wide: true, hint: "Тело SKILL.md; front matter сформирует Studio" })}</div>`);
}

function selectedOptions(values, choices) {
  const selected = new Set(values || []);
  return choices.map((item) => `<option value="${escapeHtml(item.skill_ref)}"${selected.has(item.skill_ref) ? " selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.source_level)}</option>`).join("");
}

function renderInputCard(name, input, index) {
  return `<div class="repeat-card input-card" data-name="${escapeHtml(name)}"><div class="repeat-card-header"><span class="repeat-number">I${index + 1}</span><strong>${escapeHtml(name)}</strong><button type="button" class="remove-button remove-repeat" data-group="input" data-name="${escapeHtml(name)}">Удалить</button></div><div class="field-grid three">${field("Ключ", `input-name-${index}`, name)}${selectField("Тип", `input-type-${index}`, input.type || "string", ["string", "integer", "number", "boolean", "object", "array"])}${field("Default (JSON или строка)", `input-default-${index}`, input.default === undefined ? "" : JSON.stringify(input.default))}<label class="check-field"><input id="input-required-${index}" type="checkbox"${input.required ? " checked" : ""}>Обязательный</label>${field("Описание", `input-description-${index}`, input.description || "", { wide: true })}</div></div>`;
}

function renderAgentCard(name, agent, index) {
  const refs = [{ value: "", label: "Inline system prompt" }, ...state.catalog.agents.map((item) => ({ value: item.agent_ref, label: `${item.name} · ${item.model || "model from route"}` }))];
  return `<div class="repeat-card route-agent-card" data-name="${escapeHtml(name)}"><div class="repeat-card-header"><span class="repeat-number">A${index + 1}</span><strong>${escapeHtml(name)}</strong><button type="button" class="remove-button remove-repeat" data-group="agent" data-name="${escapeHtml(name)}">Удалить</button></div><div class="field-grid three">${field("Alias", `route-agent-name-${index}`, name)}${selectField("Reusable agent", `route-agent-ref-${index}`, agent.agent_ref || "", refs)}${selectField("Model", `route-agent-model-${index}`, agent.model || "", state.catalog.choices.models.length ? state.catalog.choices.models : [agent.model || "REPLACE_WITH_MODEL_ID"])}${selectField("Permissions", `route-agent-permission-${index}`, agent.permissions || "read_only", state.catalog.choices.permissions)}${field("Allowed tools", `route-agent-tools-${index}`, (agent.allowed_tools || []).join(", "), { hint: "Через запятую" })}<div class="field"><label for="route-agent-skills-${index}">Skills</label><select id="route-agent-skills-${index}" multiple>${selectedOptions(agent.skill_refs, state.catalog.skills)}</select><small>Cmd/Ctrl — несколько значений</small></div>${field("System prompt file", `route-agent-prompt-file-${index}`, agent.system_prompt_file || "", { wide: true, hint: "Используется, если reusable agent не выбран" })}${field("System prompt (для inline)", `route-agent-prompt-${index}`, agent.system_prompt || "", { type: "textarea", wide: true, hint: "Оставьте пустым при использовании prompt file" })}</div></div>`;
}

function conditionFields(prefix, condition = {}) {
  const composite = !condition.ref && (condition.all || condition.any || condition.not);
  const preserved = composite
    ? `<div class="override-banner">Составное условие all/any/not сохранится без изменений.</div>`
    : "";
  return `<div data-original-condition="${escapeHtml(JSON.stringify(condition))}">${preserved}<div class="field-grid three">${field("Condition ref", `${prefix}-when-ref`, condition.ref || "")}${selectField("Operator", `${prefix}-when-op`, condition.op || "eq", ["eq", "ne", "lt", "lte", "gt", "gte", "contains", "exists"])}${field("Value (JSON)", `${prefix}-when-value`, condition.value === undefined ? "" : JSON.stringify(condition.value))}</div></div>`;
}

function renderAgentStepFields(step, prefix, agentNames) {
  const schema = JSON.stringify(step.output_schema || { type: "object" }, null, 2);
  return `<div class="field-grid three">${selectField("Agent", `${prefix}-agent`, step.agent || agentNames[0] || "", agentNames)}${field("Needs", `${prefix}-needs`, (step.needs || []).join(", "), { hint: "ID шагов через запятую" })}${field("Timeout, сек.", `${prefix}-timeout`, step.timeout_seconds || "", { type: "number" })}${field("Prompt template", `${prefix}-prompt`, step.prompt?.template || "", { type: "textarea", wide: true })}${field("Output schema (JSON)", `${prefix}-schema`, schema, { type: "textarea", wide: true })}</div><div class="nested-body"><h4>Необязательное условие when</h4>${conditionFields(prefix, step.when || {})}</div>`;
}

function renderNestedStep(name, step, index, parent, agentNames) {
  const prefix = `nested-${parent}-${index}`;
  return `<div class="repeat-card nested-step-card" data-name="${escapeHtml(name)}" data-parent="${escapeHtml(parent)}"><div class="repeat-card-header"><span class="repeat-number">N${index + 1}</span><strong>${escapeHtml(name)}</strong><button type="button" class="remove-button remove-repeat" data-group="nested" data-parent="${escapeHtml(parent)}" data-name="${escapeHtml(name)}">Удалить</button></div><div class="field-grid">${field("ID nested step", `${prefix}-name`, name)}</div>${renderAgentStepFields(step, prefix, agentNames)}</div>`;
}

function renderStepCard(name, step, index, agentNames) {
  const prefix = `route-step-${index}`;
  let body;
  if (step.kind === "loop") {
    const nested = Object.entries(step.body?.steps || {}).map(([nestedName, nestedStep], nestedIndex) => renderNestedStep(nestedName, nestedStep, nestedIndex, name, agentNames)).join("");
    body = `<div class="field-grid three">${field("Needs", `${prefix}-needs`, (step.needs || []).join(", "))}${field("Max iterations", `${prefix}-iterations`, step.max_iterations || 1, { type: "number", min: 1 })}${field("Timeout, сек.", `${prefix}-timeout`, step.timeout_seconds || 900, { type: "number", min: 1 })}${selectField("On limit", `${prefix}-limit`, step.on_limit || "fail", ["fail", "pause"])}${field("Until ref", `${prefix}-until-ref`, step.until?.ref || "${loop.steps.work.output.approved}")}${selectField("Until op", `${prefix}-until-op`, step.until?.op || "eq", ["eq", "ne", "lt", "lte", "gt", "gte", "contains", "exists"])}${field("Until value (JSON)", `${prefix}-until-value`, JSON.stringify(step.until?.value ?? true))}</div><div class="nested-body"><h4>Шаги одной итерации</h4><div class="repeat-list nested-list">${nested}</div><button type="button" class="add-button add-nested" data-parent="${escapeHtml(name)}">+ Добавить шаг в loop</button></div>`;
  } else {
    body = renderAgentStepFields(step, prefix, agentNames);
  }
  return `<div class="repeat-card route-step-card" data-name="${escapeHtml(name)}"><div class="repeat-card-header"><span class="repeat-number">${index + 1}</span><strong>${escapeHtml(name)}</strong><button type="button" class="remove-button remove-repeat" data-group="step" data-name="${escapeHtml(name)}">Удалить</button></div><div class="field-grid">${field("ID шага", `${prefix}-name`, name)}${selectField("Kind", `${prefix}-kind`, step.kind || "agent", ["agent", "loop"])}</div>${body}</div>`;
}

function renderScenario(document) {
  const metadata = document.metadata || {};
  const inputs = Object.entries(document.inputs || {}).map(([name, input], index) => renderInputCard(name, input, index)).join("");
  const agents = Object.entries(document.agents || {}).map(([name, agent], index) => renderAgentCard(name, agent, index)).join("");
  const agentNames = Object.keys(document.agents || {});
  const steps = Object.entries(document.steps || {}).map(([name, step], index) => renderStepCard(name, step, index, agentNames)).join("");
  const scopeChoices = state.catalog.choices.scenario_scopes.includes(state.current.scope)
    ? state.catalog.choices.scenario_scopes
    : [state.current.scope, ...state.catalog.choices.scenario_scopes];
  const readOnly = state.current.writable === false
    ? '<div class="read-only-banner"><span>Встроенный маршрут доступен только для чтения. Нажмите «Создать», чтобы собрать управляемую копию.</span></div>'
    : "";
  return readOnly + [
    section("Паспорт маршрута", "Имя определяет имя YAML-файла", `<div class="field-grid">${field("Name", "route-name", metadata.name || state.current.name, { disabled: !state.isNew })}${field("Title", "route-title", metadata.title || "")}${field("Description", "route-description", metadata.description || "", { wide: true })}${selectField("Scope", "route-scope", state.current.scope, scopeChoices, { disabled: !state.isNew })}${field("Max parallel agents", "route-max-parallel", document.max_parallel_agents || "", { type: "number", min: 1 })}</div>`),
    section("Inputs", "Типизированные входы маршрута", `<div id="route-inputs" class="repeat-list">${inputs}</div><button type="button" class="add-button" id="add-input">+ Добавить input</button>`),
    section("Agents", "Модели, права, reusable agents и разрешённые Skills", `<div id="route-agents" class="repeat-list">${agents}</div><button type="button" class="add-button" id="add-agent">+ Добавить агента</button>`),
    section("Route graph", "DAG-шаги и вложенные review/repair loops", `<div id="route-steps" class="repeat-list">${steps}</div><button type="button" class="add-button" id="add-step">+ Добавить шаг</button>`),
    section("Result", "Выход сценария", `<div class="field-grid">${field("From expression", "route-result", document.result?.from || "", { wide: true, hint: "Например ${steps.analyze.output}" })}</div>`),
  ].join("");
}

function renderEditor() {
  if (!state.current) return;
  $("#connection-state").hidden = true;
  $("#editor-shell").hidden = false;
  renderHeader();
  const document = state.current.document;
  const html = state.kind === "config" ? renderConfig(document)
    : state.kind === "scenario" ? renderScenario(document)
      : state.kind === "agent" ? renderAgent(document, state.current.writable)
        : renderSkill(document, state.current.writable);
  $("#editor-content").innerHTML = html;
  markClean();
}

function lines(value) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function commaList(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function numberValue(id, fallback = undefined) {
  const raw = $(id).value.trim();
  return raw === "" ? fallback : Number(raw);
}

function parseFlexible(value) {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try { return JSON.parse(trimmed); } catch (_error) { return trimmed; }
}

function parseSchema(value, label) {
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
    return parsed;
  } catch (_error) {
    throw new Error(`${label}: ожидается JSON object`);
  }
}

function collectConfig() {
  const trusted = {};
  $$(".trust-row").forEach((row) => {
    const name = $('[data-field="name"]', row).value.trim();
    const hash = $('[data-field="hash"]', row).value.trim();
    if (name && hash) trusted[name] = hash;
  });
  return {
    schema_version: state.current.document.schema_version,
    runtime: {
      data_dir: $("#cfg-data-dir").value.trim(),
      max_parallel_agents: numberValue("#cfg-max-parallel"),
      default_step_timeout_seconds: numberValue("#cfg-timeout"),
      graceful_cancel_seconds: numberValue("#cfg-cancel"),
      max_stdout_bytes_per_step: numberValue("#cfg-stdout"),
      max_stderr_bytes_per_step: numberValue("#cfg-stderr"),
    },
    gigacode: {
      executable: $("#cfg-executable").value.trim(),
      model_allowlist: lines($("#cfg-models").value),
      environment_allowlist: lines($("#cfg-environment").value),
    },
    permissions: {
      default: $("#cfg-permission").value,
      allow_full_access: $("#cfg-allow-full").checked,
      require_full_access_confirmation: $("#cfg-confirm-full").checked,
      max_parallel_full_access_agents: numberValue("#cfg-full-parallel"),
      max_full_access_loop_iterations: numberValue("#cfg-full-loop"),
      trusted_scenario_hashes: trusted,
    },
    web: {
      enabled: $("#cfg-web-enabled").checked,
      host: $("#cfg-web-host").value,
      port: $("#cfg-web-port").value.trim() === "auto" ? "auto" : Number($("#cfg-web-port").value),
      open_automatically: $("#cfg-web-open").checked,
    },
  };
}

function collectAgent() {
  return {
    name: $("#agent-name").value.trim(),
    description: $("#agent-description").value.trim(),
    model: $("#agent-model").value || undefined,
    approvalMode: $("#agent-approval").value || undefined,
    color: $("#agent-color").value.trim() || undefined,
    tools: lines($("#agent-tools").value),
    disallowedTools: lines($("#agent-disallowed").value),
    system_prompt: $("#agent-prompt").value,
  };
}

function collectSkill() {
  return {
    name: $("#skill-name").value.trim(),
    description: $("#skill-description").value.trim(),
    priority: numberValue("#skill-priority"),
    "user-invocable": $("#skill-user").checked,
    "disable-model-invocation": $("#skill-model-disabled").checked,
    paths: lines($("#skill-paths").value),
    instructions: $("#skill-instructions").value,
  };
}

function collectCondition(prefix) {
  const input = $(`#${prefix}-when-ref`);
  const ref = input?.value.trim();
  if (!ref) {
    const raw = input?.closest("[data-original-condition]")?.dataset.originalCondition;
    if (raw) {
      const original = JSON.parse(raw);
      if (original.all || original.any || original.not) return original;
    }
    return undefined;
  }
  return {
    ref,
    op: $(`#${prefix}-when-op`).value,
    value: parseFlexible($(`#${prefix}-when-value`).value),
  };
}

function collectAgentStep(card, prefix, original = {}) {
  const step = {
    ...clone(original),
    kind: "agent",
    agent: $(`#${prefix}-agent`).value,
    needs: commaList($(`#${prefix}-needs`).value),
    prompt: {
      ...(original.prompt || {}),
      template: $(`#${prefix}-prompt`).value,
    },
    output_schema: parseSchema($(`#${prefix}-schema`).value, "Output schema"),
  };
  const timeout = numberValue(`#${prefix}-timeout`);
  if (timeout !== undefined) step.timeout_seconds = timeout;
  else delete step.timeout_seconds;
  const when = collectCondition(prefix);
  if (when) step.when = when;
  else delete step.when;
  return step;
}

function collectScenario() {
  const inputs = {};
  $$(".input-card").forEach((card, index) => {
    const name = $(`#input-name-${index}`).value.trim();
    const input = {
      ...clone(state.current.document.inputs?.[card.dataset.name] || {}),
      type: $(`#input-type-${index}`).value,
      required: $(`#input-required-${index}`).checked,
    };
    const description = $(`#input-description-${index}`).value.trim();
    const defaultValue = parseFlexible($(`#input-default-${index}`).value);
    if (description) input.description = description;
    else delete input.description;
    if (defaultValue !== undefined) input.default = defaultValue;
    else delete input.default;
    inputs[name] = input;
  });

  const agents = {};
  $$(".route-agent-card").forEach((card, index) => {
    const name = $(`#route-agent-name-${index}`).value.trim();
    const ref = $(`#route-agent-ref-${index}`).value;
    const agent = {
      ...clone(state.current.document.agents?.[card.dataset.name] || {}),
      model: $(`#route-agent-model-${index}`).value,
      permissions: $(`#route-agent-permission-${index}`).value,
    };
    delete agent.agent_ref;
    delete agent.system_prompt;
    delete agent.system_prompt_file;
    if (ref) agent.agent_ref = ref;
    else if ($(`#route-agent-prompt-file-${index}`).value.trim()) {
      agent.system_prompt_file = $(`#route-agent-prompt-file-${index}`).value.trim();
    } else agent.system_prompt = $(`#route-agent-prompt-${index}`).value;
    const tools = commaList($(`#route-agent-tools-${index}`).value);
    const skills = [...$(`#route-agent-skills-${index}`).selectedOptions].map((option) => option.value);
    delete agent.allowed_tools;
    delete agent.skill_refs;
    if (tools.length) agent.allowed_tools = tools;
    if (skills.length) agent.skill_refs = skills;
    agents[name] = agent;
  });

  const steps = {};
  $$(".route-step-card").forEach((card, index) => {
    const prefix = `route-step-${index}`;
    const name = $(`#${prefix}-name`).value.trim();
    const kind = $(`#${prefix}-kind`).value;
    const original = clone(state.current.document.steps?.[card.dataset.name] || {});
    if (kind === "agent") {
      steps[name] = collectAgentStep(card, prefix, original);
      return;
    }
    const nestedSteps = {};
    $$(".nested-step-card", card).forEach((nestedCard, nestedIndex) => {
      const nestedPrefix = `nested-${card.dataset.name}-${nestedIndex}`;
      const nestedName = $(`#${CSS.escape(nestedPrefix)}-name`).value.trim();
      const originalNested = original.body?.steps?.[nestedCard.dataset.name] || {};
      nestedSteps[nestedName] = collectAgentStep(
        nestedCard,
        nestedPrefix,
        originalNested,
      );
    });
    steps[name] = {
      ...original,
      kind: "loop",
      needs: commaList($(`#${prefix}-needs`).value),
      max_iterations: numberValue(`#${prefix}-iterations`, 1),
      timeout_seconds: numberValue(`#${prefix}-timeout`, 900),
      on_limit: $(`#${prefix}-limit`).value,
      body: { ...(original.body || {}), steps: nestedSteps },
      until: {
        ref: $(`#${prefix}-until-ref`).value,
        op: $(`#${prefix}-until-op`).value,
        value: parseFlexible($(`#${prefix}-until-value`).value),
      },
    };
  });

  const document = {
    ...clone(state.current.document),
    schema_version: "gigacode-agent-runtime/scenario-v1",
    kind: "Scenario",
    metadata: {
      ...(state.current.document.metadata || {}),
      name: $("#route-name").value.trim(),
      title: $("#route-title").value.trim(),
    },
    inputs,
    agents,
    steps,
    result: { from: $("#route-result").value.trim() },
  };
  const description = $("#route-description").value.trim();
  const maxParallel = numberValue("#route-max-parallel");
  if (description) document.metadata.description = description;
  else delete document.metadata.description;
  if (maxParallel !== undefined) document.max_parallel_agents = maxParallel;
  else delete document.max_parallel_agents;
  return document;
}

function collectCurrentDocument() {
  if (state.kind === "config") return collectConfig();
  if (state.kind === "scenario") return collectScenario();
  if (state.kind === "agent") return collectAgent();
  return collectSkill();
}

function syncCurrent() {
  state.current.document = collectCurrentDocument();
  if (state.kind === "scenario") {
    state.current.name = state.current.document.metadata.name;
    state.current.scope = $("#route-scope").value;
  } else if (state.kind !== "config") {
    state.current.name = state.current.document.name;
  }
}

function uniqueName(base, existing) {
  let index = 1;
  let candidate = base;
  while (existing[candidate]) candidate = `${base}-${++index}`;
  return candidate;
}

function structuralEdit(action) {
  try {
    syncCurrent();
    action(state.current.document);
    renderEditor();
    markDirty();
  } catch (error) {
    toast(error.message, true);
  }
}

async function previewCurrent() {
  try {
    syncCurrent();
    const draft = {
      kind: state.kind,
      scope: state.current.scope,
      name: state.kind === "config" ? null : state.current.name,
      document: state.current.document,
    };
    $("#preview-resource").disabled = true;
    const preview = await api("/api/studio/preview", { method: "POST", body: JSON.stringify(draft) });
    state.preview = preview;
    $("#preview-summary").innerHTML = `<span>${escapeHtml(preview.target_path)}</span><span>${escapeHtml(preview.current_hash || "NEW FILE")}</span><span>${escapeHtml(preview.candidate_hash)}</span>`;
    $("#preview-validation").textContent = JSON.stringify(preview.validation, null, 2);
    $("#preview-diff").textContent = preview.diff || "Файл уже соответствует кандидату — diff пуст.";
    $("#preview-activation").textContent = preview.activation;
    $("#apply-resource").disabled = false;
    $("#preview-dialog").showModal();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("#preview-resource").disabled = state.current.writable === false;
  }
}

async function applyPreview() {
  if (!state.preview) return;
  const button = $("#apply-resource");
  button.disabled = true;
  try {
    const result = await api("/api/studio/apply", { method: "POST", body: JSON.stringify({ preview_id: state.preview.preview_id }) });
    $("#preview-dialog").close();
    state.original = clone(state.current);
    markClean();
    const backup = result.backup_path ? ` Backup: ${result.backup_path}` : "";
    toast(`Сохранено: ${result.target_path}.${backup}`);
    state.preview = null;
    if (state.kind !== "config") {
      const kind = state.kind;
      const scope = state.current.scope;
      const name = state.current.name;
      await loadCatalog();
      await selectResource(kind, scope, name);
    } else {
      $("#resource-path").textContent = result.target_path;
    }
  } catch (error) {
    toast(error.message, true);
  }
}

function switchKind(kind) {
  state.kind = kind;
  $$(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.kind === kind));
  $("#catalog-search").value = "";
  renderCatalog();
  const items = currentItems();
  if (kind === "config") selectResource("config", "selected").catch(showFatal);
  else if (items.length) selectResource(kind, items[0].source_level || "user", items[0].name).catch(showFatal);
  else newResource();
}

function showFatal(error) {
  $("#connection-state").innerHTML = `<div class="empty-state"><strong>Studio недоступна</strong><p>${escapeHtml(error.message)}</p></div>`;
  toast(error.message, true);
}

function bindEvents() {
  document.addEventListener("input", (event) => {
    if (event.target.closest("#editor-content")) markDirty();
  });
  $("#catalog-search").addEventListener("input", renderCatalog);
  $("#new-resource").addEventListener("click", newResource);
  $("#preview-resource").addEventListener("click", previewCurrent);
  $("#apply-resource").addEventListener("click", applyPreview);
  $("#reload-resource").addEventListener("click", () => {
    state.current = clone(state.original);
    renderEditor();
  });
  $$(".nav-item").forEach((node) => node.addEventListener("click", () => switchKind(node.dataset.kind)));

  $("#catalog-list").addEventListener("click", (event) => {
    const item = event.target.closest(".catalog-item");
    if (!item) return;
    const name = state.kind === "config" ? null : item.dataset.name;
    selectResource(state.kind, item.dataset.scope, name).catch(showFatal);
  });

  $("#editor-content").addEventListener("click", (event) => {
    const target = event.target;
    if (target.id === "override-skill") {
      state.current.override_from = state.current.source_path;
      state.current.scope = "user";
      state.current.writable = true;
      state.current.source_path = `${state.catalog.paths.skills}/${state.current.name}/SKILL.md`;
      state.isNew = false;
      renderEditor();
      markDirty();
      return;
    }
    if (target.id === "add-trust") {
      structuralEdit((document) => { document.permissions.trusted_scenario_hashes[`scenario-${Date.now()}`] = "sha256:"; });
      return;
    }
    if (target.id === "add-input") {
      structuralEdit((document) => { document.inputs[uniqueName("input", document.inputs)] = { type: "string", required: false }; });
      return;
    }
    if (target.id === "add-agent") {
      structuralEdit((document) => {
        const name = uniqueName("agent", document.agents);
        document.agents[name] = { model: state.catalog.choices.models[0] || "REPLACE_WITH_MODEL_ID", permissions: "read_only", system_prompt: "Опиши задачу агента." };
      });
      return;
    }
    if (target.id === "add-step") {
      structuralEdit((document) => {
        const name = uniqueName("step", document.steps);
        document.steps[name] = { kind: "agent", agent: Object.keys(document.agents)[0] || "agent", needs: [], prompt: { template: "Выполни шаг." }, output_schema: { type: "object" } };
      });
      return;
    }
    const addNested = target.closest(".add-nested");
    if (addNested) {
      const topCard = addNested.closest(".route-step-card");
      const topIndex = $$(".route-step-card").indexOf(topCard);
      const parentName = $(`#route-step-${topIndex}-name`).value.trim();
      structuralEdit((document) => {
        const steps = document.steps[parentName].body.steps;
        const name = uniqueName("work", steps);
        steps[name] = { kind: "agent", agent: Object.keys(document.agents)[0] || "agent", needs: [], prompt: { template: "Выполни итерацию." }, output_schema: { type: "object" } };
      });
      return;
    }
    const remove = target.closest(".remove-repeat");
    if (!remove) return;
    let actualName = remove.dataset.name;
    let actualParent = remove.dataset.parent;
    if (remove.dataset.group === "input") {
      const index = $$(".input-card").indexOf(remove.closest(".input-card"));
      actualName = $(`#input-name-${index}`).value.trim();
    } else if (remove.dataset.group === "agent") {
      const index = $$(".route-agent-card").indexOf(remove.closest(".route-agent-card"));
      actualName = $(`#route-agent-name-${index}`).value.trim();
    } else if (remove.dataset.group === "step") {
      const index = $$(".route-step-card").indexOf(remove.closest(".route-step-card"));
      actualName = $(`#route-step-${index}-name`).value.trim();
    } else if (remove.dataset.group === "nested") {
      const topCard = remove.closest(".route-step-card");
      const topIndex = $$(".route-step-card").indexOf(topCard);
      const nestedIndex = $$(".nested-step-card", topCard).indexOf(remove.closest(".nested-step-card"));
      actualParent = $(`#route-step-${topIndex}-name`).value.trim();
      actualName = $(`#nested-${CSS.escape(topCard.dataset.name)}-${nestedIndex}-name`).value.trim();
    }
    structuralEdit((document) => {
      if (remove.dataset.group === "trust") {
        const rows = Object.keys(document.permissions.trusted_scenario_hashes);
        delete document.permissions.trusted_scenario_hashes[rows[Number(remove.closest(".trust-row").dataset.index)]];
      } else if (remove.dataset.group === "input") delete document.inputs[actualName];
      else if (remove.dataset.group === "agent") delete document.agents[actualName];
      else if (remove.dataset.group === "step") delete document.steps[actualName];
      else if (remove.dataset.group === "nested") delete document.steps[actualParent].body.steps[actualName];
    });
  });

  $("#editor-content").addEventListener("change", (event) => {
    if (!event.target.id?.startsWith("route-step-") || !event.target.id.endsWith("-kind")) return;
    const card = event.target.closest(".route-step-card");
    const name = card.dataset.name;
    const kind = event.target.value;
    event.target.value = state.current.document.steps[name]?.kind || "agent";
    structuralEdit((document) => {
      if (kind === "loop") {
        document.steps[name] = { kind: "loop", needs: [], max_iterations: 3, timeout_seconds: 900, on_limit: "fail", body: { steps: { work: { kind: "agent", agent: Object.keys(document.agents)[0] || "agent", needs: [], prompt: { template: "Выполни итерацию." }, output_schema: { type: "object" } } } }, until: { ref: "${loop.steps.work.output.approved}", op: "eq", value: true } };
      } else {
        document.steps[name] = { kind: "agent", agent: Object.keys(document.agents)[0] || "agent", needs: [], prompt: { template: "Выполни шаг." }, output_schema: { type: "object" } };
      }
    });
  });
}

async function bootstrap() {
  bindEvents();
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get("token");
  history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  let auth;
  if (token) {
    auth = await api("/api/bootstrap", { method: "POST", body: JSON.stringify({ token }) });
  } else {
    try {
      auth = await api("/api/session");
    } catch (_error) {
      throw new Error("Одноразовый bootstrap token отсутствует, а действующая сессия не найдена. Откройте Studio заново из GigaCode.");
    }
  }
  state.csrf = auth.csrf_token;
  await loadCatalog();
  await selectResource("config", "selected");
}

bootstrap().catch(showFatal);
