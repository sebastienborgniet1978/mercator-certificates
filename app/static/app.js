(() => {
  "use strict";

  const STATE_LABEL = {
    valid: "Valide", warning: "À surveiller", critical: "Critique",
    expired: "Expiré", revoked: "Révoqué", nodate: "Sans date",
  };
  const STATE_ORDER = { expired: 0, revoked: 1, critical: 2, warning: 3, valid: 4, nodate: 5 };

  let data = null;           // dernière réponse de l'API
  let cat = "";              // "", "certificate", "license"
  const CAT_LABEL = { certificate: "Certificat", license: "Licence", domain: "Domaine" };
  let sortKey = "end_validity", sortDir = 1;
  const $ = (id) => document.getElementById(id);

  // Création d'éléments sans innerHTML : les données Mercator sont saisies par des
  // utilisateurs, on ne les injecte jamais comme HTML.
  function el(tag, props = {}, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("data-")) n.setAttribute(k, v);
      else n[k] = v;
    }
    for (const c of children) if (c != null) n.append(c);
    return n;
  }
  // Liens vers l'interface web de Mercator (nécessite MERCATOR_PUBLIC_URL)
  const mercatorUrl = (c, suffix = "") => data && data.mercator_public_url
    ? data.mercator_public_url + "/admin/certificates/" + encodeURIComponent(c.id) + suffix : null;
  const chip = (state) => el("span", { class: "chip " + state, text: STATE_LABEL[state] || state });
  const names = (list) => (list || []).map((x) => x.name).join(", ");
  const fmtDate = (d) => (d ? d.split("-").reverse().join("/") : "—");

  async function load(force = false) {
    $("refresh").disabled = true;
    try {
      const r = await fetch("/api/certificates" + (force ? "?refresh=true" : ""));
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || "Erreur HTTP " + r.status);
      data = body;
      document.title = data.title;
      $("title").textContent = data.title;
      banner(data.stale_error
        ? "Mercator est injoignable (" + data.stale_error + ") : affichage des dernières données en cache."
        : null, true);
      const t = new Date(data.fetched_at);
      $("fetched").textContent = "Données du " + t.toLocaleString("fr-FR");
      fillTypes();
      render();
    } catch (e) {
      banner("Impossible de récupérer les certificats : " + e.message, false);
    } finally {
      $("refresh").disabled = false;
    }
  }

  function banner(msg, isWarn) {
    const b = $("banner");
    b.hidden = !msg;
    b.className = "banner" + (isWarn ? " warn" : "");
    b.textContent = msg || "";
  }

  const inCat = (c) => !cat || c.category === cat;

  function fillTypes() {
    const sel = $("f-type"), cur = sel.value;
    const types = [...new Set(data.items.filter(inCat).map((c) => c.type).filter(Boolean))].sort();
    sel.replaceChildren(el("option", { value: "", text: "Tous les types" }),
      ...types.map((t) => el("option", { value: t, text: t })));
    sel.value = types.includes(cur) ? cur : "";
  }

  function filtered() {
    const q = $("q").value.trim().toLowerCase();
    const st = $("f-state").value, ty = $("f-type").value;
    return data.items.filter((c) => {
      if (!inCat(c)) return false;
      if (st && c.state !== st) return false;
      if (ty && c.type !== ty) return false;
      if (!q) return true;
      const hay = [c.name, c.description, c.type, c.ext_refs, names(c.logical_servers), names(c.applications)]
        .join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function sortItems(items) {
    const k = sortKey;
    const val = (c) => {
      if (k === "state") return STATE_ORDER[c.state];
      return c[k];
    };
    return items.slice().sort((a, b) => {
      const x = val(a), y = val(b);
      // les valeurs vides sont toujours en fin de liste
      if (x == null || x === "") return y == null || y === "" ? 0 : 1;
      if (y == null || y === "") return -1;
      if (typeof x === "number") return (x - y) * sortDir;
      return String(x).localeCompare(String(y), "fr", { numeric: true }) * sortDir;
    });
  }

  function renderKpis() {
    const active = $("f-state").value;
    const s = { total: 0, valid: 0, warning: 0, critical: 0, expired: 0, revoked: 0, nodate: 0 };
    for (const c of data.items.filter(inCat)) { s.total++; s[c.state]++; }
    const defs = [
      ["", "Total", s.total],
      ["expired", "Expirés", s.expired],
      ["critical", "≤ " + data.thresholds.critical + " jours", s.critical],
      ["warning", "≤ " + data.thresholds.warning + " jours", s.warning],
      ["valid", "Valides", s.valid],
    ];
    if (s.revoked) defs.push(["revoked", "Révoqués", s.revoked]);
    if (s.nodate) defs.push(["nodate", "Sans date", s.nodate]);
    $("kpis").replaceChildren(...defs.map(([key, label, n]) =>
      el("button", { class: "kpi" + (active === key ? " active" : ""), "data-s": key, type: "button",
                     onclick: () => { $("f-state").value = active === key ? "" : key; render(); } },
        el("div", { class: "n", text: String(n) }), el("div", { class: "l", text: label }))));
  }

  function renderSeg() {
    const n = (k) => data.items.filter((c) => !k || c.category === k).length;
    $("seg").replaceChildren(...[["", "Tous"], ["certificate", "Certificats"], ["license", "Licences"], ["domain", "Domaines"]].map(
      ([k, label]) => el("button", { type: "button", class: cat === k ? "active" : "",
        onclick: () => { cat = k; $("f-type").value = ""; fillTypes(); render(); } },
        label, el("span", { class: "c", text: "(" + n(k) + ")" }))));
  }

  function render() {
    if (!data) return;
    renderSeg();
    renderKpis();
    const items = sortItems(filtered());
    $("count").textContent = items.length + " / " + data.items.filter(inCat).length + " éléments";
    $("empty").hidden = items.length > 0;
    $("rows").replaceChildren(...items.map((c) =>
      el("tr", { onclick: () => openDetail(c) },
        el("td", { text: c.name }),
        el("td", {}, el("span", { class: "chip cat-" + c.category, text: CAT_LABEL[c.category] })),
        el("td", { text: c.type }),
        el("td", { class: "num", text: fmtDate(c.start_validity) }),
        el("td", { class: "num", text: fmtDate(c.end_validity) }),
        el("td", { class: "num", text: c.days_left == null ? "—" : String(c.days_left) }),
        el("td", {}, chip(c.state)),
        el("td", { text: c.status_label }),
        el("td", {}, ...c.logical_servers.map((s) => el("span", { class: "tag", text: s.name }))),
        el("td", {}, ...c.applications.map((a) => el("span", { class: "tag", text: a.name }))),
        el("td", {}, mercatorUrl(c, "/edit")
          ? el("a", { class: "lnk", href: mercatorUrl(c, "/edit"), target: "_blank", rel: "noopener",
                      title: "Ouvrir l'écran d'édition dans Mercator pour renouveler",
                      onclick: (e) => e.stopPropagation(), text: "Renouveler ↗" })
          : null))));
    document.querySelectorAll("th[data-k]").forEach((th) => {
      th.classList.remove("sorted-asc", "sorted-desc");
      if (th.dataset.k === sortKey) th.classList.add(sortDir === 1 ? "sorted-asc" : "sorted-desc");
    });
  }

  function openDetail(c) {
    const row = (label, ...content) => [el("dt", { text: label }), el("dd", {}, ...content)];
    const tags = (list) => list.length
      ? list.map((x) => el("span", { class: "tag", text: x.name })) : ["—"];
    const dl = el("dl", {},
      ...row("Catégorie", el("span", { class: "chip cat-" + c.category, text: CAT_LABEL[c.category] })),
      ...row("Type", c.type || "—"),
      ...row("Début de validité", fmtDate(c.start_validity)),
      ...row("Fin de validité", fmtDate(c.end_validity)),
      ...row("Jours restants", c.days_left == null ? "—" : String(c.days_left)),
      ...row("Échéance", chip(c.state)),
      ...row("Statut (RFC 6960)", c.status_label || "—"),
      ...row("Serveurs logiques", ...tags(c.logical_servers)),
      ...row("Applications", ...tags(c.applications)),
      ...row("Réf. externes", c.ext_refs || "—"),
      ...row("Description", el("pre", { text: c.description || "—" })),
      ...row("Mis à jour", c.updated_at ? new Date(c.updated_at).toLocaleString("fr-FR") : "—"));
    const nodes = [el("h2", { text: c.name }), dl];
    if (data.mercator_public_url) {
      nodes.push(
        el("a", { class: "btn btn-primary", href: mercatorUrl(c, "/edit"), target: "_blank", rel: "noopener",
                  text: "Gérer le renouvellement dans Mercator ↗" }),
        el("p", {}, el("a", { href: mercatorUrl(c), target: "_blank", rel: "noopener", text: "Voir la fiche dans Mercator ↗" })));
    }
    $("detail").replaceChildren(...nodes);
    $("drawer").hidden = false;
  }

  function csvCell(v) {
    const s = String(v ?? "");
    return /[";\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function exportCsv() {
    const head = ["Nom", "Catégorie", "Type", "Début", "Fin", "Jours restants", "Échéance", "Statut", "Serveurs", "Applications", "Description"];
    const lines = [head, ...sortItems(filtered()).map((c) => [
      c.name, CAT_LABEL[c.category], c.type, c.start_validity, c.end_validity, c.days_left, STATE_LABEL[c.state],
      c.status_label, names(c.logical_servers), names(c.applications), c.description,
    ])].map((r) => r.map(csvCell).join(";"));
    // BOM + « ; » : s'ouvre directement dans Excel FR
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = el("a", { href: URL.createObjectURL(blob),
      download: "certificats_" + new Date().toISOString().slice(0, 10) + ".csv" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // --- rapport de contrôle PDF
  const fmtDT = (iso) => new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  const SCOPE = { "": "Tout", certificate: "Certificats", license: "Licences", domain: "Domaines" };

  async function loadHistory() {
    try {
      const rows = await (await fetch("/api/reports")).json();
      $("hist-empty").hidden = rows.length > 0;
      $("hist").replaceChildren(...rows.map((h) => el("tr", {},
        el("td", { text: fmtDT(h.generated_at) }), el("td", { text: h.controller }),
        el("td", { text: SCOPE[h.scope] || "" }), el("td", { text: String(h.total) }),
        el("td", { text: String(h.expired + h.critical + h.warning + h.revoked) }),
        el("td", {}, el("a", { href: "/api/reports/" + h.id + "/pdf", target: "_blank", rel: "noopener", text: "PDF" }),
                     el("a", { href: "/api/reports/" + h.id + "/json", download: h.id + ".json", text: "Données" })))));
    } catch (e) { /* historique indisponible : sans incidence sur la génération */ }
  }
  function rmsg(text, err) {
    const m = $("r-msg"); m.hidden = !text; m.textContent = text || ""; m.className = "r-msg" + (err ? " err" : "");
  }
  $("report").onclick = () => {
    let who = ""; try { who = localStorage.getItem("controller") || ""; } catch (e) {}
    $("r-who").value = who; $("r-scope").value = cat; $("r-comment").value = ""; rmsg(null);
    $("dlg").showModal(); loadHistory();
  };
  $("r-cancel").onclick = () => $("dlg").close();
  $("rform").onsubmit = async (ev) => {
    ev.preventDefault();
    const btn = $("r-go"); btn.disabled = true; rmsg("Lecture de Mercator et génération du rapport…");
    try {
      const r = await fetch("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ controller: $("r-who").value.trim(), comment: $("r-comment").value,
                               category: $("r-scope").value }) });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Erreur HTTP " + r.status);
      try { localStorage.setItem("controller", $("r-who").value.trim()); } catch (e) {}
      rmsg("Rapport " + body.id + " généré et archivé.");
      const a = el("a", { href: "/api/reports/" + body.id + "/pdf", download: body.id + ".pdf" });
      document.body.append(a); a.click(); a.remove();
      load(false); loadHistory();
    } catch (e) { rmsg(e.message, true); }
    finally { btn.disabled = false; }
  };

  // --- événements
  $("refresh").onclick = () => load(true);
  $("export").onclick = () => data && exportCsv();
  $("q").oninput = render;
  $("f-state").onchange = render;
  $("f-type").onchange = render;
  $("reset").onclick = () => { cat = ""; fillTypes(); $("q").value = ""; $("f-state").value = ""; $("f-type").value = ""; render(); };
  $("close").onclick = () => { $("drawer").hidden = true; };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("drawer").hidden = true; });
  document.querySelectorAll("th[data-k]").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.k;
      if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
      render();
    };
  });

  load();
})();
