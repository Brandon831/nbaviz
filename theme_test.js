// Checks that the page themes itself from the favorite team: loads a built page in jsdom with different favorites and modes and prints the derived tokens. node theme_test.js docs/index.html (needs jsdom)
const { JSDOM, VirtualConsole } = require('jsdom'); const fs = require('fs'); const html = fs.readFileSync(process.argv[2], 'utf8');
function run(fav, dark){ return new Promise(res => { const vc = new VirtualConsole(); vc.on('jsdomError', ()=>{}); vc.on('warn', ()=>{});
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc, url: 'https://example.test/', beforeParse(window){
    const noop = new Proxy({}, { get: (t, k) => k === 'canvas' ? {} : (k === 'measureText' ? () => ({width: 10}) : (k === 'createImageData' ? (w, h) => ({data: new Uint8ClampedArray(w*h*4)}) : (k === 'getImageData' ? (x,y,w,h) => ({data: new Uint8ClampedArray(w*h*4)}) : () => noop))), set: () => true });
    window.HTMLCanvasElement.prototype.getContext = function(){ return noop; }; window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} }; window.matchMedia = (q) => ({ matches: dark && /dark/.test(q), addEventListener(){}, addListener(){} }); window.scrollTo = () => {}; window.fetch = () => Promise.reject(new Error('no network')); window.requestAnimationFrame = (f) => setTimeout(f, 0);
    if (fav) window.localStorage.setItem('nba-fav', fav);
  }});
  setTimeout(() => { const st = dom.window.document.documentElement.style; res({fav: dom.window.NBA_FAV, mast: st.getPropertyValue('--mast'), accent: st.getPropertyValue('--gold'), bg: st.getPropertyValue('--bg'), ink: st.getPropertyValue('--ink'), chartInk: dom.window.NBA_APP ? 'read' : 'none'}); }, 900); }); }
(async () => { for (const [f, d] of [[null, false], ['LAL', false], ['BOS', true], ['CHI', false]]) console.log(JSON.stringify(await run(f, d))); })();
