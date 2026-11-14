"""What the Desk adds to a page beside Scriba's player: looking.

Scriba's page code (loaded by ``browser_cdp.scriba_page_bundle``) applies a
step to an element it is given a locator for. It has no way to look at a page
it has not been shown before: no snapshot, no lookup by what a control is
called. This script is that part, and only that part. It never clicks, types
or submits by itself: every action goes through ``__scriba.applyStep``, with a
locator made by ``__scriba.captureLocator`` and checked by
``__scriba.resolveLocator`` to point at exactly the element that was found.

It lives in the same isolated world as Scriba's code, which the page's own
scripts cannot reach. It reads what a person could see or use: names of
links, buttons and fields, a value beside a label, the rows of a table, the
text of the page (given back as data for the content scan, never executed).
"""

DESK_PAGE_JS = r"""
(function(){
  if (globalThis.__desk || !globalThis.__scriba) return;
  const S = globalThis.__scriba;
  const norm = (t) => String(t == null ? '' : t).replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el || !el.isConnected || !el.getClientRects().length) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  };
  // The name a person would use for a control. A subset of the accessible-name rules.
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return norm(aria);
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const text = norm(by.split(/\s+/).map((id) => (document.getElementById(id) || {}).textContent || '').join(' '));
      if (text) return text;
    }
    if (el.matches('input[type=submit],input[type=button]')) return norm(el.value);
    if (el.matches('input,select,textarea')) {
      if (el.id) {
        const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (label) return norm(label.textContent);
      }
      const wrap = el.closest('label');
      if (wrap) {
        const copy = wrap.cloneNode(true);
        copy.querySelectorAll('input,select,textarea').forEach((n) => n.remove());
        return norm(copy.textContent);
      }
      return norm(el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || '');
    }
    return norm(el.textContent || el.getAttribute('title') || el.getAttribute('alt') || '');
  };
  const KINDS = {
    link: 'a[href]',
    button: 'button,input[type=submit],input[type=button],[role=button]',
    field: 'input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea',
    control: 'a[href],button,input[type=submit],input[type=button],[role=button]',
  };
  const dialogEl = () => {
    for (const d of document.querySelectorAll('dialog[open],[role=dialog],[role=alertdialog],[aria-modal="true"]')) {
      if (visible(d)) return d;
    }
    return null;
  };
  const score = (name, want) => {
    const n = String(name).toLowerCase(), w = String(want || '').toLowerCase();
    if (!w) return 0;
    return n === w ? 3 : n.startsWith(w) ? 2 : n.includes(w) ? 1 : 0;
  };
  const absolute = (value) => { try { return new URL(value, location.href).href } catch { return null } };
  const isPassword = (el) => el.matches('input') && (el.type === 'password'
    || /password/.test(el.getAttribute('autocomplete') || '')
    || /pass(word|wd)?|pwd/i.test((el.getAttribute('name') || '') + ' ' + (el.id || '')));
  const state = { found: [], inDialog: [] };
  const describe = (el, i, sc) => {
    const form = el.form || el.closest('form');
    const d = dialogEl();
    const row = el.closest('tr,li,article');
    return {
      i, score: sc, name: nameOf(el).slice(0, 200), tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      href: el.matches('a[href]') ? absolute(el.getAttribute('href')) : null,
      inDialog: !!(d && d.contains(el)), inForm: !!form,
      formAction: form ? absolute(el.getAttribute('formaction') || form.getAttribute('action') || location.href) : null,
      formMethod: form ? (el.getAttribute('formmethod') || form.getAttribute('method') || 'get').toLowerCase() : null,
      submits: !!form && el.matches('button:not([type=button]):not([type=reset]),input[type=submit]'),
      password: isPassword(el), disabled: !!el.disabled,
      context: row ? norm(row.textContent).slice(0, 300) : '',
    };
  };
  const find = (kind, want) => {
    state.found = [];
    const out = [];
    for (const el of document.querySelectorAll(KINDS[kind] || KINDS.control)) {
      if (!visible(el)) continue;
      const sc = score(nameOf(el), want);
      if (!sc) continue;
      state.found.push(el);
      out.push(describe(el, state.found.length - 1, sc));
    }
    return out.sort((a, b) => b.score - a.score).slice(0, 25);
  };
  const dialog = () => {
    const d = dialogEl();
    state.inDialog = [];
    if (!d) return null;
    const buttons = [];
    for (const b of d.querySelectorAll(KINDS.control)) {
      if (!visible(b)) continue;
      state.inDialog.push(b);
      buttons.push(describe(b, state.inDialog.length - 1, 0));
    }
    const heading = d.querySelector('h1,h2,h3');
    return { name: norm(d.getAttribute('aria-label') || (heading && heading.textContent) || 'dialog').slice(0, 120), buttons };
  };
  // Wait for something to be true by watching the page change, not by polling on a clock.
  const until = (probe, ms) => new Promise((resolve) => {
    const first = probe();
    if (first || ms <= 0) return resolve(first);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true; observer.disconnect(); clearTimeout(timer); resolve(probe());
    };
    const observer = new MutationObserver(() => { if (probe()) finish(); });
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true });
    const timer = setTimeout(finish, ms);
  });
  // One look: the controls called `want`, and whether a dialog is in the way.
  const look = async (kind, want, ms) => {
    await until(() => find(kind, want).length > 0, ms);
    return { candidates: find(kind, want), dialog: dialog(), url: location.href, title: document.title };
  };
  // Act on a found element, through Scriba's player, only if Scriba's locator points back at exactly it.
  const act = async (which, i, step, allow) => {
    const el = (which === 'dialog' ? state.inDialog : state.found)[i];
    if (!el || !el.isConnected) return { stale: true };
    const locator = S.captureLocator(el);
    const hit = S.resolveLocator(document, locator);
    if (hit.el !== el) return { ambiguous: true, locator };
    if (step.action === 'select' && el instanceof HTMLSelectElement) {
      // The one action not done by Scriba's player: at this revision its `select` step throws on a
      // native <select> (it calls the text input's value setter on it). Same site check, then the
      // option is chosen by its value or its label, and the page is told as a person's choice would.
      if (!S.originAllowed(location.href, allow)) return { locator, out: { error: 'Refused to act on ' + location.origin + '.' } };
      const want = String(step.value == null ? '' : step.value);
      const option = [...el.options].find((o) => o.value === want) || [...el.options].find((o) => norm(o.textContent).toLowerCase() === want.toLowerCase());
      if (!option) return { locator, out: { error: 'The list has no choice "' + want.slice(0, 80) + '".' } };
      el.value = option.value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return { locator, name: nameOf(el).slice(0, 200), matchedBy: hit.matchedBy, out: { done: true, matchedBy: hit.matchedBy } };
    }
    const out = await S.applyStep(Object.assign({}, step, { locator }), allow);
    return { locator, name: nameOf(el).slice(0, 200), matchedBy: (out && out.matchedBy) || hit.matchedBy, out };
  };
  // Act on a locator kept from an earlier run. Refused when what it now points at is called something else.
  const replay = async (step, allow, ms, wantName) => {
    const hit = await until(() => { const h = S.resolveLocator(document, step.locator || {}); return h.el ? h : null }, ms);
    if (!hit) return { missing: true };
    const name = nameOf(hit.el);
    if (wantName && !score(name, wantName)) return { missing: true, different: name.slice(0, 120) };
    // A kept locator is only ever used to go somewhere, never to submit.
    if ((hit.el.form || hit.el.closest('form')) && hit.el.matches('button:not([type=button]),input[type=submit]')) return { missing: true, commits: true };
    const out = await S.applyStep(step, allow);
    return { name: name.slice(0, 200), matchedBy: (out && out.matchedBy) || hit.matchedBy, healed: !!hit.healed, out };
  };
  const readNow = (label) => {
    const want = String(label).toLowerCase();
    const same = (el) => norm(el.textContent).toLowerCase().replace(/:$/, '') === want;
    for (const dt of document.querySelectorAll('dt')) {
      const dd = dt.nextElementSibling;
      if (same(dt) && dd && dd.tagName === 'DD') return { found: true, value: norm(dd.textContent).slice(0, 2000), how: 'definition' };
    }
    for (const th of document.querySelectorAll('tbody th, tr > th[scope=row]')) {
      const td = th.parentElement.querySelector('td');
      if (same(th) && td) return { found: true, value: norm(td.textContent).slice(0, 2000), how: 'row' };
    }
    for (const el of document.querySelectorAll(KINDS.field)) {
      if (nameOf(el).toLowerCase() !== want) continue;
      if (isPassword(el)) return { found: false, password: true };
      return { found: true, value: String(el.value == null ? '' : el.value).slice(0, 2000), how: 'field' };
    }
    return null;
  };
  const read = async (label, ms) => (await until(() => readNow(label), ms)) || { found: false };
  const tableOf = (doc, want) => {
    const w = String(want || '').toLowerCase();
    for (const t of doc.querySelectorAll('table')) {
      const caption = norm((t.caption && t.caption.textContent) || t.getAttribute('aria-label') || t.id || '');
      if (w && !caption.toLowerCase().includes(w)) continue;
      return {
        found: true, caption, headers: [...t.querySelectorAll('thead th')].map((h) => norm(h.textContent)),
        rows: [...t.querySelectorAll('tbody tr')].slice(0, 500).map((r) => [...r.children].map((c) => norm(c.textContent).slice(0, 300))),
      };
    }
    return { found: false };
  };
  const table = async (want, ms) => {
    await until(() => tableOf(document, want).found, ms);
    const pages = [];
    for (const a of document.querySelectorAll('nav a[href], a[rel~="next"]')) {
      const url = absolute(a.getAttribute('href'));
      if (url && new URL(url).origin === location.origin && /[?&]page=\d+/.test(url) && !pages.includes(url)) pages.push(url);
    }
    return Object.assign(tableOf(document, want), { url: location.href, pages });
  };
  // Several pages of the same table at once: reads only, same site, same session.
  const tables = (urls, want) => Promise.all(urls.map(async (url) => {
    try {
      const response = await fetch(url, { credentials: 'include' });
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      return Object.assign({ url: response.url, status: response.status }, tableOf(doc, want));
    } catch (error) {
      return { url, status: 0, found: false, error: String((error && error.message) || error) };
    }
  }));
  const download = async (url, maxBytes) => {
    let response;
    try { response = await fetch(url, { credentials: 'include' }) }
    catch (error) { return { ok: false, error: 'network', message: String((error && error.message) || error) } }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length > maxBytes) return { ok: false, error: 'too_large', size: bytes.length };
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return { ok: response.ok, status: response.status, url: response.url, redirected: response.redirected,
             type: response.headers.get('content-type') || '', disposition: response.headers.get('content-disposition') || '',
             size: bytes.length, b64: btoa(binary) };
  };
  // The page's text, as data for the content scan: what is shown, and what is in the page but not shown.
  const texts = () => {
    const body = document.body || document.documentElement;
    let hidden = '';
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode()) && hidden.length < 5000) {
      const parent = node.parentElement;
      if (!parent || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(parent.tagName)) continue;
      const text = norm(node.nodeValue);
      if (text && !visible(parent)) hidden += text + '\n';
    }
    return { url: location.href, visible: (body.innerText || '').slice(0, 20000), hidden };
  };
  const page = () => ({
    url: location.href, title: document.title.slice(0, 200),
    headings: [...document.querySelectorAll('h1,h2')].slice(0, 6).map((h) => norm(h.textContent).slice(0, 120)),
    links: [...document.querySelectorAll('a[href]')].filter(visible).slice(0, 40).map((a) => nameOf(a).slice(0, 80)).filter(Boolean),
    buttons: [...document.querySelectorAll(KINDS.button)].filter(visible).slice(0, 20).map((b) => nameOf(b).slice(0, 80)).filter(Boolean),
    dialog: dialog(),
  });
  globalThis.__desk = { look, act, replay, read, table, tables, download, texts, page };
})();
"""
