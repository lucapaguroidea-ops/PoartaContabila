// The review page (WP-66, 00_LAW §8 A8). Every value from the server is written as text
// (textContent), never as markup: a document's fields come from outside this firm.
"use strict";

(() => {
  const KEYS = { token: "poarta.token", name: "poarta.name", cui: "poarta.cui", period: "poarta.period" };
  const NAME_MAX = 64; // answers.OPERATOR_NAME_MAX
  const TYPES = new Set(["bool", "cui", "slug", "str", "int", "object", "null"]);
  const TITLES = {
    v3_approve: "Approve a document primar",
    v2_close: "Close the month (poartă V2)",
    need_rj_export: "Upload the registru jurnal",
    recon_ambiguous: "Which line in the books is this document?",
    recon_review_contest: "Contest a reconcile verdict",
    recon_how_mismatch: "Posted differently than expected",
    no_counterparty: "Name the counterparty",
    define_articol: "Choose the articol de cale",
    define_module: "Choose the write module",
    request_devalidare: "Devalidare needed in SAGA",
    explained_rule: "Explain with a rule",
    patch_maps: "Map a partner to an analytic",
    v4_codit: "Confirm CO.DiT",
    codit_combo: "Choose the CO.DiT axes",
  };

  // ----- storage: the token lives only as long as this tab -----

  function read(area, key) {
    try { return window[area].getItem(key) || ""; } catch { return ""; }
  }
  function write(area, key, value) {
    try { window[area].setItem(key, value); } catch { /* private mode: kept in memory only */ }
  }
  function forget(area, key) {
    try { window[area].removeItem(key); } catch { /* nothing kept */ }
  }
  const memory = { token: "" };
  const token = () => read("sessionStorage", KEYS.token) || memory.token;
  const name = () => read("localStorage", KEYS.name);

  // ----- DOM, text only -----

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
  const app = () => document.getElementById("app");
  const show = (...nodes) => app().replaceChildren(...nodes);
  const text = (value) => (typeof value === "string" ? value : JSON.stringify(value));
  // a refused answer: the server's validation errors, as sentences
  function problem(value) {
    if (Array.isArray(value)) {
      return value.map((e) => (e && e.msg ? `${(e.loc || []).join(".") || "answer"}: ${e.msg}` : text(e))).join("; ");
    }
    return text(value);
  }

  // ----- the API -----

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function api(method, path, body) {
    const headers = { Authorization: "Bearer " + token() };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (method !== "GET") headers["X-Operator-Name"] = name();
    const resp = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
    });
    let data = null;
    try { data = await resp.json(); } catch { data = null; }
    if (!resp.ok) {
      const detail = data && data.detail !== undefined ? text(data.detail) : resp.statusText;
      throw new ApiError(resp.status, `HTTP ${resp.status}: ${detail}`);
    }
    return data;
  }

  // ----- sign in: the shared token, and who is answering -----

  // X-Operator-Name travels as an HTTP header (Latin-1): ă, ș, ț are written without marks.
  function signature(raw) {
    const plain = raw.normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
    return /^[\x20-\x7e]{1,64}$/.test(plain) ? plain : "";
  }

  function signIn(message) {
    const tokenIn = el("input", { id: "token", type: "password", autocomplete: "off", required: true });
    const nameIn = el("input", {
      id: "name", type: "text", value: name(), maxlength: NAME_MAX, autocomplete: "name", required: true,
    });
    const error = el("p", { class: "error", role: "alert" }, message || "");
    const form = el(
      "form",
      {
        class: "signin",
        onsubmit: (event) => {
          event.preventDefault();
          const who = signature(nameIn.value);
          if (!tokenIn.value.trim()) { error.textContent = "Paste the operator token."; return; }
          if (!who) { error.textContent = `Your name: 1–${NAME_MAX} letters, digits or spaces.`; return; }
          memory.token = tokenIn.value.trim();
          write("sessionStorage", KEYS.token, memory.token);
          write("localStorage", KEYS.name, who);
          inbox();
        },
      },
      el("label", { for: "name" }, "Your name"),
      nameIn,
      el("p", { class: "muted small" }, "Every answer is recorded with it."),
      el("label", { for: "token" }, "Operator token"),
      tokenIn,
      el("p", { class: "muted small" }, "Kept in this tab only; closing the tab forgets it."),
      error,
      el("button", { type: "submit", class: "primary" }, "Sign in"),
    );
    show(form);
    (name() ? tokenIn : nameIn).focus();
  }

  function signOut() {
    memory.token = "";
    forget("sessionStorage", KEYS.token);
    signIn();
  }

  // ----- the inbox -----

  function lastMonth() {
    const now = new Date();
    const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  function inbox() {
    if (!token() || !name()) { signIn(); return; }
    const cuiIn = el("input", { id: "cui", type: "text", inputmode: "numeric", value: read("localStorage", KEYS.cui) });
    const periodIn = el("input", { id: "period", type: "month", value: read("localStorage", KEYS.period) || lastMonth() });
    const list = el("div", { id: "items", "aria-live": "polite" });

    async function load() {
      const cui = cuiIn.value.trim();
      const period = periodIn.value;
      if (!/^\d{2,10}$/.test(cui)) { list.replaceChildren(el("p", { class: "error" }, "Write the firm's CUI (digits, no RO).")); return; }
      if (!/^\d{4}-\d{2}$/.test(period)) { list.replaceChildren(el("p", { class: "error" }, "Choose the month.")); return; }
      write("localStorage", KEYS.cui, cui);
      write("localStorage", KEYS.period, period);
      list.replaceChildren(el("p", { class: "muted" }, "Loading…"));
      try {
        const data = await api("GET", `/inbox/${encodeURIComponent(cui)}/${encodeURIComponent(period)}`);
        const items = data.items || [];
        list.replaceChildren(
          el("p", { class: "muted" }, items.length
            ? `${items.length} waiting for firm ${cui} (open documents of any month; reconcile and close of ${period}).`
            : `Nothing waits on an accountant for firm ${cui} (reconcile and close of ${period} included).`),
          ...items.map((item) => card(item, load)),
        );
      } catch (err) {
        if (err.status === 401) { signIn("The token was refused. Sign in again."); return; }
        list.replaceChildren(el("p", { class: "error" }, err.message));
      }
    }

    const toolbar = el(
      "form",
      { class: "toolbar", onsubmit: (event) => { event.preventDefault(); load(); } },
      el("div", {}, el("label", { for: "cui" }, "Firm (CUI)"), cuiIn),
      el("div", {}, el("label", { for: "period" }, "Month for reconcile and close"), periodIn),
      el("div", {}, el("button", { type: "submit", class: "primary" }, "Show questions")),
      el("div", { class: "who" }, `Answering as ${name()} `,
        el("button", { type: "button", onclick: signOut }, "Sign out")),
    );
    show(toolbar, list);
    if (cuiIn.value) load(); else cuiIn.focus();
  }

  // ----- one question -----

  function card(item, reload) {
    const q = item.question;
    const node = el("section", { class: "card" });
    if (!q) {
      const job = item.job || {};
      node.append(
        el("h2", {}, "Needs a person; nothing to answer here"),
        el("p", { class: "flag" }, job.error || "No reason recorded."),
        el("p", { class: "muted small" }, `Job ${job.job_id} · ${job.articol_id} · ${job.period} · ${job.status}`),
      );
      return node;
    }
    node.append(el("h2", {}, TITLES[item.kind] || item.kind), summary(q));
    if (q.error) node.append(el("p", { class: "refused" }, "The last answer was refused: " + problem(q.error)));
    node.append(...facts(q), explanation(item.explanation));
    node.append(el("details", {}, el("summary", {}, "Everything the question holds"),
      el("pre", {}, JSON.stringify(q, null, 2))));
    if (item.answer_path) node.append(answerForm(item, reload));
    return node;
  }

  function summary(q) {
    const doc = q.document;
    if (doc) {
      const partner = doc.partner || {};
      const totals = doc.totals || {};
      return el("p", { class: "muted" }, [
        doc.number, doc.date, partner.name && `${partner.name}${partner.cui ? ` (CUI ${partner.cui})` : ""}`,
        totals.gross && `${totals.gross} ${doc.currency || ""}`.trim(), q.articol_id && `articol de cale ${q.articol_id}`,
      ].filter(Boolean).join(" · "));
    }
    if (q.period) return el("p", { class: "muted" }, `Firm ${q.cui || ""} · ${q.period}${q.material ? " · material" : ""}`);
    return el("p", { class: "muted" }, "");
  }

  function facts(q) {
    const out = [];
    const judge = q.judge;
    if (judge && typeof judge === "object") {
      const parts = [judge.risk && `risk ${judge.risk}`, judge.needs_human && "asks for a person",
        judge.accounts_ok === false && "accounts not confirmed"].filter(Boolean);
      if (parts.length) out.push(el("p", { class: "flag" }, `Jev: ${parts.join(", ")}.`));
    }
    const lines = q.document && Array.isArray(q.document.lines) ? q.document.lines : [];
    if (lines.length) {
      out.push(el("h3", {}, "Lines"), el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Description"), el("th", { class: "num" }, "Qty"),
          el("th", { class: "num" }, "Net"), el("th", { class: "num" }, "TVA %"), el("th", { class: "num" }, "Gross"))),
        el("tbody", {}, lines.map((line) => el("tr", {}, el("td", {}, line.desc || ""),
          el("td", { class: "num" }, line.qty ?? ""), el("td", { class: "num" }, line.net ?? ""),
          el("td", { class: "num" }, line.vat_rate ?? ""), el("td", { class: "num" }, line.gross ?? "")))))));
    }
    if (Array.isArray(q.blockers) && q.blockers.length) {
      out.push(el("h3", {}, "Blockers"), el("ul", {}, q.blockers.map((b) => el("li", {}, text(b)))));
    }
    return out;
  }

  function explanation(e) {
    const box = el("div", { class: "explain" }, el("h3", {}, "Explanation · System Two explains, it decides nothing"));
    if (!e || !e.explanation) {
      box.append(el("p", { class: "muted" }, "No explanation for this question."));
      return box;
    }
    box.append(el("p", {}, e.explanation));
    if (Array.isArray(e.facts_cited) && e.facts_cited.length) {
      box.append(el("ul", { class: "small" }, e.facts_cited.map((f) => el("li", {}, `${f.field}: ${text(f.value)}`))));
    }
    if (Array.isArray(e.missing) && e.missing.length) {
      box.append(el("p", { class: "small" }, "Missing from the question: " + e.missing.join("; ")));
    }
    if (e.served_by) box.append(el("p", { class: "muted small" }, e.served_by));
    return box;
  }

  // ----- the answer: the catalog's shape, sent unchanged -----

  function spec(value) {
    if (Array.isArray(value)) return { list: true, options: [] };
    const parts = String(value).split("|");
    const nullable = parts.includes("null");
    const options = parts.filter((p) => p !== "null");
    const isEnum = options.length > 0 && options.every((p) => !TYPES.has(p));
    return { list: false, nullable, isEnum, options: isEnum ? options : [], type: isEnum ? "enum" : options[0] };
  }

  function template(schema) {
    const out = {};
    for (const [field, value] of Object.entries(schema || {})) {
      const s = spec(value);
      // a choice starts empty: sending the form unchanged decides nothing
      out[field] = s.list ? [] : s.isEnum || s.nullable ? null : s.type === "bool" ? false : s.type === "object" ? {} : "";
    }
    return out;
  }

  function answerForm(item, reload) {
    const schema = item.answer_schema || {};
    const box = el("textarea", { "aria-label": "Answer (JSON)", spellcheck: "false" }, JSON.stringify(template(schema), null, 2));
    const result = el("p", { role: "status" });
    const send = el("button", { type: "button", class: "primary" }, `Send as ${name()}`);
    const json = el("details", {}, el("summary", {}, "Answer as JSON"), box);
    const choices = [];

    for (const [field, value] of Object.entries(schema)) {
      const s = spec(value);
      if (!s.isEnum) continue;
      const row = el("div", { class: "choices", role: "group", "aria-label": field });
      for (const option of s.options) {
        row.append(el("button", {
          type: "button",
          "aria-pressed": "false",
          onclick: (event) => {
            let body;
            try { body = JSON.parse(box.value); } catch { body = template(schema); }
            body[field] = option;
            box.value = JSON.stringify(body, null, 2);
            for (const b of row.children) b.setAttribute("aria-pressed", String(b === event.currentTarget));
            json.open = true; // what will be sent, before it is sent
            send.disabled = false;
            result.textContent = "";
          },
        }, option));
      }
      choices.push(el("p", { class: "small muted" }, field), row);
    }

    send.addEventListener("click", async () => {
      let body;
      try { body = JSON.parse(box.value); } catch { result.className = "error"; result.textContent = "The answer is not valid JSON."; return; }
      send.disabled = true;
      result.className = "muted";
      result.textContent = "Sending…";
      try {
        const after = await api("POST", item.answer_path, body);
        const still = after && after.question;
        if (still && still.kind === item.kind && still.error) {
          result.className = "refused";
          result.textContent = "Refused: " + problem(still.error);
          send.disabled = false;
          return;
        }
        result.className = "sent";
        result.textContent = "Sent.";
        await reload();
      } catch (err) {
        if (err.status === 401) { signIn("The token was refused. Sign in again."); return; }
        result.className = "error";
        result.textContent = err.message;
        send.disabled = false;
      }
    });

    // nothing is sent until the person chooses or writes an answer
    send.disabled = true;
    box.addEventListener("input", () => { send.disabled = false; });
    json.open = choices.length === 0;
    return el("div", {},
      el("h3", {}, "Your answer"),
      ...choices,
      json,
      el("div", { class: "choices" }, send),
      result,
    );
  }

  document.addEventListener("DOMContentLoaded", inbox);
})();
