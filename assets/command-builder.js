/* Command builder.
 *
 * Renders a form from assets/variables.js (generated from the collection's
 * meta/argument_specs.yml) and turns the selections into something runnable.
 *
 * Two rules shape the output:
 *
 * 1. Only values that differ from the role default are emitted. Every
 *    variable in this collection has a working default, so a command that
 *    restates them is noise -- and noise is what stops people reading a
 *    command before they run it.
 * 2. Credentials are never emitted onto the command line. A Slack incoming
 *    webhook URL is the bearer token for that channel; putting it in -e
 *    leaks it into shell history, into `ps` output for every local user, and
 *    into CI logs. Those variables render as .env lines instead.
 */
(function () {
  "use strict";

  var data = window.LV_DATA;
  // Guard on the element the builder actually writes into, so a page that
  // loads the script without the section simply does nothing.
  if (!data || !document.getElementById("cb-form")) return;

  var FQCN = "sameeralam3127.linux_vitals";
  var TAGS = [
    ["discovery", "Facts, services, memory, logs, kernel, boot, security"],
    ["kernel", "Kernel and reboot-required checks"],
    ["security", "SELinux, AppArmor, failed logins"],
    ["boot", "Boot partition and rescue image"],
    ["self_healing", "Restart attempts (only acts if enabled)"],
    ["certs", "TLS certificate checks (only acts if enabled)"],
    ["reporting", "Rebuild reports"],
    ["notifications", "Send summaries"]
  ];

  var state = {
    playbook: "healthcheck",
    inventory: "inventory.ini",
    become: false,
    check: false,
    forks: "",
    maintenanceId: "",
    tags: [],
    vars: {},        // name -> raw string/bool from the form
    view: "cli",
    onlyChanged: false,
    search: ""
  };

  /* ---------- helpers ---------- */

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "html") node.innerHTML = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) { node.appendChild(kid); });
    return node;
  }

  // YAML/JSON-ish rendering of a default, for display and comparison.
  function fmtDefault(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (Array.isArray(v)) return v.join(", ");
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function isChanged(spec) {
    var current = state.vars[spec.name];
    if (current === undefined) return false;
    if (spec.type === "bool") return Boolean(current) !== Boolean(spec.default);
    return String(current).trim() !== fmtDefault(spec.default).trim();
  }

  function allSpecs() {
    return data.roles.reduce(function (acc, role) { return acc.concat(role.vars); }, []);
  }

  // Values that reach a shell need quoting; a single-quoted string is safest,
  // with the usual '\'' dance for embedded quotes.
  function shellQuote(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'";
  }

  function valueForCli(spec) {
    var raw = state.vars[spec.name];
    if (spec.type === "bool") return raw ? "true" : "false";
    if (spec.type === "list") {
      var items = String(raw).split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      return JSON.stringify(items);
    }
    if (spec.type === "dict") return String(raw).trim();
    return String(raw);
  }

  function yamlValue(spec, indent) {
    var raw = state.vars[spec.name];
    if (spec.type === "bool") return raw ? "true" : "false";
    if (spec.type === "int") return String(raw);
    if (spec.type === "list") {
      var items = String(raw).split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      if (!items.length) return "[]";
      return "\n" + items.map(function (i) { return indent + "  - " + i; }).join("\n");
    }
    if (spec.type === "dict") {
      var text = String(raw).trim();
      try {
        var obj = JSON.parse(text);
        var keys = Object.keys(obj);
        if (!keys.length) return "{}";
        return "\n" + keys.map(function (k) {
          return indent + "  " + k + ": " + JSON.stringify(obj[k]);
        }).join("\n");
      } catch (e) {
        return text;   // let them see their own malformed input rather than hide it
      }
    }
    return JSON.stringify(String(raw));
  }

  /* ---------- output ---------- */

  function changedSpecs() {
    return allSpecs().filter(isChanged);
  }

  function buildCli() {
    var changed = changedSpecs();
    var safe = changed.filter(function (s) { return !s.secret; });
    var lines = [];

    lines.push("# " + state.playbook + " — " + (safe.length + (state.maintenanceId ? 1 : 0)) + " variable(s) overridden");
    var cmd = "ansible-playbook -i " + (state.inventory || "inventory.ini") + " " + FQCN + "." + state.playbook;

    if (state.become) cmd += " \\\n  --become";
    if (state.check) cmd += " \\\n  --check";
    if (state.forks) cmd += " \\\n  --forks " + state.forks;
    if (state.tags.length) cmd += " \\\n  --tags " + state.tags.join(",");
    if (state.maintenanceId) {
      cmd += " \\\n  -e linux_vitals_maintenance_id=" + shellQuote(state.maintenanceId);
    }
    safe.forEach(function (spec) {
      cmd += " \\\n  -e " + shellQuote(spec.name + "=" + valueForCli(spec));
    });

    lines.push(cmd);
    return lines.join("\n");
  }

  function buildGroupVars() {
    var changed = changedSpecs().filter(function (s) { return !s.secret; });
    var out = ["---", "# group_vars/all.yml", ""];
    if (state.maintenanceId) {
      out.push("linux_vitals_maintenance_id: " + JSON.stringify(state.maintenanceId));
    }
    if (!changed.length && !state.maintenanceId) {
      out.push("# Every variable is at its default — nothing to set.");
    }
    data.roles.forEach(function (role) {
      var mine = role.vars.filter(function (s) { return changed.indexOf(s) !== -1; });
      if (!mine.length) return;
      out.push("");
      out.push("# " + role.label + " — " + role.blurb);
      mine.forEach(function (spec) {
        out.push(spec.name + ": " + yamlValue(spec, ""));
      });
    });
    return out.join("\n");
  }

  function buildEnv() {
    var secrets = changedSpecs().filter(function (s) { return s.secret; });
    var out = [
      "# .env — beside your inventory, never committed.",
      "# Paths and the .env lookup resolve from inventory_dir, not playbook_dir.",
      ""
    ];
    if (!secrets.length) {
      out.push("# No credential variables set in the form.");
      return out.join("\n");
    }
    secrets.forEach(function (spec) {
      var key = spec.env || spec.name.toUpperCase();
      out.push(key + "=" + String(state.vars[spec.name]));
    });
    return out.join("\n");
  }

  function render() {
    var changed = changedSpecs();
    var secrets = changed.filter(function (s) { return s.secret; });

    var chips = document.getElementById("cb-chips");
    chips.innerHTML = "";
    chips.appendChild(el("span", {
      class: "cb-chip",
      "data-tone": changed.length ? "accent" : "",
      text: changed.length + " of " + allSpecs().length + " variables changed"
    }));
    chips.appendChild(el("span", { class: "cb-chip", text: state.playbook }));
    if (state.tags.length) {
      chips.appendChild(el("span", { class: "cb-chip", text: state.tags.length + " tag(s)" }));
    }
    if (secrets.length) {
      chips.appendChild(el("span", {
        class: "cb-chip", "data-tone": "warn",
        text: secrets.length + " credential(s) → .env"
      }));
    }

    var body = state.view === "cli" ? buildCli()
             : state.view === "yaml" ? buildGroupVars()
             : buildEnv();
    document.getElementById("cb-output").textContent = body;

    var note = document.getElementById("cb-note");
    if (state.view === "cli" && secrets.length) {
      note.innerHTML = "<strong>" + secrets.length + " credential variable(s) are deliberately not in this command.</strong> " +
        "A webhook URL is the bearer token for that channel — on a command line it lands in shell history, in <code>ps</code> " +
        "output for every local user on the control node, and in CI logs. Use the <strong>.env</strong> tab instead.";
    } else if (state.view === "env") {
      note.innerHTML = "Write this to <code>.env</code> beside your inventory and keep it out of git. " +
        "Inventory and extra-vars values win over <code>.env</code>, so anything set in both is taken from the inventory.";
    } else if (state.view === "yaml") {
      note.innerHTML = "Values here are overridden by <code>-e</code> on the command line, which is what makes " +
        "<code>group_vars</code> the right home for fleet-wide settings and <code>-e</code> the right place for one run.";
    } else {
      note.textContent = "Only variables that differ from their role default are emitted. Every variable has a working default.";
    }

    // Reflect changed-ness in the form itself.
    allSpecs().forEach(function (spec) {
      var field = document.getElementById("f-" + spec.name);
      if (field) field.classList.toggle("is-changed", isChanged(spec));
    });
    data.roles.forEach(function (role) {
      var counter = document.getElementById("count-" + role.id);
      if (!counter) return;
      var n = role.vars.filter(isChanged).length;
      counter.textContent = n ? n + " changed" : role.vars.length + " vars";
      counter.setAttribute("data-changed", n ? "true" : "false");
    });
    applyFilter();
  }

  function applyFilter() {
    var q = state.search.trim().toLowerCase();
    data.roles.forEach(function (role) {
      var shownInRole = 0;
      role.vars.forEach(function (spec) {
        var field = document.getElementById("f-" + spec.name);
        if (!field) return;
        var matches = !q ||
          spec.name.toLowerCase().indexOf(q) !== -1 ||
          (spec.description || "").toLowerCase().indexOf(q) !== -1;
        var visible = matches && (!state.onlyChanged || isChanged(spec));
        field.classList.toggle("is-hidden", !visible);
        if (visible) shownInRole++;
      });
      var group = document.getElementById("group-" + role.id);
      var empty = document.getElementById("empty-" + role.id);
      if (empty) empty.style.display = shownInRole ? "none" : "";
      if (group && (q || state.onlyChanged) && shownInRole) group.open = true;
    });
  }

  /* ---------- form construction ---------- */

  function fieldFor(spec) {
    var field = el("div", { class: "cb-field" + (spec.secret ? " cb-secret" : ""), id: "f-" + spec.name });
    var head = el("div", { class: "cb-field-head" }, [
      el("label", { for: "i-" + spec.name, text: spec.name }),
      el("span", { class: "cb-type", text: spec.type })
    ]);
    field.appendChild(head);

    var input;
    if (spec.type === "bool") {
      input = el("input", { type: "checkbox", id: "i-" + spec.name });
      input.checked = Boolean(spec.default);
      state.vars[spec.name] = Boolean(spec.default);
      input.addEventListener("change", function () {
        state.vars[spec.name] = input.checked;
        render();
      });
      field.appendChild(el("div", { class: "cb-check" }, [input, el("span", { text: "enabled" })]));
    } else if (spec.choices) {
      input = el("select", { id: "i-" + spec.name });
      spec.choices.forEach(function (choice) {
        var opt = el("option", { value: choice, text: choice });
        if (choice === spec.default) opt.selected = true;
        input.appendChild(opt);
      });
      state.vars[spec.name] = fmtDefault(spec.default);
      input.addEventListener("change", function () {
        state.vars[spec.name] = input.value;
        render();
      });
      field.appendChild(input);
    } else if (spec.type === "dict" || (spec.type === "list" && fmtDefault(spec.default).length > 48)) {
      input = el("textarea", { id: "i-" + spec.name, rows: "3" });
      input.value = spec.type === "dict" ? JSON.stringify(spec.default) : fmtDefault(spec.default);
      state.vars[spec.name] = input.value;
      input.addEventListener("input", function () {
        state.vars[spec.name] = input.value;
        render();
      });
      field.appendChild(input);
    } else {
      input = el("input", {
        type: spec.type === "int" ? "number" : "text",
        id: "i-" + spec.name
      });
      input.value = fmtDefault(spec.default);
      state.vars[spec.name] = input.value;
      input.addEventListener("input", function () {
        state.vars[spec.name] = input.value;
        render();
      });
      field.appendChild(input);
    }

    if (spec.description) {
      field.appendChild(el("p", {
        class: "cb-help",
        html: spec.description.replace(/`([^`]+)`/g, "<code>$1</code>")
      }));
    }
    if (spec.type === "list") {
      field.appendChild(el("p", { class: "cb-help", text: "Comma-separated." }));
    }
    if (spec.secret) {
      field.appendChild(el("p", {
        class: "cb-warn",
        text: "Credential — emitted to the .env tab, never onto the command line."
      }));
    }
    return field;
  }

  function buildForm() {
    var host = document.getElementById("cb-form");
    data.roles.forEach(function (role) {
      var group = el("details", { class: "cb-group", id: "group-" + role.id });
      if (role.id === "vitals_scan") group.open = true;
      group.appendChild(el("summary", {}, [
        el("span", { text: role.label }),
        el("span", { class: "cb-group-note", text: role.blurb }),
        el("span", { class: "cb-count", id: "count-" + role.id, text: role.vars.length + " vars" })
      ]));
      role.vars.forEach(function (spec) { group.appendChild(fieldFor(spec)); });
      group.appendChild(el("div", {
        class: "cb-empty", id: "empty-" + role.id,
        text: "No variables in this role match the filter.", style: "display:none"
      }));
      host.appendChild(group);
    });
  }

  /* ---------- wiring ---------- */

  function bind(id, event, fn) {
    var node = document.getElementById(id);
    if (node) node.addEventListener(event, fn);
  }

  function init() {
    buildForm();

    var tagHost = document.getElementById("cb-tags");
    TAGS.forEach(function (pair) {
      var btn = el("button", {
        type: "button", class: "cb-btn", "aria-pressed": "false",
        title: pair[1], text: pair[0]
      });
      btn.addEventListener("click", function () {
        var on = btn.getAttribute("aria-pressed") === "true";
        btn.setAttribute("aria-pressed", on ? "false" : "true");
        state.tags = on
          ? state.tags.filter(function (t) { return t !== pair[0]; })
          : state.tags.concat([pair[0]]);
        render();
      });
      tagHost.appendChild(btn);
    });

    bind("cb-playbook", "change", function (e) {
      state.playbook = e.target.value;
      var idRow = document.getElementById("cb-maintenance-row");
      // baseline/postcheck are only meaningful with a shared maintenance id.
      idRow.style.display = (state.playbook === "healthcheck") ? "none" : "";
      render();
    });
    bind("cb-inventory", "input", function (e) { state.inventory = e.target.value; render(); });
    bind("cb-maintenance", "input", function (e) { state.maintenanceId = e.target.value; render(); });
    bind("cb-forks", "input", function (e) { state.forks = e.target.value; render(); });
    bind("cb-become", "change", function (e) { state.become = e.target.checked; render(); });
    bind("cb-checkmode", "change", function (e) { state.check = e.target.checked; render(); });
    bind("cb-search", "input", function (e) { state.search = e.target.value; applyFilter(); });
    bind("cb-only-changed", "click", function (e) {
      state.onlyChanged = !state.onlyChanged;
      e.currentTarget.setAttribute("aria-pressed", String(state.onlyChanged));
      applyFilter();
    });
    bind("cb-reset", "click", function () {
      allSpecs().forEach(function (spec) {
        var input = document.getElementById("i-" + spec.name);
        if (!input) return;
        if (spec.type === "bool") { input.checked = Boolean(spec.default); state.vars[spec.name] = Boolean(spec.default); }
        else if (spec.type === "dict") { input.value = JSON.stringify(spec.default); state.vars[spec.name] = input.value; }
        else { input.value = fmtDefault(spec.default); state.vars[spec.name] = input.value; }
      });
      render();
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (btn) {
      btn.addEventListener("click", function () {
        state.view = btn.getAttribute("data-view");
        Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (other) {
          other.setAttribute("aria-pressed", String(other === btn));
        });
        render();
      });
    });

    bind("cb-copy", "click", function (e) {
      var text = document.getElementById("cb-output").textContent;
      var btn = e.currentTarget;
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = "Copied";
        setTimeout(function () { btn.textContent = "Copy"; }, 1400);
      }).catch(function () {
        btn.textContent = "Press ⌘C";
        setTimeout(function () { btn.textContent = "Copy"; }, 1800);
      });
    });

    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
