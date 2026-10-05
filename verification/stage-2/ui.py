"""Browser helpers for the stage-2 UI suite (Playwright sync API, black box).

Written from spec/stage-2.md and stage-2/LEDGER.md only. The browser talks to the product at
`pf.BASE` (env POCKETFUL_URL); money effects are verified through the JSON API (`pf.Api`).

Use from a test module with `from ui import *`. That imports the `browser` (module scope)
and `page` (function scope) fixtures; there is no pytest-playwright.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import Error as PwError
from playwright.sync_api import Page, expect, sync_playwright

import pf
import pf2
from pf import PW, err, new_key, ok, user  # noqa: F401  (re-exported for test modules)

BASE = pf.BASE
T = 5000                       # default explicit wait (ms)
SHOTS = Path(os.environ.get("UI_SHOTS", "/tmp/df-prover-shots"))
BROWSER_ACCEPT = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8")
SIGNED_IN_ROUTES = ["/", "/requests", "/split", "/authorizations"]
PUBLIC_ROUTES = ["/login", "/signup"]
ALL_ROUTES = SIGNED_IN_ROUTES + PUBLIC_ROUTES
# One element that proves each screen has rendered.
SCREEN_MARK = {"/": "wallet-balance", "/requests": "incoming-list", "/split": "split-amount",
               "/authorizations": "authorization-list", "/login": "login-email",
               "/signup": "signup-email"}
ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")

expect.set_options(timeout=T)
L = pytest.mark.ledger


# ---------------------------------------------------------------- browser lifecycle

@contextlib.contextmanager
def _no_proxy_env():
    """The sandbox exports HTTP(S)_PROXY; keep it away from the Playwright driver/browser."""
    saved = {k: os.environ.pop(k) for k in list(os.environ)
             if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy")}
    try:
        yield
    finally:
        os.environ.update(saved)


@pytest.fixture(scope="module")
def browser():
    with _no_proxy_env():
        p = sync_playwright().start()
        b = p.chromium.launch(headless=True, args=["--no-proxy-server"])
    try:
        yield b
    finally:
        with contextlib.suppress(Exception):
            b.close()
        p.stop()


def new_page(browser, width=1280, height=900) -> Page:
    ctx = browser.new_context(base_url=BASE, viewport={"width": width, "height": height})
    ctx.set_default_timeout(10000)
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())   # a confirm() must not silently cancel an action
    pg.errors = []                          # uncaught page errors, for diagnostics
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.rec = Recorder(pg)
    return pg


def close_page(pg: Page):
    with contextlib.suppress(Exception):
        pg.unroute_all(behavior="ignoreErrors")
    with contextlib.suppress(Exception):
        pg.context.close()


@pytest.fixture
def page(browser):
    """A fresh context and page per test. `page.rec` records every request."""
    pg = new_page(browser)
    try:
        yield pg
    finally:
        close_page(pg)


# ---------------------------------------------------------------- small helpers

def tid(page_or_loc, name: str):
    return page_or_loc.get_by_test_id(name)


def fmt(minor: int, minor_units: int, cur: str) -> str:
    """R-243 formatted amount, from the integer with string arithmetic (never floats)."""
    assert isinstance(minor, int) and minor >= 0, minor
    s = str(minor)
    if minor_units == 0:
        return f"{s} {cur}"
    s = s.rjust(minor_units + 1, "0")
    return f"{s[:-minor_units]}.{s[-minor_units:]} {cur}"


def dec(minor: int, minor_units: int) -> str:
    """The decimal input form of an amount, e.g. 2000 -> '20.00' (S-206)."""
    return fmt(minor, minor_units, "X")[:-2]


def path_of(url: str) -> str:
    return urlsplit(url).path


def assert_text(loc, expected: str, timeout: int = T):
    """Wait for the text, then check it exactly as rendered (no normalisation)."""
    expect(loc).to_have_text(expected, timeout=timeout)
    got = loc.inner_text().strip()
    assert got == expected, f"rendered text {got!r} != {expected!r}"


def set_value(loc, value: str):
    """Type a value as a person would; fall back for inputs that refuse text."""
    try:
        loc.fill(value)
    except PwError:
        loc.evaluate("""(e, v) => { e.value = v;
            e.dispatchEvent(new Event('input', {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true})); }""", value)


def goto(page: Page, route: str, mark: str | None = None):
    page.goto(route)
    m = mark or SCREEN_MARK.get(route)
    if m:
        expect(tid(page, m).first).to_be_visible(timeout=10000)


def sign_in(page: Page, email: str, password: str = PW):
    page.goto("/login")
    set_value(tid(page, "login-email"), email)
    set_value(tid(page, "login-password"), password)
    tid(page, "login-submit").click()
    expect(tid(page, "current-handle")).to_be_visible(timeout=10000)


def sign_in_as(page: Page, w, handle: str, route: str = "/"):
    u = next(u for u in w.fixture["users"] if u["handle"] == handle)
    sign_in(page, u["email"], u["password"])
    goto(page, route)


def settle(page: Page, ms: int = 400):
    """Give a just-released (stale) response a chance to be (wrongly) applied."""
    page.wait_for_timeout(ms)


def wait_until(page: Page, cond, timeout: int = T, what: str = "condition"):
    end = time.monotonic() + timeout / 1000
    while time.monotonic() < end:
        if cond():
            return
        page.wait_for_timeout(50)
    assert cond(), f"timed out waiting for {what}"


def dom_testids(page: Page, container: str, prefix: str) -> list[str]:
    """Ids (testid minus prefix) of the container's items, in DOM order."""
    return tid(page, container).evaluate(
        "(el, p) => [...el.querySelectorAll(`[data-testid^='${p}']`)]"
        ".map(e => e.dataset.testid.slice(p.length))", prefix)


def wallet(page: Page) -> dict:
    out = {}
    for k in ("balance", "available", "held"):
        loc = tid(page, f"wallet-{k}")
        out[k] = loc.get_attribute("data-amount") if loc.count() else None
    return out


# ---------------------------------------------------------------- forms

def fill_pay(page: Page, handle="bob", amount="15.00", note="", visibility="public"):
    set_value(tid(page, "pay-handle"), handle)
    set_value(tid(page, "pay-amount"), amount)
    set_value(tid(page, "pay-note"), note)
    tid(page, "pay-visibility").select_option(visibility)


def pay_values(page: Page) -> tuple:
    return (tid(page, "pay-handle").input_value(), tid(page, "pay-amount").input_value(),
            tid(page, "pay-note").input_value(), tid(page, "pay-visibility").input_value())


def fill_request(page: Page, handle="bob", amount="12.00", note=""):
    set_value(tid(page, "request-handle"), handle)
    set_value(tid(page, "request-amount"), amount)
    set_value(tid(page, "request-note"), note)


def fill_authorize(page: Page, handle="bob", amount="20.00", note="", visibility="public"):
    set_value(tid(page, "authorize-handle"), handle)
    set_value(tid(page, "authorize-amount"), amount)
    set_value(tid(page, "authorize-note"), note)
    tid(page, "authorize-visibility").select_option(visibility)


def is_post(path: str):
    return lambda r: r.request.method == "POST" and path_of(r.url) == path


def submit_and_response(page: Page, button: str, path: str, timeout: int = 10000):
    """Click `button` and return the POST `path` response it causes."""
    with page.expect_response(is_post(path), timeout=timeout) as ri:
        tid(page, button).click()
    return ri.value


# ---------------------------------------------------------------- request recording

class Recorder:
    """Every request the page makes: method, url, path, headers, body, status, failure."""

    def __init__(self, page: Page):
        self.entries: list[dict] = []
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)

    def _on_request(self, r):
        self.entries.append({"request": r, "method": r.method, "url": r.url,
                             "path": path_of(r.url), "headers": dict(r.headers),
                             "body": r.post_data, "type": r.resource_type,
                             "status": None, "failed": None})

    def _find(self, r):
        for e in reversed(self.entries):
            if e["request"] is r:
                return e
        return None

    def _on_response(self, resp):
        e = self._find(resp.request)
        if e is not None:
            e["status"] = resp.status

    def _on_failed(self, r):
        e = self._find(r)
        if e is not None:
            e["failed"] = r.failure or "failed"

    def clear(self):
        self.entries.clear()

    def of(self, method: str, path: str) -> list[dict]:
        return [e for e in self.entries if e["method"] == method and e["path"] == path]

    def posts(self, path: str) -> list[dict]:
        return self.of("POST", path)

    def api_calls(self) -> list[dict]:
        return [e for e in self.entries if e["type"] in ("fetch", "xhr")]


def key_of(entry: dict) -> str | None:
    return entry["headers"].get("idempotency-key")


def body_of(entry: dict):
    return json.loads(entry["body"]) if entry["body"] else None


# ---------------------------------------------------------------- route interception

class LoseResponses:
    """Lose the next `times` responses to METHOD `path`.

    commit=True: forward the request first (`route.fetch()`, so the server commits), then
    abort the browser's request (or answer with `status`, e.g. 502, and an empty body).
    commit=False: abort without forwarding; the server never sees the request.
    Later requests pass through untouched. `self.results` holds what the server answered.
    """

    def __init__(self, page: Page, path="/payments", method="POST", times=1, commit=True,
                 status: int | None = None):
        self.page, self.path, self.method = page, path, method
        self.left, self.commit, self.status = times, commit, status
        self.results: list[dict] = []
        self.seen = 0
        self._matcher = lambda url: path_of(url) == self.path
        page.route(self._matcher, self._handle)

    def _handle(self, route, request):
        if request.method != self.method or self.left <= 0:
            route.fallback()
            return
        self.left -= 1
        self.seen += 1
        if self.commit:
            r = route.fetch()
            self.results.append({"status": r.status, "body": r.text()})
        if self.status is None:
            route.abort("failed")
        else:
            route.fulfill(status=self.status, body="", content_type="text/plain")

    def remove(self):
        self.left = 0
        with contextlib.suppress(Exception):
            self.page.unroute(self._matcher, self._handle)


def commit_then_lose(page: Page, path="/payments", times=1) -> LoseResponses:
    return LoseResponses(page, path, times=times, commit=True)


def lose_before_server(page: Page, path="/payments", times=1) -> LoseResponses:
    return LoseResponses(page, path, times=times, commit=False)


class Hold:
    """Hold matching requests while armed, to deliver them late / out of order.

    snapshot=True: the request is forwarded at once (`route.fetch()`), so the held response
    carries the server state of that moment; `release()` delivers that stale response.
    snapshot=False: the request is not forwarded until `release()` (`route.continue_()`).
    """

    def __init__(self, page: Page, paths, method="GET", snapshot=True):
        self.page, self.paths, self.method, self.snapshot = page, set(paths), method, snapshot
        self.armed = False
        self.held: list[tuple] = []
        self._matcher = lambda url: path_of(url) in self.paths
        page.route(self._matcher, self._handle)

    def _handle(self, route, request):
        if not self.armed or request.method != self.method:
            route.fallback()
            return
        if self.snapshot:
            r = route.fetch()
            self.held.append((route, path_of(request.url), r.status, r.headers, r.body()))
        else:
            self.held.append((route, path_of(request.url), None, None, None))

    def arm(self):
        self.armed = True

    def disarm(self):
        self.armed = False

    def wait_held(self, n=1, timeout=T):
        wait_until(self.page, lambda: len(self.held) >= n, timeout,
                   f"{n} held {self.method} {sorted(self.paths)} request(s); does the UI read "
                   "the JSON API for this?")

    def held_paths(self):
        return [h[1] for h in self.held]

    def release(self):
        items, self.held = self.held, []
        for route, _path, status, headers, body in items:
            with contextlib.suppress(PwError):
                if status is None:
                    route.continue_()
                else:
                    route.fulfill(status=status, headers=headers, body=body)

    def remove(self):
        self.disarm()
        self.release()
        with contextlib.suppress(Exception):
            self.page.unroute(self._matcher, self._handle)


# ---------------------------------------------------------------- raw HTTP (non-JSON)

_raw = httpx.Client(timeout=10.0, trust_env=False, follow_redirects=False)


def raw_get(path: str, accept: str | None = None, token: str | None = None):
    h = {}
    if accept is not None:
        h["Accept"] = accept
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    return _raw.get(BASE + path, headers=h)


def is_html(resp) -> bool:
    ct = resp.headers.get("content-type", "").lower()
    return "text/html" in ct and "<html" in resp.text.lower()


def looks_like_json_page(page: Page) -> bool:
    txt = page.evaluate("() => (document.body ? document.body.innerText : '')").strip()
    if not txt.startswith(("{", "[")):
        return False
    with contextlib.suppress(ValueError):
        json.loads(txt)
        return True
    return False


# ---------------------------------------------------------------- fixtures (data)

def plain_fixture(currency="EUR", minor_units=2, balances=(10000, 2500, 500, 0)):
    """ada, bob, cy, dee with no seeded payments or requests."""
    users = [user("u_ada", "ada", balances[0]), user("u_bob", "bob", balances[1]),
             user("u_cy", "cy", balances[2]), user("u_dee", "dee", balances[3])]
    return pf.fixture(users=users, payments=[], requests=[], currency=currency,
                      minor_units=minor_units)


def rich_fixture():
    """Payments, requests in every state, holds in every state (for screens and visuals)."""
    reqs = pf.SEED_REQUESTS + [
        {"id": "rq_3", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 700,
         "note": "tickets", "status": "pending"},
        {"id": "rq_4", "requester_id": "u_cy", "payer_id": "u_ada", "amount": 250,
         "note": "snacks", "status": "cancelled"},
    ]
    auths = [
        pf2.seed_auth("a_1", "u_ada", "u_bob", 2000, note="deposit"),
        pf2.seed_auth("a_2", "u_bob", "u_ada", 2000, note="rental", vis="private"),
        pf2.seed_auth("a_4", "u_ada", "u_cy", 300, status="voided", note="cancelled hold"),
        pf2.seed_auth("a_5", "u_cy", "u_ada", 400, status="expired", note="old",
                      expires_at=pf2.in_hours(-3)),
        pf2.seed_auth("a_6", "u_bob", "u_ada", 700, note="lapsed",
                      expires_at=pf2.in_hours(-2)),   # open but past: expired by clock
    ]
    return pf2.fixture2(authorizations=auths, requests=reqs)


# ---------------------------------------------------------------- visual probes (JS)

_VIS_JS = """
const vis = e => { if (!e || !e.isConnected) return false;
  const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
  return r.width >= 4 && r.height >= 4 && cs.visibility !== 'hidden' && cs.display !== 'none'
         && parseFloat(cs.opacity) > 0; };
const ownText = e => { const c = e.cloneNode(true);
  c.querySelectorAll('input,select,textarea,option').forEach(x => x.remove());
  return (c.textContent || '').trim(); };
"""

UNLABELLED_JS = "() => {" + _VIS_JS + """
  const out = [];
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image'].includes(type)) continue;
    if (!vis(el)) continue;
    let ok = false;
    for (const l of (el.labels || [])) if (vis(l) && ownText(l)) ok = true;
    const lb = el.getAttribute('aria-labelledby');
    if (!ok && lb) for (const id of lb.split(/\\s+/)) {
      const t = document.getElementById(id); if (t && vis(t) && ownText(t)) ok = true; }
    const al = (el.getAttribute('aria-label') || '').trim().toLowerCase();
    if (!ok && al) {   // aria-label counts only when that text is visible beside the input
      let p = el.parentElement;
      for (let i = 0; i < 3 && p && !ok; i++, p = p.parentElement)
        if (vis(p) && (p.innerText || '').toLowerCase().includes(al)) ok = true; }
    if (!ok) out.push(el.getAttribute('data-testid') || el.name || el.id
                      || el.outerHTML.slice(0, 80));
  }
  return out; }"""

NO_TRANSITIONS_CSS = ("*,*::before,*::after{transition:none!important;"
                      "animation:none!important;caret-color:transparent!important}")

FOCUS_MARK_JS = "() => {" + _VIS_JS + """
  if (document.activeElement) document.activeElement.blur();
  const snap = e => { const s = getComputedStyle(e);
    return {outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth,
            outlineColor: s.outlineColor, boxShadow: s.boxShadow,
            border: [s.borderTopColor, s.borderBottomColor, s.borderTopWidth,
                     s.borderBottomWidth].join(' '),
            bg: s.backgroundColor, color: s.color, deco: s.textDecorationLine}; };
  window.__pfSnap = snap;
  const out = {}; let i = 0;
  for (const e of document.querySelectorAll('input,select,textarea,button,a[href]')) {
    if (!vis(e)) continue; e.dataset.pfIdx = String(i); out[i] = snap(e); i++; }
  return out; }"""

FOCUS_NOW_JS = """() => { const e = document.activeElement;
  if (!e || e === document.body || e.dataset.pfIdx === undefined) return null;
  return {idx: e.dataset.pfIdx, tag: e.tagName.toLowerCase(),
          name: e.getAttribute('data-testid') || e.id || (e.innerText || '').trim().slice(0, 30),
          snap: window.__pfSnap(e)}; }"""

CONTRAST_JS = "() => {" + _VIS_JS + """
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', {willReadFrequently: true});
  const rgba = c => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (top, base) => [0, 1, 2].map(i => top[i] * top[3] + base[i] * (1 - top[3]));
  const bgOf = el => { const layers = [];
    for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none') return null;
      const c = rgba(s.backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let base = [255, 255, 255];
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base; };
  const lum = c => { const f = v => { v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE', 'OPTION', 'TEMPLATE']);
  const res = {checked: 0, unknown: 0, fails: []};
  for (const el of document.body.querySelectorAll('*')) {
    if (skip.has(el.tagName) || !vis(el) || el.closest(':disabled')) continue;
    const isField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
    let text = '';
    if (isField) { if (['hidden', 'checkbox', 'radio', 'range', 'color']
                         .includes((el.type || '').toLowerCase())) continue;
                   text = (el.tagName === 'SELECT'
                           ? (el.selectedOptions[0] || {}).text : el.value) || ''; }
    else for (const n of el.childNodes) if (n.nodeType === 3) text += n.textContent;
    text = text.trim(); if (!text) continue;
    const s = getComputedStyle(el); const bg = bgOf(el);
    if (!bg) { res.unknown++; continue; }
    const fg = over(rgba(s.color), bg); const r = ratio(fg, bg);
    const px = parseFloat(s.fontSize), bold = parseInt(s.fontWeight, 10) >= 700;
    const need = (px >= 24 || (bold && px >= 18.66)) ? 3 : 4.5;   // WCAG AA, large text 3:1
    res.checked++;
    if (r + 1e-9 < need) res.fails.push({text: text.slice(0, 40),
      testid: (el.closest('[data-testid]') || {dataset: {}}).dataset.testid || null,
      ratio: Math.round(r * 100) / 100, need, fg: fg.map(Math.round),
      bg: bg.map(Math.round), px});
  }
  return res; }"""

NAV_JS = """() => { const roots = [...document.querySelectorAll('nav, [role=navigation], header')];
  const seen = new Set(); const out = [];
  for (const r of roots) for (const a of r.querySelectorAll('a[href]')) {
    const p = new URL(a.getAttribute('href'), location.href).pathname;
    const t = (a.textContent || '').trim().replace(/\\s+/g, ' ');
    const k = p + '|' + t; if (!seen.has(k)) { seen.add(k); out.push([p, t]); } }
  return out; }"""


def font_px(loc) -> float:
    return float(loc.evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))


def style_of(loc, *props) -> dict:
    return loc.evaluate("(e, ps) => { const s = getComputedStyle(e);"
                        " return Object.fromEntries(ps.map(p => [p, s.getPropertyValue(p)])); }",
                        list(props))


def no_hscroll(page: Page) -> tuple[bool, int, int]:
    sw, iw = page.evaluate(
        "() => [document.documentElement.scrollWidth, window.innerWidth]")
    return sw <= iw, sw, iw


def focus_problems(page: Page, max_tabs: int = 25) -> list[str]:
    """Tab through the page; every focused control must look different from unfocused."""
    page.add_style_tag(content=NO_TRANSITIONS_CSS)
    base = page.evaluate(FOCUS_MARK_JS)
    problems, seen = [], set()
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        now = page.evaluate(FOCUS_NOW_JS)
        if now is None:
            continue
        if now["idx"] in seen:
            break
        seen.add(now["idx"])
        a, b = base[now["idx"]], now["snap"]
        ring = (b["outlineStyle"] != "none" and b["outlineWidth"] not in ("0px", "")
                and (a["outlineStyle"], a["outlineWidth"], a["outlineColor"])
                != (b["outlineStyle"], b["outlineWidth"], b["outlineColor"]))
        other = any(a[k] != b[k] for k in ("boxShadow", "border", "bg", "color", "deco"))
        if not (ring or other):
            problems.append(f"{now['tag']} {now['name']!r}: no visible focus change")
    if not seen:
        problems.append("Tab reached no input, button or link")
    return problems


def shot(page: Page, name: str):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
