#!/usr/bin/env python3
"""Checks that the page's JavaScript award ladders and awards_models.py agree, on a built page.

    python check_models.py docs/index.html

Runs the page's own JavaScript for the Defensive Player ladder (ballot model), the All-Defensive teams and the MVP ladder in node, on
the data blocks embedded in the page, and compares them with awards_models.Models on the same blocks, for every embedded season.
Needs node. Exits non-zero on any disagreement."""
import json, os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import awards_models
path = sys.argv[1] if len(sys.argv) > 1 else 'docs/index.html'
html = open(path, encoding='utf-8').read()
def block(i): return json.loads(re.search(r'<script id="%s" type="application/json">(.*?)</script>' % i, html, re.S).group(1))
shot, leaders, awards = block('shot-data'), block('leaders-data'), block('awards-data')
# the awards section of the page script, from the model constants to the All-Defensive teams
start = html.index('var AWF = L.awardfit'); end = html.index('function clutchFor(key, blend)', start)   # through royFor and smoyFor; clutch needs data the page loads elsewhere
js = html[start:end]
assert 'function dscore' in js and 'function allDefFor' in js and 'function mvpFor' in js, 'could not find the award functions in the page'
F = awards_models.F
stub = r'''
var window = {NBA_STANDINGS: {}, NBA_AVG_PID: 99999999};
var L = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8')), AWD = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8')), STAND = JSON.parse(require('fs').readFileSync(process.argv[4], 'utf8'));
var F = %s;
function objs(rows){ return rows.map(function(a){ var o = {}; F.forEach(function(f, i){ o[f] = a[i]; }); return o; }); }
var SD = {}; SD[L.key] = {players: objs(L.players), tg: L.tg, maxg: L.maxg};
Object.keys(L.hist || {}).forEach(function(k){ var s = L.hist[k]; SD[k] = {players: objs(s.players), tg: s.tg, maxg: s.maxg}; });
Object.keys(STAND).forEach(function(k){ window.NBA_STANDINGS[k] = STAND[k]; });
var document = {getElementById: function(){ return {textContent: '{}'}; }};
var SEAS_KEYS = Object.keys(SD).sort(), CUR = L.key;
''' % json.dumps(F)
tail = r'''
var out = {};
Object.keys(SD).sort().forEach(function(k){
  var mv = mvpFor(k, true), dp = dpoyFor(k, false), ry = royFor(k, true), sm = smoyFor(k, true);
  out[k] = {dpoy: dp.map(function(r){ return [r.p.pid, r.score]; }), alldef: allDefFor(k, false).map(function(r){ return r.p.pid; }),
            mvp: mv.map(function(r){ return [r.p.pid, r.score]; }), dpoy_blend: dpoyFor(k, true).map(function(r){ return [r.p.pid, r.score]; }),
            roy: ry.map(function(r){ return [r.p.pid, r.score]; }), smoy: sm.map(function(r){ return [r.p.pid, r.score]; }),
            shares: {mvp: voteShares(mv, 'mvp'), dpoy: voteShares(dp, 'dpoy'), roy: voteShares(ry, 'roy'), smoy: voteShares(sm, 'smoy')}};
});
process.stdout.write(JSON.stringify(out));
'''
with tempfile.TemporaryDirectory() as td:
    for name, obj in (('L.json', leaders), ('AWD.json', awards), ('STAND.json', {k: v['stand'] for k, v in shot['seasons'].items()})): json.dump(obj, open(os.path.join(td, name), 'w'))
    open(os.path.join(td, 'run.js'), 'w').write(stub + js + tail)
    r = subprocess.run(['node', os.path.join(td, 'run.js'), os.path.join(td, 'L.json'), os.path.join(td, 'AWD.json'), os.path.join(td, 'STAND.json')], capture_output=True, text=True)
    if r.returncode: sys.exit('node failed:\n' + r.stderr[-3000:])
    jsout = json.loads(r.stdout)
M = awards_models.Models(shot, leaders, {}, awards, json.load(open(os.path.join(HERE, 'static', 'defmodel.json'))))
problems = []; n = 0
for k in sorted(jsout):
    mv, dp, ry, sm = M.mvp(k, True), M.dpoy(k, False), M.roy(k), M.smoy(k, True)
    py = {'dpoy': [[r['p']['pid'], r['score']] for r in dp], 'alldef': [r['p']['pid'] for r in M.alldef(k, False)],
          'mvp': [[r['p']['pid'], r['score']] for r in mv], 'dpoy_blend': [[r['p']['pid'], r['score']] for r in M.dpoy(k, True)],
          'roy': [[r['p']['pid'], r['score']] for r in ry], 'smoy': [[r['p']['pid'], r['score']] for r in sm]}
    for aw, lst in (('mvp', mv), ('dpoy', dp), ('roy', ry), ('smoy', sm)):
        a, b = jsout[k]['shares'][aw], M.shares(lst, aw)
        if (a is None) != (b is None) or (a and b and (len(a) != len(b) or max(abs(x - y) for x, y in zip(a, b)) > 1e-9)): problems.append(f'{k} {aw} vote shares differ between the page and python')
        n += 1
    for what in py:
        a, b = jsout[k][what], py[what]
        if what == 'alldef':
            if a != b: problems.append(f'{k} {what}: page {a} vs python {b}')
        else:
            if [x[0] for x in a] != [x[0] for x in b]: problems.append(f'{k} {what}: different order (page top 5 {[x[0] for x in a[:5]]} vs python {[x[0] for x in b[:5]]})')
            else:
                d = max((abs(x[1] - y[1]) for x, y in zip(a, b)), default=0)
                if d > 1e-6: problems.append(f'{k} {what}: scores differ by up to {d:.2e}')
        n += 1
    # the page's DEFM constant must equal static/defmodel.json's ballot weights
m = re.search(r'var DEFM = (\{.*?\}), DEFM_RECENT = (\{.*?\}), DEFM_STATS = (\{.*?\}), DEFM_RIM = (\{.*?\}),', html, re.S)
page = [json.loads(m.group(i)) for i in (1, 2, 3, 4)]; ref = M.DEF
for name, a, b in (('DEFM', page[0], {c: ref[c] for c in ('cols', 'mu', 'sd', 'w')}), ('DEFM_RECENT', page[1], {c: ref['recent'][c] for c in ('cols', 'mu', 'sd', 'w', 'from')}),
                   ('DEFM_STATS', page[2], ref['stats']), ('DEFM_RIM', page[3], {c: ref['stats_rim'][c] for c in ('cols', 'mu', 'sd', 'w')})):
    if a != b: problems.append(f'{name} in the page differs from static/defmodel.json')
# the fitted constants the page reads from the leaders block must be the ones in static/awardfit.json
af = json.load(open(os.path.join(HERE, 'static', 'awardfit.json')))
if (leaders.get('awardfit') or {}) != af: problems.append('awardfit in the page differs from static/awardfit.json')
gm = json.load(open(os.path.join(HERE, 'static', 'gamemodel.json')))
if (leaders.get('gamemodel') or {}) != gm: problems.append('gamemodel in the page differs from static/gamemodel.json')
print(f'{path}: {n} ladders compared over {len(jsout)} seasons; page constants DEFM/DEFM_RECENT/DEFM_STATS/DEFM_RIM checked against static/defmodel.json, awardfit against static/awardfit.json')
if problems: print('PROBLEMS:'); [print(' -', p) for p in problems]; sys.exit(1)
print('OK: the page\'s JavaScript and awards_models.py agree')
