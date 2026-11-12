// Renders the shot chart with the page's own code in jsdom + @napi-rs/canvas, saves court.png, and fails if any canvas path command carries NaN (which the browser silently skips). npm install jsdom@24 @napi-rs/canvas (once), then node render_test.js docs/index.html
// renders the shot chart with the page's own code (jsdom + a real canvas) and saves a PNG
const { JSDOM, VirtualConsole } = require('jsdom'); const fs = require('fs'); const { createCanvas } = require('@napi-rs/canvas');
const html = fs.readFileSync(process.argv[2], 'utf8'); const vc = new VirtualConsole(); vc.on('jsdomError', e => console.log('jsdomError', e && e.message)); vc.on('warn', ()=>{});
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc, url: 'https://example.test/', beforeParse(window){
  // every <canvas> gets a real drawing surface; drawImage from another <canvas> hands over its backing surface
  const surfaces = new WeakMap();
  function surface(el){ let s = surfaces.get(el); if (!s){ s = createCanvas(el.width || 300, el.height || 150); surfaces.set(el, s); } return s; }
  // resize the surface at the moment the page sets width/height (that is when a canvas is cleared), not later
  ['width', 'height'].forEach(function(prop){ const desc = Object.getOwnPropertyDescriptor(window.HTMLCanvasElement.prototype, prop);
    Object.defineProperty(window.HTMLCanvasElement.prototype, prop, { get(){ return desc.get.call(this); }, set(v){ desc.set.call(this, v); const s = surface(this); s[prop] = v; } }); });
  window.HTMLCanvasElement.prototype.getContext = function(){ const s = surface(this), ctx = s.getContext('2d'); const origDraw = ctx.drawImage.bind(ctx);
    ctx.drawImage = function(img, ...rest){ if (img && img.tagName === 'CANVAS') return origDraw(surface(img), ...rest); return origDraw(img, ...rest); };
    if (this.id === 'court' && !ctx.__logged){ ctx.__logged = true; const log = []; window.__pathlog = log;
      ['beginPath','moveTo','lineTo','arc','stroke','strokeRect','setLineDash','save','restore','setTransform','closePath','fill','ellipse','arcTo','quadraticCurveTo','bezierCurveTo','rect','clip'].forEach(function(m){ const f = ctx[m].bind(ctx); ctx[m] = function(...args){ log.push(m + '(' + args.map(a => typeof a === 'number' ? a.toFixed(1) : JSON.stringify(a)).join(',') + ')'); return f(...args); }; });
    }
    return ctx; };
  window.HTMLCanvasElement.prototype.toPNG = function(){ return surface(this).toBuffer('image/png'); };
  window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} }; window.matchMedia = () => ({ matches: false, addEventListener(){}, addListener(){} });
  window.scrollTo = () => {}; window.fetch = () => Promise.reject(new Error('no network')); window.requestAnimationFrame = (f) => setTimeout(f, 0);
  Object.defineProperty(window.HTMLElement.prototype, 'clientWidth', { get(){ return 540; } });
  // jsdom does not resolve CSS custom properties: hand the page the palette it would read from :root
  const vars = {'--ink':'#1b2430','--muted':'#6b6f76','--court':'#f3efe6','--cline':'#6b7280','--cold':'#3b6fb6','--hot':'#e2673f','--freq':'#7a3b8f','--rule':'#d8d2c6','--head':'sans-serif','--body':'sans-serif','--surface':'#ffffff'};
  const gcs = window.getComputedStyle.bind(window);
  window.getComputedStyle = function(el, ps){ const cs = gcs(el, ps); const orig = cs.getPropertyValue.bind(cs); cs.getPropertyValue = function(n){ return vars[n] !== undefined ? vars[n] : orig(n); }; return cs; };
  window.addEventListener('error', e => console.log('window.error', e.error && e.error.stack || e.message));
}});
const w = dom.window, d = w.document;
setTimeout(() => {
  const cv = d.getElementById('court'); fs.writeFileSync('/home/claude/work/court.png', cv.toPNG()); console.log('saved court.png', cv.width, 'x', cv.height);
  const log = w.__pathlog || []; const bad = log.filter(l => /NaN|Infinity|undefined/.test(l));
  if (bad.length){ console.log('CANVAS PROBLEMS: ' + bad.length + ' path commands with NaN/Infinity, e.g. ' + bad.slice(0, 3).join(' ; ')); process.exit(1); }
  console.log('canvas path commands checked: ' + log.length + ', none with NaN or Infinity');
}, 1500);
