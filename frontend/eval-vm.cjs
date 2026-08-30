const { readFileSync } = require('node:fs');
const vm = require('node:vm');

const bundle = readFileSync('dist/assets/' + require('node:fs').readdirSync('dist/assets').filter(f => f.endsWith('.js'))[0], 'utf8');

// Build a proper DOM stub with MutationObserver, IntersectionObserver, ResizeObserver
class MutationObserver {
  constructor(cb) { this.cb = cb; }
  observe(target, init) { this.target = target; this.init = init; }
  disconnect() {}
  takeRecords() { return []; }
}
class IntersectionObserver { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} unobserve() {} }
class ResizeObserver { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} unobserve() {} }

const root = { id: 'root', children: [], innerHTML: '', textContent: '', appendChild(c) { this.children.push(c); c.parent = this; }, removeChild() {}, insertBefore(c) { this.children.push(c); c.parent = this; } };
const body = { id: 'body', children: [root], appendChild(c) { this.children.push(c); c.parent = this; }, insertBefore(c, ref) { const i = this.children.indexOf(ref); if (i >= 0) this.children.splice(i, 0, c); else this.children.push(c); } };
const head = { children: [], appendChild(c) { this.children.push(c) } };

const document = {
  documentElement: { style: {} },
  head,
  body,
  getElementById: (id) => id === 'root' ? root : null,
  querySelector: (sel) => null,
  querySelectorAll: () => [],
  createElement: (tag) => {
    const el = {
      tagName: tag.toUpperCase(), children: [], style: {}, classList: { add: () => {}, remove: () => {}, contains: () => false, toggle: () => {} },
      setAttribute: () => {}, getAttribute: () => null, removeAttribute: () => {},
      appendChild: function(c) { this.children.push(c); c.parent = this; return c; },
      insertBefore: function(c, ref) { this.children.push(c); c.parent = this; return c; },
      removeChild: function(c) { this.children = this.children.filter(x => x !== c); return c; },
      addEventListener: () => {}, removeEventListener: () => {},
      relList: { supports: () => false },
    };
    return el;
  },
  createTextNode: (text) => ({ nodeType: 3, textContent: text, parent: null }),
  createDocumentFragment: () => ({ children: [], appendChild(c) { this.children.push(c); return c; } }),
  addEventListener: () => {}, removeEventListener: () => {},
  dispatchEvent: () => {},
  hidden: false, visibilityState: 'visible',
};

const sandbox = {
  console: { log: (...a) => console.log('LOG:', ...a.map(x => typeof x === 'string' ? x.substring(0, 300) : x)), error: (...a) => console.log('ERR:', ...a.map(x => x && x.stack ? x.stack : String(x))), warn: (...a) => console.log('WARN:', ...a.map(x => String(x).substring(0, 200))) },
  document,
  window: null,
  navigator: { userAgent: 'node-vm-stub' },
  localStorage: { getItem: () => null, setItem: () => {} },
  sessionStorage: { getItem: () => null, setItem: () => {} },
  location: { href: 'http://127.0.0.1:5180/', pathname: '/' },
  fetch: () => Promise.reject(new Error('fetch stubbed')),
  MutationObserver, IntersectionObserver, ResizeObserver,
  requestAnimationFrame: (cb) => setTimeout(cb, 16),
  cancelAnimationFrame: clearTimeout,
  setTimeout, setInterval, clearTimeout, clearInterval, queueMicrotask,
  Promise, Symbol, Object, Array, Map, Set, WeakMap, WeakSet, JSON, Math, Date, RegExp,
  Error, TypeError, ReferenceError, SyntaxError, RangeError,
  URL, Blob, FormData: function FormData() {}, Headers: function Headers() {}, Request: function Request() {}, Response: function Response() {},
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
  performance: { now: () => Date.now() },
  structuredClone: (x) => JSON.parse(JSON.stringify(x)),
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
sandbox.document.defaultView = sandbox;

process.on('uncaughtException', (e) => console.log('UNCAUGHT:', e.stack || e.message));
process.on('unhandledRejection', (e) => console.log('UNHANDLED:', (e && (e.stack || e.message)) || String(e)));

vm.createContext(sandbox);
try {
  vm.runInContext(bundle, sandbox, { filename: 'bundle.js', timeout: 10000 });
  console.log('BUNDLE_OK');
} catch (e) {
  console.log('BUNDLE_THROW: ' + (e.stack || e.message));
}
