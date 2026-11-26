/* LinuxVitals site.
 *
 * Everything here is progressive enhancement over markup that already reads
 * correctly on its own: a visitor with JavaScript off, behind a proxy that
 * blocks api.github.com, or past the unauthenticated rate limit still gets a
 * complete page.
 *
 * Data sources, in the order they are trusted:
 *   assets/fleet.js      the demo dashboard's own report.json (tools/build_demo.py)
 *   assets/variables.js  the role argument specs (tools/build_variables.py)
 *   assets/changelog.js  CHANGELOG.md (tools/build_changelog.py)
 *   api.github.com       live extras: release, CI, stars, milestones, commits
 */
(function () {
  "use strict";

  var REPO = "sameeralam3127/linux-vitals";
  var API = "https://api.github.com/repos/" + REPO;
  var GH = "https://github.com/" + REPO;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var FLEET = window.LV_FLEET || null;
  var SPECS = window.LV_DATA || null;

  function $(id) { return document.getElementById(id); }
  function each(list, fn) { Array.prototype.forEach.call(list, fn); }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) {
      node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
    });
    return node;
  }

  // Text with `code spans`, built as DOM nodes so nothing from the API is ever
  // parsed as HTML.
  function codeText(text) {
    var frag = document.createDocumentFragment();
    String(text).split(/(`[^`]+`)/).forEach(function (part) {
      if (/^`[^`]+`$/.test(part)) frag.appendChild(el("code", { text: part.slice(1, -1) }));
      else if (part) frag.appendChild(document.createTextNode(part));
    });
    return frag;
  }

  function ago(iso) {
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    var units = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
    if (!window.Intl || !Intl.RelativeTimeFormat) { return new Date(iso).toISOString().slice(0, 10); }
    var rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    for (var i = 0; i < units.length; i++) {
      if (diff >= units[i][1]) { return rtf.format(-Math.floor(diff / units[i][1]), units[i][0]); }
    }
    return rtf.format(0, "minute");
  }

  function fmtDate(iso) {
    try {
      return new Date(iso + (iso.length === 10 ? "T12:00:00Z" : "")).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    } catch (e) { return iso; }
  }

  // Run fn once the element scrolls near the viewport.
  function whenVisible(node, fn) {
    if (!node) return;
    if (!("IntersectionObserver" in window)) { fn(); return; }
    var io = new IntersectionObserver(function (entries) {
      if (entries.some(function (e) { return e.isIntersecting; })) { io.disconnect(); fn(); }
    }, { rootMargin: "0px 0px -10% 0px" });
    io.observe(node);
  }

  function countUp(node, to, suffix) {
    suffix = suffix || "";
    if (reduced || !isFinite(to)) { node.textContent = to + suffix; return; }
    var start = performance.now(), dur = 900, decimals = (String(to).split(".")[1] || "").length;
    (function frame(now) {
      var t = Math.min(1, (now - start) / dur), eased = 1 - Math.pow(1 - t, 3);
      node.textContent = (to * eased).toFixed(decimals) + suffix;
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  /* ================================================================ chrome */

  var root = document.documentElement;
  var sun = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
  var moon = '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
  function paintIcon() { $("theme-icon").innerHTML = root.getAttribute("data-theme") === "light" ? moon : sun; }
  paintIcon();
  $("theme-toggle").addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    paintIcon();
    try { localStorage.setItem("lv-theme", next); } catch (e) {}
  });

  var nav = $("nav"), links = $("nav-links"), toggle = $("nav-toggle"), bar = $("progress");
  toggle.addEventListener("click", function () {
    var open = links.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
  links.addEventListener("click", function (e) {
    if (e.target.tagName === "A") { links.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); }
  });
  var ticking = false;
  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      nav.classList.toggle("scrolled", window.scrollY > 8);
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.transform = "scaleX(" + (max > 0 ? Math.min(1, window.scrollY / max) : 0) + ")";
      ticking = false;
    });
  }, { passive: true });

  each(document.querySelectorAll(".copy"), function (btn) {
    btn.addEventListener("click", function () {
      var src = document.querySelector(btn.getAttribute("data-copy"));
      if (!src) return;
      navigator.clipboard.writeText(src.innerText.trim()).then(function () {
        var was = btn.textContent;
        btn.textContent = "Copied";
        btn.classList.add("done");
        setTimeout(function () { btn.textContent = was; btn.classList.remove("done"); }, 1600);
      }).catch(function () {});
    });
  });

  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) {
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
        var panel = $(t.getAttribute("aria-controls"));
        if (panel) panel.classList.toggle("active", t === tab);
      });
    });
  });

  var revealables = document.querySelectorAll(".reveal");
  if (reduced || !("IntersectionObserver" in window)) {
    each(revealables, function (n) { n.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry, i) {
        if (entry.isIntersecting) {
          setTimeout(function () { entry.target.classList.add("in"); }, Math.min(i * 60, 240));
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    each(revealables, function (n) { io.observe(n); });
  }

  var navAnchors = {};
  each(document.querySelectorAll('.nav-links a[href^="#"]'), function (a) { navAnchors[a.getAttribute("href").slice(1)] = a; });
  if ("IntersectionObserver" in window) {
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var a = navAnchors[entry.target.id];
        if (!a || !entry.isIntersecting) return;
        Object.keys(navAnchors).forEach(function (k) { navAnchors[k].classList.remove("active"); });
        a.classList.add("active");
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    each(document.querySelectorAll("section[id]"), function (s) { spy.observe(s); });
  }

  /* ============================================================== terminal */

  // A tiny typewriter. Each line is [kind, text]: "$" is typed as a command,
  // anything else is printed whole after a short pause. Kinds map to classes:
  // d dim, g green, y yellow, r red, p accent.
  function Terminal(pre) {
    this.pre = pre;
    this.run = 0;
  }
  Terminal.prototype.play = function (lines) {
    var pre = this.pre, run = ++this.run, self = this;
    pre.textContent = "";
    if (reduced) {
      lines.forEach(function (line) { self.write(line, line[1]); pre.appendChild(document.createTextNode("\n")); });
      return;
    }
    var cursor = el("span", { class: "cur" });
    var i = 0;
    function next() {
      if (run !== self.run) return;
      if (i >= lines.length) { pre.appendChild(cursor); return; }
      var line = lines[i++];
      if (line[0] === "$") {
        var span = self.write(line, ""), text = line[1], c = 0;
        pre.appendChild(cursor);
        (function type() {
          if (run !== self.run) return;
          span.textContent = text.slice(0, ++c);
          if (c < text.length) setTimeout(type, 14 + Math.random() * 22);
          else setTimeout(function () { cursor.remove(); pre.appendChild(document.createTextNode("\n")); next(); }, 260);
        })();
      } else {
        setTimeout(function () {
          if (run !== self.run) return;
          self.write(line, line[1]);
          pre.appendChild(document.createTextNode("\n"));
          next();
        }, line[0] === "" ? 40 : 120);
      }
    }
    next();
  };
  Terminal.prototype.write = function (line, text) {
    if (line[0] === "$") {
      this.pre.appendChild(el("span", { class: "p", text: "$ " }));
      var cmd = el("span", { text: text });
      this.pre.appendChild(cmd);
      return cmd;
    }
    var span = el("span", { class: line[0] || "", text: text });
    this.pre.appendChild(span);
    return span;
  };

  /* ============================================================ fleet model */

  // Mirrors vitals_scan/tasks/severity.yml and vitals_report/tasks/render.yml:
  // an override wins, then the shipped map; a host fails when any finding is
  // at or above the threshold; a host is healthy only if it passes AND every
  // check on it ran.
  var ORDER = ["info", "warning", "critical"];
  var DEFAULT_MAP = {};
  if (SPECS) {
    SPECS.roles.forEach(function (role) {
      role.vars.forEach(function (v) {
        if (v.name === "linux_vitals_finding_severities") DEFAULT_MAP = v.default || {};
      });
    });
  }

  function levelOf(finding, overrides) {
    if (overrides[finding.id]) return overrides[finding.id];
    return finding.severity || DEFAULT_MAP[finding.id] || "warning";
  }

  function statusOf(findings, threshold, overrides) {
    var t = ORDER.indexOf(threshold);
    return findings.some(function (f) { return ORDER.indexOf(levelOf(f, overrides)) >= t; }) ? "Fail" : "Pass";
  }

  function band(pct) {
    return pct >= 95 ? "Excellent" : pct >= 80 ? "Good" : pct >= 60 ? "Fair" : "Poor";
  }

  function score(fleet, threshold, overrides) {
    var hosts = fleet.hosts.map(function (h) {
      var base = (fleet.baseline_findings || {})[h.inventory_name];
      var now = statusOf(h.findings, threshold, overrides);
      var before = base ? statusOf(base, threshold, overrides) : null;
      return {
        host: h, status: now, before: before,
        unknown: h.findings.filter(function (f) { return f.status === "unknown"; }).length,
        regressed: before === "Pass" && now === "Fail"
      };
    });
    var healthy = hosts.filter(function (r) { return r.status === "Pass" && r.unknown === 0; }).length;
    var pct = hosts.length ? Math.round(healthy / hosts.length * 1000) / 10 : 0;
    return {
      hosts: hosts, pct: pct, band: band(pct),
      pass: hosts.filter(function (r) { return r.status === "Pass"; }).length,
      fail: hosts.filter(function (r) { return r.status === "Fail"; }).length,
      regressed: hosts.filter(function (r) { return r.regressed; }).length,
      unknownHosts: hosts.filter(function (r) { return r.unknown > 0; }).length
    };
  }

  function setRing(ring, label, pct) {
    if (!ring) return;
    ring.style.setProperty("--pct", pct);
    if (label) label.textContent = (Math.round(pct * 10) / 10) + "%";
  }

  /* ============================================================ hero replay */

  (function heroReplay() {
    if (!FLEET) return;
    var pre = $("run-log");
    if (!pre) return;
    var hosts = FLEET.hosts;
    var id = (FLEET.maintenance && FLEET.maintenance.maintenance_id) || "CHG-2026-1012";
    var WIDTH = 78;

    function pad(s, n) { s = String(s); while (s.length < n) s += " "; return s; }
    function header(text) {
      var stars = Math.max(3, WIDTH - text.length - 1);
      return ["h", text + " " + new Array(stars + 1).join("*")];
    }
    function healed(h) { return (h.self_healing && h.self_healing.services_healed) || []; }
    function verdict(h) {
      var unknown = h.findings.filter(function (f) { return f.status === "unknown"; }).length;
      var top = h.findings.slice().sort(function (a, b) { return ORDER.indexOf(b.severity) - ORDER.indexOf(a.severity); })[0];
      var line = pad(h.inventory_name, 10) + pad(h.os.distribution, 20);
      if (h.status === "Pass") {
        var fixed = healed(h);
        return ["g", line + "Pass" + (fixed.length ? "   auto-fixed " + fixed.join(", ") : "") + (unknown ? "   " + unknown + " unknown" : "")];
      }
      if (unknown && (!top || top.status === "unknown")) return ["c", line + "Fail   " + unknown + " check(s) could not run"];
      return ["r", line + "Fail   " + (top ? top.severity + ": " + top.id : h.findings.length + " findings")];
    }

    // The task names below are the real ones from the roles; the per-host
    // results are the sample fleet the demo dashboard is rendered from.
    var lines = [
      ["$", "ansible-playbook -i inventory.ini \\"],
      ["", "    sameeralam3127.linux_vitals.postcheck \\"],
      ["", "    -e linux_vitals_maintenance_id=" + id],
      ["", ""],
      header("PLAY [LinuxVitals postcheck health check (post-maintenance)]"),
      ["", ""],
      header("TASK [vitals_scan : Build host health findings]")
    ];
    hosts.forEach(function (h) { lines.push(["g", "ok: [" + h.inventory_name + "]"]); });
    lines.push(["", ""], header("TASK [vitals_heal : Attempt one restart for enabled failed services]"));
    hosts.forEach(function (h) {
      var fixed = healed(h);
      lines.push(fixed.length ? ["y", "changed: [" + h.inventory_name + "] => (item=" + fixed[0] + ")"] : ["c", "skipping: [" + h.inventory_name + "]"]);
    });
    lines.push(["", ""], header("TASK [vitals_report : Generate consolidated HTML dashboard]"),
      ["y", "changed: [" + hosts[0].inventory_name + " -> localhost]"], ["", ""],
      ["d", "# reports/linux_vitals_report.html, compared with the baseline for " + id]);
    hosts.forEach(function (h) { lines.push(verdict(h)); });
    var s = FLEET.summary || {};
    lines.push(["", ""], ["h", "Health score " + s.health_score_pct + "% (" + s.health_score_band + "), " +
      s.failing_host_count + " failing, " + s.regressed_count + " regressed, " + s.improved_count + " improved"]);

    // Keep the newest line in view, the way a terminal scrolls.
    var term = new Terminal(pre);
    var write = term.write;
    term.write = function (line, text) {
      var span = write.call(term, line, text);
      pre.scrollTop = pre.scrollHeight;
      return span;
    };
    if (window.MutationObserver) {
      new MutationObserver(function () { pre.scrollTop = pre.scrollHeight; }).observe(pre, { childList: true, subtree: true, characterData: true });
    }

    $("run-replay").addEventListener("click", function () { term.play(lines); });
    term.play(lines);
  })();

  /* ====================================================== triage playground */

  (function triage() {
    if (!FLEET || !$("tp-hosts")) return;
    var state = { threshold: "info", gate: "", count: 0, overrides: {} };
    var previous = {};

    // Findings this fleet raises, most common first.
    var counts = {};
    FLEET.hosts.forEach(function (h) {
      var seen = {};
      h.findings.forEach(function (f) { if (!seen[f.id]) { seen[f.id] = 1; counts[f.id] = (counts[f.id] || 0) + 1; } });
    });
    var ids = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a] || a.localeCompare(b); });

    var tbody = $("tp-overrides");
    ids.forEach(function (fid) {
      var def = DEFAULT_MAP[fid] || "warning";
      var sel = el("select", { "aria-label": "Severity for " + fid });
      ORDER.forEach(function (lvl) {
        var opt = el("option", { value: lvl, text: lvl + (lvl === def ? " (default)" : "") });
        if (lvl === def) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", function () {
        if (sel.value === def) delete state.overrides[fid]; else state.overrides[fid] = sel.value;
        sel.classList.toggle("changed", sel.value !== def);
        render();
      });
      tbody.appendChild(el("tr", {}, [
        el("td", { text: fid }),
        el("td", {}, [el("span", { class: "n", text: "×" + counts[fid] }), sel])
      ]));
    });

    function seg(id, key) {
      each($(id).querySelectorAll("button"), function (btn) {
        btn.addEventListener("click", function () {
          state[key] = btn.getAttribute("data-v");
          each($(id).querySelectorAll("button"), function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
          render();
        });
      });
    }
    seg("tp-threshold", "threshold");
    seg("tp-gate", "gate");
    $("tp-count").addEventListener("input", function (e) {
      state.count = Math.max(0, parseInt(e.target.value, 10) || 0);
      render();
    });

    function yaml() {
      var out = ["---"];
      var keys = Object.keys(state.overrides);
      if (state.threshold !== "info") out.push("linux_vitals_fail_on_severity: " + state.threshold);
      if (keys.length) {
        out.push("linux_vitals_finding_severity_overrides:");
        keys.forEach(function (k) { out.push("  " + k + ": " + state.overrides[k]); });
      }
      if (state.gate) {
        out.push("linux_vitals_fail_on_status: " + state.gate);
        if (state.count) out.push("linux_vitals_fail_threshold_count: " + state.count);
      }
      if (out.length === 1) out.push("# Everything at its default: any finding fails a host, and no gate.");
      return out.join("\n");
    }

    function render() {
      var s = score(FLEET, state.threshold, state.overrides);
      setRing($("tp-ring"), $("tp-pct"), s.pct);
      $("tp-pass").textContent = s.pass;
      $("tp-fail").textContent = s.fail;
      $("tp-reg").textContent = s.regressed;
      var bandText = "Health score " + s.pct + "% — " + s.band + ".";
      if (s.unknownHosts) {
        bandText += " " + s.unknownHosts + " host" + (s.unknownHosts === 1 ? " has" : "s have") +
          " a check that could not run, so " + (s.unknownHosts === 1 ? "it" : "they") + " never count as healthy, whatever the threshold.";
      }
      $("tp-band").textContent = bandText;

      var grid = $("tp-hosts");
      grid.innerHTML = "";
      s.hosts.forEach(function (r) {
        var h = r.host, name = h.inventory_name;
        var failing = h.findings.filter(function (f) { return ORDER.indexOf(levelOf(f, state.overrides)) >= ORDER.indexOf(state.threshold); });
        var detail = !h.findings.length ? "no findings"
          : failing.length ? failing.length + " of " + h.findings.length + " findings count"
          : h.findings.length + " finding" + (h.findings.length === 1 ? "" : "s") + ", below threshold";
        if (r.unknown) detail += " · " + r.unknown + " unknown";
        if (r.regressed) detail += " · regressed";
        else if (!r.before) detail += " · new host";
        var title = h.findings.map(function (f) {
          return f.id + " (" + levelOf(f, state.overrides) + (f.status === "unknown" ? ", unknown" : "") + ")";
        }).join("\n") || "No findings";
        var card = el("div", { class: "hcard" + (r.status === "Fail" ? " fail" : ""), title: title }, [
          el("div", { class: "hn" }, [el("span", { text: name }), el("span", { class: "st " + r.status.toLowerCase(), text: r.status })]),
          el("div", { class: "ho", text: h.os.distribution }),
          el("div", { class: "hf", text: detail })
        ]);
        if (previous[name] && previous[name] !== r.status && !reduced) card.classList.add("flip");
        previous[name] = r.status;
        grid.appendChild(card);
      });

      var gate = $("tp-gate-out");
      gate.innerHTML = "";
      if (!state.gate) {
        gate.setAttribute("data-state", "off");
        gate.appendChild(el("span", { class: "exit", text: "exit 0" }));
        gate.appendChild(el("span", { text: "No gate: the exit code does not depend on fleet health." }));
      } else {
        var n = state.gate === "any_fail" ? s.fail : s.regressed;
        var fails = n > state.count;
        gate.setAttribute("data-state", fails ? "fail" : "ok");
        gate.appendChild(el("span", { class: "exit", text: fails ? "exit 2" : "exit 0" }));
        gate.appendChild(el("span", {}, [
          (state.gate === "any_fail" ? n + " failing" : n + " regressed") + " host" + (n === 1 ? "" : "s") +
          " vs. a threshold of " + state.count + " — " +
          (fails ? "the play fails, after the reports and notifications are written." : "the run passes.")
        ]));
      }
      $("tp-yaml").textContent = yaml();
    }
    render();
  })();

  /* ===================================================== detection explorer */

  var FAMILIES = [
    {
      id: "debian", name: "Debian / Ubuntu", sub: "apt · reboot-required-file",
      facts: [["Primary", "/run/reboot-required"], ["Then", "/var/run/reboot-required"], ["Bootloader", "GRUB_DEFAULT + grubenv"]],
      lines: [
        ["$", "test -e /run/reboot-required && echo present"],
        ["", "present"],
        ["$", "cat /run/reboot-required.pkgs"],
        ["", "linux-image-6.8.0-47-generic"],
        ["", "libc6"],
        ["$", "grep '^GRUB_DEFAULT' /etc/default/grub"],
        ["", "GRUB_DEFAULT=0"],
        ["d", "# report.json → hosts[].reboot"],
        ["y", '"required": true,'],
        ["p", '"source": "reboot-required-file",'],
        ["", '"pending_packages": ["linux-image-6.8.0-47-generic", "libc6"]']
      ]
    },
    {
      id: "rhel", name: "RHEL / Rocky / Alma / Amazon Linux", sub: "dnf · needs-restarting",
      facts: [["Primary", "needs-restarting -r"], ["Exit codes", "0 = no, 1 = yes, anything else = unusable"], ["Bootloader", "grubby --default-kernel"]],
      lines: [
        ["$", "needs-restarting -r; echo \"exit=$?\""],
        ["", "Core libraries or services have been updated since boot-up:"],
        ["", "  * kernel"],
        ["", "Reboot is required to fully utilize these updates."],
        ["", "exit=1"],
        ["$", "grubby --default-kernel"],
        ["", "/boot/vmlinuz-5.14.0-503.14.1.el9_5.x86_64"],
        ["d", "# report.json → hosts[].reboot"],
        ["y", '"required": true,'],
        ["p", '"source": "needs-restarting"'],
        ["d", "# hosts[].bootloader"],
        ["g", '"default_source": "grubby", "default_matches_latest": true']
      ]
    },
    {
      id: "fedora", name: "Fedora (dnf5)", sub: "dnf5 · dnf-needs-restarting",
      facts: [["Primary", "needs-restarting -r"], ["Fallback", "dnf needs-restarting --reboothint"], ["Bootloader", "BLS entries / grubby"]],
      lines: [
        ["$", "command -v needs-restarting || echo missing"],
        ["", "missing"],
        ["d", "# dnf5 dropped the standalone binary — use the plugin instead"],
        ["$", "dnf needs-restarting --reboothint; echo \"exit=$?\""],
        ["", "Reboot is required to fully utilize these updates."],
        ["", "exit=1"],
        ["d", "# report.json → hosts[].reboot"],
        ["y", '"required": true,'],
        ["p", '"source": "dnf-needs-restarting"']
      ]
    },
    {
      id: "suse", name: "openSUSE / SLES", sub: "zypper · zypper-needs-rebooting",
      facts: [["Primary", "zypper needs-rebooting (102 = reboot)"], ["Fallback", "/run/reboot-needed and friends"], ["Bootloader", "grub2-editenv + grubenv"]],
      lines: [
        ["$", "zypper needs-rebooting; echo \"exit=$?\""],
        ["", "Core libraries or services have been updated."],
        ["", "Reboot is required to ensure that your system benefits from these updates."],
        ["", "exit=102"],
        ["$", "grub2-editenv list | grep saved_entry"],
        ["", "saved_entry=opensuse-leap-15.6-6.4.0-150600.23.25-default"],
        ["d", "# report.json → hosts[].reboot"],
        ["y", '"required": true,'],
        ["p", '"source": "zypper-needs-rebooting"']
      ]
    },
    {
      id: "none", name: "No usable check", sub: "any family · kernel-comparison",
      facts: [["Rule", "an unusable answer is never \"no reboot\""], ["Fallback", "running vs. latest installed kernel"], ["Dashboard", "\"no distro check\""]],
      lines: [
        ["$", "needs-restarting -r; echo \"exit=$?\""],
        ["r", "sh: needs-restarting: not found"],
        ["", "exit=127"],
        ["d", "# not 0 or 1: supported=false — fall back, and say so"],
        ["$", "uname -r"],
        ["", "5.14.0-427.13.1.el9_4.x86_64"],
        ["$", "ls /lib/modules"],
        ["", "5.14.0-427.13.1.el9_4.x86_64  5.14.0-503.14.1.el9_5.x86_64"],
        ["d", "# report.json → hosts[].reboot"],
        ["y", '"required": true, "detection_supported": false,'],
        ["p", '"source": "kernel-comparison",'],
        ["", '"reason": "Reboot required: running kernel is not the latest installed kernel (no distro reboot check available on this host)"']
      ]
    }
  ];

  (function detection() {
    var list = $("dx-list");
    if (!list) return;
    var term = new Terminal($("dx-term")), current = FAMILIES[0], started = false;
    function select(fam, play) {
      current = fam;
      each(list.children, function (b) { b.setAttribute("aria-selected", String(b.getAttribute("data-id") === fam.id)); });
      $("dx-title").textContent = "vitals_scan · " + fam.name;
      var facts = $("dx-facts");
      facts.innerHTML = "";
      fam.facts.forEach(function (f) {
        facts.appendChild(el("span", { class: "note" }, [f[0] + ": ", el("code", { text: f[1] })]));
      });
      if (play) term.play(fam.lines);
    }
    FAMILIES.forEach(function (fam) {
      var btn = el("button", { type: "button", class: "dx-item", role: "tab", "data-id": fam.id, "aria-selected": "false" },
        [el("b", { text: fam.name }), el("span", { text: fam.sub })]);
      btn.addEventListener("click", function () { started = true; select(fam, true); });
      list.appendChild(btn);
    });
    $("dx-replay").addEventListener("click", function () { started = true; term.play(current.lines); });
    select(FAMILIES[0], false);
    whenVisible($("dx-term"), function () { if (!started) { started = true; term.play(current.lines); } });
  })();

  /* ======================================================= workflow replay */

  (function workflow() {
    var steps = $("wf-steps");
    if (!steps || !FLEET) return;
    var id = (FLEET.maintenance && FLEET.maintenance.maintenance_id) || "CHG-2026-1012";
    var base = FLEET.baseline_findings || {};
    var baseHosts = FLEET.hosts.filter(function (h) { return base[h.inventory_name]; });
    var s = FLEET.summary || {};
    var regressed = FLEET.hosts.filter(function (h) { return h.comparison && h.comparison.status_regressed; });
    var improved = FLEET.hosts.filter(function (h) { return h.comparison && h.comparison.status_improved; });
    var names = function (list) { return list.map(function (h) { return h.inventory_name; }).join(", ") || "none"; };
    function recap(hosts) {
      return hosts.slice(0, 3).map(function (h) {
        var n = h.inventory_name;
        return ["g", (n + "                ").slice(0, 16) + ": unreachable=0  failed=0"];
      }).concat([["d", "… " + (hosts.length - 3) + " more hosts, none failed"]]);
    }
    var scripts = {
      baseline: [
        ["$", "ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline -e linux_vitals_maintenance_id=" + id],
        ["", "PLAY [LinuxVitals baseline health check (pre-maintenance)] ****"],
        ["", "TASK [vitals_scan : Collect host discovery and extended system details]"],
        ["d", "ok: [" + baseHosts.slice(0, 4).map(function (h) { return h.inventory_name; }).join("] ok: [") + "] …"],
        ["", "TASK [vitals_report : Persist this host's snapshot for the current phase]"],
        ["y", "changed: " + baseHosts.length + " hosts → reports/snapshots/" + id + "/baseline/"],
        ["", "PLAY RECAP ****"]
      ].concat(recap(baseHosts)),
      patch: [
        ["d", "# however you normally patch — LinuxVitals is not involved"],
        ["$", "ansible-playbook -i inventory.ini your-patching.yml --limit linux_servers"],
        ["y", "changed: [web-01] => kernel, openssl, nginx"],
        ["y", "changed: [db-01] => kernel, glibc"],
        ["d", "…"],
        ["", "TASK [Reboot when the kernel changed]"],
        ["g", "changed: [web-01] => rebooted"],
        ["d", "…"]
      ],
      postcheck: [
        ["$", "ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.postcheck -e linux_vitals_maintenance_id=" + id],
        ["", "PLAY [LinuxVitals postcheck health check (post-maintenance)] ****"],
        ["", "TASK [vitals_heal : Attempt self-healing for failed enabled services]"],
        ["y", "changed: [web-01] => nginx.service"],
        ["", "TASK [vitals_report : Build before/after comparison for this host]"],
        ["d", "ok: " + FLEET.hosts.length + " hosts (" + (s.new_hosts_count || 0) + " without a baseline)"],
        ["", "TASK [vitals_report : Build reports]"],
        ["g", "improved:  " + names(improved)],
        ["r", "regressed: " + names(regressed)],
        ["p", "health score " + s.health_score_pct + "% (" + s.health_score_band + ") · " + s.auto_fixed_count + " auto-fixed"],
        ["", "→ reports/linux_vitals_report.html"]
      ]
    };
    var term = new Terminal($("wf-term")), current = "baseline", started = false;
    function select(step) {
      current = step;
      each(steps.children, function (n) { n.setAttribute("aria-pressed", String(n.getAttribute("data-step") === step)); });
      $("wf-title").textContent = "control node · " + (step === "patch" ? "maintenance" : step);
      started = true;
      term.play(scripts[step]);
    }
    each(steps.children, function (n) {
      n.addEventListener("click", function () { select(n.getAttribute("data-step")); });
      n.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(n.getAttribute("data-step")); }
      });
    });
    $("wf-replay").addEventListener("click", function () { select(current); });
    whenVisible($("wf-term"), function () { if (!started) select("baseline"); });
  })();

  /* ============================================== static release timeline */

  var releaseLinks = {};
  function renderTimeline() {
    var tl = $("tl"), log = window.LV_CHANGELOG;
    if (!tl || !log) return;
    tl.innerHTML = "";
    var shown = 0, LIMIT = 5;
    log.forEach(function (entry, idx) {
      var unreleased = entry.version === "Unreleased";
      var url = releaseLinks[entry.version] ||
        (unreleased ? GH + "/compare/v" + (log[1] && log[1].version) + "...main"
                    : GH + "/blob/main/CHANGELOG.md");
      var head = el("div", { class: "tl-head" }, [
        el("a", { href: url, text: unreleased ? "Next release" : "v" + entry.version }),
        el("time", { text: unreleased ? "unreleased · on main" : fmtDate(entry.date) })
      ]);
      var counts = Object.keys(entry.sections).map(function (k) { return entry.sections[k] + " " + k.toLowerCase(); }).join(" · ");
      var item = el("div", { class: "tl-item" + (idx === 1 ? " latest" : "") }, [head]);
      if (counts) item.appendChild(el("div", { class: "road-meta", text: counts }));
      var ul = el("ul");
      entry.highlights.slice(0, 4).forEach(function (h) { ul.appendChild(el("li", {}, [codeText(h)])); });
      if (entry.highlights.length) item.appendChild(ul);
      if (shown++ >= LIMIT) item.style.display = "none";
      tl.appendChild(item);
    });
    if (log.length > LIMIT) {
      var more = el("button", { type: "button", class: "tl-more", text: "Show " + (log.length - LIMIT) + " older releases" });
      more.addEventListener("click", function () {
        each(tl.querySelectorAll(".tl-item"), function (n) { n.style.display = ""; });
        more.remove();
      });
      tl.appendChild(more);
    }
  }
  renderTimeline();

  /* ======================================================== static roadmap */

  // What docs/roadmap.md says, for when the milestones API is unreachable.
  var ROADMAP_FALLBACK = [
    { title: "2.2.0", theme: "Trust", due: "2026-11-30", open: 7, closed: 1,
      desc: "The report can be believed. Nothing new on the dashboard except filesystem capacity.", url: GH + "/milestone/5" },
    { title: "2.3.0", theme: "Coverage", due: "2027-01-31", open: 8, closed: 0,
      desc: "The report is more complete, the task tree is one a contributor can navigate, and the fleet-size claim is measured.", url: GH + "/milestone/6" },
    { title: "2.1.0", theme: "Shipped", due: "2026-10-10", open: 0, closed: 3,
      desc: "The 2.16 floor fixes, the fleet health gate, the check-mode refusal, Debian 12 and Amazon Linux 2023 in CI.", url: GH + "/milestone/4" }
  ];

  function renderRoadmap(list) {
    var host = $("roadmap-list");
    if (!host) return;
    host.innerHTML = "";
    list.forEach(function (m) {
      var total = m.open + m.closed, pct = total ? Math.round(m.closed / total * 100) : 0;
      var fill = el("i");
      var card = el("div", { class: "ms reveal in" }, [
        el("div", { class: "ms-head" }, [
          el("h3", {}, [el("a", { href: m.url, text: m.title + (m.theme ? " — " + m.theme : "") })]),
          el("span", { class: "ms-due", text: m.open ? "due " + fmtDate(m.due) : "shipped" })
        ]),
        el("p", {}, [codeText(m.desc)]),
        el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct), "aria-label": m.title + " progress" }, [fill]),
        el("div", { class: "ms-count", text: m.closed + " of " + total + " issues closed · " + pct + "%" })
      ]);
      if (m.issues && m.issues.length) {
        var ul = el("ul");
        m.issues.slice(0, 6).forEach(function (i) {
          ul.appendChild(el("li", { class: i.state }, [el("a", { href: i.html_url }, [
            el("span", { class: "s " + (i.state === "closed" ? "c" : "o"), text: i.state === "closed" ? "✓" : "○" }),
            el("span", { text: "#" + i.number + " " + i.title })
          ])]));
        });
        if (m.issues.length > 6) ul.appendChild(el("li", {}, [el("a", { href: m.url, text: "+ " + (m.issues.length - 6) + " more →" })]));
        card.appendChild(ul);
      }
      host.appendChild(card);
      whenVisible(card, function () { setTimeout(function () { fill.style.width = pct + "%"; }, 80); });
    });
  }
  renderRoadmap(ROADMAP_FALLBACK);

  /* =============================================================== live data */

  // GitHub allows 60 unauthenticated requests an hour per IP, shared with
  // everything else the visitor does on github.com. Cache for ten minutes so
  // a few page loads don't spend the budget.
  var TTL = 10 * 60 * 1000;
  function get(path) {
    var key = "lv-gh:" + path, cached = null;
    try { cached = JSON.parse(localStorage.getItem(key) || "null"); } catch (e) {}
    if (cached && Date.now() - cached.t < TTL) return Promise.resolve(cached.d);
    if (!window.fetch) return Promise.reject(new Error("no fetch"));
    return fetch(API + path, { headers: { Accept: "application/vnd.github+json" } }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    }).then(function (d) {
      try { localStorage.setItem(key, JSON.stringify({ t: Date.now(), d: d })); } catch (e) {}
      return d;
    });
  }
  function mark(id, state) { var n = $(id); if (n) n.setAttribute("data-live", state); }

  get("").then(function (repo) {
    countUp($("k-stars"), repo.stargazers_count);
    $("v-stars").textContent = repo.stargazers_count === 1 ? "star on GitHub" : "stars on GitHub";
    mark("stat-stars", "ok");
    if (repo.pushed_at) {
      $("k-updated").textContent = ago(repo.pushed_at);
      $("v-updated").textContent = "last commit";
      $("foot-updated").textContent = "Last updated " + ago(repo.pushed_at);
      mark("stat-updated", "ok");
    }
  }).catch(function () {});

  get("/releases?per_page=20").then(function (rels) {
    rels = rels.filter(function (r) { return !r.draft && !r.prerelease; });
    rels.forEach(function (r) { releaseLinks[r.tag_name.replace(/^v/, "")] = r.html_url; });
    renderTimeline();
    var rel = rels[0];
    if (!rel) return;
    $("k-version").textContent = rel.tag_name;
    $("v-version").textContent = "released " + ago(rel.published_at);
    mark("stat-version", "ok");
    each(document.querySelectorAll("[data-lv-version-bare]"), function (n) { n.textContent = rel.tag_name.replace(/^v/, ""); });
  }).catch(function () {});

  get("/actions/workflows/ci.yml/runs?branch=main&status=completed&per_page=1").then(function (data) {
    var run = data.workflow_runs && data.workflow_runs[0];
    if (!run) return;
    var ok = run.conclusion === "success";
    $("k-ci").textContent = ok ? "Passing" : "Failing";
    $("v-ci").textContent = "CI on main · 6 distros";
    mark("stat-ci", ok ? "ok" : "fail");
    var badge = $("feed-ci");
    badge.textContent = "";
    badge.appendChild(el("a", { href: run.html_url, style: "padding:0;border:0;display:inline;color:var(--" + (ok ? "good" : "critical") + ")", text: ok ? "● CI passing" : "● CI failing" }));
  }).catch(function () {});

  get("/commits?sha=main&per_page=6").then(function (commits) {
    var list = $("feed-list");
    if (!commits.length) return;
    list.innerHTML = "";
    commits.forEach(function (c) {
      var msg = (c.commit.message || "").split("\n")[0];
      var who = (c.author && c.author.login) || (c.commit.author && c.commit.author.name) || "";
      list.appendChild(el("a", { href: c.html_url }, [
        codeText(msg),
        el("span", { class: "meta", text: c.sha.slice(0, 7) + " · " + who + " · " + ago(c.commit.author.date) })
      ]));
    });
  }).catch(function () {});

  get("/contributors?per_page=24").then(function (people) {
    var host = $("avatars");
    people = people.filter(function (p) { return p.type === "User"; });
    if (!people.length) return;
    host.innerHTML = "";
    people.forEach(function (p) {
      host.appendChild(el("a", { href: p.html_url, title: p.login + " · " + p.contributions + " commits" }, [
        el("img", { src: p.avatar_url + "&s=68", alt: p.login, width: "34", height: "34", loading: "lazy" })
      ]));
    });
  }).catch(function () {});

  // Release milestones are the ones named like a version; the older themed
  // milestones predate the roadmap and are all closed out.
  get("/milestones?state=all&per_page=30").then(function (ms) {
    var releases = ms.filter(function (m) { return /^\d+\.\d+\.\d+$/.test(m.title); });
    if (!releases.length) return;
    var themes = {};
    ROADMAP_FALLBACK.forEach(function (f) { themes[f.title] = f.theme; });
    var open = releases.filter(function (m) { return m.state === "open"; })
      .sort(function (a, b) { return (a.due_on || "9").localeCompare(b.due_on || "9"); });
    var closed = releases.filter(function (m) { return m.state === "closed"; })
      .sort(function (a, b) { return (b.closed_at || "").localeCompare(a.closed_at || ""); }).slice(0, 1);
    var chosen = open.concat(closed);
    return Promise.all(chosen.map(function (m) {
      return get("/issues?milestone=" + m.number + "&state=all&per_page=50").catch(function () { return []; });
    })).then(function (issueLists) {
      renderRoadmap(chosen.map(function (m, i) {
        var issues = (issueLists[i] || []).filter(function (x) { return !x.pull_request; })
          .sort(function (a, b) { return (a.state === b.state ? 0 : a.state === "open" ? -1 : 1) || a.number - b.number; });
        // Prefer the curated one-liner; a milestone description is a list of
        // issue numbers after its first sentence.
        var known = ROADMAP_FALLBACK.filter(function (f) { return f.title === m.title && m.state === "open"; })[0];
        var first = (m.description || "").replace(/^[^:]*:\s*/, "").split(/\.(?:\s|$)/)[0];
        var desc = known ? known.desc : first ? first.charAt(0).toUpperCase() + first.slice(1) + "." : "";
        return {
          title: m.title,
          theme: m.state === "closed" ? "Shipped" : (themes[m.title] || (m.description || "").split(":")[0]),
          due: m.state === "closed" ? (m.closed_at || "").slice(0, 10) : (m.due_on || "").slice(0, 10),
          open: m.open_issues, closed: m.closed_issues,
          desc: desc,
          url: m.html_url,
          issues: issues
        };
      }));
    });
  }).catch(function () {});
})();
