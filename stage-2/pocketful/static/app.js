/* Pocketful browser client: one script for every screen (D-200).
 *
 * The bearer token lives in localStorage, so a session survives an
 * export/import upgrade (R-232). Every API call asks for JSON (S-200).
 * Money is formatted and parsed with integer/string arithmetic only (R-243,
 * D-213). Writes that need idempotency keep one key per unchanged form
 * (D-209); refreshes carry a sequence number so the latest wins (D-210).
 */
"use strict";
(function () {
  const TOKEN_KEY = "pocketful.token";
  const session = { me: null };

  /* ---------- DOM helpers ---------- */

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (name === "class") node.className = value;
      else if (name === "testid") node.setAttribute("data-testid", value);
      else if (name === "text") node.textContent = value;
      else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
      else node.setAttribute(name, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const byTestId = (id, root) => (root || document).querySelector(`[data-testid="${id}"]`);

  function field(label, input, hint) {
    const id = input.id || (input.id = "f-" + input.getAttribute("data-testid"));
    return el("div", { class: "field" }, el("label", { for: id, text: label }), input,
      hint ? el("span", { class: "hint", text: hint }) : null);
  }

  /** Show exactly one message element for a testid; absent when cleared (S-207). */
  function showMessage(anchor, testid, state, text) {
    clearMessage(testid);
    const role = state === "state-refused" ? "alert" : "status";
    anchor.append(el("p", { class: `notice ${state}`, testid, role, text }));
  }

  function clearMessage(...testids) {
    for (const testid of testids) {
      const node = byTestId(testid);
      if (node) node.remove();
    }
  }

  function flash(anchor, text) {
    const old = anchor.querySelector(".flash");
    if (old) old.remove();
    anchor.append(el("p", { class: "notice state-success flash", role: "status", text }));
  }

  function busy(button, on) {
    button.disabled = on;
    button.classList.toggle("state-loading", on);
  }

  /* ---------- money ---------- */

  function decimalText(minor, mu) {
    let digits = String(Math.abs(Math.trunc(minor)));
    if (mu === 0) return digits;
    digits = digits.padStart(mu + 1, "0");
    return digits.slice(0, -mu) + "." + digits.slice(-mu);
  }

  function money(minor) {
    return decimalText(minor, session.me.minor_units) + " " + session.me.currency;
  }

  /** "15.5" -> 1550 at two minor units; null when not a valid amount (D-213). */
  function parseAmount(text) {
    const mu = session.me.minor_units;
    const trimmed = String(text).trim();
    const pattern = mu === 0 ? /^\d+$/ : new RegExp("^\\d+(\\.\\d{1," + mu + "})?$");
    if (!pattern.test(trimmed)) return null;
    const [whole, fraction = ""] = trimmed.split(".");
    const digits = (whole + fraction.padEnd(mu, "0")).replace(/^0+(?=\d)/, "");
    if (digits.length > 15) return null;
    return Number(digits);
  }

  const amountHint = () => session.me.minor_units === 0
    ? `Whole ${session.me.currency}, e.g. 1500`
    : `In ${session.me.currency}, e.g. ${decimalText(15 * 10 ** session.me.minor_units, session.me.minor_units)}`;

  /* ---------- people and time ---------- */

  const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  function when(rfc3339) {
    const date = new Date(rfc3339);
    return isNaN(date) ? rfc3339 : timeFormat.format(date);
  }

  /* ---------- API ---------- */

  function newKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    (window.crypto || {}).getRandomValues ? crypto.getRandomValues(bytes)
      : bytes.forEach((_, i) => { bytes[i] = Math.floor(Math.random() * 256); });
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  }

  /**
   * Returns {kind: "ok", status, data} | {kind: "refused", status, error} | {kind: "lost"}.
   * A 4xx with an error body is a confirmed refusal; anything else that is not
   * a success (network failure, no response, 5xx) is an unknown outcome (S-203).
   */
  async function api(method, path, body, key) {
    const headers = { "Accept": "application/json" };
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers["Authorization"] = "Bearer " + token;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (key) headers["Idempotency-Key"] = key;
    let response;
    try {
      response = await fetch(path, { method, headers, cache: "no-store",
        body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (err) {
      return { kind: "lost" };
    }
    let data = null;
    try { data = await response.json(); } catch (err) { data = null; }
    if (response.ok) return { kind: "ok", status: response.status, data };
    if (response.status >= 400 && response.status < 500 && data && data.error) {
      if (response.status === 401 && token && !path.startsWith("/auth/")) signOut();
      return { kind: "refused", status: response.status, error: data.error };
    }
    return { kind: "lost", status: response.status };
  }

  const REFUSALS = {
    insufficient_funds: "You don't have enough available funds for that.",
    not_found: "We couldn't find anyone with that handle.",
    self_payment: "You can't send money to yourself.",
    self_request: "You can't request money from yourself.",
    request_not_pending: "That request was already settled elsewhere. The list has been refreshed.",
    authorization_not_open: "That hold is no longer open. The list has been refreshed.",
    authorization_expired: "That hold has expired. The list has been refreshed.",
    capture_exceeds_authorization: "That's more than the amount still held.",
    forbidden: "You're not allowed to do that.",
    email_taken: "That email is already registered. Try signing in.",
    handle_taken: "An account with a handle like that already exists. Try a different email.",
    unauthenticated: "That email and password don't match.",
    validation_failed: "Please check the details and try again.",
  };
  const refusalText = error => REFUSALS[error.code] || error.message || "That didn't work.";

  function signOut() {
    localStorage.removeItem(TOKEN_KEY);
    location.replace("/login");
  }

  /* ---------- shell ---------- */

  function renderShell(screen) {
    const nav = document.getElementById("nav");
    nav.hidden = false;
    for (const link of nav.querySelectorAll("a")) {
      if (link.dataset.nav === screen) link.setAttribute("aria-current", "page");
    }
    const account = document.getElementById("account");
    account.hidden = false;
    account.replaceChildren(
      el("div", { class: "who" },
        el("strong", { testid: "current-user", text: session.me.display_name }),
        el("span", { class: "handle", testid: "current-handle", text: session.me.handle })),
      el("button", { class: "btn btn-secondary btn-small", type: "button", testid: "logout-button",
        text: "Log out", onclick: signOut }));
  }

  function main() { return document.getElementById("main"); }

  /* ---------- signup and login ---------- */

  function authScreen(kind) {
    const isSignup = kind === "signup";
    const email = el("input", { testid: `${kind}-email`, type: "email", autocomplete: "email", required: true });
    const password = el("input", { testid: `${kind}-password`, type: "password", required: true,
      autocomplete: isSignup ? "new-password" : "current-password" });
    const name = isSignup ? el("input", { testid: "signup-display-name", autocomplete: "name", required: true }) : null;
    const submit = el("button", { class: "btn btn-primary", type: "submit", testid: `${kind}-submit`,
      text: isSignup ? "Create account" : "Sign in" });
    const form = el("form", { class: "form", novalidate: true },
      field("Email", email),
      isSignup ? field("Display name", name, "How friends will see you") : null,
      field("Password", password, isSignup ? "At least 8 characters" : null),
      submit);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      busy(submit, true);
      const body = { email: email.value, password: password.value };
      if (isSignup) body.display_name = name.value;
      const result = await api("POST", isSignup ? "/auth/signup" : "/auth/login", body);
      busy(submit, false);
      if (result.kind === "ok") {
        localStorage.setItem(TOKEN_KEY, result.data.token);
        location.assign("/");
        return;
      }
      let text = "We couldn't reach Pocketful. Check your connection and try again.";
      if (result.kind === "refused") {
        text = result.error.code === "validation_failed"
          ? (isSignup ? "Use an email like name@example.com and a password of at least 8 characters."
                      : "Enter your email and password.")
          : refusalText(result.error);
      }
      showMessage(form, "auth-error", "state-refused", text);
    });
    main().replaceChildren(el("section", { class: "card auth-card" },
      el("h1", { class: "page-title", text: isSignup ? "Create your account" : "Welcome back" }),
      el("p", { class: "lede", text: isSignup ? "Send, request and split money with friends."
                                              : "Sign in to see your wallet." }),
      form,
      el("p", { class: "lede", style: "margin: 16px 0 0" },
        isSignup ? "Already have an account? " : "New to Pocketful? ",
        el("a", { href: isSignup ? "/login" : "/signup", text: isSignup ? "Sign in" : "Create an account" }))));
  }

  /* ---------- keyed forms (D-209) ---------- */

  /** One idempotency key per unchanged form; any edit mints a new one on next submit. */
  function keyedForm(form) {
    const state = { key: null };
    const reset = () => { state.key = null; };
    form.addEventListener("input", reset);
    form.addEventListener("change", reset);
    return () => (state.key = state.key || newKey());
  }

  /* ---------- wallet home ---------- */

  let refreshSeq = 0;

  function walletSummary() {
    const me = session.me;
    return el("section", { class: "card", "aria-label": "Your wallet" },
      el("div", { class: "wallet" },
        el("div", null,
          el("p", { class: "wallet-label", text: "Available to spend" }),
          el("p", { class: "wallet-hero state-available", testid: "wallet-available",
            "data-amount": me.available, text: money(me.available) }),
          el("div", { class: "wallet-secondary" },
            el("span", null, "Total balance ",
              el("span", { class: "money", testid: "wallet-balance", "data-amount": me.balance,
                text: money(me.balance) })),
            me.held > 0 ? el("span", { class: "state-held" }, "On hold ",
              el("span", { class: "money state-held", testid: "wallet-held", "data-amount": me.held,
                text: money(me.held) })) : null)),
        el("button", { class: "btn btn-secondary", type: "button", testid: "wallet-refresh",
          text: "Refresh", onclick: () => refreshWallet() })));
  }

  function activityItem(p) {
    const me = session.me.user_id;
    const direction = p.to_user_id === me ? "in" : p.from_user_id === me ? "out" : "other";
    const title = direction === "in" ? `${p.from_handle} paid you`
      : direction === "out" ? `You paid ${p.to_handle}` : `${p.from_handle} paid ${p.to_handle}`;
    const kind = p.authorization_id ? "Captured hold" : p.request_id ? "Request paid"
      : p.settlement_id ? "Settlement" : null;
    return el("li", { class: `item direction-${direction}`, testid: `activity-item-${p.payment_id}`,
      "data-visibility": p.visibility },
      el("div", { class: "item-main" },
        el("div", { class: "item-title", text: title }),
        el("div", { class: "item-note", testid: `activity-note-${p.payment_id}`, text: p.note }),
        el("div", { class: "item-meta" },
          el("span", { testid: `activity-parties-${p.payment_id}`, text: `${p.from_handle} → ${p.to_handle}` }),
          el("time", { datetime: p.created_at, text: when(p.created_at) }),
          el("span", { class: "badge muted", text: p.visibility === "private" ? "Private" : "Public" }),
          kind ? el("span", { class: "badge muted", text: kind }) : null)),
      el("div", { class: "item-amount" },
        el("span", { class: "sr-only", text: direction === "in" ? "Received " : direction === "out" ? "Sent " : "" }),
        el("span", { testid: `activity-amount-${p.payment_id}`, text: money(p.amount) })));
  }

  function renderActivity(container, payments) {
    container.replaceChildren(payments.length
      ? el("ul", { class: "list", testid: "activity-list" }, payments.map(activityItem))
      : el("p", { class: "empty", testid: "empty-activity",
          text: "No activity yet. Payments you send or receive, and public payments, appear here." }));
  }

  async function refreshWallet() {
    const seq = ++refreshSeq;
    const button = byTestId("wallet-refresh");
    if (button) button.classList.add("state-loading");
    const [me, feed] = await Promise.all([api("GET", "/me"), api("GET", "/activity?limit=50")]);
    if (seq !== refreshSeq) return;  // a later refresh was issued: it wins (D-210)
    if (me.kind === "ok") {
      session.me = me.data;
      const slot = document.getElementById("wallet-summary-slot");
      if (slot) slot.replaceChildren(walletSummary());
    }
    const activity = document.getElementById("activity-slot");
    if (feed.kind === "ok" && activity) renderActivity(activity, feed.data.payments);
    const after = byTestId("wallet-refresh");
    if (after) after.classList.remove("state-loading");
  }

  function payForm() {
    const handle = el("input", { testid: "pay-handle", autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
    const amount = el("input", { testid: "pay-amount", inputmode: "decimal", autocomplete: "off" });
    const note = el("input", { testid: "pay-note", maxlength: "200", autocomplete: "off" });
    const visibility = el("select", { testid: "pay-visibility" },
      el("option", { value: "public", text: "Public — shown in everyone's feed" }),
      el("option", { value: "private", text: "Private — only you and the recipient" }));
    const submit = el("button", { class: "btn btn-primary", type: "submit", testid: "pay-submit", text: "Send money" });
    const form = el("form", { class: "form", novalidate: true },
      el("div", { class: "row row-2" }, field("To (handle)", handle), field("Amount", amount, amountHint())),
      field("Note (optional)", note),
      field("Who can see it", visibility),
      el("div", { class: "actions" }, submit));
    const keyFor = keyedForm(form);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      clearMessage("pay-error", "pay-uncertain");
      const minor = parseAmount(amount.value);
      if (minor === null) {
        showMessage(form, "pay-error", "state-refused",
          `Enter an amount like ${decimalText(15 * 10 ** session.me.minor_units, session.me.minor_units)}, with at most ${session.me.minor_units} decimal places.`);
        return;
      }
      const body = { to_handle: handle.value.trim(), amount: minor, note: note.value, visibility: visibility.value };
      busy(submit, true);
      const result = await api("POST", "/payments", body, keyFor());
      busy(submit, false);
      if (result.kind === "ok") {
        flash(form, `Sent ${money(result.data.amount)} to ${result.data.to_handle}.`);
      } else if (result.kind === "refused") {
        showMessage(form, "pay-error", "state-refused", refusalText(result.error));
      } else {
        showMessage(form, "pay-uncertain", "state-uncertain",
          "We couldn't confirm this payment. It may have gone through. Press Send money again to retry safely — you won't be charged twice.");
        return;
      }
      await refreshWallet();
    });
    return el("section", { class: "card", "aria-labelledby": "pay-title" },
      el("h2", { id: "pay-title", text: "Send money" }), form);
  }

  function requestForm() {
    const handle = el("input", { testid: "request-handle", autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
    const amount = el("input", { testid: "request-amount", inputmode: "decimal", autocomplete: "off" });
    const note = el("input", { testid: "request-note", maxlength: "200", autocomplete: "off" });
    const submit = el("button", { class: "btn btn-primary", type: "submit", testid: "request-submit", text: "Request money" });
    const form = el("form", { class: "form", novalidate: true },
      el("div", { class: "row row-2" }, field("From (handle)", handle), field("Amount", amount, amountHint())),
      field("What it's for (optional)", note),
      el("div", { class: "actions" }, submit));
    const keyFor = keyedForm(form);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      clearMessage("request-error");
      const minor = parseAmount(amount.value);
      if (minor === null) {
        showMessage(form, "request-error", "state-refused",
          `Enter an amount like ${decimalText(15 * 10 ** session.me.minor_units, session.me.minor_units)}, with at most ${session.me.minor_units} decimal places.`);
        return;
      }
      busy(submit, true);
      const result = await api("POST", "/requests", { payer_handle: handle.value.trim(), amount: minor,
        note: note.value }, keyFor());
      busy(submit, false);
      if (result.kind === "ok") {
        flash(form, `Asked ${result.data.payer_handle} for ${money(result.data.amount)}.`);
        await refreshWallet();
      } else {
        showMessage(form, "request-error", result.kind === "refused" ? "state-refused" : "state-uncertain",
          result.kind === "refused" ? refusalText(result.error)
            : "We couldn't confirm this request. Press Request money again to retry safely.");
      }
    });
    return el("section", { class: "card", "aria-labelledby": "request-title" },
      el("h2", { id: "request-title", text: "Request money" }), form);
  }

  function authorizeForm() {
    const handle = el("input", { testid: "authorize-handle", autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
    const amount = el("input", { testid: "authorize-amount", inputmode: "decimal", autocomplete: "off" });
    const note = el("input", { testid: "authorize-note", maxlength: "200", autocomplete: "off" });
    const visibility = el("select", { testid: "authorize-visibility" },
      el("option", { value: "public", text: "Public when captured" }),
      el("option", { value: "private", text: "Private — only you and the recipient" }));
    const submit = el("button", { class: "btn btn-primary", type: "submit", testid: "authorize-submit", text: "Place hold" });
    const form = el("form", { class: "form", novalidate: true },
      el("div", { class: "row row-2" }, field("For (handle)", handle), field("Amount to hold", amount, amountHint())),
      field("Note (optional)", note),
      field("Who can see it once captured", visibility),
      el("div", { class: "actions" }, submit));
    const keyFor = keyedForm(form);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      clearMessage("authorize-error");
      const minor = parseAmount(amount.value);
      if (minor === null) {
        showMessage(form, "authorize-error", "state-refused",
          `Enter an amount like ${decimalText(15 * 10 ** session.me.minor_units, session.me.minor_units)}, with at most ${session.me.minor_units} decimal places.`);
        return;
      }
      busy(submit, true);
      const result = await api("POST", "/authorizations", { to_handle: handle.value.trim(), amount: minor,
        note: note.value, visibility: visibility.value }, keyFor());
      busy(submit, false);
      if (result.kind === "ok") {
        flash(form, `Holding ${money(result.data.amount)} for ${result.data.to_handle} until ${when(result.data.expires_at)}.`);
      } else {
        showMessage(form, "authorize-error", result.kind === "refused" ? "state-refused" : "state-uncertain",
          result.kind === "refused" ? refusalText(result.error)
            : "We couldn't confirm this hold. Press Place hold again to retry safely.");
        if (result.kind !== "refused") return;
      }
      await refreshWallet();
    });
    return el("section", { class: "card", "aria-labelledby": "authorize-title" },
      el("h2", { id: "authorize-title", text: "Hold money for someone" }),
      el("p", { class: "lede", text: "Reserve money now; they collect it later, all at once or in parts. Held money can't be spent until the hold is captured, voided or expires." }),
      form);
  }

  async function walletScreen() {
    const feed = await api("GET", "/activity?limit=50");
    const activity = el("div", { id: "activity-slot" });
    main().replaceChildren(
      el("h1", { class: "page-title", text: `Hi, ${session.me.display_name}` }),
      el("div", { class: "grid" },
        el("div", { id: "wallet-summary-slot" }, walletSummary()),
        el("div", { class: "grid grid-2" }, payForm(), requestForm()),
        el("section", { class: "card", "aria-labelledby": "activity-title" },
          el("div", { class: "section-head" }, el("h2", { id: "activity-title", text: "Activity" })),
          activity),
        authorizeForm()));
    if (feed.kind === "ok") renderActivity(activity, feed.data.payments);
    else activity.replaceChildren(el("p", { class: "notice state-refused", role: "alert",
      text: "We couldn't load your activity. Use Refresh to try again." }));
  }

  /* ---------- requests ---------- */

  const STATUS_CLASS = { pending: "state-pending", paid: "state-success", declined: "state-refused",
    cancelled: "muted", open: "state-held", captured: "state-success", voided: "muted", expired: "muted" };
  const STATUS_LABEL = { pending: "Waiting", paid: "Paid", declined: "Declined", cancelled: "Cancelled",
    open: "Holding", captured: "Captured", voided: "Released", expired: "Expired" };

  function statusBadge(status) {
    return el("span", { class: `badge ${STATUS_CLASS[status] || "muted"}`, text: STATUS_LABEL[status] || status });
  }

  /** Per-target idempotency keys: a retried click on the same item reuses its key. */
  const actionKeys = new Map();
  const actionKey = id => actionKeys.get(id) || actionKeys.set(id, newKey()).get(id);

  function requestItem(r, incoming, act) {
    const id = r.request_id;
    const pending = r.status === "pending";
    const who = incoming ? `${r.requester_handle} asked you` : `You asked ${r.payer_handle}`;
    return el("li", { class: `item ${incoming ? "direction-out" : "direction-in"}`, testid: `request-item-${id}`,
      "data-status": r.status },
      el("div", { class: "item-main" },
        el("div", { class: "item-title", text: who }),
        el("div", { class: "item-note", text: r.note }),
        el("div", { class: "item-meta" }, statusBadge(r.status),
          el("time", { datetime: r.created_at, text: when(r.created_at) }))),
      el("div", { class: "item-amount", testid: `request-amount-${id}`, text: money(r.amount) }),
      pending ? el("div", { class: "item-actions actions" },
        incoming ? [
          el("button", { class: "btn btn-primary btn-small", type: "button", testid: `request-pay-${id}`,
            text: `Pay ${money(r.amount)}`, onclick: e => act(e.currentTarget, "pay", id) }),
          el("button", { class: "btn btn-secondary btn-small", type: "button", testid: `request-decline-${id}`,
            text: "Decline", onclick: e => act(e.currentTarget, "decline", id) }),
        ] : el("button", { class: "btn btn-danger btn-small", type: "button", testid: `request-cancel-${id}`,
            text: "Cancel request", onclick: e => act(e.currentTarget, "cancel", id) })) : null);
  }

  async function requestsScreen() {
    const banner = el("div");
    const lists = el("div", { class: "grid grid-2" });
    let loadSeq = 0;
    async function load() {
      const seq = ++loadSeq;
      const [incoming, outgoing] = await Promise.all([
        api("GET", "/requests?direction=incoming&limit=200"),
        api("GET", "/requests?direction=outgoing&limit=200")]);
      if (seq !== loadSeq) return;
      if (incoming.kind !== "ok" || outgoing.kind !== "ok") {
        lists.replaceChildren(el("p", { class: "notice state-uncertain", role: "alert",
          text: "We couldn't load your requests. Try again in a moment." }));
        return;
      }
      const inc = incoming.data.requests, out = outgoing.data.requests;
      const column = (title, testid, items, incomingSide, emptyText) =>
        el("section", { class: "card", "aria-label": title },
          el("h2", { text: title }),
          el("ul", { class: "list", testid }, items.map(r => requestItem(r, incomingSide, act))),
          items.length ? null : el("p", { class: "empty", text: emptyText }));
      lists.replaceChildren(
        column("Asked of you", "incoming-list", inc, true, "No one has asked you for money."),
        column("You asked", "outgoing-list", out, false, "You haven't requested money yet."));
      clearMessage("empty-requests");
      if (!inc.length && !out.length) {
        banner.append(el("p", { class: "empty", testid: "empty-requests",
          text: "No requests yet. Ask someone for money from your wallet, or split a bill." }));
      }
    }
    async function act(button, action, id) {
      clearMessage("request-error");
      busy(button, true);
      const result = action === "pay"
        ? await api("POST", `/requests/${encodeURIComponent(id)}/pay`, {}, actionKey("pay:" + id))
        : await api("POST", `/requests/${encodeURIComponent(id)}/${action}`);
      busy(button, false);
      if (result.kind === "ok") {
        flash(banner, action === "pay" ? `Paid ${money(result.data.amount)} to ${result.data.to_handle}.`
          : action === "decline" ? "Request declined." : "Request cancelled.");
      } else {
        showMessage(banner, "request-error", result.kind === "refused" ? "state-refused" : "state-uncertain",
          result.kind === "refused" ? refusalText(result.error)
            : "We couldn't confirm that. Press the button again to retry safely.");
      }
      await load();
    }
    main().replaceChildren(
      el("h1", { class: "page-title", text: "Requests" }),
      el("p", { class: "lede", text: "Money people have asked you for, and money you've asked for." }),
      banner, lists);
    lists.append(el("p", { class: "state-loading loading-line", role: "status", text: "Loading requests…" }));
    await load();
  }

  /* ---------- split ---------- */

  /** Server rule (stage-1 §9): equal shares, extra units to the first participants. */
  function equalShares(amount, count) {
    const base = Math.floor(amount / count), extra = amount - base * count;
    return Array.from({ length: count }, (_, i) => base + (i < extra ? 1 : 0));
  }

  function parseHandles(text) {
    return text.split(",").map(h => h.trim()).filter(Boolean);
  }

  async function splitScreen() {
    const amount = el("input", { testid: "split-amount", inputmode: "decimal", autocomplete: "off" });
    const handles = el("input", { testid: "split-handles", autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
    const note = el("input", { testid: "split-note", maxlength: "200", autocomplete: "off" });
    const submit = el("button", { class: "btn btn-primary", type: "submit", testid: "split-submit", text: "Send requests" });
    const preview = el("div", { class: "preview", testid: "split-preview", "aria-live": "polite" });
    const form = el("form", { class: "form", novalidate: true },
      el("div", { class: "row row-2" }, field("Total you paid", amount, amountHint()),
        field("Split between (handles)", handles, `Comma-separated, in order — include ${session.me.handle} to take a share`)),
      field("What it was for (optional)", note),
      el("div", null, el("h3", { text: "Each person pays" }), preview),
      el("div", { class: "actions" }, submit));
    const result = el("div");
    function renderPreview() {
      const minor = parseAmount(amount.value);
      const people = parseHandles(handles.value);
      if (minor === null || !people.length) {
        preview.replaceChildren(el("p", { class: "hint", style: "margin:0",
          text: "Enter an amount and at least one handle to see the shares." }));
        return;
      }
      const shares = equalShares(minor, people.length);
      preview.replaceChildren(...people.map((h, i) => el("div", { class: "preview-row" },
        el("span", { text: h === session.me.handle ? `${h} (you)` : h }),
        el("span", { class: "money", testid: `split-share-${h}`, text: money(shares[i]) }))));
    }
    form.addEventListener("input", renderPreview);
    const keyFor = keyedForm(form);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      clearMessage("split-error");
      const minor = parseAmount(amount.value);
      const people = parseHandles(handles.value);
      if (minor === null || !people.length) {
        showMessage(form, "split-error", "state-refused", minor === null
          ? `Enter an amount like ${decimalText(15 * 10 ** session.me.minor_units, session.me.minor_units)}, with at most ${session.me.minor_units} decimal places.`
          : "Add at least one handle.");
        return;
      }
      busy(submit, true);
      const res = await api("POST", "/splits", { amount: minor, participant_handles: people, note: note.value }, keyFor());
      busy(submit, false);
      if (res.kind !== "ok") {
        showMessage(form, "split-error", res.kind === "refused" ? "state-refused" : "state-uncertain",
          res.kind === "refused"
            ? (res.error.code === "validation_failed" ? "Check the amount and use each handle only once." : refusalText(res.error))
            : "We couldn't confirm this split. Press Send requests again to retry safely.");
        return;
      }
      const asked = res.data.requests.map(r => r.payer_handle);
      result.replaceChildren(el("p", { class: "notice state-success", role: "status",
        text: asked.length ? `Requests sent to ${asked.join(", ")}. Track them on the Requests page.`
          : "Split recorded. There was no one else to ask." }));
    });
    renderPreview();
    main().replaceChildren(
      el("h1", { class: "page-title", text: "Split a bill" }),
      el("p", { class: "lede", text: "You paid for something shared. We'll ask everyone else for their part — shares are equal, and any leftover cent goes to the first people listed." }),
      el("section", { class: "card" }, form, result));
  }

  /* ---------- authorizations (holds) ---------- */

  function authorizationItem(a, act) {
    const id = a.authorization_id;
    const incoming = a.to_user_id === session.me.user_id;
    const open = a.status === "open";
    const who = incoming ? `${a.from_handle} is holding money for you` : `You're holding money for ${a.to_handle}`;
    const capture = open && incoming
      ? el("input", { testid: `authorization-capture-amount-${id}`, inputmode: "decimal", autocomplete: "off",
          value: decimalText(a.remaining_amount, session.me.minor_units), id: `cap-${id}` }) : null;
    return el("li", { class: `item ${incoming ? "direction-in" : "direction-out"}`, testid: `authorization-item-${id}`,
      "data-status": a.status },
      el("div", { class: "item-main" },
        el("div", { class: "item-title", text: who }),
        el("div", { class: "item-note", text: a.note }),
        el("div", { class: "item-meta" }, statusBadge(a.status),
          open && a.remaining_amount !== a.amount ? el("span", { class: "state-held", text: `${money(a.remaining_amount)} still held` }) : null,
          a.status === "captured" ? el("span", null, "Captured ",
            el("span", { testid: `authorization-captured-${id}`, text: money(a.captured_amount) })) : null,
          el("span", null, `${open ? "Expires" : "Expiry"} ${when(a.expires_at)} · `,
            el("time", { datetime: a.expires_at, testid: `authorization-expires-${id}`, text: a.expires_at })),
          el("span", { class: "badge muted", text: a.visibility === "private" ? "Private" : "Public" }))),
      el("div", { class: "item-amount", testid: `authorization-amount-${id}`, text: money(a.amount) }),
      open ? el("div", { class: "item-actions" }, incoming
        ? el("div", { class: "capture-row" },
            el("div", { class: "field" }, el("label", { for: `cap-${id}`, text: "Amount to collect" }), capture),
            el("button", { class: "btn btn-primary btn-small", type: "button", testid: `authorization-capture-${id}`,
              text: "Collect", onclick: e => act(e.currentTarget, "capture", a, capture) }))
        : el("button", { class: "btn btn-danger btn-small", type: "button", testid: `authorization-void-${id}`,
            text: "Release hold", onclick: e => act(e.currentTarget, "void", a) })) : null);
  }

  async function authorizationsScreen() {
    const banner = el("div");
    const listSlot = el("div");
    let loadSeq = 0;
    async function load() {
      const seq = ++loadSeq;
      const res = await api("GET", "/authorizations?limit=200");
      if (seq !== loadSeq) return;
      if (res.kind !== "ok") {
        listSlot.replaceChildren(el("p", { class: "notice state-uncertain", role: "alert",
          text: "We couldn't load your holds. Try again in a moment." }));
        return;
      }
      const items = res.data.authorizations;
      listSlot.replaceChildren(items.length
        ? el("ul", { class: "list", testid: "authorization-list" }, items.map(a => authorizationItem(a, act)))
        : el("p", { class: "empty", testid: "empty-authorizations",
            text: "No holds yet. Place one from your wallet to reserve money for someone." }));
    }
    async function act(button, action, a, input) {
      clearMessage("authorization-error");
      const id = a.authorization_id;
      let result;
      if (action === "capture") {
        const minor = parseAmount(input.value);
        if (minor === null) {
          showMessage(banner, "authorization-error", "state-refused",
            `Enter an amount like ${decimalText(a.remaining_amount, session.me.minor_units)}, with at most ${session.me.minor_units} decimal places.`);
          return;
        }
        busy(button, true);
        result = await api("POST", `/authorizations/${encodeURIComponent(id)}/capture`, { amount: minor },
          actionKey(`capture:${id}:${minor}`));
      } else {
        busy(button, true);
        result = await api("POST", `/authorizations/${encodeURIComponent(id)}/void`);
      }
      busy(button, false);
      if (result.kind === "ok") {
        flash(banner, action === "capture" ? `Collected ${money(result.data.amount)} from ${result.data.from_handle}.`
          : "Hold released. The money is available again.");
      } else {
        showMessage(banner, "authorization-error", result.kind === "refused" ? "state-refused" : "state-uncertain",
          result.kind === "refused" ? refusalText(result.error)
            : "We couldn't confirm that. Press the button again to retry safely.");
      }
      await load();
    }
    main().replaceChildren(
      el("h1", { class: "page-title", text: "Holds" }),
      el("p", { class: "lede", text: "Money reserved for someone to collect later. Holds release automatically when they expire." }),
      banner, el("section", { class: "card" }, listSlot));
    listSlot.append(el("p", { class: "state-loading loading-line", role: "status", text: "Loading holds…" }));
    await load();
  }

  /* ---------- boot ---------- */

  const SCREENS = { wallet: walletScreen, requests: requestsScreen, split: splitScreen,
    authorizations: authorizationsScreen };

  async function boot() {
    const screen = document.body.dataset.screen;
    if (screen === "login" || screen === "signup") {
      authScreen(screen);
      return;
    }
    if (!localStorage.getItem(TOKEN_KEY)) {
      location.replace("/login");
      return;
    }
    const me = await api("GET", "/me");
    if (me.kind !== "ok") {
      if (me.kind === "refused" && me.status === 401) return;  // signOut already redirected
      main().replaceChildren(el("div", { class: "card" },
        el("p", { class: "notice state-uncertain", role: "alert",
          text: "We couldn't reach Pocketful just now." }),
        el("p", null, el("button", { class: "btn btn-primary", type: "button", text: "Try again",
          onclick: () => location.reload() }))));
      return;
    }
    session.me = me.data;
    renderShell(screen);
    await SCREENS[screen]();
  }

  boot();
})();
