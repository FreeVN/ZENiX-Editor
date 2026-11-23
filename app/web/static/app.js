"use strict";

// ZENiX Ringbus Editor: volledige werkkopie in geheugen, opslaan post de hele staat.
// Geen externe requests: alles komt van de lokale FastAPI-server.

const TYPE_OPTIONS = [
  ["", 0], ["fire", 1], ["smoke", 2], ["di", 3], ["do", 4],
  ["motorless", 5], ["smoke op", 6], ["smoke cl", 7], ["smoke o/c", 8],
];

const DEVICE_OPTIONS = [
  ["", 0], ["FIRE", 1], ["SMOKE", 2], ["FIO_8_8", 3], ["FIRE2M", 4],
  ["MOTORLESS", 5], ["DIN", 6], ["DOM12", 7], ["SMOKE OP", 10], ["SMOKE CL", 11],
  ["SMOKE O/C", 12], ["MOTORLESS2M", 13], ["FIRE2S", 14], ["DOM08", 15],
  ["FIO_12_0", 16], ["FIO_8_4", 17], ["FIO_0_12", 18], ["FIRE2B", 19],
  ["FIRE_LOCAL", 20], ["DOM16", 21], ["SMOKE_LOCAL", 22], ["DIN2", 23], ["DOM2", 24],
];

const MAX_UNDO = 50;

let state = null;
let sid = null;
let filename = null;
let savedSnapshot = null;
let undoStack = [];
let redoStack = [];
let serverWarnings = [];
let nameRules = null;
let selected = new Set();
let keyCounter = 0;
let lastMessage = "";
let toastTimer = null;

const $ = (id) => document.getElementById(id);

// --------------------------------------------------------------- hulpfuncties

function newKey() {
  keyCounter += 1;
  return "e" + keyCounter;
}

function byKey(key) {
  return state ? state.elements.find((e) => e._key === key) : null;
}

function snapshot() {
  return JSON.stringify({
    project: state.project,
    rings: state.rings,
    zones: state.zones,
    elements: state.elements,
    alarms: state.alarms,
  });
}

function fmtId(element) {
  return element.id === null || element.id === undefined ? "nieuw" : element.id;
}

function zoneName(ref) {
  if (ref === null || ref === undefined || ref === "") return "";
  const match = state.zones.find(
    (z) => z.id !== null && z.id !== undefined && String(z.id) === String(ref));
  return match ? match.name : String(ref);
}

function parseZoneRefs(text) {
  const parts = String(text || "").replace(/;/g, ",").split(",");
  const refs = [];
  parts.forEach((part) => {
    const token = part.trim();
    if (!token) return;
    if (/^\d+$/.test(token)) {
      const asId = Number(token);
      const exists = state.zones.some((z) => Number(z.id) === asId);
      if (exists) { refs.push(asId); return; }
    }
    const zone = state.zones.find((z) => (z.name || "").trim() === token);
    if (!zone) throw new Error("Onbekende zone: " + token);
    refs.push(zone.id === null || zone.id === undefined ? zone.name : zone.id);
  });
  return refs;
}

function toast(message, kind) {
  const box = $("toast");
  box.textContent = message;
  box.className = "toast" + (kind ? " " + kind : "");
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => box.classList.add("hidden"), 4200);
}

// ------------------------------------------------------------- state mutatie

function pushUndo() {
  undoStack.push(snapshot());
  if (undoStack.length > MAX_UNDO) undoStack.shift();
  redoStack = [];
  updateHistoryButtons();
}

function mutate(fn) {
  if (!state) return;
  pushUndo();
  fn();
  renderAll();
}

function undo() {
  if (!undoStack.length) return;
  redoStack.push(snapshot());
  restoreSnapshot(undoStack.pop());
}

function redo() {
  if (!redoStack.length) return;
  undoStack.push(snapshot());
  restoreSnapshot(redoStack.pop());
}

function restoreSnapshot(json) {
  const data = JSON.parse(json);
  state.project = data.project;
  state.rings = data.rings;
  state.zones = data.zones;
  state.elements = data.elements;
  state.alarms = data.alarms || [];
  renderAll();
  updateHistoryButtons();
}

function updateHistoryButtons() {
  $("btn-undo").disabled = !undoStack.length;
  $("btn-redo").disabled = !redoStack.length;
}

function regroup() {
  const order = state.rings.map((r) => r.id);
  const known = state.elements.filter((e) => order.indexOf(e.ringId) >= 0);
  const rest = state.elements.filter((e) => order.indexOf(e.ringId) < 0);
  const grouped = [];
  order.forEach((ringId) => {
    known.filter((e) => e.ringId === ringId).forEach((e) => grouped.push(e));
  });
  state.elements = grouped.concat(rest);
}

// ------------------------------------------------------------------ openen

function applyOpen(data) {
  state = {
    project: data.state.project || "",
    rings: data.state.rings || [],
    zones: data.state.zones || [],
    alarms: data.state.alarms || [],
    elements: (data.state.elements || []).map((e) => {
      const copy = Object.assign({}, e);
      copy._key = newKey();
      return copy;
    }),
  };
  sid = data.sid;
  filename = data.filename || "";
  savedSnapshot = snapshot();
  undoStack = [];
  redoStack = [];
  selected = new Set();
  serverWarnings = data.warnings || [];
  nameRules = data.name_rules || null;
  lastMessage = "";

  $("toolbar").hidden = false;
  $("workspace").hidden = false;
  $("path-input").value = "";
  $("filter-input").value = "";
  renderAll();
  updateHistoryButtons();
  toast("Project geopend: " + (state.project || filename), "ok");
}

async function openFile(file) {
  if (!file) return;
  if (!confirmDiscard()) return;
  try {
    const buffer = await file.arrayBuffer();
    const response = await fetch("/api/projects/open", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Filename": file.name,
      },
      body: buffer,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Openen mislukt (" + response.status + ")");
    applyOpen(body);
  } catch (err) {
    toast(err.message, "error");
  }
}

async function openPath() {
  const path = $("path-input").value.trim();
  if (!path) { toast("Geef een pad onder samples/ op", "error"); return; }
  if (!confirmDiscard()) return;
  try {
    const response = await fetch("/api/projects/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Openen mislukt (" + response.status + ")");
    applyOpen(body);
  } catch (err) {
    toast(err.message, "error");
  }
}

function confirmDiscard() {
  if (!state) return true;
  return snapshot() === savedSnapshot || window.confirm(
    "Er zijn niet-opgeslagen wijzigingen. Doorgaan en ze laten vallen?");
}

async function closeProject() {
  if (!state) return;
  if (!confirmDiscard()) return;
  const current = sid;
  sid = null;
  state = null;
  filename = null;
  savedSnapshot = null;
  undoStack = [];
  redoStack = [];
  selected = new Set();
  serverWarnings = [];
  nameRules = null;
  lastMessage = "";
  $("toolbar").hidden = true;
  $("workspace").hidden = true;
  $("element-body").textContent = "";
  $("zones-body").textContent = "";
  $("alarms-body").textContent = "";
  $("matrix-head").textContent = "";
  $("matrix-body").textContent = "";
  updateStatus();
  updateHistoryButtons();
  if (current) {
    fetch("/api/projects/" + current, { method: "DELETE" }).catch(() => {});
  }
}

function reloadProject() {
  if (!state || savedSnapshot === null) return;
  if (!window.confirm("Alle niet-opgeslagen wijzigingen terugdraaien?")) return;
  restoreSnapshot(savedSnapshot);
  lastMessage = "Herladen zonder opslaan; het project is ongemoeid.";
  updateStatus();
}

// ------------------------------------------------------------ naamregels

// De server is de autoriteit; deze controle gebruikt dezelfde regelset uit het
// open-response (name_rules) en dezelfde baseline als de server, zodat alleen
// toegevoegde of gewijzigde velden een save blokkeren. Een overtreding die al
// in het bronproject zat, blijft een waarschuwing (zie name_check.js).

function baselineState() {
  if (savedSnapshot === null) return null;
  try {
    return JSON.parse(savedSnapshot);
  } catch (err) {
    return null;
  }
}

function nameEntries() {
  if (!state || typeof window.ZenixNameCheck === "undefined") return [];
  return window.ZenixNameCheck.collect(state, nameRules, baselineState());
}

function elementNameIssues() {
  const issues = new Map();
  nameEntries().forEach((entry) => {
    if (entry.soort === "element" && entry.key !== undefined) issues.set(entry.key, entry);
  });
  return issues;
}

function zoneNameIssues() {
  const issues = new Map();
  nameEntries().forEach((entry) => {
    if (entry.soort === "zone") issues.set(entry.index, entry);
  });
  return issues;
}

function ringNameIssues() {
  const issues = new Map();
  nameEntries().forEach((entry) => {
    if (entry.soort === "ring") issues.set(entry.index, entry);
  });
  return issues;
}

function alarmNameIssues() {
  const issues = new Map();
  nameEntries().forEach((entry) => {
    if (entry.soort === "alarm") issues.set(entry.index, entry);
  });
  return issues;
}

// Alle naamproblemen; `changed` onderscheidt blokkades van bestaande fouten.
function collectNameIssues() {
  return nameEntries();
}

function blockingNameIssues() {
  return collectNameIssues().filter((entry) => entry.changed);
}

function applyNameIssue(cell, input, issue) {
  if (issue.changed) {
    input.classList.add("invalid-name");
  } else {
    input.classList.add("name-warn");
    cell.classList.add("name-warn");
  }
  input.title = issue.message;
  input.setAttribute("aria-invalid", issue.changed ? "true" : "false");
  const note = document.createElement("span");
  note.className = issue.changed ? "name-error" : "name-warning";
  note.textContent = issue.message;
  cell.appendChild(note);
}

function focusNameField(entry) {
  let selector = null;
  if (entry.soort === "element") {
    selector = 'input[data-name-key="' + entry.key + '"]';
  } else if (entry.soort === "zone" || entry.soort === "ring" || entry.soort === "alarm") {
    selector = 'input[data-name-soort="' + entry.soort + '"][data-name-index="' + entry.index + '"]';
  }
  const input = selector ? document.querySelector(selector) : null;
  if (input) {
    input.focus();
    if (input.scrollIntoView) input.scrollIntoView({ block: "center" });
  }
  return input;
}

function focusViolation(violation) {
  if (!violation || !state) return;
  if (violation.soort === "element") {
    const element = state.elements.find((e) => String(e.id) === String(violation.id));
    if (element) focusNameField({ soort: "element", key: element._key });
  } else if (violation.soort === "zone") {
    const index = state.zones.findIndex((z) => String(z.id) === String(violation.id));
    if (index >= 0) focusNameField({ soort: "zone", index: index });
  } else if (violation.soort === "ring") {
    const index = state.rings.findIndex((r) => String(r.id) === String(violation.id));
    if (index >= 0) focusNameField({ soort: "ring", index: index });
  } else if (violation.soort === "alarm") {
    const index = state.alarms.findIndex((a) => String(a.id) === String(violation.id));
    if (index >= 0) focusNameField({ soort: "alarm", index: index });
  }
}

// ------------------------------------------------------------------ opslaan

function payload() {
  return {
    project: state.project,
    rings: state.rings,
    zones: state.zones,
    alarms: state.alarms,
    elements: state.elements.map((element) => {
      const copy = Object.assign({}, element);
      delete copy._key;
      return copy;
    }),
  };
}

async function save() {
  if (!sid || !state) return;

  const nameIssues = blockingNameIssues();
  if (nameIssues.length) {
    lastMessage = nameIssues.length + " naamfout(en): " + nameIssues[0].message;
    toast(lastMessage, "error");
    updateStatus();
    focusNameField(nameIssues[0]);
    return;
  }

  try {
    const response = await fetch("/api/projects/" + sid + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (body.detail && body.detail.error === "invalid_names") {
        const violations = body.detail.violations || [];
        const first = violations[0] || {};
        lastMessage = violations.length + " naamfout(en)" +
          (first.code ? ": " + window.ZenixNameCheck.formatMessage(first.code, nameRules, first) : "");
        toast(lastMessage, "error");
        updateStatus();
        focusViolation(first);
        return;
      }
      const detailText = typeof body.detail === "string" ? body.detail : "";
      throw new Error(detailText || "Opslaan mislukt (" + response.status + ")");
    }
    adoptServerState(body.state);
    savedSnapshot = snapshot();
    serverWarnings = body.warnings || [];
    lastMessage = "Opgeslagen als " + body.filename;
    renderAll();
    toast(lastMessage, "ok");
    const link = document.createElement("a");
    link.href = body.download;
    link.download = body.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } catch (err) {
    toast(err.message, "error");
    lastMessage = err.message;
    updateStatus();
  }
}

// Neem de staat over die de server na het opslaan uit het bestand terugleest:
// echte ids, vendor-namen en de opgeslagen volgorde. Bestaande _key's blijven
// per element-id behouden; selectie wordt opgeschoond. De undo/redo-stacks
// blijven bewust ongemoeid: ze zijn de geschiedenis van wat de gebruiker deed en
// undo na een save moet die bewerking terugzetten, niet een herschreven versie.
function adoptServerState(serverState) {
  if (!state || !serverState) return;
  const keyById = new Map();
  state.elements.forEach((element) => {
    if (element.id !== null && element.id !== undefined) {
      keyById.set(String(element.id), element._key);
    }
  });
  const used = new Set();
  state.project = serverState.project || "";
  state.rings = serverState.rings || [];
  state.zones = serverState.zones || [];
  state.alarms = serverState.alarms || [];
  state.elements = (serverState.elements || []).map((raw) => {
    const copy = Object.assign({}, raw);
    const oldKey = copy.id !== null && copy.id !== undefined
      ? keyById.get(String(copy.id)) : undefined;
    if (oldKey !== undefined && !used.has(oldKey)) {
      copy._key = oldKey;
      used.add(oldKey);
    } else {
      copy._key = newKey();
      used.add(copy._key);
    }
    return copy;
  });
  selected = new Set(Array.from(selected).filter((key) => used.has(key)));
  updateHistoryButtons();
}

// ---------------------------------------------------------------- rendering

function renderAll() {
  if (!state) return;
  $("project-name").value = state.project || "";
  $("project-file").textContent = filename ? "bron: " + filename : "";
  renderRings();
  renderZones();
  renderAlarms();
  renderAddOptions();
  renderElements();
  renderMatrix();
  renderWarnings();
  updateStatus();
}

function renderRings() {
  const body = $("rings-body");
  body.textContent = "";
  const issues = ringNameIssues();
  state.rings.forEach((ring, index) => {
    const row = document.createElement("tr");

    const idCell = document.createElement("td");
    idCell.textContent = ring.id === null || ring.id === undefined ? "nieuw" : ring.id;
    idCell.className = "id-cell";
    row.appendChild(idCell);

    const nameCell = document.createElement("td");
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = ring.name || "";
    nameInput.dataset.nameSoort = "ring";
    nameInput.dataset.nameIndex = String(index);
    nameInput.addEventListener("change", () => mutate(() => {
      state.rings[index].name = nameInput.value.trim();
    }));
    nameCell.appendChild(nameInput);
    if (issues.has(index)) applyNameIssue(nameCell, nameInput, issues.get(index));
    row.appendChild(nameCell);

    const hostCell = document.createElement("td");
    const hostInput = document.createElement("input");
    hostInput.type = "text";
    hostInput.value = ring.host || "";
    hostInput.addEventListener("change", () => mutate(() => {
      state.rings[index].host = hostInput.value.trim();
    }));
    hostCell.appendChild(hostInput);
    row.appendChild(hostCell);

    body.appendChild(row);
  });
}

function addRing(event) {
  event.preventDefault();
  const nameInput = $("ring-new-name");
  const hostInput = $("ring-new-host");
  const name = nameInput.value.trim();
  if (!name) { toast("Geef de ring een naam", "error"); return; }
  if (state.rings.some((r) => (r.name || "").trim() === name)) {
    toast("Er bestaat al een ring met deze naam", "error");
    return;
  }
  const host = hostInput.value.trim() || "localhost";
  mutate(() => {
    state.rings.push({ id: null, name: name, host: host, cpuType: 5 });
  });
  nameInput.value = "";
  hostInput.value = "";
}

function renderZones() {
  const body = $("zones-body");
  body.textContent = "";
  const issues = zoneNameIssues();
  state.zones.forEach((zone, index) => {
    const row = document.createElement("tr");

    const idCell = document.createElement("td");
    idCell.textContent = zone.id === null || zone.id === undefined ? "nieuw" : zone.id;
    idCell.className = "id-cell";
    row.appendChild(idCell);

    const nameCell = document.createElement("td");
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = zone.name || "";
    nameInput.dataset.nameSoort = "zone";
    nameInput.dataset.nameIndex = String(index);
    nameInput.addEventListener("change", () => mutate(() => {
      state.zones[index].name = nameInput.value.trim();
    }));
    nameCell.appendChild(nameInput);
    if (issues.has(index)) applyNameIssue(nameCell, nameInput, issues.get(index));
    row.appendChild(nameCell);

    const descCell = document.createElement("td");
    const descInput = document.createElement("input");
    descInput.type = "text";
    descInput.value = zone.description || "";
    descInput.addEventListener("change", () => mutate(() => {
      state.zones[index].description = descInput.value.trim();
    }));
    descCell.appendChild(descInput);
    row.appendChild(descCell);

    const actionCell = document.createElement("td");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Verwijderen";
    remove.addEventListener("click", () => deleteZone(index));
    actionCell.appendChild(remove);
    row.appendChild(actionCell);

    body.appendChild(row);
  });
}

function renderAlarms() {
  const body = $("alarms-body");
  if (!body) return;
  body.textContent = "";
  const issues = alarmNameIssues();
  state.alarms.forEach((alarm, index) => {
    const row = document.createElement("tr");

    const idCell = document.createElement("td");
    idCell.textContent = alarm.id === null || alarm.id === undefined ? index : alarm.id;
    idCell.className = "id-cell";
    row.appendChild(idCell);

    const ringCell = document.createElement("td");
    const ring = state.rings.find((r) => String(r.id) === String(alarm.ringId));
    ringCell.textContent = ring ? ring.name : (alarm.ringId === -1 ? "" : String(alarm.ringId));
    row.appendChild(ringCell);

    const nameCell = document.createElement("td");
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = alarm.name || "";
    nameInput.dataset.nameSoort = "alarm";
    nameInput.dataset.nameIndex = String(index);
    nameInput.addEventListener("change", () => mutate(() => {
      state.alarms[index].name = nameInput.value.trim();
    }));
    nameCell.appendChild(nameInput);
    if (issues.has(index)) applyNameIssue(nameCell, nameInput, issues.get(index));
    row.appendChild(nameCell);

    const descCell = document.createElement("td");
    const descInput = document.createElement("input");
    descInput.type = "text";
    descInput.value = alarm.description || "";
    descInput.addEventListener("change", () => mutate(() => {
      state.alarms[index].description = descInput.value.trim();
    }));
    descCell.appendChild(descInput);
    row.appendChild(descCell);

    body.appendChild(row);
  });
}

function deleteZone(index) {
  const zone = state.zones[index];
  if (!window.confirm("Zone '" + (zone.name || "?") + "' verwijderen?")) return;
  mutate(() => {
    const refs = new Set();
    if (zone.id !== null && zone.id !== undefined) refs.add(Number(zone.id));
    refs.add(zone.name);
    state.elements.forEach((element) => {
      element.zones = (element.zones || []).filter(
        (ref) => !refs.has(Number(ref)) && !refs.has(String(ref)));
    });
    state.zones.splice(index, 1);
  });
}

function addZone(event) {
  event.preventDefault();
  const nameInput = $("zone-new-name");
  const descInput = $("zone-new-desc");
  const name = nameInput.value.trim();
  if (!name) { toast("Geef de zone een naam", "error"); return; }
  if (state.zones.some((z) => (z.name || "").trim() === name)) {
    toast("Er bestaat al een zone met deze naam", "error");
    return;
  }
  mutate(() => {
    state.zones.push({ id: null, name: name, description: descInput.value.trim(), elements: [] });
  });
  nameInput.value = "";
  descInput.value = "";
}

function optionList(select, options, current) {
  select.textContent = "";
  options.forEach(([label, value]) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label === "" ? "(geen)" : label + " (" + value + ")";
    select.appendChild(option);
  });
  if (current !== undefined && current !== null &&
      !options.some(([, value]) => String(value) === String(current))) {
    const option = document.createElement("option");
    option.value = String(current);
    option.textContent = "onbekend (" + current + ")";
    select.appendChild(option);
  }
  if (current !== undefined && current !== null) select.value = String(current);
}

function renderAddOptions() {
  const ringSelect = $("add-ring");
  ringSelect.textContent = "";
  state.rings.forEach((ring) => {
    if (ring.id === null || ring.id === undefined) return;
    const option = document.createElement("option");
    option.value = String(ring.id);
    option.textContent = ring.name + " (" + ring.id + ")";
    ringSelect.appendChild(option);
  });
  optionList($("add-type"), TYPE_OPTIONS, 3);
  optionList($("add-device"), DEVICE_OPTIONS, 1);
}

function warningInfo() {
  const keys = new Set();
  const items = [];
  const names = {};
  const addresses = {};
  state.elements.forEach((element) => {
    const name = (element.name || "").trim();
    if (!name) {
      keys.add(element._key);
      items.push("Element zonder naam (id " + fmtId(element) + ")");
    } else {
      (names[name] = names[name] || []).push(element);
      if (/[\t\n\r]/.test(name)) {
        keys.add(element._key);
        items.push("Naam met tab/regeleinde: '" + name.replace(/[\t\n\r]/g, " ") + "'");
      }
    }
    if (element.unit !== "" && element.address !== "") {
      const key = [element.ringId, element.unit, element.address].join("|");
      (addresses[key] = addresses[key] || []).push(element);
    }
  });
  Object.keys(names).forEach((name) => {
    if (names[name].length > 1) {
      names[name].forEach((element) => keys.add(element._key));
      items.push("Naam '" + name + "' komt " + names[name].length + " keer voor");
    }
  });
  Object.keys(addresses).forEach((key) => {
    if (addresses[key].length > 1) {
      const parts = key.split("|");
      addresses[key].forEach((element) => keys.add(element._key));
      items.push("Ring " + parts[0] + ", unit " + parts[1] + ", adres " + parts[2] +
        " komt " + addresses[key].length + " keer voor");
    }
  });
  const zoneNames = {};
  state.zones.forEach((zone) => {
    const name = (zone.name || "").trim();
    if (!name) items.push("Zone zonder naam");
    else (zoneNames[name] = zoneNames[name] || []).push(zone);
  });
  Object.keys(zoneNames).forEach((name) => {
    if (zoneNames[name].length > 1) items.push("Zonenaam '" + name + "' komt dubbel voor");
  });
  return { keys: keys, items: items };
}

const BOOL_FIELDS = [["enabled", "en."], ["invert", "inv."], ["normalOpen", "n.o."]];

function renderElements() {
  const body = $("element-body");
  body.textContent = "";
  const info = warningInfo();
  const nameIssues = elementNameIssues();
  const filter = ($("filter-input").value || "").trim().toLowerCase();

  const ringIds = state.rings.map((r) => r.id);
  state.elements.forEach((element) => {
    if (ringIds.indexOf(element.ringId) < 0) ringIds.push(element.ringId);
  });

  ringIds.forEach((ringId) => {
    const ring = state.rings.find((r) => r.id === ringId);
    const elements = state.elements.filter((e) => e.ringId === ringId);
    if (!elements.length) return;

    const header = document.createElement("tr");
    header.className = "ring-header";
    const headerCell = document.createElement("td");
    headerCell.colSpan = 16;
    headerCell.textContent = "Ring " + ringId + " \u2014 " + (ring ? ring.name : "onbekend") +
      " (" + elements.length + " elementen)";
    header.appendChild(headerCell);
    body.appendChild(header);

    elements.forEach((element) => {
      if (filter) {
        const haystack = [element.name, element.unitId, element.description,
          element.alarmFunction].join(" ").toLowerCase();
        if (haystack.indexOf(filter) < 0) return;
      }
      body.appendChild(buildRow(element, info.keys.has(element._key),
        nameIssues.get(element._key)));
    });
  });
}

function matrixValue(element, alarmId) {
  const cells = element.controlMatrix;
  if (!Array.isArray(cells)) return -1;
  for (let i = 0; i < cells.length; i += 1) {
    const cell = cells[i];
    if (cell && typeof cell === "object") {
      if (String(cell.alarmId) === String(alarmId)) {
        return cell.waarde === null || cell.waarde === undefined ? -1 : Number(cell.waarde);
      }
    } else if (String(i) === String(alarmId)) {
      return Number(cell);
    }
  }
  return -1;
}

// Houd de matrix exact één cel per alarm, in alarmvolgorde. Dit voorkomt dat
// een gedeeltelijke lijst uit een oude staat de lengte-invariant breekt.
function ensureMatrix(element) {
  const existing = Array.isArray(element.controlMatrix) ? element.controlMatrix : [];
  const byId = {};
  existing.forEach((cell, index) => {
    if (cell && typeof cell === "object") byId[String(cell.alarmId)] = cell.waarde;
    else byId[String(index)] = cell;
  });
  element.controlMatrix = state.alarms.map((alarm, index) => {
    const alarmId = alarm.id === null || alarm.id === undefined ? index : alarm.id;
    const value = byId[String(alarmId)];
    return {
      alarmId: Number(alarmId),
      waarde: value === null || value === undefined ? -1 : Number(value),
    };
  });
}

function setMatrixCell(element, alarmId, value) {
  ensureMatrix(element);
  const cell = element.controlMatrix.find((c) => String(c.alarmId) === String(alarmId));
  if (cell) cell.waarde = value;
}

function renderMatrix() {
  const head = $("matrix-head");
  const body = $("matrix-body");
  if (!head || !body) return;
  head.textContent = "";
  body.textContent = "";

  const elementHead = document.createElement("th");
  elementHead.textContent = "element";
  head.appendChild(elementHead);
  state.alarms.forEach((alarm, index) => {
    const th = document.createElement("th");
    th.textContent = (alarm.name || "alarm " + index) + " (" + index + ")";
    head.appendChild(th);
  });
  const actionHead = document.createElement("th");
  actionHead.textContent = "rij";
  head.appendChild(actionHead);

  state.elements.forEach((element) => {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    nameCell.textContent = element.name || "(nieuw element)";
    nameCell.className = "matrix-name";
    row.appendChild(nameCell);

    state.alarms.forEach((alarm, index) => {
      const alarmId = alarm.id === null || alarm.id === undefined ? index : alarm.id;
      const cell = document.createElement("td");
      cell.className = "matrix-cell";
      const input = document.createElement("input");
      input.type = "number";
      input.min = "-1";
      input.value = String(matrixValue(element, alarmId));
      input.addEventListener("change", () => {
        const raw = input.value.trim();
        if (!/^-?\d+$/.test(raw) || Number(raw) < -1) {
          toast("Een matrixwaarde is -1 of een geheel getal vanaf 0", "error");
          renderMatrix();
          return;
        }
        mutate(() => { setMatrixCell(byKey(element._key), alarmId, Number(raw)); });
      });
      cell.appendChild(input);
      row.appendChild(cell);
    });

    const actionCell = document.createElement("td");
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "Rij op -1";
    reset.addEventListener("click", () => mutate(() => {
      const target = byKey(element._key);
      ensureMatrix(target);
      target.controlMatrix.forEach((c) => { c.waarde = -1; });
    }));
    actionCell.appendChild(reset);
    row.appendChild(actionCell);

    body.appendChild(row);
  });
}

function textCell(element, field, type) {
  const cell = document.createElement("td");
  const input = document.createElement("input");
  input.type = type || "text";
  input.value = element[field] === null || element[field] === undefined ? "" : element[field];
  input.addEventListener("change", () => {
    const raw = input.value;
    if (type === "number") {
      if (!/^-?\d+$/.test(raw.trim())) {
        toast("Voer een geheel getal in", "error");
        renderElements();
        return;
      }
      mutate(() => {
        const target = byKey(element._key);
        target[field] = Number(raw);
        if (field === "address") target.addressOnUnit = Number(raw) - 1;
      });
    } else {
      mutate(() => { byKey(element._key)[field] = raw; });
    }
  });
  cell.appendChild(input);
  return cell;
}

function boolCell(element, field) {
  const cell = document.createElement("td");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(element[field]);
  input.addEventListener("change", () => mutate(() => {
    byKey(element._key)[field] = input.checked;
  }));
  cell.appendChild(input);
  return cell;
}

function selectCell(element, field, options, isNumber) {
  const cell = document.createElement("td");
  const select = document.createElement("select");
  optionList(select, options, element[field]);
  select.addEventListener("change", () => mutate(() => {
    byKey(element._key)[field] = isNumber ? Number(select.value) : select.value;
  }));
  cell.appendChild(select);
  return cell;
}

function buildRow(element, hasWarning, nameIssue) {
  const row = document.createElement("tr");
  row.dataset.key = element._key;
  row.dataset.ring = element.ringId;
  row.draggable = true;
  if (hasWarning) row.className = "warn";

  const checkCell = document.createElement("td");
  checkCell.className = "col-check";
  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = selected.has(element._key);
  check.addEventListener("change", () => {
    if (check.checked) selected.add(element._key); else selected.delete(element._key);
  });
  checkCell.appendChild(check);
  row.appendChild(checkCell);

  const idCell = document.createElement("td");
  idCell.className = "id-cell";
  idCell.textContent = fmtId(element);
  row.appendChild(idCell);

  const nameCell = textCell(element, "name");
  const nameInput = nameCell.querySelector("input");
  if (nameInput) {
    nameInput.dataset.nameKey = element._key;
    if (nameIssue) applyNameIssue(nameCell, nameInput, nameIssue);
  }
  if (hasWarning) nameCell.classList.add("name-warn");
  row.appendChild(nameCell);

  const ringCell = document.createElement("td");
  const ringSelect = document.createElement("select");
  state.rings.forEach((ring) => {
    if (ring.id === null || ring.id === undefined) return;
    const option = document.createElement("option");
    option.value = String(ring.id);
    option.textContent = ring.name;
    ringSelect.appendChild(option);
  });
  ringSelect.value = String(element.ringId);
  ringSelect.addEventListener("change", () => mutate(() => {
    byKey(element._key).ringId = Number(ringSelect.value);
    regroup();
  }));
  ringCell.appendChild(ringSelect);
  row.appendChild(ringCell);

  row.appendChild(textCell(element, "unit", "number"));
  row.appendChild(textCell(element, "address", "number"));
  row.appendChild(selectCell(element, "type", TYPE_OPTIONS, true));
  row.appendChild(selectCell(element, "deviceType", DEVICE_OPTIONS, true));
  row.appendChild(textCell(element, "unitId"));

  BOOL_FIELDS.forEach(([field]) => row.appendChild(boolCell(element, field)));

  row.appendChild(textCell(element, "safe"));
  row.appendChild(textCell(element, "alarmFunction"));
  row.appendChild(textCell(element, "description"));

  const zonesCell = document.createElement("td");
  const zonesInput = document.createElement("input");
  zonesInput.type = "text";
  zonesInput.value = (element.zones || []).map(zoneName).join(", ");
  zonesInput.addEventListener("change", () => {
    let refs;
    try {
      refs = parseZoneRefs(zonesInput.value);
    } catch (err) {
      toast(err.message, "error");
      renderElements();
      return;
    }
    mutate(() => { byKey(element._key).zones = refs; });
  });
  zonesCell.appendChild(zonesInput);
  row.appendChild(zonesCell);

  return row;
}

function renderWarnings() {
  const list = $("warnings-list");
  list.textContent = "";
  const items = [];
  const seen = new Set();
  serverWarnings.forEach((warning) => {
    const message = warning.message || String(warning);
    if (!seen.has(message)) { seen.add(message); items.push(message); }
  });
  if (state) {
    warningInfo().items.forEach((message) => {
      if (!seen.has(message)) { seen.add(message); items.push(message); }
    });
  }
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "Geen waarschuwingen.";
    list.appendChild(li);
    return;
  }
  items.forEach((message) => {
    const li = document.createElement("li");
    li.textContent = message;
    list.appendChild(li);
  });
}

function updateStatus() {
  if (!state) {
    $("status-text").textContent = "Geen project geopend.";
    $("dirty").classList.add("hidden");
    return;
  }
  const dirty = snapshot() !== savedSnapshot;
  const parts = [
    state.elements.length + " elementen",
    state.zones.length + " zones",
    state.rings.length + " ringen",
    dirty ? "niet opgeslagen" : "opgeslagen",
  ];
  if (lastMessage) parts.push(lastMessage);
  $("status-text").textContent = parts.join(" \u2013 ");
  $("dirty").classList.toggle("hidden", !dirty);
  $("element-count").textContent = "(" + state.elements.length + ")";
}

// -------------------------------------------------------------- toevoegen

function addElement(event) {
  event.preventDefault();
  if (!state) return;
  const ringId = Number($("add-ring").value);
  const unit = Number($("add-unit").value);
  const address = Number($("add-address").value);
  if (!Number.isInteger(unit) || unit < 0) { toast("Unit moet een geheel getal zijn", "error"); return; }
  if (!Number.isInteger(address) || address < 1) { toast("Adres moet minimaal 1 zijn", "error"); return; }
  let zones;
  try {
    zones = parseZoneRefs($("add-zones").value);
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  mutate(() => {
    state.elements.push({
      id: null,
      _key: newKey(),
      name: $("add-name").value.trim(),
      ringId: ringId,
      ring: (state.rings.find((r) => r.id === ringId) || {}).name || "",
      unit: unit,
      address: address,
      addressOnUnit: address - 1,
      unitId: $("add-unitid").value.trim(),
      type: Number($("add-type").value),
      deviceType: Number($("add-device").value),
      enabled: true,
      invert: false,
      normalOpen: true,
      safe: null,
      description: "",
      alarmFunction: "AND",
      controlMatrix: state.alarms.map((alarm, index) => ({
        alarmId: alarm.id === null || alarm.id === undefined ? index : alarm.id,
        waarde: -1,
      })),
      zones: zones,
    });
    regroup();
  });
  $("add-unit").value = "";
  $("add-address").value = "";
  $("add-unitid").value = "";
  $("add-zones").value = "";
  $("add-name").value = "";
}

// ---------------------------------------------------------------- bulk acties

function bulkRename() {
  if (!state) return;
  if (!selected.size) { toast("Selecteer eerst een of meer rijen", "error"); return; }
  const search = $("bulk-search").value;
  const replace = $("bulk-replace").value;
  const prefix = $("bulk-prefix").value;
  const suffix = $("bulk-suffix").value;
  const startRaw = $("bulk-start").value.trim();
  const start = startRaw === "" ? null : Number(startRaw);
  if (start !== null && !Number.isInteger(start)) { toast("Nummering moet een geheel getal zijn", "error"); return; }
  if (!search && !prefix && !suffix && start === null) {
    toast("Vul zoek/vervang, prefix, suffix of nummering in", "error");
    return;
  }
  const chosen = state.elements.filter((e) => selected.has(e._key));
  mutate(() => {
    chosen.forEach((element, index) => {
      let name = element.name || "";
      if (search) name = name.split(search).join(replace);
      name = prefix + name + suffix;
      if (start !== null) name = name + (start + index);
      element.name = name;
    });
  });
}

function deleteSelected() {
  if (!state) return;
  if (!selected.size) { toast("Selecteer eerst een of meer rijen", "error"); return; }
  if (!window.confirm(selected.size + " element(en) verwijderen?")) return;
  mutate(() => {
    state.elements = state.elements.filter((e) => !selected.has(e._key));
    selected = new Set();
  });
}

// ------------------------------------------------------------- drag & drop

function moveElement(draggedKey, targetKey) {
  const dragged = byKey(draggedKey);
  const target = byKey(targetKey);
  if (!dragged || !target || dragged === target || dragged.ringId !== target.ringId) return;
  mutate(() => {
    state.elements = state.elements.filter((e) => e !== dragged);
    const index = state.elements.indexOf(target);
    state.elements.splice(index, 0, dragged);
    regroup();
  });
}

function wireDragAndDrop(tbody) {
  tbody.addEventListener("dragstart", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (!row) return;
    row.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", row.dataset.key);
  });
  tbody.addEventListener("dragend", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (row) row.classList.remove("dragging");
    Array.from(tbody.querySelectorAll("tr.drop-target"))
      .forEach((r) => r.classList.remove("drop-target"));
  });
  tbody.addEventListener("dragover", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (!row) return;
    const dragged = tbody.querySelector("tr.dragging");
    if (!dragged || dragged.dataset.ring !== row.dataset.ring) return;
    event.preventDefault();
    Array.from(tbody.querySelectorAll("tr.drop-target"))
      .forEach((r) => r.classList.remove("drop-target"));
    row.classList.add("drop-target");
  });
  tbody.addEventListener("drop", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (!row) return;
    event.preventDefault();
    const dragged = tbody.querySelector("tr.dragging");
    if (!dragged) return;
    moveElement(dragged.dataset.key, row.dataset.key);
  });
}

// ------------------------------------------------------------------ wiring

function boot() {
  $("file-input").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) openFile(file);
    event.target.value = "";
  });
  $("btn-open-path").addEventListener("click", openPath);
  $("path-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); openPath(); }
  });
  $("btn-undo").addEventListener("click", undo);
  $("btn-redo").addEventListener("click", redo);
  $("btn-save").addEventListener("click", save);
  $("btn-reload").addEventListener("click", reloadProject);
  $("btn-close").addEventListener("click", closeProject);
  $("btn-bulk-rename").addEventListener("click", bulkRename);
  $("btn-delete").addEventListener("click", deleteSelected);
  $("select-all").addEventListener("change", (event) => {
    if (!state) return;
    if (event.target.checked) state.elements.forEach((e) => selected.add(e._key));
    else selected = new Set();
    renderElements();
  });
  $("filter-input").addEventListener("input", () => { if (state) renderElements(); });
  $("zone-add-form").addEventListener("submit", addZone);
  $("ring-add-form").addEventListener("submit", addRing);
  $("element-add-form").addEventListener("submit", addElement);
  wireDragAndDrop($("element-body"));

  document.addEventListener("keydown", (event) => {
    const mod = event.ctrlKey || event.metaKey;
    if (!mod) return;
    if (event.key === "z" && !event.shiftKey) { event.preventDefault(); undo(); }
    else if (event.key === "y" || (event.key === "z" && event.shiftKey)) {
      event.preventDefault();
      redo();
    }
  });
  updateStatus();
}

document.addEventListener("DOMContentLoaded", boot);
