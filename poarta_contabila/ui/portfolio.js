// The portfolio calendar (R45): every firm's filing items by due date, read-only.
// It reads GET /calendar and nothing else; it sends nothing. Every value is written as
// text (textContent), never as markup. The firm is shown by its tenant key only.
"use strict";

(() => {
  const TOKEN = "poarta.token"; // the review page's key: one sign-in per tab serves both
  // the columns, in order; the route emits exactly these fields (filings.PORTFOLIO_FIELDS)
  const COLUMNS = [
    ["tenant", "Firm (key)"],
    ["form", "Form"],
    ["filing_id", "Item"],
    ["period", "Period"],
    ["due", "Due"],
    ["dating", "Dated?"],
    ["reason", "Why no date"],
    ["mode", "Mode"],
    ["frequency", "Frequency"],
    ["state", "State"],
    ["lock", "Lock set"],
  ];
  const GROUPS = [
    ["dated", "Dated", "By due date. A date is what the calendar recorded when the item was opened."],
    ["refused", "Refused: no due date", "The calendar refused a date; its reason is shown. Nothing here is hidden."],
    ["later", "Later: owed once its quarter ends", "A quarterly filing whose quarter does not end in the period."],
    ["unrecorded", "Unrecorded", "Opened before due dates were recorded; open the period again."],
  ];

  const memory = { token: "" };
  function token() {
    try { return window.sessionStorage.getItem(TOKEN) || memory.token; } catch { return memory.token; }
  }
  function keep(value) {
    memory.token = value;
    try { window.sessionStorage.setItem(TOKEN, value); } catch { /* kept in memory only */ }
  }
  function forget() {
    memory.token = "";
    try { window.sessionStorage.removeItem(TOKEN); } catch { /* nothing kept */ }
  }

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "class") node.className = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }
  const show = (...nodes) => document.getElementById("app").replaceChildren(...nodes);

  function signIn(message) {
    const tokenIn = el("input", { id: "token", type: "password", autocomplete: "off", required: true });
    const error = el("p", { class: "error", role: "alert" }, message || "");
    show(el(
      "form",
      {
        class: "signin",
        onsubmit: (event) => {
          event.preventDefault();
          if (!tokenIn.value.trim()) { error.textContent = "Paste the operator token."; return; }
          keep(tokenIn.value.trim());
          load();
        },
      },
      el("label", { for: "token" }, "Operator token"),
      tokenIn,
      el("p", { class: "muted small" }, "Kept in this tab only; closing the tab forgets it."),
      error,
      el("button", { type: "submit", class: "primary" }, "Sign in"),
    ));
    tokenIn.focus();
  }

  function table(rows) {
    return el("div", { class: "scroll" }, el(
      "table", {},
      el("thead", {}, el("tr", {}, COLUMNS.map(([, title]) => el("th", {}, title)))),
      el("tbody", {}, rows.map((row) => el(
        "tr", {}, COLUMNS.map(([key]) => el("td", {}, row[key] === null || row[key] === undefined ? "—" : String(row[key]))),
      ))),
    ));
  }

  async function load() {
    if (!token()) { signIn(); return; }
    show(el("p", { class: "muted" }, "Loading…"));
    let resp;
    try {
      resp = await fetch("/calendar", {
        method: "GET",
        headers: { Authorization: "Bearer " + token() },
        credentials: "omit",
        cache: "no-store",
      });
    } catch (err) {
      show(el("p", { class: "error" }, String(err)));
      return;
    }
    if (resp.status === 401) { forget(); signIn("The token was refused. Sign in again."); return; }
    let data = null;
    try { data = await resp.json(); } catch { data = null; }
    if (!resp.ok || !data) {
      const detail = data && data.detail !== undefined ? JSON.stringify(data.detail) : resp.statusText;
      show(el("p", { class: "error" }, `HTTP ${resp.status}: ${detail}`));
      return;
    }
    const counts = GROUPS.map(([key]) => (data[key] || []).length);
    const total = counts.reduce((a, b) => a + b, 0);
    const nodes = [
      el("div", { class: "toolbar" },
        el("div", { class: "who" }, `${total} filing items: ${counts[0]} dated, ${counts[1]} refused, ${counts[2]} later, ${counts[3]} unrecorded.`),
        el("div", {}, el("button", { type: "button", onclick: load }, "Reload")),
        el("div", {}, el("button", { type: "button", onclick: () => { forget(); signIn(); } }, "Sign out"))),
    ];
    if (total > 0 && counts[0] === 0) {
      nodes.push(el("p", { class: "refused", role: "status" },
        "No item has a due date. The calendar dated nothing: every item is listed below with its reason."));
    }
    for (const [i, [key, title, help]] of GROUPS.entries()) {
      const rows = data[key] || [];
      nodes.push(el("section", { class: "card" },
        el("h2", {}, `${title} (${counts[i]})`),
        el("p", { class: "muted small" }, help),
        rows.length ? table(rows) : el("p", { class: "muted" }, "None.")));
    }
    show(...nodes);
  }

  load();
})();
