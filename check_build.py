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
if not leaders.get('sched'): problems.append('no scores or schedule')
if not leaders.get('race', {}).get('dates'): problems.append('no MVP race data')
size = len(html.encode('utf-8')) / 1e6
if size > 15: problems.append(f'page is {size:.1f} MB; the hosting limit is 16 MB')
print(f'{path}: {size:.2f} MB | seasons {sorted(seasons)} | current season {leaders["key"]}: {leaders["games"]} games through {leaders["asof"]} | {len(leaders["sched"])} schedule rows')
if problems:
    print('PROBLEMS:'); [print(' -', p) for p in problems]; sys.exit(1)
print('OK')
