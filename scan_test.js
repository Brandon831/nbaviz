// Render audit of a built page in jsdom: scans every tab for NaN/undefined, empty cells, unresolved names, duplicate ids and unlabeled controls. node scan_test.js docs/index.html (needs jsdom).
const { JSDOM, VirtualConsole } = require('jsdom'); const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8'); const errors = []; const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e && e.message || e))); vc.on('error', m => errors.push('console.error: ' + m)); vc.on('warn', ()=>{});
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc, url: 'https://example.test/', beforeParse(window){
  const noop = new Proxy({}, { get: (t, k) => k === 'canvas' ? {} : (k === 'measureText' ? () => ({width: 10}) : (k === 'createImageData' ? (w, h) => ({data: new Uint8ClampedArray(w*h*4)}) : (k === 'getImageData' ? (x,y,w,h) => ({data: new Uint8ClampedArray(w*h*4)}) : () => noop))), set: () => true });
  window.HTMLCanvasElement.prototype.getContext = function(){ return noop; };
  window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} }; window.matchMedia = () => ({ matches: false, addEventListener(){}, addListener(){} });
  window.scrollTo = () => {}; window.fetch = () => Promise.reject(new Error('no network')); window.requestAnimationFrame = (f) => setTimeout(f, 0);
  window.addEventListener('error', e => errors.push('window.error: ' + (e.error && e.error.stack || e.message)));
}});
const w = dom.window, d = w.document;
setTimeout(() => {
  const views = Array.from(d.querySelectorAll('[role=tabpanel]')).map(v => v.id);
  const findings = [];
  views.forEach(id => {
    const view = id.replace('view-', ''); try { if (w.NBA_NAV) w.NBA_NAV.show(view); } catch (e) { findings.push(id + ': show() threw ' + e.message); }
    const el = d.getElementById(id); if (!el) return; const txt = el.textContent;
    ['NaN', 'undefined', 'null', '[object', 'Infinity', 'NaN%'].forEach(bad => { const n = (txt.match(new RegExp(bad.replace('[', '\\['), 'g')) || []).length; if (n) findings.push(id + ': "' + bad + '" x' + n + ' e.g. ' + txt.slice(Math.max(0, txt.indexOf(bad) - 60), txt.indexOf(bad) + 40).replace(/\s+/g, ' ')); });
    const emptyTd = Array.from(el.querySelectorAll('td')).filter(c => !c.textContent.trim() && !c.querySelector('*')).length; if (emptyTd) findings.push(id + ': ' + emptyTd + ' empty table cells');
    const dashes = (txt.match(/–/g) || []).length; if (dashes > 40) findings.push(id + ': ' + dashes + ' dashes (missing values?)');
    const unnamed = (txt.match(/Player \d{3,}/g) || []).length; if (unnamed) findings.push(id + ': ' + unnamed + ' unresolved player names');
    const imgs = Array.from(el.querySelectorAll('img')).filter(i => !i.getAttribute('alt')).length; if (imgs) findings.push(id + ': ' + imgs + ' images without alt');
    const badHref = Array.from(el.querySelectorAll('a[href]')).filter(a => /undefined|null|NaN/.test(a.getAttribute('href'))).length; if (badHref) findings.push(id + ': ' + badHref + ' links with bad hrefs');
    const dupIds = {}; Array.from(el.querySelectorAll('[id]')).forEach(e => { dupIds[e.id] = (dupIds[e.id] || 0) + 1; }); const dups = Object.keys(dupIds).filter(k => dupIds[k] > 1); if (dups.length) findings.push(id + ': duplicate ids ' + dups.slice(0, 5).join(','));
    findings.push(id + ': ' + txt.replace(/\s+/g, ' ').trim().length + ' chars, ' + el.querySelectorAll('table').length + ' tables, ' + el.querySelectorAll('svg').length + ' svgs, ' + el.querySelectorAll('button').length + ' buttons');
  });
  // whole document duplicate ids
  const all = {}; Array.from(d.querySelectorAll('[id]')).forEach(e => { all[e.id] = (all[e.id] || 0) + 1; }); const dupAll = Object.keys(all).filter(k => all[k] > 1); if (dupAll.length) findings.push('DOCUMENT duplicate ids: ' + dupAll.join(', '));
  // buttons and controls without accessible names
  const unnamedBtns = Array.from(d.querySelectorAll('button')).filter(b => !b.textContent.trim() && !b.getAttribute('aria-label') && !b.getAttribute('title')).length; findings.push('buttons without a name: ' + unnamedBtns);
  const inputsNoLabel = Array.from(d.querySelectorAll('input:not([type=hidden]),select')).filter(i => !i.id || (!d.querySelector('label[for="' + i.id + '"]') && !i.closest('label') && !i.getAttribute('aria-label'))).map(i => i.id || i.name || i.type); findings.push('inputs/selects without a label: ' + inputsNoLabel.length + ' ' + inputsNoLabel.slice(0, 8).join(','));
  console.log(findings.join('\n')); console.log('\nruntime errors: ' + errors.length); errors.slice(0, 8).forEach(e => console.log(' - ' + String(e).split('\n').slice(0, 2).join(' | ')));
}, 1500);
