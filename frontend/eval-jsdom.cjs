const { JSDOM, VirtualConsole } = require('jsdom');
const { readFileSync } = require('node:fs');

const html = readFileSync('dist/index.html', 'utf8');

const vc = new VirtualConsole();
const allLogs = [];
vc.on('log', (...a) => allLogs.push(['log', ...a].map(String).join(' ')));
vc.on('error', (...a) => allLogs.push(['error', ...a].map(String).join(' ')));
vc.on('warn', (...a) => allLogs.push(['warn', ...a].map(String).join(' ')));
vc.on('info', (...a) => allLogs.push(['info', ...a].map(String).join(' ')));
vc.on('jsdomError', (e) => allLogs.push(['jsdomError', (e && (e.stack || e.message)) || String(e)]));
vc.on('moduleEvaluationError', (e) => allLogs.push(['moduleEvalError', (e && (e.stack || e.message)) || String(e)]));

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5180/',
  runScripts: 'dangerously',
  resources: 'usable',
  pretendToBeVisual: true,
  virtualConsole: vc,
});

const errs = [];
dom.window.addEventListener('error', (e) => errs.push('WIN_ERROR: ' + ((e.error && (e.error.stack || e.error.message)) || e.message) + ' @ ' + e.filename + ':' + e.lineno));
dom.window.addEventListener('unhandledrejection', (e) => errs.push('UNHANDLED: ' + ((e.reason && (e.reason.stack || e.reason.message)) || String(e.reason))));

dom.window.fetch = async () => { throw new Error('fetch stubbed'); };

process.on('uncaughtException', (e) => allLogs.push(['UNCAUGHT', e.stack || e.message]));

setTimeout(() => {
  const doc = dom.window.document;
  const root = doc.getElementById('root');
  const rootHTML = root ? (root.innerHTML || 'EMPTY') : 'NO_ROOT';
  console.log('=== ALL LOGS (' + allLogs.length + ') ===');
  allLogs.forEach((l, i) => console.log('[' + i + ']', ...l));
  console.log('=== DOM ERRORS (' + errs.length + ') ===');
  errs.forEach((e, i) => console.log('[' + i + ']', e));
  console.log('=== ROOT INNERHTML LENGTH: ' + rootHTML.length + ' ===');
  console.log('=== ROOT FIRST 600 ===');
  console.log(rootHTML.substring(0, 600));
  console.log('=== FINGERPRINT: ' + rootHTML.includes('ENHANCED-UI-VERIFY-0823') + ' ===');
  process.exit(0);
}, 6000);
