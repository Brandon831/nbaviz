#!/usr/bin/env python3
"""
Builds the NBA dashboard (one self-contained HTML file) from public ESPN data published by sportsdataverse.

    python nba_build.py --raw raw --out docs/index.html

Raw files are downloaded into --raw the first time and re-downloaded for the current season on every run.
Static inputs live in ./static (awards.json, defmodel.json, roster.json); the page layout lives in template.html.
"""
import argparse, base64, datetime as dt, json, math, os, sys, urllib.request
from fractions import Fraction
import numpy as np, pandas as pd, pyarrow.parquet as pq

# ----------------------------------------------------------------------------- configuration
SEASONS = [2023, 2024, 2025, 2026, 2027]          # season = year the season ends (2027 = 2026-27)
CURRENT = 2027
RELEASES = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download'
HERE = os.path.dirname(os.path.abspath(__file__))
DIVS = {'Atlantic':['BOS','BKN','NY','PHI','TOR'],'Central':['CHI','CLE','DET','IND','MIL'],'Southeast':['ATL','CHA','MIA','ORL','WSH'],
        'Northwest':['DEN','MIN','OKC','POR','UTAH'],'Pacific':['GS','LAC','LAL','PHX','SAC'],'Southwest':['DAL','HOU','MEM','NO','SA']}
TEAM_DIV = {t: dv for dv, ts in DIVS.items() for t in ts}
CONF_OF = {dv: ('East' if dv in ('Atlantic','Central','Southeast') else 'West') for dv in DIVS}
STD = set(TEAM_DIV)
COLS = ['minutes','points','field_goals_made','field_goals_attempted','three_point_field_goals_made','three_point_field_goals_attempted',
        'free_throws_made','free_throws_attempted','offensive_rebounds','defensive_rebounds','rebounds','assists','steals','blocks','turnovers','fouls']
CV = 5.25 + math.sqrt(23.75**2 - 22**2)

def fetch(raw, kind, y, refresh=False):
    name = {'pbp': f'play_by_play_{y}.parquet', 'box': f'player_box_{y}.parquet', 'sched': f'nba_schedule_{y}.parquet'}[kind]
    tag = {'pbp': 'espn_nba_pbp', 'box': 'espn_nba_player_boxscores', 'sched': 'espn_nba_schedules'}[kind]
    local = os.path.join(raw, f'{kind}{y}.parquet')
    if refresh or not os.path.exists(local):
        os.makedirs(raw, exist_ok=True)
        url = f'{RELEASES}/{tag}/{name}'
        print('downloading', url, file=sys.stderr)
        urllib.request.urlretrieve(url, local + '.tmp'); os.replace(local + '.tmp', local)
    return local

# ----------------------------------------------------------------------------- zones (must match template.html exactly)
def zone_geo(u, v):
    d = math.hypot(u, v - 5.25)
    if d <= 4 and v >= 4: return 0
    if abs(u) <= 8 and v <= 19: return 1
    phi = math.atan2(max(v - 5.25, 0), u) * 180 / math.pi
    if abs(u) >= 22 and v <= CV: return 12 if u > 0 else 13
    w = 0 if phi < 48 else 1 if phi < 76 else 2 if phi < 104 else 3 if phi < 132 else 4
    return (7 if d >= 23.75 else 2) + w
def zone_shot(u, v, three):
    z = zone_geo(u, v)
    if three and 2 <= z <= 6:
        z = (12 if u > 0 else 13) if (v <= CV + 2 and abs(u) >= 18) else z + 5
    elif (not three) and z >= 7:
        z = 2 if z == 12 else 6 if z == 13 else z - 5
    return z
def build_lut():
    L = np.zeros((2, 101, 95), dtype=np.uint8)
    for t in range(2):
        for cx in range(101):
            for cy in range(95):
                L[t, cx, cy] = zone_shot(cx / 2 - 25, cy / 2, bool(t))
    return L
LUT = build_lut()

def shot_type(t):
    """ESPN shot description -> 0 other, 1 jump shot, 2 pull-up/step-back/fadeaway, 3 floater/hook, 4 layup, 5 dunk, 6 tip"""
    t = (t or '').lower()
    if 'dunk' in t: return 5
    if 'tip' in t: return 6
    if 'layup' in t or 'finger roll' in t: return 4
    if 'hook' in t or 'floating' in t or 'floater' in t: return 3
    if 'pullup' in t or 'step back' in t or 'fade away' in t or 'turnaround' in t: return 2
    if 'jump' in t or 'bank' in t: return 1
    return 0

def three_flag(df):
    x = df.coordinate_x.values.astype(float); yv = df.coordinate_y.values.astype(float)
    sg = np.where(x < 0, -1, 1); u = yv * sg; v = 47 - np.abs(x); dist = np.hypot(u, v - 5.25)
    geo = (((np.abs(u) >= 22) & (v <= CV)) | (dist >= 23.75)) & ~np.isnan(x) & ~np.isnan(yv)
    txt = df.text.str.contains('three point', case=False, na=False).values
    made3 = (df.scoring_play.astype(bool).values & (df.score_value == 3).values) if 'score_value' in df.columns else False
    fb = geo | txt | made3
    if 'points_attempted' in df.columns:
        pa = df.points_attempted.values.astype(float)
        return np.where(~np.isnan(pa), pa == 3, fb)
    return fb

def rank_list(items, mn):
    q = [(p, m, a, Fraction(m, a)) for p, m, a in items if m >= mn and a > 0]
    out = []
    for p, m, a, f in q:
        r = 1 + sum(1 for z in q if z[3] > f)
        if r <= 5: out.append([int(p), r, int(m), int(a)])
    return sorted(out, key=lambda z: (z[1], -z[2]))

def cup_game_id(raw, y):
    """The NBA Cup championship game is not part of the official regular season; the schedule labels it explicitly."""
    try:
        s = pd.read_parquet(fetch(raw, 'sched', y), columns=['id', 'notes_headline'])
        r = s[s.notes_headline.fillna('').str.contains('Cup Championship|In-Season Tournament Championship')]
        return int(r.id.iloc[0]) if len(r) else None
    except Exception as e:
        print('cup lookup failed for', y, e, file=sys.stderr); return None

# ----------------------------------------------------------------------------- shots, standings, badges data (one season)
def build_season(raw, y, names, cup_id):
    path = fetch(raw, 'pbp', y)
    have = set(pq.read_schema(path).names)
    cols = ['home_team_name','away_team_name','home_score','away_score','game_id','game_date','season_type','type_text','text','shooting_play','coordinate_x','coordinate_y',
            'athlete_id_1','athlete_id_2','athlete_id_3','athlete_name_1','scoring_play','team_id','home_team_id','home_team_abbrev','away_team_id','away_team_abbrev']
    cols += [c for c in ('points_attempted', 'score_value') if c in have]
    d = pd.read_parquet(path, columns=cols)
    gm = d.drop_duplicates('game_id')
    badg = set(gm[~(gm.home_team_abbrev.isin(STD) & gm.away_team_abbrev.isin(STD))].game_id)      # All-Star and exhibition games
    d = d[~d.game_id.isin(badg)]
    cup = None; cupP = set()
    if cup_id is not None and (d.game_id == cup_id).any():
        cd = d[d.game_id == cup_id]
        for c in ('athlete_id_1', 'athlete_id_2', 'athlete_id_3'): cupP |= set(cd[c].dropna().astype(int))
        hn, an = cd.home_team_abbrev.iloc[0], cd.away_team_abbrev.iloc[0]
        hs, as_ = int(cd.home_score.max()), int(cd.away_score.max())
        cup = {'date': str(cd.game_date.iloc[0]), 'text': (f'{hn} {hs}, {an} {as_}' if hs > as_ else f'{an} {as_}, {hn} {hs}')}
        d = d[d.game_id != cup_id]
    games = int(d.game_id.nunique()); asof = str(d.game_date.max())
    dates = sorted(str(x) for x in d.game_date.unique()); didx = {x: i for i, x in enumerate(dates)}
    assert len(dates) <= 255, 'more than 255 game dates in a season'
    # standings
    gg = d.groupby('game_id').agg(st=('season_type', 'first'), h=('home_team_abbrev', 'first'), a=('away_team_abbrev', 'first'),
                                  hs=('home_score', 'max'), as_=('away_score', 'max')).reset_index()
    gg = gg[gg.st == 2]
    rec = {t: [0, 0] for t in TEAM_DIV}
    for r_ in gg.itertuples():
        hw = r_.hs > r_.as_
        rec[r_.h][0 if hw else 1] += 1; rec[r_.a][1 if hw else 0] += 1
    pf = lambda t: (Fraction(rec[t][0], sum(rec[t])) if sum(rec[t]) else Fraction(-1))
    stand = {t: {'w': rec[t][0], 'l': rec[t][1], 'div': TEAM_DIV[t], 'conf': CONF_OF[TEAM_DIV[t]], 'd1': 0, 'dt': 0, 'c1': 0, 'ct': 0} for t in TEAM_DIV}
    for dv, ts in DIVS.items():
        best = max(pf(t) for t in ts); top = [t for t in ts if pf(t) == best]
        for t in top: stand[t]['d1'] = 1; stand[t]['dt'] = int(len(top) > 1)
    for cf in ('East', 'West'):
        ts = [t for t in TEAM_DIV if CONF_OF[TEAM_DIV[t]] == cf]
        best = max(pf(t) for t in ts); top = [t for t in ts if pf(t) == best]
        for t in top: stand[t]['c1'] = 1; stand[t]['ct'] = int(len(top) > 1)
    maxg = max(sum(v) for v in rec.values())
    r2 = d[(d.season_type == 2) & (d.shooting_play == True) & (~d.type_text.str.contains('Free Throw', na=False))].dropna(subset=['athlete_id_1']).copy()
    r2['three'] = three_flag(r2); r2['pid'] = r2.athlete_id_1.astype(int); r2['made'] = r2.scoring_play.astype(int)
    a1 = r2.groupby('pid').agg(fga=('made', 'size'), fgm=('made', 'sum'), tpa=('three', 'sum'))
    a1['tpm'] = r2[r2.three].groupby('pid').made.sum().reindex(a1.index).fillna(0).astype(int)
    scale = min(1, maxg / 82); minfg = max(1, int(np.ceil(300 * scale))); mintp = max(1, int(np.ceil(82 * scale)))
    lead = {'maxg': int(maxg), 'minfg': minfg, 'mintp': mintp,
            'fg': rank_list([(p, r.fgm, r.fga) for p, r in a1.iterrows()], minfg), 'tp': rank_list([(p, r.tpm, r.tpa) for p, r in a1.iterrows()], mintp)}
    tm = {}
    for a, b in (('home_team_id', 'home_team_abbrev'), ('away_team_id', 'away_team_abbrev')):
        for i, n in d[[a, b]].drop_duplicates().itertuples(index=False): tm[i] = n
    ap = pd.concat([d[['game_id', 'season_type', c]].rename(columns={c: 'p'}) for c in ('athlete_id_1', 'athlete_id_2', 'athlete_id_3')]).dropna(subset=['p'])
    ap['p'] = ap.p.astype(int); ap['po'] = (ap.season_type == 3).astype(int)
    gp = ap.drop_duplicates(['game_id', 'p']).groupby(['p', 'po']).size().to_dict()
    s = d[(d.shooting_play == True) & (~d.type_text.str.contains('Free Throw', na=False))].dropna(subset=['coordinate_x', 'coordinate_y', 'athlete_id_1', 'athlete_name_1']).copy()
    sgn = np.where(s.coordinate_x < 0, -1, 1)
    u = s.coordinate_y.values * sgn; v = 47 - np.abs(s.coordinate_x.values)
    dist = np.hypot(u, v - 5.25); keep = dist <= 40
    s = s[keep]; u = u[keep]; v = v[keep]
    cx = np.clip(np.round((u + 25) * 2), 0, 100).astype(np.int64); cy = np.clip(np.round(v * 2), 0, 94).astype(np.int64)
    made = s.scoring_play.astype(int).values; three = three_flag(s).astype(int)
    val = (((made * 2 + three) * 101 + cx) * 95 + cy).astype(np.uint16)
    po = (s.season_type.values == 3).astype(int)
    # per-shot extras (same order as the shot array). Bits 0-7 date index, 8 home, 9 assisted, 10-12 shot type, 13 driving
    home = (s.team_id.values == s.home_team_id.values).astype(np.int64)
    asst = (s.scoring_play.astype(bool).values & s.athlete_id_2.notna().values).astype(np.int64)
    sty = np.array([shot_type(t) for t in s.type_text.values], dtype=np.int64)
    di = np.array([didx[str(x)] for x in s.game_date.values], dtype=np.int64)
    # a "driving" label (driving layup, dunk, floater...) means the shot came off the dribble
    drv = np.array([('driving' in (t or '').lower()) for t in s.type_text.values], dtype=np.int64)
    ex = (di | (home << 8) | (asst << 9) | (sty << 10) | (drv << 13)).astype(np.uint16)
    zone = LUT[three, cx, cy]
    # opponent shooting by zone (the defending team is the one that did not take the shot)
    defender = np.where(home == 1, s.away_team_abbrev.values, s.home_team_abbrev.values)
    opp = {}
    for t in TEAM_DIV:
        m = (defender == t)
        opp[t] = {'reg': [np.bincount(zone[m & (po == 0)], minlength=14).tolist(), np.bincount(zone[m & (po == 0) & (made == 1)], minlength=14).tolist()],
                  'po':  [np.bincount(zone[m & (po == 1)], minlength=14).tolist(), np.bincount(zone[m & (po == 1) & (made == 1)], minlength=14).tolist()]}
    s = s.assign(val=val, ex=ex, po=po, pid=s.athlete_id_1.astype(int))
    for pid, nm in s[['pid', 'athlete_name_1']].drop_duplicates('pid').itertuples(index=False): names[int(pid)] = nm
    team = s.groupby('pid').team_id.agg(lambda x: x.value_counts().index[0]).map(tm)
    pl = []; chunks = []; xchunks = []
    for pid, g in s.groupby('pid', sort=True):
        m0 = g.po.values == 0; m1 = g.po.values == 1
        r = g.val.values[m0]; p = g.val.values[m1]
        pl.append([int(pid), str(team[pid]), int(len(r)), int(len(p)), int(gp.get((int(pid), 0), 0)), int(gp.get((int(pid), 1), 0)), 1 if int(pid) in cupP else 0])
        chunks += [r, p]; xchunks += [g.ex.values[m0], g.ex.values[m1]]
    arr = np.concatenate(chunks).astype('<u2'); xarr = np.concatenate(xchunks).astype('<u2')
    assert len(arr) == len(xarr)
    return {'stand': stand, 'lead': lead, 'cup': cup, 'games': games, 'asof': asof, 'label': f'{y-1}-{str(y)[2:]}', 'pl': pl,
            'd': base64.b64encode(arr.tobytes()).decode(), 'x': base64.b64encode(xarr.tobytes()).decode(), 'dates': dates, 'opp': opp}

# ----------------------------------------------------------------------------- box scores: player totals, team ratings, clutch time
def box_games(raw, y, cup_id):
    d = pd.read_parquet(fetch(raw, 'box', y)); d = d[d.season_type == 2]
    d = d[d.team_abbreviation.isin(STD) & d.opponent_team_abbreviation.isin(STD)]
    if cup_id is not None: d = d[d.game_id != cup_id]
    return d

def box_players(raw, y, cup_id):
    d = box_games(raw, y, cup_id)
    games = int(d.game_id.nunique()); asof = str(d.game_date.max())
    tg = {k: int(v) for k, v in d.groupby('team_abbreviation').game_id.nunique().items()}
    act = d[(d.did_not_play == False) & d.minutes.notna()].sort_values(['game_date', 'game_date_time'])
    g = act.groupby('athlete_id')
    a = g[COLS].sum().astype(float); a['gp'] = g.game_id.nunique()
    a['gst'] = act[act.starter == True].groupby('athlete_id').game_id.nunique().reindex(a.index).fillna(0).astype(int)
    last = g.tail(1).set_index('athlete_id'); a['name'] = last.athlete_display_name; a['team'] = last.team_abbreviation
    players = [[int(pid), r['name'], r['team'], int(r['gp'])] + [round(float(r[c]), 1) if c == 'minutes' else int(r[c]) for c in COLS] + [int(r['gst'])] for pid, r in a.iterrows()]
    return {'asof': asof, 'games': games, 'maxg': int(max(tg.values())), 'tg': tg, 'players': players}, d

def team_ratings(d):
    act = d[(d.did_not_play == False) & d.minutes.notna()]
    t = act.groupby(['game_id', 'team_abbreviation']).agg(pts=('points', 'sum'), fga=('field_goals_attempted', 'sum'), fta=('free_throws_attempted', 'sum'),
        oreb=('offensive_rebounds', 'sum'), tov=('turnovers', 'sum'), opp=('opponent_team_abbreviation', 'first'), opts=('opponent_team_score', 'first')).reset_index()
    t['poss'] = t.fga + 0.44 * t.fta - t.oreb + t.tov
    j = t.merge(t[['game_id', 'team_abbreviation', 'poss']].rename(columns={'team_abbreviation': 'opp', 'poss': 'oposs'}), on=['game_id', 'opp'])
    g = j.groupby('team_abbreviation').agg(pts=('pts', 'sum'), opts=('opts', 'sum'), poss=('poss', 'sum'), oposs=('oposs', 'sum'), n=('game_id', 'nunique'))
    g['ortg'] = 100 * g.pts / g.poss; g['drtg'] = 100 * g.opts / g.oposs
    return {t_: [round(float(r.drtg), 3), round(float(r.ortg), 3), int(r.n)] for t_, r in g.iterrows()}

def clutch_rows(raw, y, cup_id):
    """Clutch time = last five minutes of the fourth quarter or overtime with the score within five points (before the play)."""
    cols = ['game_id','sequence_number','period_number','clock_minutes','clock_seconds','home_score','away_score','scoring_play','score_value','shooting_play','type_text',
            'athlete_id_1','athlete_id_2','season_type','home_team_abbrev','away_team_abbrev']
    d = pd.read_parquet(fetch(raw, 'pbp', y), columns=cols)
    gm = d.drop_duplicates('game_id'); bad = set(gm[~(gm.home_team_abbrev.isin(STD) & gm.away_team_abbrev.isin(STD))].game_id)
    d = d[~d.game_id.isin(bad) & (d.season_type == 2)]
    if cup_id is not None: d = d[d.game_id != cup_id]
    d = d.assign(seq=d.sequence_number.astype(float)).sort_values(['game_id', 'seq'])
    d['hs0'] = d.groupby('game_id').home_score.shift(1).fillna(0); d['as0'] = d.groupby('game_id').away_score.shift(1).fillna(0)
    d['sec'] = d.clock_minutes * 60 + d.clock_seconds
    c = d[(d.period_number >= 4) & (d.sec <= 300) & ((d.hs0 - d.as0).abs() <= 5)].copy()
    ft = c.type_text.fillna('').str.startswith('Free Throw'); shot = c.shooting_play.fillna(False).astype(bool); sc = c.scoring_play.fillna(False).astype(bool)
    out = pd.DataFrame(index=pd.Index(sorted(c.athlete_id_1.dropna().astype(int).unique()), name='pid'))
    def add(name, mask, col='athlete_id_1', val=None):
        sub = c[mask & c[col].notna()]; s = (sub[val] if val is not None else pd.Series(1, index=sub.index)).groupby(sub[col].astype(int)).sum()
        out[name] = s.reindex(out.index).fillna(0)
    add('pts', sc, val='score_value'); add('fga', shot & ~ft); add('fgm', shot & ~ft & sc); add('fta', shot & ft); add('ftm', shot & ft & sc)
    add('ast', sc & ~ft, col='athlete_id_2')
    add('tov', c.type_text.fillna('').str.contains('Turnover|Traveling|Offensive Foul$', regex=True))
    ev = pd.concat([c[['game_id', 'athlete_id_1']].rename(columns={'athlete_id_1': 'p'}), c[c.athlete_id_2.notna() & sc & ~ft][['game_id', 'athlete_id_2']].rename(columns={'athlete_id_2': 'p'})]).dropna()
    ev['p'] = ev.p.astype(int); out['games'] = ev.drop_duplicates(['game_id', 'p']).groupby('p').size().reindex(out.index).fillna(0)
    return [[int(pid), int(r.pts), int(r.fgm), int(r.fga), int(r.ftm), int(r.fta), int(r.ast), int(r.tov), int(r.games)] for pid, r in out.astype(float).iterrows()]

# ----------------------------------------------------------------------------- MVP race: the MVP ladder re-run after every game date this season
GS_FIELDS = ['points','field_goals_made','field_goals_attempted','free_throws_made','free_throws_attempted','offensive_rebounds','defensive_rebounds','steals','assists','blocks','fouls','turnovers']
def game_score_total(r):
    return (r['points'] + 0.4*r['field_goals_made'] - 0.7*r['field_goals_attempted'] - 0.4*(r['free_throws_attempted'] - r['free_throws_made'])
            + 0.7*r['offensive_rebounds'] + 0.3*r['defensive_rebounds'] + r['steals'] + 0.7*r['assists'] + 0.7*r['blocks'] - 0.4*r['fouls'] - r['turnovers'])

def mvp_race(d, hist_players, hist_stand, top_n=8):
    """d = this season's box games. hist_players = {season_key: players list} for the finished seasons, oldest first; hist_stand = {season_key: stand}.
       Same model as the page: Game Score per game blended with the last three seasons (weights 5/3/2, this season counts gp/(gp+10)), plus a team-success bonus."""
    keys = sorted(hist_players)[-3:][::-1]          # most recent first
    HW = [5, 3, 2]; prior = {}
    for j, k in enumerate(keys):
        for p in hist_players[k]:
            gp = p[3]
            if gp >= 1:
                gsv = (p[5] + 0.4*p[6] - 0.7*p[7] - 0.4*(p[11] - p[10]) + 0.7*p[12] + 0.3*p[13] + p[16] + 0.7*p[15] + 0.7*p[17] - 0.4*p[19] - p[18]) / gp
                prior.setdefault(p[0], []).append((HW[j] * min(gp, 60) / 60, gsv))
    pri = {pid: sum(w * v for w, v in h) / sum(w for w, _ in h) for pid, h in prior.items()}
    q = {}
    if keys:
        for t, s in hist_stand[keys[0]].items():
            q[t] = s['w'] / (s['w'] + s['l']) if (s['w'] + s['l']) else 0.5
    act = d[(d.did_not_play == False) & d.minutes.notna()].sort_values(['game_date', 'game_date_time'])
    tgm = d.drop_duplicates(['game_id', 'team_abbreviation'])[['game_id', 'team_abbreviation', 'game_date', 'team_winner']]
    dates = sorted(str(x) for x in d.game_date.unique()); out = {'dates': dates, 'blend': {}, 'now': {}}
    snap_scores = []
    for D in dates:
        sub = act[act.game_date.astype(str) <= D]
        g = sub.groupby('athlete_id'); a = g[COLS].sum(); a['gp'] = g.game_id.nunique(); a['team'] = g.team_abbreviation.last()
        tt = tgm[tgm.game_date.astype(str) <= D]
        tgs = tt.groupby('team_abbreviation').game_id.nunique().to_dict(); maxg = max(tgs.values())
        wl = tt.groupby('team_abbreviation').team_winner.agg(w='sum', n='count')
        res = {'blend': {}, 'now': {}}
        for pid, r in a.iterrows():
            gp = int(r.gp); team = r.team
            if gp < max(1, math.ceil(0.7 * tgs.get(team, maxg))) or r.minutes / gp < 25: continue
            cur = game_score_total(r) / gp
            W = int(wl.w.get(team, 0)); N = int(wl.n.get(team, 0)); L_ = N - W
            for mode in ('blend', 'now'):
                if mode == 'blend':
                    w = gp / (gp + 10); P = w * cur + (1 - w) * pri.get(int(pid), 8.0); qq = q.get(team, 0.5)
                else:
                    P = cur; qq = 0.5
                T = (W + 15 * qq) / (W + L_ + 15)
                res[mode][int(pid)] = P + 0.2 * (100 * T - 50)
        snap_scores.append(res)
    final = snap_scores[-1]
    keep = set()
    for mode in ('blend', 'now'):
        keep |= {pid for pid, _ in sorted(final[mode].items(), key=lambda kv: -kv[1])[:top_n]}
    for mode in ('blend', 'now'):
        for pid in keep:
            out[mode][str(pid)] = [round(s[mode][pid], 3) if pid in s[mode] else None for s in snap_scores]
    return out

# ----------------------------------------------------------------------------- scores and schedule
def games_table(raw, y, horizon_days=14):
    sch = pd.read_parquet(fetch(raw, 'sched', y))
    sch = sch[sch.season_type == 2].copy() if 'season_type' in sch.columns else sch.copy()
    sch['start'] = pd.to_datetime(sch['start_date'], utc=True); sch['et'] = sch.start.dt.tz_convert('America/New_York')
    sch['edate'] = sch.et.dt.strftime('%Y-%m-%d'); sch['etime'] = sch.et.dt.strftime('%-I:%M %p ET')
    box = pd.read_parquet(fetch(raw, 'box', y)); box = box[(box.did_not_play == False) & box.minutes.notna()]
    top = box.sort_values(['points', 'minutes'], ascending=[False, True]).drop_duplicates('game_id').set_index('game_id')
    done = sch[sch.status_type_completed == True]
    last = done.edate.max() if len(done) else None
    horizon = (pd.Timestamp(last) + pd.Timedelta(days=horizon_days)).strftime('%Y-%m-%d') if last else None
    rows = []
    for r in sch.sort_values('start').itertuples():
        comp = bool(r.status_type_completed)
        # completed games, plus the upcoming days; older unplayed rows (postponements) are left out
        if not comp and not (last and last < r.edate <= horizon): continue
        if r.home_abbreviation not in STD or r.away_abbreviation not in STD: continue
        t = top.loc[int(r.id)] if comp and int(r.id) in top.index else None
        rows.append([r.edate, r.etime, r.away_abbreviation, r.home_abbreviation, 1 if comp else 0, int(r.away_score) if comp else None, int(r.home_score) if comp else None,
                     1 if (comp and int(r.status_period) > 4) else 0, 1 if 'Cup Championship' in str(r.notes_headline or '') else 0,
                     (t.athlete_display_name if t is not None else None), (t.team_abbreviation if t is not None else None), (int(t.points) if t is not None else None),
                     int(t.athlete_id) if t is not None else None])
    return rows

# ----------------------------------------------------------------------------- assemble the data blocks and the page
def norm_name(s):
    import unicodedata, re
    s = unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace('-', ' '))
    return ' '.join(t for t in s.split() if t not in ('jr', 'sr', 'ii', 'iii', 'iv'))

def build_blocks(raw, refresh_current=True):
    cups = {y: cup_game_id(raw, y) for y in SEASONS}
    print('cup championship games:', cups, file=sys.stderr)
    names = {}; seasons = {}; hist = {}; teams = {}; clutch = {}; cur = None; cur_d = None
    for y in SEASONS:
        k = str(y)
        seasons[k] = build_season(raw, y, names, cups[y])
        L, d = box_players(raw, y, cups[y])
        teams[k] = team_ratings(d); clutch[k] = clutch_rows(raw, y, cups[y])
        if y == CURRENT: cur, cur_d = L, d
        else: hist[k] = L
    static = os.path.join(HERE, 'static')
    roster = json.load(open(os.path.join(static, 'roster.json')))
    allids = {norm_name(r.athlete_display_name): int(r.athlete_id) for r in cur_d.drop_duplicates('athlete_id').itertuples()}
    for r in roster['roster']:
        if r.get('pid') is None:
            base = norm_name(r['name'].replace('López', 'Lopez'))
            if base in allids: r['pid'] = allids[base]
    mem = cur_d[cur_d.team_abbreviation == 'MEM'].drop_duplicates('game_id')
    record = [int(mem.team_winner.sum()), int((~mem.team_winner.astype(bool)).sum())]
    hp = {k: hist[k]['players'] for k in hist}; hs = {k: seasons[k]['stand'] for k in hist}
    leaders = {'key': str(CURRENT), 'asof': cur['asof'], 'games': cur['games'], 'maxg': cur['maxg'], 'tg': cur['tg'], 'players': cur['players'],
               'hist': hist, 'mem': {'record': record, 'coach': roster['coach'], 'roster': roster['roster'], 'rosterAsOf': roster['rosterAsOf']},
               'teams': teams, 'clutch': clutch, 'race': mvp_race(cur_d, hp, hs), 'sched': games_table(raw, CURRENT)}
    shot = {'names': {str(k): v for k, v in names.items()}, 'seasons': seasons}
    return shot, leaders

def assemble(template_path, shot, leaders, awards, out_path):
    t = open(template_path, encoding='utf-8').read()
    for ph, obj in (('/*DATA*/', shot), ('/*LEADERS*/', leaders), ('/*AWARDS*/', awards)):
        assert ph in t, ph
        t = t.replace(ph, json.dumps(obj, separators=(',', ':')))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    open(out_path, 'w', encoding='utf-8').write(t)
    return len(t)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', default='raw', help='folder for downloaded source files')
    ap.add_argument('--out', default='docs/index.html')
    ap.add_argument('--data-only', default=None, help='write the two data blocks as JSON files into this folder instead of the page')
    ap.add_argument('--template', default=os.path.join(HERE, 'template.html'))
    ap.add_argument('--no-refresh', action='store_true', help='do not re-download the season in progress (for testing)')
    ap.add_argument('--current', type=int, default=None, help='year the current season ends (2027 = 2026-27); the five most recent seasons are built')
    a = ap.parse_args()
    global CURRENT, SEASONS
    if a.current:
        CURRENT = a.current; SEASONS = list(range(CURRENT - 4, CURRENT + 1))
    if not a.no_refresh:
        for kind in ('pbp', 'box', 'sched'): fetch(a.raw, kind, CURRENT, refresh=True)
    shot, leaders = build_blocks(a.raw)
    awards = json.load(open(os.path.join(HERE, 'static', 'awards.json')))
    if a.data_only:
        os.makedirs(a.data_only, exist_ok=True)
        json.dump(shot, open(os.path.join(a.data_only, 'shot.json'), 'w'), separators=(',', ':')); json.dump(leaders, open(os.path.join(a.data_only, 'leaders.json'), 'w'), separators=(',', ':'))
        print('wrote data blocks to', a.data_only)
    else:
        n = assemble(a.template, shot, leaders, awards, a.out)
        print(f'wrote {a.out} ({n/1e6:.2f} MB); data through {leaders["asof"]} ({leaders["games"]} games)')

if __name__ == '__main__':
    main()
