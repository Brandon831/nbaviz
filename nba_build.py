#!/usr/bin/env python3
"""
Builds the NBA dashboard (one self-contained HTML file) from public ESPN data published by sportsdataverse.

    python nba_build.py --raw raw --out docs/index.html

Raw files are downloaded into --raw the first time and re-downloaded for the current season on every run.
Static inputs live in ./static (awards.json, defmodel.json, roster.json); the page layout lives in template.html.
"""
import argparse, base64, datetime as dt, json, math, os, re, sys, urllib.request
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

# franchise codes that changed: the data is kept under today's code, with a note on the page
OLD_CODES = {'NJ': 'BKN', 'SEA': 'OKC', 'NOH': 'NO', 'NOK': 'NO'}
def readp(path, columns=None):
    """pandas.read_parquet, then every team-abbreviation column is mapped to today's franchise codes."""
    d = pd.read_parquet(path, columns=columns)
    for c in d.columns:
        if 'abbrev' in c and (d[c].dtype == object or pd.api.types.is_string_dtype(d[c])): d[c] = d[c].astype(object).replace(OLD_CODES)
    return d

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
        s = readp(fetch(raw, 'sched', y), columns=['id', 'notes_headline'])
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
    d = readp(path, columns=cols)
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
    # shots per game and team by zone group (rim, paint, mid-range, above-the-break three, corner three), regular season only
    GRP = np.array([0, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4])
    m0 = (po == 0)
    cnt = pd.DataFrame({'g': s.game_id.values[m0], 'h': home[m0], 'k': GRP[zone[m0]]}).groupby(['g', 'h', 'k']).size()
    shotgrp = {}
    for (g_, h_, k_), n_ in cnt.items(): shotgrp.setdefault((int(g_), int(h_)), [0] * 5)[int(k_)] = int(n_)
    shooter = np.where(home == 1, s.home_team_abbrev.values, s.away_team_abbrev.values)
    off = {}
    for t in TEAM_DIV:
        m = (shooter == t)
        off[t] = {'reg': [np.bincount(zone[m & (po == 0)], minlength=14).tolist(), np.bincount(zone[m & (po == 0) & (made == 1)], minlength=14).tolist()],
                  'po':  [np.bincount(zone[m & (po == 1)], minlength=14).tolist(), np.bincount(zone[m & (po == 1) & (made == 1)], minlength=14).tolist()]}
    s = s.assign(val=val, ex=ex, po=po, pid=s.athlete_id_1.astype(int), gid=s.game_id.astype(np.int64), zone=zone, made=made)
    for pid, nm in s[['pid', 'athlete_name_1']].drop_duplicates('pid').itertuples(index=False): names[int(pid)] = nm
    team = s.groupby('pid').team_id.agg(lambda x: x.value_counts().index[0]).map(tm)
    pl = []; chunks = []; xchunks = []; gchunks = []
    for pid, g in s.groupby('pid', sort=True):
        m0 = g.po.values == 0; m1 = g.po.values == 1
        r = g.val.values[m0]; p = g.val.values[m1]
        pl.append([int(pid), str(team[pid]), int(len(r)), int(len(p)), int(gp.get((int(pid), 0), 0)), int(gp.get((int(pid), 1), 0)), 1 if int(pid) in cupP else 0])
        chunks += [r, p]; xchunks += [g.ex.values[m0], g.ex.values[m1]]; gchunks += [g.gid.values[m0], np.full(int(m1.sum()), -1, dtype=np.int64)]
    if ADD_AVG and pl:
        reg = s[s.po == 0].sort_values(['game_id']); po_ = s[s.po == 1].sort_values(['game_id']); npl = len(pl)
        n_reg = int(round(len(reg) / npl)); n_po = int(round(len(po_) / npl))
        def sample(df, n):
            """a stratified sample: every zone, makes and misses separately, gets its share of the n shots (largest remainder), each stratum thinned evenly"""
            if n <= 0 or not len(df): return np.zeros(0, dtype=np.uint16), np.zeros(0, dtype=np.uint16)
            groups = [(k, g) for k, g in df.groupby(['zone', 'made'], sort=True)]
            exact = [n * len(g) / len(df) for _, g in groups]; base = [int(math.floor(x)) for x in exact]; short = n - sum(base)
            order = sorted(range(len(groups)), key=lambda i: -(exact[i] - base[i]))
            for i in order[:short]: base[i] += 1
            vals = []; exs = []
            for (_, g), m in zip(groups, base):
                if m <= 0: continue
                ix = np.linspace(0, len(g) - 1, m).round().astype(int); vals.append(g.val.values[ix]); exs.append(g.ex.values[ix])
            out = pd.DataFrame({'v': np.concatenate(vals), 'x': np.concatenate(exs)}); return out.v.values, out.x.values
        rv, rx = sample(reg, n_reg); pv, px = sample(po_, n_po)
        gr_avg = int(round(sum(p[4] for p in pl) / npl)); gp_avg = int(round(sum(p[5] for p in pl) / npl))
        pl.append([AVG_PID, 'NBA', int(len(rv)), int(len(pv)), gr_avg, gp_avg, 0]); names[AVG_PID] = AVG_NAME
        chunks += [rv, pv]; xchunks += [rx, px]; gchunks += [np.full(len(rv), -1, dtype=np.int64), np.full(len(pv), -1, dtype=np.int64)]
    arr = np.concatenate(chunks).astype('<u2'); xarr = np.concatenate(xchunks).astype('<u2')
    assert len(arr) == len(xarr)
    return {'stand': stand, 'lead': lead, 'cup': cup, 'games': games, 'asof': asof, 'label': f'{y-1}-{str(y)[2:]}', 'pl': pl,
            'd': base64.b64encode(arr.tobytes()).decode(), 'x': base64.b64encode(xarr.tobytes()).decode(), 'dates': dates, 'opp': opp, 'off': off, '_grp': shotgrp, '_gid': np.concatenate(gchunks)}

# ----------------------------------------------------------------------------- box scores: player totals, team ratings, clutch time
def box_games(raw, y, cup_id):
    d = readp(fetch(raw, 'box', y)); d = d[d.season_type == 2]
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
    if ADD_AVG and players:
        act_rows = [p for p in players if p[3] > 0]; n = len(act_rows)
        avg = [AVG_PID, AVG_NAME, 'NBA', max(1, int(round(sum(p[3] for p in act_rows) / n)))] + [round(sum(p[i] for p in act_rows) / n, 2) for i in range(4, len(players[0]))]
        players.append(avg)
    return {'asof': asof, 'games': games, 'maxg': int(max(tg.values())), 'tg': tg, 'players': players, 'pos': {str(k): v for k, v in positions(d).items()}}, d

def team_ratings(d):
    act = d[(d.did_not_play == False) & d.minutes.notna()]
    t = act.groupby(['game_id', 'team_abbreviation']).agg(pts=('team_score', 'first'), fga=('field_goals_attempted', 'sum'), fta=('free_throws_attempted', 'sum'),
        oreb=('offensive_rebounds', 'sum'), tov=('turnovers', 'sum'), opp=('opponent_team_abbreviation', 'first'), opts=('opponent_team_score', 'first')).reset_index()
    t['poss'] = t.fga + 0.44 * t.fta - t.oreb + t.tov
    j = t.merge(t[['game_id', 'team_abbreviation', 'poss']].rename(columns={'team_abbreviation': 'opp', 'poss': 'oposs'}), on=['game_id', 'opp'])
    g = j.groupby('team_abbreviation').agg(pts=('pts', 'sum'), opts=('opts', 'sum'), poss=('poss', 'sum'), oposs=('oposs', 'sum'), n=('game_id', 'nunique'))
    g['ortg'] = 100 * g.pts / g.poss; g['drtg'] = 100 * g.opts / g.oposs
    return {t_: [round(float(r.drtg), 3), round(float(r.ortg), 3), int(r.n)] for t_, r in g.iterrows()}

def clutch_rows(raw, y, cup_id):
    """Clutch time = last five minutes of the fourth quarter or overtime with the score within five points (before the play)."""
    c = clutch_plays(raw, y, cup_id); return clutch_sum(c)

def clutch_plays(raw, y, cup_id):
    """The clutch plays of a season (with game dates), from which clutch totals through any date can be built."""
    cols = ['game_id','sequence_number','period_number','clock_minutes','clock_seconds','home_score','away_score','scoring_play','score_value','shooting_play','type_text',
            'athlete_id_1','athlete_id_2','season_type','home_team_abbrev','away_team_abbrev','game_date']
    d = readp(fetch(raw, 'pbp', y), columns=cols)
    gm = d.drop_duplicates('game_id'); bad = set(gm[~(gm.home_team_abbrev.isin(STD) & gm.away_team_abbrev.isin(STD))].game_id)
    d = d[~d.game_id.isin(bad) & (d.season_type == 2)]
    if cup_id is not None: d = d[d.game_id != cup_id]
    d = d.assign(seq=d.sequence_number.astype(float)).sort_values(['game_id', 'seq'])
    d['hs0'] = d.groupby('game_id').home_score.shift(1).fillna(0); d['as0'] = d.groupby('game_id').away_score.shift(1).fillna(0)
    d['sec'] = d.clock_minutes * 60 + d.clock_seconds
    c = d[(d.period_number >= 4) & (d.sec <= 300) & ((d.hs0 - d.as0).abs() <= 5)].copy()
    return c

def clutch_sum(c):
    """Clutch totals per player from a set of clutch plays c (see clutch_rows)."""
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

# ----------------------------------------------------------------------------- game-by-game team rows (Team stats tab)
BUILT_AT = None
ARGS = None
AVG_PID = 99999999   # Armando "NBA" Venegas: the average of every player with data in the season (embedded seasons only); never a real ESPN id
AVG_NAME = 'Armando "NBA" Venegas'
ADD_AVG = False
TEAMS30 = sorted(TEAM_DIV)
TG_WIDTH = 42     # per game: date index, home team, away team, minutes, then each team's 19 numbers (box totals, then shots by zone group)
TG_COLS = ['points', 'field_goals_made', 'field_goals_attempted', 'three_point_field_goals_made', 'three_point_field_goals_attempted', 'free_throws_made',
           'free_throws_attempted', 'offensive_rebounds', 'defensive_rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'fouls']
def team_games(raw, y, d, shotgrp):
    act = d[(d.did_not_play == False) & d.minutes.notna()]
    tot = act.groupby(['game_id', 'team_abbreviation'])[TG_COLS].sum()
    gmin = act.groupby('game_id').minutes.sum() / 10
    meta = d.drop_duplicates(['game_id', 'team_abbreviation'])[['game_id', 'team_abbreviation', 'game_date', 'home_away', 'team_score']]
    per = readp(fetch(raw, 'pbp', y), columns=['game_id', 'period_number']).groupby('game_id').period_number.max()
    dates = sorted({str(x) for x in meta.game_date}); didx = {x: i for i, x in enumerate(dates)}; tix = {t: i for i, t in enumerate(TEAMS30)}
    rows = []
    for gid, g in meta.groupby('game_id'):
        h = g[g.home_away == 'home']; a = g[g.home_away == 'away']
        if len(h) != 1 or len(a) != 1: continue
        h = h.iloc[0]; a = a.iloc[0]
        p = per.get(gid)
        ot = max(0, int(p) - 4) if p is not None and p == p else max(0, int(round((gmin.get(gid, 240 / 5) - 48) / 5)))
        def block(r, side):
            v = [int(r.team_score)] + [int(tot.loc[(gid, r.team_abbreviation)][c]) for c in TG_COLS[1:]]
            return v + shotgrp.get((int(gid), side), [0] * 5)
        rows.append((didx[str(h.game_date)], int(gid), [didx[str(h.game_date)], tix[h.team_abbreviation], tix[a.team_abbreviation], 48 + 5 * ot] + block(h, 1) + block(a, 0)))
    rows.sort(key=lambda r: (r[0], r[1]))
    arr = np.array([r[2] for r in rows], dtype=np.int64)
    assert arr.shape[1] == TG_WIDTH and arr.max() < 65536 and arr.min() >= 0
    return {'teams': TEAMS30, 'dates': dates, 'w': TG_WIDTH, 'd': base64.b64encode(arr.astype('<u2').tobytes()).decode(), '_gids': [r[1] for r in rows]}

# ----------------------------------------------------------------------------- Grizzlies roster from ESPN's public feed (falls back to static/roster.json)
ESPN_ROSTER_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/mem/roster'
def roster_from_espn(static_roster):
    """The current roster and coach from ESPN's team feed. Two-way flags come from static/roster.json (matched by player id), since the feed does not
    mark them reliably. Returns None, and the build keeps the static file, if the feed cannot be read or looks incomplete."""
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(ESPN_ROSTER_URL, headers={'User-Agent': 'nba-dashboard'}), timeout=20) as r: j = json.load(r)
        tw = {int(p['pid']): int(p.get('tw', 0)) for p in static_roster.get('roster', [])}
        out = []
        for ath in j.get('athletes', []):
            pid = int(ath['id']); exp = ath.get('experience', {}).get('years'); col = ath.get('college', {}).get('name') if isinstance(ath.get('college'), dict) else None
            out.append({'n': int(ath['jersey']) if str(ath.get('jersey', '')).isdigit() else None, 'name': ath.get('displayName'), 'pid': pid,
                        'pos': (ath.get('position') or {}).get('abbreviation'), 'ht': ath.get('displayHeight'), 'wt': ath.get('weight'),
                        'bd': (ath.get('dateOfBirth') or '')[:10] or None, 'exp': 'R' if exp in (0, None) else str(exp), 'col': [col] if col else [], 'tw': tw.get(pid, 0)})
        if len(out) < 13: return None
        coach = None
        c = j.get('coach') or []
        if c: coach = (c[0].get('firstName', '') + ' ' + c[0].get('lastName', '')).strip() or None
        print(f'roster: {len(out)} players from ESPN' + (f', coach {coach}' if coach else ''), file=sys.stderr)
        return {'coach': coach or static_roster.get('coach'), 'rosterAsOf': dt.date.today().isoformat(), 'roster': out, 'source': 'espn'}
    except Exception as e:
        print('roster: ESPN feed not used (' + str(e)[:80] + '); keeping static/roster.json', file=sys.stderr); return None

# ----------------------------------------------------------------------------- positions (guard / forward / center), for the All-Defensive slots
POS_GROUP = {'PG': 'G', 'SG': 'G', 'G': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'GF': 'F', 'C': 'C', 'FC': 'C'}
LAST_POS = {}
def positions(d):
    """{player id: 'G' | 'F' | 'C'} from the box scores' position labels; a missing label falls back to the player's last known group, then forward."""
    out = {}
    if 'athlete_position_abbreviation' in d.columns:
        lab = d.dropna(subset=['athlete_position_abbreviation']).drop_duplicates('athlete_id')
        for pid, p in zip(lab.athlete_id, lab.athlete_position_abbreviation):
            g = POS_GROUP.get(str(p));
            if g: out[int(pid)] = g
    for pid in d.athlete_id.dropna().unique():
        pid = int(pid)
        if pid not in out: out[pid] = LAST_POS.get(pid, 'F')
    LAST_POS.update(out); return out

# ----------------------------------------------------------------------------- lineups and on/off ratings (rebuilt from substitutions)
TOV_RE = re.compile(r'Turnover|Traveling|Kicked Ball|^Lane$|Double Lane')
def resolve_subs(events, starters, roster, boxmin, tol):
    """events: [(period, clock_sec, team, pin, pout)] with None for a missing id. Tries every way of filling the gaps (the player leaving must be one
    of the five on the floor; the player entering must be a teammate not on the floor) and keeps the one whose rebuilt minutes agree with the box score.
    Returns the filled events, or None when no filling works or there are too many gaps."""
    gaps = [i for i, e in enumerate(events) if e[3] is None or e[4] is None]
    if not gaps: return events
    import itertools
    def minutes(evs):
        on = {t: set(v) for t, v in starters.items()}; sec = {}; curper = None; tprev = 0.0
        for p_, t_, team, pin, pout in [(e[0], e[1], e[2], e[3], e[4]) for e in evs if e is not None] + [(None, None, None, None, None)]:
            if p_ != curper:
                if curper is not None:
                    for tm in on:
                        for q in on[tm]: sec[q] = sec.get(q, 0.0) + tprev
                if p_ is None: break
                curper = p_; tprev = 720.0 if p_ <= 4 else 300.0
            dt = tprev - t_
            for tm in on:
                for q in on[tm]: sec[q] = sec.get(q, 0.0) + dt
            tprev = t_
            if pout not in on[team] or pin in on[team]: return None
            on[team].discard(pout); on[team].add(pin)
        return sec
    def options(i, evs_so_far):
        p_, t_, team, pin, pout = events[i]
        # who is on the floor just before this event, given the fills chosen so far
        on = set(starters[team])
        for e in evs_so_far[:i]:
            if e is not None and e[2] == team: on.discard(e[4]); on.add(e[3])
        outs = [pout] if pout is not None else sorted(on)
        ins = [pin] if pin is not None else sorted(roster[team] - on)
        # a partial event is sometimes a duplicate of a complete one logged at the same moment: dropping it is an option too
        return [None] + [(a, b) for b in outs for a in ins]
    best = None; tried = 0
    def search(i, evs):
        nonlocal best, tried
        if tried > 4000: return
        if i == len(gaps):
            tried += 1; sec = minutes(evs)
            if sec is None: return
            worst = max(abs(sec.get(p, 0.0) / 60.0 - boxmin.get(p, 0.0)) for p in set(sec) | set(boxmin))
            if worst <= tol and (best is None or worst < best[0]): best = (worst, list(evs))
            return
        gi = gaps[i]
        for opt in options(gi, evs):
            e = events[gi]; evs[gi] = None if opt is None else (e[0], e[1], e[2], opt[0], opt[1]); search(i + 1, evs)
        evs[gi] = events[gi]
    search(0, list(events))
    return best[1] if best else None

def lineup_data(raw, y, cup_id, box_d, keep_games=False, tol=1.5, use_cache=True):
    """Who was on the floor, rebuilt from substitution events, starting from the box-score starters.
    A game is used only if every lineup stays at exactly five players and every player's rebuilt minutes agree with the box score (within 1.5 minutes);
    the others are left out rather than guessed at. Possessions are counted from events (field goal attempts + 0.44 x free throw attempts - offensive rebounds + turnovers)."""
    cache = os.path.join(raw, f'lineups{y}.json')
    size = os.path.getsize(fetch(raw, 'pbp', y))
    if use_cache and y != CURRENT and not keep_games and os.path.exists(cache):
        c = json.load(open(cache))
        if c.get('pbp_size') == size and c.get('v') == 6: return c['data']
    cols = ['game_id','sequence_number','period_number','clock_minutes','clock_seconds','type_text','athlete_id_1','athlete_id_2','team_id','home_team_id','away_team_id',
            'home_team_abbrev','away_team_abbrev','home_score','away_score','shooting_play','scoring_play','coordinate_x','coordinate_y','season_type']
    d = readp(fetch(raw, 'pbp', y), columns=cols)
    gm = d.drop_duplicates('game_id'); bad = set(gm[~(gm.home_team_abbrev.isin(STD) & gm.away_team_abbrev.isin(STD))].game_id)
    d = d[~d.game_id.isin(bad) & (d.season_type == 2)]
    if cup_id is not None: d = d[d.game_id != cup_id]
    # chronological order: period, then game clock counting down, then ESPN's sequence number to break ties (sequence numbers alone sometimes interleave periods)
    d = d.assign(seq=d.sequence_number.astype(float), neg=-(d.clock_minutes * 60 + d.clock_seconds)).sort_values(['game_id', 'period_number', 'neg', 'seq'])
    act = box_d[(box_d.did_not_play == False) & box_d.minutes.notna()]
    starters = {(int(g), int(t)): [int(x) for x in grp.athlete_id] for (g, t), grp in act[act.starter == True].groupby(['game_id', 'team_id'])}
    boxmin = {(int(g), int(p)): float(m) for g, p, m in zip(act.game_id, act.athlete_id, act.minutes)}
    roster = {(int(g), int(t)): set(int(x) for x in grp.athlete_id) for (g, t), grp in act.groupby(['game_id', 'team_id'])}
    repaired = 0
    abbr = {}
    for a, b_ in (('home_team_id', 'home_team_abbrev'), ('away_team_id', 'away_team_abbrev')):
        for i, n in d[[a, b_]].drop_duplicates().itertuples(index=False): abbr[int(i)] = n
    tt = d.type_text.fillna('').values; has1 = d.athlete_id_1.notna().values
    is_sub = np.array([x.startswith('Substitution') for x in tt]); is_ft = np.array([x.startswith('Free Throw') for x in tt])
    is_fga = (d.shooting_play.values == True) & ~is_ft & has1
    is_oreb = (tt == 'Offensive Rebound') & has1
    is_tov = np.array([bool(TOV_RE.search(x)) for x in tt]) & has1
    comp = np.where(is_fga, 1.0, np.where(is_ft, 0.44, np.where(is_oreb, -1.0, np.where(is_tov, 1.0, 0.0))))
    # which field-goal attempts are at the rim (the page's restricted-area zone), and which went in: for the rim-deterrence signal
    cxr = d.coordinate_x.values.astype(float); cyr = d.coordinate_y.values.astype(float)
    with np.errstate(invalid='ignore'):
        sgn = np.where(cxr < 0, -1.0, 1.0); u_ = cyr * sgn; v_ = 47.0 - np.abs(cxr)
        ucol = np.clip(np.round(np.nan_to_num(u_) + 50).astype(int), 0, 100); vrow = np.clip(np.round(np.nan_to_num(v_) * 2).astype(int), 0, 94)
    is_rim = is_fga & ~np.isnan(cxr) & (LUT[0, ucol, vrow] == 0)
    is_make = (d.scoring_play.values == True)
    gid = d.game_id.values; per = d.period_number.values; clk = (d.clock_minutes.values * 60 + d.clock_seconds.values)
    tid = d.team_id.values; a1 = d.athlete_id_1.values; a2 = d.athlete_id_2.values; hs = d.home_score.values; as_ = d.away_score.values
    hid_all = d.home_team_id.values; aid_all = d.away_team_id.values
    bounds = np.flatnonzero(np.r_[True, gid[1:] != gid[:-1], True])
    lineups = {}; onoff = {}; clean = 0; total = 0; pm_all = {}; flows = {}; errs = []
    for bi in range(len(bounds) - 1):
        lo, hi = bounds[bi], bounds[bi + 1]; g = int(gid[lo]); total += 1
        h, a = int(hid_all[lo]), int(aid_all[lo])
        if (g, h) not in starters or (g, a) not in starters or len(starters[(g, h)]) != 5 or len(starters[(g, a)]) != 5: continue
        # substitutions with a missing player id: infer them from the box score (see resolve_subs); patch the id arrays for this game only
        sub_idx = [i for i in range(lo, hi) if is_sub[i]]
        if any(not (a1[i] == a1[i]) or not (a2[i] == a2[i]) for i in sub_idx):
            if (g, h) not in roster or (g, a) not in roster: continue
            evs = [(int(per[i]), float(min(max(clk[i] if clk[i] == clk[i] else 0.0, 0.0), 720.0 if per[i] <= 4 else 300.0)), int(tid[i]) if tid[i] == tid[i] else -1,
                    int(a1[i]) if a1[i] == a1[i] else None, int(a2[i]) if a2[i] == a2[i] else None) for i in sub_idx]
            if any(e[2] not in (h, a) for e in evs): continue
            filled = resolve_subs(evs, {h: starters[(g, h)], a: starters[(g, a)]}, {h: roster[(g, h)], a: roster[(g, a)]},
                                  {p: m for (gg, p), m in boxmin.items() if gg == g}, tol)
            if filled is None: continue
            a1 = a1.copy(); a2 = a2.copy()
            for i, e in zip(sub_idx, filled):
                if e is None: is_sub[i] = False
                else: a1[i] = e[3]; a2[i] = e[4]
            repaired += 1
        on = {h: set(starters[(g, h)]), a: set(starters[(g, a)])}; cur = {h: tuple(sorted(on[h])), a: tuple(sorted(on[a]))}; acc = {h: {}, a: {}}
        def vec(t): return acc[t].setdefault(cur[t], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        ok = True; curper = None; tprev = 720.0; ph = pa = 0; elapsed0 = 0.0; marks = []
        for i in range(lo, hi):
            p_ = int(per[i])
            if p_ != curper:
                if curper is not None and tprev > 0:
                    for t in (h, a): vec(t)[0] += tprev
                if curper is not None: elapsed0 += (720.0 if curper <= 4 else 300.0)
                curper = p_; tprev = 720.0 if p_ <= 4 else 300.0
            t_ = clk[i]
            if not (t_ == t_): t_ = tprev
            t_ = min(max(t_, 0.0), tprev); dt = tprev - t_
            if dt > 0:
                for t in (h, a): vec(t)[0] += dt
            tprev = t_
            h2 = int(hs[i]) if hs[i] == hs[i] else ph; a2_ = int(as_[i]) if as_[i] == as_[i] else pa
            dh = h2 - ph; da = a2_ - pa
            if dh > 0 or da > 0:
                if dh < 0: dh = 0
                if da < 0: da = 0
                vh, va = vec(h), vec(a); vh[1] += dh; vh[2] += da; va[1] += da; va[2] += dh
            ph, pa = max(ph, h2), max(pa, a2_)
            if keep_games: marks.append((elapsed0 + (720.0 if p_ <= 4 else 300.0) - tprev, ph - pa))
            c = comp[i]
            if c != 0.0 and tid[i] == tid[i]:
                t = int(tid[i])
                if t in acc:
                    o = a if t == h else h; vec(t)[3] += c; vec(o)[4] += c
                    if is_fga[i]:
                        vo = vec(o); vo[5] += 1
                        if is_rim[i]: vo[6] += 1; vo[7] += 1 if is_make[i] else 0
            if is_sub[i]:
                t = int(tid[i]) if tid[i] == tid[i] else -1
                pin = a1[i]; pout = a2[i]
                if t not in on or pin != pin or pout != pout or int(pout) not in on[t]: ok = False; break
                on[t].discard(int(pout)); on[t].add(int(pin))
                if len(on[t]) != 5: ok = False; break
                cur[t] = tuple(sorted(on[t]))
        if not ok: continue
        if tprev > 0:
            for t in (h, a): vec(t)[0] += tprev
        # every player's rebuilt minutes must agree with the box score
        secp = {}
        for t in (h, a):
            for key, v in acc[t].items():
                for p in key: secp[p] = secp.get(p, 0.0) + v[0]
        worst = 0.0
        for p, sec in secp.items():
            if (g, p) not in boxmin: worst = 99.0; break
            worst = max(worst, abs(sec / 60.0 - boxmin[(g, p)]))
        if worst > tol: continue
        clean += 1; errs.append(worst)
        for t in (h, a):
            T = [0.0] * 8
            for key, v in acc[t].items():
                for k in range(8): T[k] += v[k]
                L = lineups.setdefault((abbr[t], key), [0.0] * 6)
                for k in range(5): L[k] += v[k]
                L[5] += 1
            mine = {}
            for key, v in acc[t].items():
                for p in key:
                    m = mine.setdefault(p, [0.0] * 8)
                    for k in range(8): m[k] += v[k]
            for p, m in mine.items():
                # [games, on: sec, pts for, pts against, poss for, poss against, off: the same five, then on: opp FGA, rim FGA, rim FGM, off: the same three]
                o = onoff.setdefault(p, [0] + [0.0] * 16)
                o[0] += 1
                for k in range(5): o[1 + k] += m[k]; o[6 + k] += T[k] - m[k]
                for k in range(3): o[11 + k] += m[5 + k]; o[14 + k] += T[5 + k] - m[5 + k]
                if keep_games: pm_all.setdefault(g, {})[p] = round(m[1] - m[2])
        if keep_games:
            fl = []; k = 0; mk = marks
            end = int(round(elapsed0 + (720.0 if curper <= 4 else 300.0))) // 60
            for minute in range(end + 1):
                while k + 1 < len(mk) and mk[k + 1][0] <= minute * 60: k += 1
                fl.append(mk[k][1] if mk and mk[0][0] <= minute * 60 or minute == 0 else 0)
            flows[g] = fl
    # pairs, from every lineup
    pairs = {}
    for (team, key), v in lineups.items():
        for i in range(5):
            for j in range(i + 1, 5):
                P = pairs.setdefault((team, key[i], key[j]), [0.0] * 5)
                for k in range(5): P[k] += v[k]
    def top(dct, n):
        by = {}
        for k, v in dct.items(): by.setdefault(k[0], []).append((k, v))
        out = {}
        for team, rows in by.items():
            rows.sort(key=lambda r: -r[1][0])
            out[team] = [list(k[1:]) + [round(x, 1) for x in v[:5]] + ([int(v[5])] if len(v) > 5 else []) for k, v in rows[:n]]
        return out
    res = {'coverage': [clean, total], 'repaired': repaired, 'maxerr': round(float(np.max(errs)), 2) if errs else None,
           'onoff': {str(p): [int(o[0])] + [round(x, 2) for x in o[1:]] for p, o in onoff.items()},
           'lineups': top(lineups, 15), 'pairs': top(pairs, 15)}
    if keep_games: res['pm'] = {str(g): v for g, v in pm_all.items()}; res['flows'] = {str(g): v for g, v in flows.items()}
    if use_cache and y != CURRENT and not keep_games:
        json.dump({'v': 6, 'pbp_size': size, 'data': res}, open(cache, 'w'), separators=(',', ':'))
    return res

def flows_data(raw, y, cup_id):
    """The score margin (home minus away) at the end of every minute, for every regular-season game. Needs only the scores and the game clock, so it works even for the few games whose lineups cannot be rebuilt."""
    d = readp(fetch(raw, 'pbp', y), columns=['game_id', 'sequence_number', 'period_number', 'clock_minutes', 'clock_seconds', 'home_team_abbrev', 'away_team_abbrev', 'home_score', 'away_score', 'season_type'])
    gm = d.drop_duplicates('game_id'); bad = set(gm[~(gm.home_team_abbrev.isin(STD) & gm.away_team_abbrev.isin(STD))].game_id)
    d = d[~d.game_id.isin(bad) & (d.season_type == 2)]
    if cup_id is not None: d = d[d.game_id != cup_id]
    d = d.assign(seq=d.sequence_number.astype(float), neg=-(d.clock_minutes * 60 + d.clock_seconds)).sort_values(['game_id', 'period_number', 'neg', 'seq'])
    out = {}
    for g, grp in d.groupby('game_id', sort=False):
        per = grp.period_number.values; clk = grp.clock_minutes.values * 60 + grp.clock_seconds.values; hs = grp.home_score.values; as_ = grp.away_score.values
        elapsed0 = 0.0; curper = None; ph = pa = 0; marks = []
        for i in range(len(grp)):
            p_ = int(per[i]); length = 720.0 if p_ <= 4 else 300.0
            if p_ != curper:
                if curper is not None: elapsed0 += 720.0 if curper <= 4 else 300.0
                curper = p_
            t_ = clk[i]; t_ = length if not (t_ == t_) else min(max(float(t_), 0.0), length)
            h2 = int(hs[i]) if hs[i] == hs[i] else ph; a2 = int(as_[i]) if as_[i] == as_[i] else pa
            ph, pa = max(ph, h2), max(pa, a2); marks.append((elapsed0 + length - t_, ph - pa))
        end = int(round(elapsed0 + (720.0 if curper <= 4 else 300.0))) // 60; fl = []; k = 0
        for minute in range(end + 1):
            while k + 1 < len(marks) and marks[k + 1][0] <= minute * 60: k += 1
            fl.append(marks[k][1] if (marks[0][0] <= minute * 60 or minute == 0) else 0)
        out[str(int(g))] = fl
    return out

# ----------------------------------------------------------------------------- per-game box scores (season in progress)
def game_boxes(d, gids, pm, flows):
    """One entry per game, in the order of the team-game rows: [game id, score margin at the end of each minute or None, home player lines, away player lines].
    A player line: [id, minutes, pts, reb, ast, stl, blk, tov, pf, fgm, fga, 3pm, 3pa, ftm, fta, oreb, plus-minus or None, started]."""
    act = d[(d.did_not_play == False) & d.minutes.notna()]
    by = {int(g): grp for g, grp in act.groupby('game_id')}
    out = []
    for g in gids:
        grp = by.get(int(g))
        if grp is None: out.append([int(g), None, [], []]); continue
        sides = {}
        for side, name in (('home', 'home'), ('away', 'away')):
            rows = grp[grp.home_away == side].sort_values(['starter', 'minutes'], ascending=[False, False])
            sides[name] = [[int(r.athlete_id), int(r.minutes), int(r.points), int(r.rebounds), int(r.assists), int(r.steals), int(r.blocks), int(r.turnovers), int(r.fouls),
                            int(r.field_goals_made), int(r.field_goals_attempted), int(r.three_point_field_goals_made), int(r.three_point_field_goals_attempted),
                            int(r.free_throws_made), int(r.free_throws_attempted), int(r.offensive_rebounds), (pm.get(str(g), {}).get(str(int(r.athlete_id)), pm.get(str(g), {}).get(int(r.athlete_id)))), 1 if r.starter else 0] for r in rows.itertuples()]
        out.append([int(g), flows.get(str(g)), sides['home'], sides['away']])
    return out

def remaining_games(raw, y):
    """Every regular-season game still to be played, as [date, away, home]."""
    sch = readp(fetch(raw, 'sched', y))
    sch = sch[sch.season_type == 2].copy() if 'season_type' in sch.columns else sch.copy()
    sch['et'] = pd.to_datetime(sch['start_date'], utc=True).dt.tz_convert('America/New_York'); sch['edate'] = sch.et.dt.strftime('%Y-%m-%d')
    done = sch[sch.status_type_completed == True]; last = done.edate.max() if len(done) else ''
    todo = sch[(sch.status_type_completed != True) & (sch.edate > last) & sch.home_abbreviation.isin(STD) & sch.away_abbreviation.isin(STD)].sort_values(['edate', 'id'])
    return [[r.edate, r.away_abbreviation, r.home_abbreviation] for r in todo.itertuples()]

# ----------------------------------------------------------------------------- season tracker: each award's ladder at every game date so far
def award_snapshots(raw, y, d, cup_id, shot, leaders, awards, defmodel, top_n=8):
    """Replays the season day by day: after each game date, every award ladder is recomputed from the games played so far, with the same
    rules the page uses that day (including the games-played eligibility rule, which is why early dates can have few names)."""
    import awards_models
    act = d[(d.did_not_play == False) & d.minutes.notna()].copy(); act['dt'] = act.game_date.astype(str)
    dates = sorted(act.dt.unique()); cur = str(y)
    plays = clutch_plays(raw, y, cup_id); plays['dt'] = plays.game_date.astype(str)
    M = awards_models.Models(shot, leaders, {}, awards, defmodel)
    fit = leaders.get('mipfit') or M.mip_fit()
    out = {'dates': dates, 'awards': {a: [] for a in ('mvp', 'dpoy', 'roy', 'smoy', 'mip', 'clutch')}}
    for D in dates:
        cut = act[act.dt <= D]
        tg = {k: int(v) for k, v in cut.groupby('team_abbreviation').game_id.nunique().items()}
        g = cut.groupby('athlete_id'); a = g[COLS].sum().astype(float); a['gp'] = g.game_id.nunique()
        a['gst'] = cut[cut.starter == True].groupby('athlete_id').game_id.nunique().reindex(a.index).fillna(0).astype(int)
        last = g.tail(1).set_index('athlete_id'); a['name'] = last.athlete_display_name; a['team'] = last.team_abbreviation
        players = [[int(pid), r['name'], r['team'], int(r['gp'])] + [float(r[c]) for c in COLS] + [int(r['gst'])] for pid, r in a.iterrows()]
        M.SEAS[cur] = {'players': [dict(zip(awards_models.F, p)) for p in players], 'tg': tg, 'maxg': int(max(tg.values())), 'pos': leaders.get('pos', {})}
        games = cut.drop_duplicates(['game_id', 'team_abbreviation'])
        M.STAND[cur] = {t: {'w': int(x.team_winner.sum()), 'l': int((~x.team_winner.astype(bool)).sum())} for t, x in games.groupby('team_abbreviation')}
        M.TEAMS[cur] = team_ratings(d[d.game_date.astype(str) <= D]); M.TD[cur] = M._tdef(cur)
        crow = clutch_sum(plays[plays.dt <= D])
        pick = lambda lst: [[r['p']['pid'], round(r['score'], 2)] for r in lst[:top_n]]
        out['awards']['mvp'].append(pick(M.mvp(cur, True))); out['awards']['dpoy'].append(pick(M.dpoy(cur, False))); out['awards']['roy'].append(pick(M.roy(cur)))
        out['awards']['smoy'].append(pick(M.smoy(cur, True))); out['awards']['mip'].append(pick(M.mip(cur, fit, True))); out['awards']['clutch'].append(pick(M.clutch(cur, crow)))
    return out

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
    sch = readp(fetch(raw, 'sched', y))
    sch = sch[sch.season_type == 2].copy() if 'season_type' in sch.columns else sch.copy()
    sch['start'] = pd.to_datetime(sch['start_date'], utc=True); sch['et'] = sch.start.dt.tz_convert('America/New_York')
    sch['edate'] = sch.et.dt.strftime('%Y-%m-%d'); sch['etime'] = sch.et.dt.strftime('%-I:%M %p ET')
    box = readp(fetch(raw, 'box', y)); box = box[(box.did_not_play == False) & box.minutes.notna()]
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
                     int(t.athlete_id) if t is not None else None, int(r.id)])
    return rows

# ----------------------------------------------------------------------------- assemble the data blocks and the page
def norm_name(s):
    import unicodedata, re
    s = unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace('-', ' '))
    return ' '.join(t for t in s.split() if t not in ('jr', 'sr', 'ii', 'iii', 'iv'))

def team_colors(d):
    """ESPN's primary and secondary color for each team, as six-digit hex codes (cosmetic: the page falls back to a default without them)."""
    if not {'team_color', 'team_alternate_color'} <= set(d.columns): return {}
    out = {}
    for r in d.drop_duplicates('team_abbreviation').itertuples():
        pc = str(r.team_color or '').lower().lstrip('#'); sc = str(r.team_alternate_color or '').lower().lstrip('#')
        if re.fullmatch(r'[0-9a-f]{6}', pc): out[r.team_abbreviation] = [pc, sc if re.fullmatch(r'[0-9a-f]{6}', sc) else '']
    return out

def build_blocks(raw, refresh_current=True):
    global ADD_AVG
    ADD_AVG = True
    cups = {y: cup_game_id(raw, y) for y in SEASONS}
    print('cup championship games:', cups, file=sys.stderr)
    names = {}; seasons = {}; hist = {}; teams = {}; clutch = {}; tgames = {}; onoff = {}; lineups = {}; pairs = {}; lcov = {}; cur = None; cur_d = None; gbox = None; gx = None
    for y in SEASONS:
        k = str(y)
        seasons[k] = build_season(raw, y, names, cups[y])
        L, d = box_players(raw, y, cups[y])
        tgames[k] = team_games(raw, y, d, seasons[k].pop('_grp'))
        gids = tgames[k].pop('_gids'); shot_gid = seasons[k].pop('_gid')
        ld = lineup_data(raw, y, cups[y], d, keep_games=(y == CURRENT))
        onoff[k] = ld['onoff']; lineups[k] = ld['lineups']; pairs[k] = ld['pairs']; lcov[k] = ld['coverage']
        if y == CURRENT:
            gbox = game_boxes(d, gids, ld.get('pm', {}), flows_data(raw, y, cups[y]))
            order = {int(g): i for i, g in enumerate(gids)}
            gx = np.array([order.get(int(g), 65535) if g >= 0 else 65535 for g in shot_gid], dtype='<u2')
            seasons[k]['gx'] = base64.b64encode(gx.tobytes()).decode(); tgames[k]['gids'] = [int(g) for g in gids]
        teams[k] = team_ratings(d); clutch[k] = clutch_rows(raw, y, cups[y])
        if y == CURRENT: cur, cur_d = L, d; globals()['_CUR_D'] = d; globals()['_CUR_CUP'] = cups[y]
        else: hist[k] = L
    static = os.path.join(HERE, 'static')
    roster = json.load(open(os.path.join(static, 'roster.json')))
    if not getattr(ARGS, 'no_espn_roster', False):
        live = roster_from_espn(roster)
        if live: roster = live
    allids = {norm_name(r.athlete_display_name): int(r.athlete_id) for r in cur_d.drop_duplicates('athlete_id').itertuples()}
    for r in roster['roster']:
        if r.get('pid') is None:
            base = norm_name(r['name'].replace('López', 'Lopez'))
            if base in allids: r['pid'] = allids[base]
    mem = cur_d[cur_d.team_abbreviation == 'MEM'].drop_duplicates('game_id')
    record = [int(mem.team_winner.sum()), int((~mem.team_winner.astype(bool)).sum())]
    hp = {k: hist[k]['players'] for k in hist}; hs = {k: seasons[k]['stand'] for k in hist}
    leaders = {'key': str(CURRENT), 'asof': cur['asof'], 'games': cur['games'], 'maxg': cur['maxg'], 'tg': cur['tg'], 'players': cur['players'], 'pos': cur.get('pos', {}),
               'hist': hist, 'mem': {'record': record, 'coach': roster['coach'], 'roster': roster['roster'], 'rosterAsOf': roster['rosterAsOf']},
               'teams': teams, 'tgames': tgames, 'tcolors': team_colors(cur_d), 'onoff': onoff, 'lineups': lineups, 'pairs': pairs, 'lcov': lcov, 'gbox': gbox, 'remaining': remaining_games(raw, CURRENT), 'builtAt': BUILT_AT, 'clutch': clutch, 'race': mvp_race(cur_d, hp, hs), 'sched': games_table(raw, CURRENT)}
    shot = {'names': {str(k): v for k, v in names.items()}, 'seasons': seasons}
    return shot, leaders

# ----------------------------------------------------------------------------- archived seasons (one file each, loaded by the page on demand)
ARCHIVE_VERSION = 6
def season_payload(raw, y):
    """Everything the page needs for one finished season, as one JSON-ready object. Cached in raw/ because finished seasons never change."""
    cache = os.path.join(raw, f'season{y}.json')
    if os.path.exists(cache):
        c = json.load(open(cache))
        if c.get('v') == ARCHIVE_VERSION: return c['data']
    global ADD_AVG
    ADD_AVG = True
    cup = cup_game_id(raw, y); names = {}
    s = build_season(raw, y, names, cup); L, d = box_players(raw, y, cup)
    tg = team_games(raw, y, d, s.pop('_grp')); tg.pop('_gids', None); s.pop('_gid', None)
    ld = lineup_data(raw, y, cup, d)
    data = {'key': str(y), 'shot': s, 'names': {str(k): v for k, v in names.items()}, 'hist': L, 'teams': team_ratings(d), 'tgames': tg,
            'onoff': ld['onoff'], 'lineups': ld['lineups'], 'pairs': ld['pairs'], 'lcov': ld['coverage']}
    json.dump({'v': ARCHIVE_VERSION, 'data': data}, open(cache, 'w'), separators=(',', ':'))
    return data

def build_archive(raw, first_year, out_dir, url_of):
    """Writes season-<year>.json for every finished season from first_year up to the oldest embedded one, and returns the manifest for the page."""
    os.makedirs(out_dir, exist_ok=True); manifest = {}
    for y in range(first_year, SEASONS[0]):
        p = season_payload(raw, y); path = os.path.join(out_dir, f'season-{y}.json')
        slim = dict(p); slim['hist'] = {k: v for k, v in p['hist'].items() if k != 'pos'}   # positions are only needed by the build's own backtest
        json.dump(slim, open(path, 'w'), separators=(',', ':'))
        sch = readp(fetch(raw, 'sched', y)); scheduled = int((sch.season_type == 2).sum()) if 'season_type' in sch.columns else len(sch)
        bg = p['hist']['games']; lc = p['lcov']
        manifest[str(y)] = {'label': p['shot']['label'], 'games': p['shot']['games'], 'boxGames': bg, 'scheduled': scheduled, 'lineups': round(lc[0] / lc[1], 3) if lc[1] else 0,
                            'url': url_of(y), 'bytes': os.path.getsize(path), 'partial': bool(bg < 0.9 * scheduled)}
        print(f'archive {y}: box scores for {bg} of {scheduled} games, lineups {lc[0]}/{lc[1]}, {os.path.getsize(path)/1e6:.2f} MB', file=sys.stderr)
    return manifest

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
    ap.add_argument('--built-at', default=None, help='timestamp to record in the page (defaults to now, in UTC); fixed for reproducible test builds')
    ap.add_argument('--no-espn-roster', action='store_true', help='do not fetch the Grizzlies roster from ESPN; use static/roster.json as is')
    ap.add_argument('--no-refresh', action='store_true', help='do not re-download the season in progress (for testing)')
    ap.add_argument('--history', type=int, default=None, help='also build one data file per finished season back to this end-year (2004 = 2003-04), for the page to load on demand')
    ap.add_argument('--archive-dir', default=None, help='where the season files go (default: a data/ folder beside the page)')
    ap.add_argument('--archive-urls', default=None, help='JSON file mapping end-year to the URL the page should fetch, when the files are hosted elsewhere (default: data/season-<year>.json beside the page)')
    ap.add_argument('--current', type=int, default=None, help='year the current season ends (2027 = 2026-27); the five most recent seasons are built')
    a = ap.parse_args()
    global CURRENT, SEASONS, BUILT_AT, ARGS
    ARGS = a
    BUILT_AT = a.built_at or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    if a.current:
        CURRENT = a.current; SEASONS = list(range(CURRENT - 4, CURRENT + 1))
    if not a.no_refresh:
        for kind in ('pbp', 'box', 'sched'): fetch(a.raw, kind, CURRENT, refresh=True)
    shot, leaders = build_blocks(a.raw)
    awards = json.load(open(os.path.join(HERE, 'static', 'awards.json')))
    if a.history:
        out_dir = a.archive_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), 'data')
        urls = json.load(open(a.archive_urls)) if a.archive_urls else {}
        shot['archive'] = build_archive(a.raw, a.history, out_dir, lambda y: urls.get(str(y), f'data/season-{y}.json'))
        # the award models over every finished season: the Most Improved regression and the scorecard on the About tab
        import awards_models
        payloads = {str(y): season_payload(a.raw, y) for y in range(a.history, SEASONS[0])}
        M = awards_models.Models(shot, leaders, payloads, awards, json.load(open(os.path.join(HERE, 'static', 'defmodel.json'))))
        leaders['mipfit'] = M.mip_fit(); leaders['backtest'] = M.backtest(leaders['mipfit'])
        print(f"Most Improved regression on {leaders['mipfit']['seasons']} seasons: {leaders['mipfit']['a']:+.3f} {leaders['mipfit']['b']:+.4f} x last-year Game Score; scorecard rows: {len(leaders['backtest'])}", file=sys.stderr)
    leaders['warnings'] = []
    try:
        sch = readp(fetch(a.raw, 'sched', CURRENT)); notes = sch.notes_headline.fillna('').str.lower() if 'notes_headline' in sch.columns else None
        if notes is not None:
            fin = sch[notes.str.contains('cup') & notes.str.contains('champ|final') & (sch.status_type_completed == True)]
            if len(fin) and _CUR_CUP is None: leaders['warnings'].append('The NBA Cup championship game has been played but the build did not recognise it, so it is being counted as a regular-season game. Check cup_game_id in nba_build.py against the schedule note "%s".' % fin.notes_headline.iloc[0])
        last_fin = str(CURRENT - 1)
        if dt.date.today().month >= 7 and last_fin not in awards: leaders['warnings'].append('static/awards.json has no entries for %d-%s yet: add that season\u2019s winners with add_awards.py so badges and the scorecard stay current.' % (CURRENT - 2, last_fin[2:]))
    except Exception as e:
        print('warning checks skipped:', e, file=sys.stderr)
    try:
        leaders['snapshots'] = award_snapshots(a.raw, CURRENT, _CUR_D, _CUR_CUP, shot, leaders, awards, json.load(open(os.path.join(HERE, 'static', 'defmodel.json'))))
        print(f"season tracker: {len(leaders['snapshots']['dates'])} game dates", file=sys.stderr)
    except Exception as e:
        print('season tracker could not be built:', e, file=sys.stderr); leaders['snapshots'] = None
    if a.data_only:
        os.makedirs(a.data_only, exist_ok=True)
        json.dump(shot, open(os.path.join(a.data_only, 'shot.json'), 'w'), separators=(',', ':')); json.dump(leaders, open(os.path.join(a.data_only, 'leaders.json'), 'w'), separators=(',', ':'))
        print('wrote data blocks to', a.data_only)
    else:
        n = assemble(a.template, shot, leaders, awards, a.out)
        print(f'wrote {a.out} ({n/1e6:.2f} MB); data through {leaders["asof"]} ({leaders["games"]} games)')

if __name__ == '__main__':
    main()
