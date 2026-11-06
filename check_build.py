#!/usr/bin/env python3
"""Sanity-checks a built dashboard before it is published. Exits non-zero if something looks wrong."""
import base64, json, re, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'docs/index.html'
html = open(path, encoding='utf-8').read()
def block(i):
    m = re.search(r'<script id="%s" type="application/json">(.*?)</script>' % i, html, re.S)
    assert m, f'missing data block {i}'
    return json.loads(m.group(1))
problems = []
for ph in ('/*DATA*/', '/*LEADERS*/', '/*AWARDS*/'):
    if ph in html: problems.append(f'placeholder {ph} was not replaced')
shot, leaders, awards = block('shot-data'), block('leaders-data'), block('awards-data')
seasons = shot['seasons']
if len(seasons) < 3: problems.append('fewer than three seasons of shot data')
cur = seasons.get(leaders['key'])
if not cur: problems.append('current season missing from the shot data')
else:
    if cur['games'] != leaders['games']: problems.append(f"play-by-play has {cur['games']} games but box scores have {leaders['games']}")
    if cur['asof'] != leaders['asof']: problems.append('play-by-play and box scores end on different dates')
    if leaders['games'] < 1: problems.append('no games played this season yet')
for k, s in seasons.items():
    n = len(base64.b64decode(s['d'])) // 2
    if len(base64.b64decode(s['x'])) // 2 != n: problems.append(f'{k}: shot extras are not aligned with the shots')
    if sum(p[2] + p[3] for p in s['pl']) != n: problems.append(f'{k}: player shot counts do not add up')
    if k != leaders['key'] and n < 150000: problems.append(f'{k}: only {n} shots, which looks incomplete')
for k in leaders['hist']:
    if leaders['hist'][k]['games'] != 1230: problems.append(f'{k}: {leaders["hist"][k]["games"]} games instead of 1230')
tg = leaders.get('tgames', {})
if sorted(tg) != sorted(seasons): problems.append('team game data is missing for some seasons')
for k, t in tg.items():
    n = len(base64.b64decode(t['d'])) // 2 // t['w']
    want = leaders['games'] if k == leaders['key'] else 1230
    if n != want: problems.append(f'{k}: {n} team-game rows instead of {want}')
if not leaders.get('sched'): problems.append('no scores or schedule')
if leaders.get('sched') and any(len(r) != 14 for r in leaders['sched']): problems.append('scores table rows have the wrong shape (nba_build.py and template.html are out of step)')
lc = leaders.get('lcov', {})
if sorted(lc) != sorted(seasons): problems.append('lineup data is missing for some seasons')
for k, (done, total) in lc.items():
    if k != leaders['key'] and total and done < 0.9 * total: problems.append(f'{k}: lineups rebuilt for only {done} of {total} games')
    if k == leaders['key'] and total >= 20 and done < 0.75 * total: problems.append(f'{k}: lineups rebuilt for only {done} of {total} games this season')
gb = leaders.get('gbox') or []
if len(gb) != leaders['games']: problems.append(f'box scores for {len(gb)} games instead of {leaders["games"]}')
elif any((not g[2]) or (not g[3]) or g[1] is None for g in gb): problems.append('some games have no box score or score-flow data')
if not isinstance(leaders.get('remaining'), list): problems.append('the remaining schedule is missing')
if not leaders.get('builtAt'): problems.append('the build time is missing')
best = shot.get('best') or {}
if len(best) < 300: problems.append(f'the best-season map has only {len(best)} players (the Show Best Season checkboxes need it)')
else:
    known = set(seasons) | set((shot.get('archive') or {}).keys())
    stray = [k for k in {v[0] for v in best.values()} if k not in known]
    if stray: problems.append(f'best seasons point at seasons not on the page: {sorted(stray)}')
if len(shot.get('arc') or {}) < 300: problems.append('the career-arc map is missing or nearly empty')
if not (leaders.get('awardfit') or {}).get('mvp', {}).get('tau'): problems.append('awardfit (vote-share temperatures) is missing from the leaders block')
if leaders.get('injuryLogNote'): print('note:', leaders['injuryLogNote'])
gm = leaders.get('gamemodel') or {}
if not all(k in gm for k in ('K', 'PW', 'GAP', 'HCA', 'B2B', 'SIG')) or not gm.get('avail'): problems.append('gamemodel (the fitted win-chance constants) is missing or incomplete in the leaders block')
if not isinstance(leaders.get('injuries'), dict): problems.append('the injury report block is missing (should be a dict, possibly empty)')
for w in leaders.get('warnings') or []:
    if w.startswith('ESPN injury report'): print('note:', w)   # an unreadable injury feed is shown on the About tab but must not block the daily publish
    else: problems.append('WARNING: ' + w)
if leaders.get('roster') is not None and len(leaders['roster'].get('roster', [])) < 13: problems.append('the Grizzlies roster has fewer than 13 players')
sn = leaders.get('snapshots')
if not sn or not sn.get('dates'): problems.append('the award tracker (snapshots) is missing')
elif any(len(v) != len(sn['dates']) for v in sn['awards'].values()): problems.append('the award tracker has a different number of days per award')
if cur:
    if cur.get('gx') and len(base64.b64decode(cur['gx'])) // 2 != len(base64.b64decode(cur['d'])) // 2: problems.append('game tags are not aligned with the shots')
    if len(cur.get('off', {})) < 30: problems.append('team offense shot zones are missing')
if not leaders.get('race', {}).get('dates'): problems.append('no MVP race data')
if len(leaders.get('tcolors', {})) < 30: print('note: team colors are missing for some teams, so the highlighted team will use the default color there')
arch = shot.get('archive') or {}
import os
for k, m in arch.items():
    u = m.get('url', '')
    if not u.startswith('http') and not u.startswith('/'):
        f = os.path.join(os.path.dirname(os.path.abspath(path)), u)
        if not os.path.exists(f): problems.append(f'archived season {k}: file {u} is missing beside the page')
        elif os.path.getsize(f) != m.get('bytes'): problems.append(f'archived season {k}: file size differs from the manifest')
    if m.get('games', 0) < 500: problems.append(f'archived season {k}: only {m.get("games")} games')
size = len(html.encode('utf-8')) / 1e6
if size > 15: problems.append(f'page is {size:.1f} MB; the hosting limit is 16 MB')
print(f'{path}: {size:.2f} MB | seasons {sorted(seasons)} | current season {leaders["key"]}: {leaders["games"]} games through {leaders["asof"]} | {len(leaders["sched"])} schedule rows | lineups rebuilt for {sum(v[0] for v in lc.values())} of {sum(v[1] for v in lc.values())} games | archived seasons: {len(arch)}')
if problems:
    print('PROBLEMS:'); [print(' -', p) for p in problems]; sys.exit(1)
print('OK')
