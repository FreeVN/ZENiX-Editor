"use strict";

// Pure naamcontrole voor de Ringbus Editor, gedeeld door de browser en de tests.
// De server blijft de autoriteit; deze module past exact dezelfde regels toe
// die de server in `name_rules` meestuurt (app/name_validation.py).
//
// Belangrijk: alleen velden die de gebruiker toevoegde of wijzigde mogen een
// save blokkeren. Een overtreding die al in de baseline zat (het geopende
// bronbestand) is een waarschuwing, net als op de server (`invalid_name_existing`).

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.ZenixNameCheck = factory();
  }
}(typeof self !== "undefined" ? self : this, function () {
  function trimmed(value) {
    if (value === null || value === undefined) return "";
    return String(value).trim();
  }

  function nameById(items) {
    const map = {};
    (items || []).forEach((item) => {
      if (!item || item.id === null || item.id === undefined) return;
      map[String(item.id)] = trimmed(item.name);
    });
    return map;
  }

  function isChanged(item, base) {
    if (!item || item.id === null || item.id === undefined) return true;
    const key = String(item.id);
    if (!Object.prototype.hasOwnProperty.call(base, key)) return true;
    return base[key] !== trimmed(item.name);
  }

  function firstForbiddenChar(name, charset) {
    if (!charset || !charset.length) return null;
    const chars = Array.from(name);
    for (let i = 0; i < chars.length; i += 1) {
      if (charset.indexOf(chars[i]) >= 0) return chars[i];
    }
    return null;
  }

  function isReservedName(name, rules) {
    if (!name) return false;
    const match = /^(bae|open)_(\d+)$/.exec(name);
    if (!match) return false;
    const cfg = (rules && rules.reserved_names) || { prefixes: ["bae_", "open_"], max: 1024 };
    const prefix = match[1] + "_";
    if ((cfg.prefixes || []).indexOf(prefix) < 0) return false;
    const number = Number(match[2]);
    return number >= 1 && number <= (cfg.max || 1024);
  }

  function formatMessage(code, rules, info) {
    const messages = (rules && rules.messages) || {};
    const template = messages[code] || "Ongeldige naam";
    const teken = info && info.teken !== undefined && info.teken !== null ? info.teken : "";
    const waarde = info && info.waarde !== undefined && info.waarde !== null ? info.waarde : "";
    return template.split("{teken}").join(teken).split("{waarde}").join(waarde);
  }

  function entry(soort, code, item, changed, rules, extra) {
    const name = trimmed(item && item.name);
    const info = { soort: soort, code: code, waarde: name, changed: Boolean(changed) };
    if (extra) Object.keys(extra).forEach((key) => { info[key] = extra[key]; });
    info.message = formatMessage(code, rules, info);
    return info;
  }

  // Geeft per item hooguit één overtreding; `changed` is true voor nieuwe of
  // door de gebruiker gewijzigde velden. `baseline` is de staat zoals geopend
  // (hetzelfde object als savedSnapshot); zonder baseline geldt alles als
  // gewijzigd.
  function collect(state, rules, baseline) {
    if (!state) return [];
    rules = rules || {};
    baseline = baseline || {};

    const elements = state.elements || [];
    const zones = state.zones || [];
    const rings = state.rings || [];
    const elementBase = nameById(baseline.elements);
    const zoneBase = nameById(baseline.zones);
    const ringBase = nameById(baseline.rings);
    const alarmBase = nameById(baseline.alarms);

    const namespace = elements.slice();
    (state.alarms || []).forEach((alarm) => namespace.push(alarm));
    ["auxiliaryElements", "aux"].forEach((key) => {
      (state[key] || []).forEach((item) => namespace.push(item));
    });

    const namespaceCounts = {};
    namespace.forEach((item) => {
      const name = trimmed(item && item.name);
      if (name) namespaceCounts[name] = (namespaceCounts[name] || 0) + 1;
    });
    const ringNames = rings.map((ring) => trimmed(ring.name)).filter(Boolean);
    const zoneCounts = {};
    zones.forEach((zone) => {
      const name = trimmed(zone.name);
      if (name) zoneCounts[name] = (zoneCounts[name] || 0) + 1;
    });
    const ringCounts = {};
    rings.forEach((ring) => {
      const name = trimmed(ring.name);
      if (name) ringCounts[name] = (ringCounts[name] || 0) + 1;
    });
    const elementNames = elements.map((element) => trimmed(element.name)).filter(Boolean);
    const elementTouched = {};
    elements.forEach((element) => {
      const name = trimmed(element.name);
      if (name && isChanged(element, elementBase)) elementTouched[name] = true;
    });

    const issues = [];

    elements.forEach((element) => {
      const name = trimmed(element.name);
      const isNew = element.id === null || element.id === undefined;
      const changed = isChanged(element, elementBase);
      const key = element._key;
      if (!name) {
        if (!isNew) issues.push(entry("element", "EMPTY", element, changed, rules, { key: key }));
        return;
      }
      const bad = firstForbiddenChar(name, rules.element_forbidden || []);
      if (bad !== null) {
        issues.push(entry("element", "INVALID_CHAR", element, changed, rules,
          { key: key, teken: bad }));
        return;
      }
      if (isReservedName(name, rules)) {
        issues.push(entry("element", "RESERVED_NAME", element, changed, rules, { key: key }));
        return;
      }
      if ((namespaceCounts[name] || 0) > 1) {
        issues.push(entry("element", "TAKEN_NAME", element, changed, rules, { key: key }));
        return;
      }
      // Botsing met een ringnaam: één melding, op het gewijzigde element.
      if (ringNames.indexOf(name) >= 0 && changed) {
        issues.push(entry("element", "TAKEN_NAME", element, true, rules, { key: key }));
      }
    });

    // Alarmen leven in dezelfde vendor-namespace als elementen: dezelfde
    // tekenset, reserveringen en uniciteitsregel.
    (state.alarms || []).forEach((alarm, index) => {
      const name = trimmed(alarm.name);
      const changed = isChanged(alarm, alarmBase);
      if (!name) {
        issues.push(entry("alarm", "EMPTY", alarm, changed, rules, { index: index }));
        return;
      }
      const charset = rules.alarm_forbidden || rules.element_forbidden || [];
      const bad = firstForbiddenChar(name, charset);
      if (bad !== null) {
        issues.push(entry("alarm", "INVALID_CHAR", alarm, changed, rules,
          { index: index, teken: bad }));
        return;
      }
      if (isReservedName(name, rules)) {
        issues.push(entry("alarm", "RESERVED_NAME", alarm, changed, rules, { index: index }));
        return;
      }
      if ((namespaceCounts[name] || 0) > 1) {
        issues.push(entry("alarm", "TAKEN_NAME", alarm, changed, rules, { index: index }));
      }
    });

    zones.forEach((zone, index) => {
      const name = trimmed(zone.name);
      const changed = isChanged(zone, zoneBase);
      if (!name) {
        issues.push(entry("zone", "EMPTY", zone, changed, rules, { index: index }));
        return;
      }
      const bad = firstForbiddenChar(name, rules.zone_forbidden || []);
      if (bad !== null) {
        issues.push(entry("zone", "INVALID_CHAR", zone, changed, rules,
          { index: index, teken: bad }));
        return;
      }
      if (isReservedName(name, rules)) {
        issues.push(entry("zone", "RESERVED_NAME", zone, changed, rules, { index: index }));
        return;
      }
      if ((zoneCounts[name] || 0) > 1) {
        issues.push(entry("zone", "TAKEN_NAME", zone, changed, rules, { index: index }));
      }
    });

    rings.forEach((ring, index) => {
      const name = trimmed(ring.name);
      const changed = isChanged(ring, ringBase);
      if (!name) {
        issues.push(entry("ring", "EMPTY", ring, changed, rules, { index: index }));
        return;
      }
      const bad = firstForbiddenChar(name, rules.zone_forbidden || []);
      if (bad !== null) {
        issues.push(entry("ring", "INVALID_CHAR", ring, changed, rules,
          { index: index, teken: bad }));
        return;
      }
      if (isReservedName(name, rules)) {
        issues.push(entry("ring", "RESERVED_NAME", ring, changed, rules, { index: index }));
        return;
      }
      if ((ringCounts[name] || 0) > 1 || (elementNames.indexOf(name) >= 0 && !elementTouched[name])) {
        issues.push(entry("ring", "TAKEN_NAME", ring, changed, rules, { index: index }));
      }
    });

    return issues;
  }

  return {
    collect: collect,
    firstForbiddenChar: firstForbiddenChar,
    isReservedName: isReservedName,
    formatMessage: formatMessage,
  };
}));
