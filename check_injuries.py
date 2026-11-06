"""Checks the logged injury reports against who actually dressed, and measures the status weights the page uses.

    python check_injuries.py            # report
    python check_injuries.py --write    # also store the measured weights in static/gamemodel.json (avail.status), which the page reads

The daily build saves ESPN's injury report to logs/injuries/<date>.json. For every listing, this script finds the player's team's next
game on or after that date (within three days) in the current season's box scores and checks whether he recorded minutes. The share
of listed players who did not play, by status, is exactly the weight the page should give that status; the script also checks the
return dates ESPN gives (did the player play before it?) and how far ahead an "Out" listing still holds (the fade). Run it once the log
covers about 60 days; the build prints a reminder when it does."""
import argparse, glob, json, os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', default='raw'); ap.add_argument('--write', action='store_true'); ap.add_argument('--window', type=int, default=3, help='days after the report in which the next game must fall')
    a = ap.parse_args()
    import nba_build
    files = sorted(glob.glob(os.path.join(HERE, 'logs', 'injuries', '*.json')))
    if not files: sys.exit('no logged reports in logs/injuries/ yet (the daily build writes one per day)')
    box = pd.read_parquet(nba_build.fetch(a.raw, 'box', nba_build.CURRENT), columns=['game_id', 'game_date', 'team_abbreviation', 'athlete_id', 'minutes', 'did_not_play', 'season_type'])
    box = box[box.season_type == 2].copy(); box['game_date'] = pd.to_datetime(box.game_date)
    games = box.drop_duplicates(['game_id', 'team_abbreviation'])[['game_id', 'game_date', 'team_abbreviation']]
    played = set(zip(box[(box.did_not_play == False) & (box.minutes > 0)].game_id, box[(box.did_not_play == False) & (box.minutes > 0)].athlete_id))
    rows = []
    for f in files:
        rep = json.load(open(f)); day = pd.Timestamp(rep['date'])
        for team, lst in rep['report'].items():
            nxt = games[(games.team_abbreviation == team) & (games.game_date >= day) & (games.game_date <= day + pd.Timedelta(days=a.window))].sort_values('game_date')
            if nxt.empty: continue
            g = nxt.iloc[0]
            for pid, name, status, detail, ret in lst:
                st = status.lower(); cat = 'out' if 'out' in st else 'doubtful' if 'doubtful' in st else 'questionable' if ('questionable' in st or 'day' in st or 'gtd' in st) else 'probable' if 'probable' in st else 'other'
                rows.append({'date': rep['date'], 'team': team, 'pid': pid, 'name': name, 'status': status, 'cat': cat, 'ret': ret, 'game_date': g.game_date, 'gap': (g.game_date - day).days, 'played': (g.game_id, pid) in played})
    d = pd.DataFrame(rows)
    if d.empty: sys.exit('no listings could be matched to a next game yet')
    print(f'{len(files)} daily reports, {len(d)} listings matched to a next game within {a.window} days, {d.date.nunique()} report days from {d.date.min()} to {d.date.max()}')
    print(f"\n{'status':14s} {'listings':>8s} {'did not play':>12s} {'page weight':>11s}")
    page = {'out': 1.0, 'doubtful': 0.8, 'questionable': 0.5, 'probable': 0.15, 'other': 0.5}
    gm = json.load(open(os.path.join(HERE, 'static', 'gamemodel.json'))); cur = (gm.get('avail') or {}).get('status') or page
    weights = {}
    for cat, grp in d.groupby('cat'):
        miss = 1 - grp.played.mean(); weights[cat] = round(float(miss), 3)
        print(f'{cat:14s} {len(grp):>8d} {100*miss:>11.0f}% {cur.get(cat, page.get(cat, 0.5)):>11.2f}')
    # "Out" listings further ahead: how often does an Out player still sit out the team's game 4-7 and 8-14 days later?
    print('\nhow long an "Out" listing holds (share who still did not play in the team\u2019s games this many days after the report):')
    out = d[d.cat == 'out']
    for lo, hi in ((0, 3), (4, 7), (8, 14), (15, 21)):
        hits = []
        for _, r in out.iterrows():
            later = games[(games.team_abbreviation == r.team) & (games.game_date >= pd.Timestamp(r.date) + pd.Timedelta(days=lo)) & (games.game_date <= pd.Timestamp(r.date) + pd.Timedelta(days=hi))]
            for _, g in later.iterrows(): hits.append((g.game_id, r.pid) not in played)
        if hits: print(f'  days {lo:>2d}-{hi:<2d}: {100*sum(hits)/len(hits):.0f}% still out ({len(hits)} player-games)')
    wr = d[(d.cat == 'out') & (d.ret != '')]
    if len(wr):
        early = 0; tot = 0
        for _, r in wr.iterrows():
            before = games[(games.team_abbreviation == r.team) & (games.game_date >= pd.Timestamp(r.date)) & (games.game_date < pd.Timestamp(r.ret))]
            tot += 1; early += int(any((g.game_id, r.pid) in played for _, g in before.iterrows()))
        print(f'\nreturn dates: {tot} Out listings carried one; {early} of them ({100*early/max(tot,1):.0f}%) played before it')
    if a.write:
        gm.setdefault('avail', {})['status'] = {k: weights[k] for k in weights if k in ('out', 'doubtful', 'questionable', 'probable')}; gm['avail']['status_checked'] = d.date.max()
        gm['avail']['status_note'] = f'measured by check_injuries.py on {len(d)} listings from {d.date.min()} to {d.date.max()}'
        json.dump(gm, open(os.path.join(HERE, 'static', 'gamemodel.json'), 'w'), indent=1); print('\nwrote the measured status weights into static/gamemodel.json (avail.status); rebuild to put them on the page')

if __name__ == '__main__': main()
