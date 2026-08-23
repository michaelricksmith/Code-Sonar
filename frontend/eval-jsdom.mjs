import { JSDOM, ResourceLoader } from 'jsdom';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const html = readFileSync('dist/index.html', 'utf8');
const errors = [];
const consoleLogs = [];

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5180/',
  runScripts: 'dangerously',
  resources: new ResourceLoader(),
  pretendToBeVisual: true,
});

dom.window.console = {
  log: (...a) => consoleLogs.push(['log', ...a].map(String).join(' ')),
  error: (...a) => errors.push(['console.error', ...a].map(String).join(' ')),
  warn: (...a) => errors.push(['console.warn', ...a].map(String).join(' ')),
  info: (...a) => consoleLogs.push(['info', ...a].map(String).join(' ')),
  debug: () => {},
};

dom.window.addEventListener('error', (e) => errors.push('window.error: ' + (e.error?.stack || e.message)));
dom.window.addEventListener('unhandledrejection', (e) => errors.push('unhandledrejection: ' + (e.reason?.stack || String(e.reason))));

dom.window.fetch = async () => { throw new Error('fetch stubbed'); };

await new Promise(r => setTimeout(r, 5000));

const root = dom.window.document.getElementById('root');
const rootHTML = root ? root.innerHTML : 'NO_ROOT';
const bodyText = dom.window.document.body.innerText;

writeFileSync(process.env.TEMP + '/jsdom-root.html', rootHTML);
writeFileSync(process.env.TEMP + '/jsdom-body.txt', bodyText);

console.log('=== ERRORS (' + errors.length + ') ===');
errors.forEach((e, i) => console.log('[' + i + ']', e));
console.log('=== CONSOLE LOGS (' + consoleLogs.length + ') ===');
consoleLogs.slice(0, 30).forEach((e, i) => console.log('[' + i + ']', e));
console.log('=== ROOT INNERHTML LENGTH: ' + rootHTML.length + ' ===');
console.log('=== ROOT FIRST 800 CHARS ===');
console.log(rootHTML.substring(0, 800));
console.log('=== BODY TEXT FIRST 500 CHARS ===');
console.log(bodyText.substring(0, 500));
console.log('=== FINGERPRINT IN DOM: ' + rootHTML.includes('ENHANCED-UI-VERIFY-0823') + ' ===');
