// Runtime smoke test of a built page in jsdom: npm install jsdom@24 (once), then node smoke_test.js docs/index.html. Exits non-zero on any runtime error.
// loads the built page in jsdom with a no-op canvas context, drives the shot-chart and awards controls, and reports every runtime error
const { JSDOM, VirtualConsole } = require('jsdom'); const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8'); const errors = []; const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e && e.message || e))); vc.on('error', m => errors.push('console.error: ' + m)); vc.on('warn', ()=>{});
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc, url: 'https://example.test/', beforeParse(window){
  const noop = new Proxy({}, { get: (t, k) => k === 'canvas' ? {} : (k === 'measureText' ? () => ({width: 10}) : (k === 'createImageData' ? (w, h) => ({data: new Uint8ClampedArray(w*h*4)}) : (k === 'getImageData' ? (x,y,w,h) => ({data: new Uint8ClampedArray(w*h*4)}) : () => noop))), set: () => true });
  window.HTMLCanvasElement.prototype.getContext = function(){ return noop; };
  window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
  window.matchMedia = () => ({ matches: false, addEventListener(){}, addListener(){} });
  window.scrollTo = () => {}; window.fetch = () => Promise.reject(new Error('no network in the smoke test'));
  window.requestAnimationFrame = (f) => setTimeout(f, 0);
  window.addEventListener('error', e => errors.push('window.error: ' + (e.error && e.error.stack || e.message)));
}});
const w = dom.window, d = w.document;
function fire(el, type){ el.dispatchEvent(new w.Event(type, {bubbles: true})); }
function step(name, fn){ try { fn(); } catch (e) { errors.push(name + ': ' + (e.stack || e)); } }
setTimeout(() => {
  const S = w.NBA_APP && w.NBA_APP.state;
  step('boot', () => { if (!S || S.pid == null) throw new Error('shot chart did not boot (no player selected)'); });
  const out = [];
  step('metric xdiff', () => { const r = d.querySelector('input[name=metric][value=xdiff]'); r.checked = true; fire(r, 'change'); out.push('xdiff legend: ' + /expected/i.test(d.getElementById('legend').textContent)); });
  step('kpi expected', () => { out.push('kpi has expected tile: ' + /vs\. expected/.test(d.getElementById('kpis').textContent)); });
  step('compare player', () => { const c = d.getElementById('cmpmode'); c.value = 'player'; fire(c, 'change'); out.push('cmpview shown: ' + !d.getElementById('cmpview').hidden + ', B pid: ' + S.cmp.pid); });
  step('difference map', () => { const r = d.querySelector('input[name=cmpview][value=diff]'); r.checked = true; fire(r, 'change'); out.push('capB: ' + d.getElementById('capB').textContent.slice(0, 80)); const v = w.NBA_APP.views(); out.push('viewB label: ' + (v.B && v.B.label)); });
  ['diff','pps','freq'].forEach(m => step('diff with metric ' + m, () => { const r = d.querySelector('input[name=metric][value=' + m + ']'); r.checked = true; fire(r, 'change'); }));
  step('side by side', () => { const r = d.querySelector('input[name=cmpview][value=side]'); r.checked = true; fire(r, 'change'); });
  step('compare league + diff', () => { const c = d.getElementById('cmpmode'); c.value = 'league'; fire(c, 'change'); const r = d.querySelector('input[name=cmpview][value=diff]'); r.checked = true; fire(r, 'change'); out.push('league diff capB: ' + d.getElementById('capB').textContent.slice(0, 70)); });
  step('compare prev + diff', () => { const c = d.getElementById('cmpmode'); c.value = 'prev'; fire(c, 'change'); out.push('prev note: ' + d.getElementById('cmpnote').textContent.slice(0, 60)); });
  step('best checkbox', () => { const c = d.getElementById('cmpmode'); c.value = 'player'; fire(c, 'change'); const b = d.getElementById('best1'); out.push('best1 label: ' + d.getElementById('best1l').textContent + ' | disabled: ' + b.disabled + ' | title: ' + d.getElementById('best1w').title.slice(0, 60)); if (!b.disabled){ b.checked = true; fire(b, 'change'); out.push('after best1: season=' + S.season + ' best=' + S.best + ' checked=' + d.getElementById('best1').checked); } });
  step('best2 checkbox', () => { const b = d.getElementById('best2'); out.push('best2 label: ' + d.getElementById('best2l').textContent + ' | disabled: ' + b.disabled); if (!b.disabled){ b.checked = true; fire(b, 'change'); out.push('after best2: cmp.best=' + S.cmp.best + ' note=' + d.getElementById('cmpnote').textContent.slice(0, 70)); } });
  step('arc rendered', () => { out.push('arc dots: ' + d.querySelectorAll('#arc circle').length + ', caption: ' + (d.querySelector('#arc .cap') || {textContent: ''}).textContent.slice(0, 60)); });
  step('arc click', () => { const c = d.querySelector('#arc circle[data-k]'); if (c){ c.dispatchEvent(new w.MouseEvent('click', {bubbles: true})); out.push('after arc click: season=' + S.season); } });
  step('player change while following', () => { d.getElementById('best1').checked = true; fire(d.getElementById('best1'), 'change'); const sel = d.getElementById('player'); if (sel.options.length > 2){ sel.value = sel.options[2].value; fire(sel, 'change'); out.push('after player change: pid=' + S.pid + ' season=' + S.season + ' best=' + S.best); } });
  step('filters toggle', () => { const b = d.getElementById('ftoggle'); b.click(); out.push('ftoggle expanded: ' + b.getAttribute('aria-expanded')); b.click(); });
  step('reset filters', () => { d.getElementById('freset').click(); out.push('after reset cmp mode: ' + S.cmp.mode); });
  step('awards tab render', () => { const a = d.getElementById('mvp-list'); out.push('mvp rows: ' + (a ? a.querySelectorAll('li').length : 'none') + ' first score cell: ' + (a && a.querySelector('.mscore') ? a.querySelector('.mscore').textContent.slice(0, 20) : '')); out.push('mvp sub: ' + (d.getElementById('mvp-sub') ? d.getElementById('mvp-sub').textContent.slice(-90) : '')); });
  step('dpoy card', () => { const a = d.getElementById('dpoy-list'); out.push('dpoy first: ' + (a && a.querySelector('.mname') ? a.querySelector('.mname').textContent + ' ' + a.querySelector('.mscore').textContent.slice(0, 16) : 'none')); });
  step('mip card', () => { const a = d.getElementById('mip-list'); out.push('mip first score: ' + (a && a.querySelector('.mscore') ? a.querySelector('.mscore').textContent.slice(0, 20) : 'none')); });
  step('tracker share view', () => { if (w.NBA_NAV) w.NBA_NAV.show('awards'); const c = d.getElementById('tr-share'); out.push('tracker share toggle present: ' + !!c); if (c){ c.checked = true; fire(c, 'change'); const svg = d.getElementById('tr-svg'); out.push('tracker share svg: ' + (svg ? svg.getAttribute('aria-label') : 'none') + ' | labels with %: ' + Array.from(d.querySelectorAll('#tr-svg .plbl')).filter(t => /%/.test(t.textContent)).length); const chips = d.querySelectorAll('#tr-chips .chip'); chips.forEach(ch => { ch.click(); }); } });
  step('about heatmap', () => { if (w.NBA_NAV) w.NBA_NAV.show('about'); const cells = d.querySelectorAll('.stbl td.h1, .stbl td.h2, .stbl td.h3, .stbl td.h4, .stbl td.h5'); out.push('shaded scorecard cells: ' + cells.length + ' key: ' + !!d.querySelector('.hkey')); });
  step('grindhouse next game', () => { if (w.NBA_NAV) w.NBA_NAV.show('hub'); const nx = d.querySelector('.hubnext'); out.push('next game: ' + (nx ? nx.textContent.replace(/\s+/g, ' ').slice(0, 330) : 'none')); });
  step('projections injuries', () => { if (w.NBA_NAV) w.NBA_NAV.show('outlook'); const inj = d.getElementById('ol-inj'); out.push('injury table rows: ' + (inj ? inj.querySelectorAll('tbody tr').length : 'none') + ' | ' + (inj ? inj.textContent.replace(/\s+/g,' ').slice(0, 200) : '')); const proj = d.getElementById('ol-proj'); out.push('projection cards: ' + (proj ? proj.children.length : 'none')); const how = d.getElementById('ol-how'); out.push('how text mentions back-to-back: ' + /back-to-back/.test(how ? how.textContent : '')); });
  step('game chance pieces', () => { const M = w.NBA_MODEL; const gc = M.gameChance('MEM', 'OKC', '2026-11-06'); out.push('MEM vs OKC tomorrow: p=' + gc.p.toFixed(3) + ' margin=' + gc.margin.toFixed(2) + ' gap=' + gc.gap.toFixed(2) + ' hca=' + gc.hca + ' rest=' + gc.rest + ' availH=' + gc.availH.adj.toFixed(2) + ' (' + gc.availH.items.map(i => i.name + ' ' + i.cost.toFixed(2)).join(', ') + ') availA=' + gc.availA.adj.toFixed(2)); const far = M.gameChance('MEM', 'OKC', '2026-12-20'); out.push('same game Dec 20: availH=' + far.availH.adj.toFixed(2) + ' availA=' + far.availA.adj.toFixed(2)); });
  step('grindhouse x link', () => { if (w.NBA_NAV) w.NBA_NAV.show('hub'); out.push('xfollow: ' + (d.querySelector('.xfollow') ? d.querySelector('.xfollow').textContent.trim().slice(0, 30) : 'none')); });
  console.log(out.join('\n'));
  console.log('\nERRORS: ' + errors.length); errors.slice(0, 12).forEach(e => console.log(' - ' + String(e).split('\n').slice(0, 3).join(' | ')));
  process.exit(errors.length ? 1 : 0);
}, 1500);
