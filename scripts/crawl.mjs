#!/usr/bin/env node
/**
 * Descarga la documentación de anylogic.help.
 *
 * Estrategia: se lanza Chromium como proceso normal (sin Playwright, que deja
 * huellas de automatización) y se controla por CDP. Se resuelve el challenge de
 * Cloudflare una vez y luego se hace `fetch()` desde el contexto de la página,
 * que comparte cookies y origen.
 *
 * Uso:
 *   node scripts/crawl.mjs                     # todo (~964 páginas)
 *   node scripts/crawl.mjs --images            # + imágenes (~3.000)
 *   node scripts/crawl.mjs --images-only       # solo lo que falte de imágenes
 *   node scripts/crawl.mjs --section anylogic  # una sección del sitio
 *   node scripts/crawl.mjs --limit 5           # prueba rápida
 *   node scripts/crawl.mjs --delay 0.5         # más lento (si Cloudflare se queja)
 *
 * Variables de entorno:
 *   ANYLOGIC_CHROME     ruta al binario de Chrome/Chromium (si no está en el PATH)
 *   ANYLOGIC_PROFILE    carpeta de perfil del navegador (por defecto .chrome-profile)
 *   ANYLOGIC_CDP_PORT   puerto de depuración (por defecto 9333)
 *
 * Solo Unix (Linux/macOS). En Windows hace falta WSL con entorno gráfico.
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const RAW = path.join(ROOT, 'raw');
const LOGS = path.join(ROOT, 'logs');
const BASE = 'https://anylogic.help';
const START = `${BASE}/anylogic/index.html`;
const PORT = Number(process.env.ANYLOGIC_CDP_PORT || 9333);
const PROFILE = process.env.ANYLOGIC_PROFILE || path.join(ROOT, '.chrome-profile');

/** Nombres con los que suele estar Chrome/Chromium en el PATH (Unix). */
const CHROME_NAMES = [
  'google-chrome',
  'google-chrome-stable',
  'chromium',
  'chromium-browser',
  'chrome',
  'brave-browser',
  'microsoft-edge',
];

/** Ruta de Chrome en macOS (no está en el PATH). */
const MAC_CHROME =
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

function findInPath(name) {
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, name);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch {}
  }
  return null;
}

/** Caché de navegadores de Playwright, por si el usuario ya los tiene. */
function findPlaywrightChrome() {
  const roots = [
    path.join(process.env.HOME || '', '.cache/ms-playwright'),
    path.join(process.env.HOME || '', 'Library/Caches/ms-playwright'),
  ];
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    const versions = fs
      .readdirSync(root)
      .filter((d) => d.startsWith('chromium-'))
      .sort()
      .reverse();
    for (const v of versions) {
      const bin = path.join(root, v, 'chrome-linux64', 'chrome');
      if (fs.existsSync(bin)) return bin;
      const mac = path.join(
        root,
        v,
        'chrome-mac',
        'Chromium.app',
        'Contents',
        'MacOS',
        'Chromium',
      );
      if (fs.existsSync(mac)) return mac;
    }
  }
  return null;
}

function resolveChrome() {
  if (process.env.ANYLOGIC_CHROME) {
    if (!fs.existsSync(process.env.ANYLOGIC_CHROME)) {
      throw new Error(
        `ANYLOGIC_CHROME apunta a una ruta que no existe: ${process.env.ANYLOGIC_CHROME}`,
      );
    }
    return process.env.ANYLOGIC_CHROME;
  }
  for (const name of CHROME_NAMES) {
    const found = findInPath(name);
    if (found) return found;
  }
  if (process.platform === 'darwin' && fs.existsSync(MAC_CHROME)) return MAC_CHROME;
  const pw = findPlaywrightChrome();
  if (pw) return pw;
  throw new Error(
    'No encontré Chrome ni Chromium. Instálalo (por ejemplo: sudo dnf install chromium) ' +
      'o indica la ruta con la variable de entorno ANYLOGIC_CHROME.',
  );
}

const WANTED = new Set([
  'anylogic',
  'advanced',
  'markup',
  'library-reference-guides',
  'tutorials',
  'cloud',
  'omniverse',
]);
const SKIP = ['/staging/', '/external-services'];

const args = process.argv.slice(2);
const opt = (name, def = null) => {
  const i = args.indexOf(`--${name}`);
  if (i === -1) return def;
  const vals = [];
  for (let j = i + 1; j < args.length && !args[j].startsWith('--'); j++) vals.push(args[j]);
  return vals.length ? vals : true;
};
const SECTION = opt('section');
const LIMIT = opt('limit');
const DELAY = Number(opt('delay', 0.15));
const DO_IMAGES = args.includes('--images') || args.includes('--images-only');
const CHECK_ONLY = args.includes('--check');
const IMAGES_ONLY = args.includes('--images-only');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function localPath(url) {
  const u = new URL(url);
  let p = u.pathname.replace(/^\//, '');
  if (p.endsWith('/')) p += 'index.html';
  if (!p.endsWith('.html')) p += '.html';
  return path.join(RAW, 'html', p);
}

async function launch() {
  const chrome = resolveChrome();
  console.log(`[crawl] navegador: ${chrome}`);
  fs.mkdirSync(PROFILE, { recursive: true });
  const proc = spawn(
    chrome,
    [
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${PROFILE}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-features=Translate',
      '--window-size=1280,900',
      START,
    ],
    { stdio: 'ignore', detached: true },
  );
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return proc;
    } catch {}
    await sleep(500);
  }
  throw new Error('Chromium no abrió el puerto de depuración');
}

async function connect() {
  let target = null;
  for (let i = 0; i < 40; i++) {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    target = list.find((t) => t.type === 'page' && t.url.includes('anylogic.help'));
    if (target) break;
    await sleep(500);
  }
  if (!target) throw new Error('No se encontró la pestaña de anylogic.help');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m);
      pending.delete(m.id);
    }
  };
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });
  const cmd = (method, params = {}) =>
    new Promise((res) => {
      const i = ++id;
      pending.set(i, res);
      ws.send(JSON.stringify({ id: i, method, params }));
    });
  await cmd('Runtime.enable');
  const evaluate = async (expression, awaitPromise = false) => {
    const r = await cmd('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise,
    });
    if (r.result?.exceptionDetails) {
      throw new Error(r.result.exceptionDetails.text || 'evaluate failed');
    }
    return r.result?.result?.value;
  };
  return { ws, evaluate, close: () => ws.close() };
}

async function waitForRealPage(ev, timeoutMs = 90000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const info = await ev(`JSON.stringify({
        t: document.title,
        n: document.body ? document.body.innerText.length : 0,
        links: document.querySelectorAll('a[href]').length,
        cf: !!document.querySelector('#challenge-running, #cf-challenge-running, .cf-browser-verification, #challenge-form')
      })`);
      const { t, n, links, cf } = JSON.parse(info || '{}');
      if (process.env.DEBUG) console.log('[debug]', JSON.stringify({ t, n, links, cf }));
      if (!cf && n > 200 && links > 20) return t;
    } catch {}
    await sleep(1000);
  }
  throw new Error(
    'Cloudflare no cedió. Completa el challenge a mano en la ventana abierta y relanza.',
  );
}

async function sitemapUrls(ev) {
  const xml = await ev(
    `fetch('https://anylogic.help/sitemap.xml').then(r=>r.text())`,
    true,
  );
  const urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  return [...new Set(urls)].filter((u) => {
    const p = new URL(u).pathname;
    if (SKIP.some((s) => p.startsWith(s))) return false;
    return WANTED.has(p.replace(/^\//, '').split('/')[0]);
  });
}

const FETCH_JS = (url) => `fetch(${JSON.stringify(url)},{credentials:'same-origin'})
  .then(async r => JSON.stringify({s:r.status,b:await r.text()}))`;

async function crawlPages(ev, urls) {
  const todo = urls.filter((u) => !fs.existsSync(localPath(u)));
  console.log(`[crawl] ${urls.length} URLs, ${todo.length} pendientes`);
  const failures = [];
  const t0 = Date.now();
  for (let i = 0; i < todo.length; i++) {
    const url = todo[i];
    const dest = localPath(url);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    let ok = false;
    for (let attempt = 0; attempt < 2 && !ok; attempt++) {
      try {
        const res = JSON.parse(await ev(FETCH_JS(url), true));
        if (res.s !== 200) throw new Error(`HTTP ${res.s}`);
        if (res.b.length < 500 || res.b.slice(0, 3000).includes('Just a moment'))
          throw new Error('challenge en la respuesta');
        fs.writeFileSync(dest, res.b);
        ok = true;
      } catch (e) {
        if (attempt === 1) {
          failures.push({ url, error: String(e.message || e) });
          console.log(`  ! ${url} -> ${e.message || e}`);
        } else await sleep(1500);
      }
    }
    if ((i + 1) % 25 === 0 || i + 1 === todo.length) {
      const rate = (i + 1) / ((Date.now() - t0) / 1000);
      const eta = (todo.length - i - 1) / rate / 60;
      console.log(
        `[crawl] ${i + 1}/${todo.length}  ${rate.toFixed(1)} pág/s  ETA ${eta.toFixed(1)} min`,
      );
    }
    await sleep(DELAY * 1000);
  }
  fs.mkdirSync(LOGS, { recursive: true });
  fs.writeFileSync(
    path.join(LOGS, 'crawl_failures.json'),
    JSON.stringify(failures, null, 2),
  );
  console.log(`[crawl] fin. fallos: ${failures.length}`);
  return failures;
}

const IMG_BATCH_JS = (urls) => `Promise.all(${JSON.stringify(urls)}.map(async (url) => {
  try {
    const r = await fetch(url, {credentials:'same-origin'});
    if (!r.ok) return {url, s: r.status};
    const b = await r.blob();
    const buf = await b.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let s = ''; const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    return {url, s: 200, b64: btoa(s)};
  } catch (e) { return {url, s: 0, err: String(e)}; }
}))`;

async function crawlImages(ev) {
  const htmlRoot = path.join(RAW, 'html');
  const files = [];
  (function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name.endsWith('.html')) files.push(p);
    }
  })(htmlRoot);

  const urls = new Set();
  for (const f of files) {
    const txt = fs.readFileSync(f, 'utf8');
    for (const m of txt.matchAll(/<img[^>]+src="([^"]+)"/g)) {
      const src = m[1];
      if (src.startsWith('data:')) continue;
      let abs;
      if (src.startsWith('http')) abs = src;
      else if (src.startsWith('/')) abs = BASE + src;
      else {
        const rel = path.relative(htmlRoot, f).replaceAll(path.sep, '/');
        abs = new URL(src, `${BASE}/${path.posix.dirname(rel)}/`).href;
      }
      if (abs.startsWith(BASE)) urls.add(abs.split('#')[0]);
    }
  }
  const list = [...urls];
  const pending = list.filter(
    (u) => !fs.existsSync(path.join(RAW, 'img', new URL(u).pathname.replace(/^\//, ''))),
  );
  console.log(`[images] ${list.length} referenciadas, ${pending.length} pendientes`);
  const failures = [];
  const BATCH = 4;
  for (let i = 0; i < pending.length; i += BATCH) {
    const batch = pending.slice(i, i + BATCH);
    let results = [];
    try {
      results = await ev(IMG_BATCH_JS(batch), true);
    } catch (e) {
      failures.push(...batch.map((url) => ({ url, error: String(e) })));
    }
    for (const res of results || []) {
      if (res.s !== 200 || !res.b64) {
        failures.push({ url: res.url, error: res.err || `HTTP ${res.s}` });
        continue;
      }
      const dest = path.join(RAW, 'img', new URL(res.url).pathname.replace(/^\//, ''));
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.writeFileSync(dest, Buffer.from(res.b64, 'base64'));
    }
    if ((i + BATCH) % 200 === 0 || i + BATCH >= pending.length) {
      console.log(`[images] ${Math.min(i + BATCH, pending.length)}/${pending.length}`);
    }
    await sleep(DELAY * 1000);
  }
  fs.writeFileSync(
    path.join(LOGS, 'image_failures.json'),
    JSON.stringify(failures, null, 2),
  );
  console.log(`[images] fin. fallos: ${failures.length}`);
}

async function main() {
  if (CHECK_ONLY) {
    const chrome = resolveChrome();
    console.log(`[crawl] navegador: ${chrome}`);
    return;
  }
  const proc = await launch();
  const { evaluate, close } = await connect();
  try {
    const title = await waitForRealPage(evaluate);
    console.log(`[crawl] Cloudflare superado: "${title}"`);
    let urls = await sitemapUrls(evaluate);
    if (SECTION) {
      const want = new Set(Array.isArray(SECTION) ? SECTION : [SECTION]);
      urls = urls.filter((u) =>
        want.has(new URL(u).pathname.replace(/^\//, '').split('/')[0]),
      );
    }
    if (LIMIT) urls = urls.slice(0, Number(Array.isArray(LIMIT) ? LIMIT[0] : LIMIT));
    if (!IMAGES_ONLY) await crawlPages(evaluate, urls);
    if (DO_IMAGES) await crawlImages(evaluate);
  } finally {
    close();
    try {
      process.kill(-proc.pid);
    } catch {
      proc.kill('SIGKILL');
    }
  }
}

main().catch((e) => {
  console.error('[crawl] ERROR:', e.message);
  process.exit(1);
});
