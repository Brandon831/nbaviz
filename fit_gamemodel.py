"""Fits the game model behind every win chance on the page, from the box scores in raw/, and writes static/gamemodel.json.

    python fit_gamemodel.py            # report only
    python fit_gamemodel.py --write    # also write static/gamemodel.json (embedded by the build as leaders.gamemodel; the page reads it)

The page's model: each team's strength is its net rating so far (points per 100 possessions, possessions = FGA + 0.44 FTA - OREB + TOV),
blended with a fraction PW of last season's final net rating, this season weighted n/(n+K) after n games. A game's expected margin for the
home team is GAP * (home strength - away strength) + HCA - B2B * (home on a back-to-back) + B2B * (away on a back-to-back), and the win
chance is Phi(margin / SIG). This script rebuilds every regular-season game since 2003-04 with the ratings each team had before that game,
then:
  1. chooses K and PW by holding each season out (log loss of the home win chance),
  2. fits GAP, HCA, B2B and SIG by least squares on the margin, on all seasons and on 2017-18 onward (home court has been falling),
  3. backtests an availability adjustment for 2018-19 onward: the value of the regulars who did not play in a game (RAPM from the
     previous season, times their minutes share), added to the margin model. That is the ceiling for an injury-report adjustment,
     since it knows exactly who sat out."""
import argparse, json, os, sys, math
import numpy as np, pandas as pd
from scipy.stats import norm
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from bootstrap import bootstrap_report
COLS = ['game_id', 'game_date', 'team_abbreviation', 'home_away', 'team_score', 'opponent_team_score', 'season_type', 'did_not_play', 'minutes', 'field_goals_attempted', 'free_throws_attempted', 'offensive_rebounds', 'turnovers', 'athlete_id']

def season_games(raw, y):
    """one row per team-game with points, possessions, rest and date, plus the per-player minutes for the availability test"""
    b = pd.read_parquet(os.path.join(raw, f'box{y}.parquet'), columns=COLS); b = b[b.season_type == 2].copy()
    act = b[(b.did_not_play == False) & b.minutes.notna()]
    t = act.groupby(['game_id', 'team_abbreviation']).agg(date=('game_date', 'first'), ha=('home_away', 'first'), pts=('team_score', 'first'), opts=('opponent_team_score', 'first'),
        fga=('field_goals_attempted', 'sum'), fta=('free_throws_attempted', 'sum'), oreb=('offensive_rebounds', 'sum'), tov=('turnovers', 'sum')).reset_index()
    t['poss'] = t.fga + 0.44 * t.fta - t.oreb + t.tov; t['date'] = pd.to_datetime(t.date); t['ha'] = t.ha.str.lower()
    t = t.merge(t[['game_id', 'team_abbreviation', 'poss']].rename(columns={'team_abbreviation': 'opp', 'poss': 'oposs'}), on='game_id').query('team_abbreviation != opp')
    t = t.sort_values(['team_abbreviation', 'date']).reset_index(drop=True)
    g = t.groupby('team_abbreviation')
    t['rest'] = (t.date - g.date.shift()).dt.days - 1
    # pre-game cumulative net rating: everything the team played before this game
    for c in ('pts', 'opts', 'poss', 'oposs'): t['c' + c] = g[c].cumsum() - t[c]
    t['n'] = g.cumcount()
    t['net_pre'] = np.where(t.n > 0, 100 * t.cpts / t.cposs.replace(0, np.nan) - 100 * t.copts / t.coposs.replace(0, np.nan), 0.0)
    final = t.groupby('team_abbreviation').agg(pts=('pts', 'sum'), opts=('opts', 'sum'), poss=('poss', 'sum'), oposs=('oposs', 'sum'))
    final_net = (100 * final.pts / final.poss - 100 * final.opts / final.oposs).to_dict()
    return t, final_net, act[['game_id', 'team_abbreviation', 'athlete_id', 'minutes']]

def build(raw, years):
    out = []; prev = None; acts = {}
    for y in years:
        t, final_net, act = season_games(raw, y); acts[y] = act
        t['prev'] = t.team_abbreviation.map(prev) if prev else np.nan; t['y'] = y
        h = t[t.ha == 'home'].set_index('game_id'); a = t[t.ha == 'away'].set_index('game_id')
        j = h.join(a[['team_abbreviation', 'rest', 'net_pre', 'n', 'prev']], rsuffix='_a', how='inner')
        out.append(j.reset_index()); prev = final_net
        print(f'  {y-1}-{str(y)[2:]}: {len(j)} games', file=sys.stderr)
    d = pd.concat(out, ignore_index=True); d['margin'] = d.pts - d.opts; d['hwin'] = (d.margin > 0).astype(float)
    d['b2b_h'] = (d.rest == 0).astype(float); d['b2b_a'] = (d.rest_a == 0).astype(float)
    return d, acts

def strength(net, n, prev, K, PW):
    p = np.where(np.isnan(prev), 0.0, prev) * PW
    return (n / (n + K)) * net + (K / (n + K)) * p

def design(d, K, PW):
    gap = strength(d.net_pre.values, d.n.values, d.prev.values, K, PW) - strength(d.net_pre_a.values, d.n_a.values, d.prev_a.values, K, PW)
    return np.c_[gap, np.ones(len(d)), d.b2b_a.values - d.b2b_h.values]   # columns: GAP, HCA, B2B (positive when the visitor is tired)

def fit_margin(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None); sig = float((y - X @ beta).std()); return beta, sig

def logloss(p, w): p = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(w * np.log(p) + (1 - w) * np.log(1 - p)))

def loso(d, X, cols=None, fixed=None, per_season=False):
    """held-out log loss and accuracy of Phi(margin/SIG), fitting the margin coefficients on the other seasons; fixed=(HCA, SIG) scores the page's
    old fixed constants instead; per_season=True also returns the log loss of each season"""
    cols = cols if cols is not None else list(range(X.shape[1])); ll = []; acc = []
    for y in sorted(d.y.unique()):
        tr = (d.y != y).values; te = ~tr
        if fixed: p = norm.cdf((X[te][:, 0] + fixed[0]) / fixed[1])
        else: beta, sig = fit_margin(X[tr][:, cols], d.margin.values[tr]); p = norm.cdf(X[te][:, cols] @ beta / sig)
        ll.append(logloss(p, d.hwin.values[te])); acc.append(float(((p > 0.5) == (d.hwin.values[te] > 0.5)).mean()))
    return (float(np.mean(ll)), float(np.mean(acc))) + ((np.array(ll),) if per_season else ())

def availability(d, acts, raw, years, min_mpg=15, min_gp=40):
    """for each game and side: the value of the team's regulars who did not play, from the previous season's RAPM.
    regulars (hindsight): players with min_gp games and min_mpg minutes a game that season. value = RAPM offense - defense (points per 100
    possessions), minutes share = season minutes per game / 48. Returns the design columns MV (value missing) and MM (minutes share missing)."""
    MV = np.zeros(len(d)); MM = np.zeros(len(d)); MVin = np.zeros(len(d)); have = np.zeros(len(d), bool)
    idx = {gid: i for i, gid in enumerate(d.game_id.values)}
    for y in years:
        cache = os.path.join(raw, f'season{y}.json'); cachep = os.path.join(raw, f'season{y-1}.json')
        if not (os.path.exists(cache) and os.path.exists(cachep)): continue
        rp = json.load(open(cachep))['data'].get('rapm') or {}; rc = json.load(open(cache))['data'].get('rapm') or {}
        if not rp or not rc: continue
        act = acts[y]; per = act.groupby('athlete_id').agg(gp=('game_id', 'nunique'), mpg=('minutes', 'mean')); reg = per[(per.gp >= min_gp) & (per.mpg >= min_mpg)]
        team_of = act.groupby('athlete_id').team_abbreviation.agg(lambda s: s.value_counts().index[0])
        played = act.groupby(['game_id', 'team_abbreviation']).athlete_id.apply(set).to_dict()
        games = d[d.y == y]
        for gid, h, a in zip(games.game_id.values, games.team_abbreviation.values, games.team_abbreviation_a.values):
            i = idx[gid]; have[i] = True
            for side, team in ((1, h), (-1, a)):
                on = played.get((gid, team), set())
                for pid in reg.index:
                    if team_of.get(pid) != team or pid in on: continue
                    share = reg.mpg[pid] / 48.0; vp = rp.get(str(pid)); vc = rc.get(str(pid))
                    v_prev = (vp[0] - vp[1]) if vp else 0.0; v_in = (vc[0] - vc[1]) if vc else 0.0
                    MV[i] += side * v_prev * share; MM[i] += side * share; MVin[i] += side * v_in * share
    return MV, MM, MVin, have

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', default='raw'); ap.add_argument('--write', action='store_true'); ap.add_argument('--first', type=int, default=2004); ap.add_argument('--last', type=int, default=2026)
    a = ap.parse_args(); years = list(range(a.first, a.last + 1))
    print('building games with pre-game ratings...', file=sys.stderr); d, acts = build(a.raw, years)
    d = d.dropna(subset=['rest', 'rest_a']).reset_index(drop=True)   # each team's first game has no rest value
    print(f'{len(d)} regular-season games, {years[0]-1}-{str(years[0])[2:]} to {years[-1]-1}-{str(years[-1])[2:]}')
    # ---- 1. the blend constants
    print('\n== Blend constants (held-out log loss of the home win chance; the page uses K=10, PW=0.4) ==')
    grid = []
    for K in (5, 10, 15, 20, 30):
        for PW in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8):
            X = design(d, K, PW); ll, acc = loso(d, X); grid.append((ll, acc, K, PW))
    grid.sort(); base = [g for g in grid if g[2] == 10 and g[3] == 0.4][0]
    print(f"{'K':>4s} {'PW':>5s} {'log loss':>9s} {'accuracy':>9s}")
    for ll, acc, K, PW in grid[:6]: print(f'{K:>4d} {PW:>5.1f} {ll:>9.4f} {100*acc:>8.1f}%')
    print(f'page {base[2]:>3d} {base[3]:>5.1f} {base[0]:>9.4f} {100*base[1]:>8.1f}%')
    ll, acc, K, PW = grid[0]
    # ---- 2. margin coefficients
    print(f'\n== Margin model with K={K}, PW={PW} (least squares on the home margin) ==')
    X = design(d, K, PW); recent = (d.y >= 2018).values
    for name, m in (('all seasons', np.ones(len(d), bool)), ('2017-18 onward', recent)):
        beta, sig = fit_margin(X[m], d.margin.values[m]); print(f'  {name:16s} GAP {beta[0]:+.3f}, HCA {beta[1]:+.2f}, B2B {beta[2]:+.2f}, SIG {sig:.2f}  ({int(m.sum())} games)')
    print('  home edge by season: ' + ', '.join(f"{y-1}-{str(y)[2:]} {fit_margin(X[(d.y==y).values], d.margin.values[(d.y==y).values])[0][1]:+.1f}" for y in years))
    # the page today, and the fitted model, on the same held-out seasons (2017-18 onward)
    dr = d[recent].reset_index(drop=True); Xr = X[recent]
    def page_ll(dd, XX):   # the page's fixed constants: margin = gap + 2.0, SIG 12.5, no rest term
        p = norm.cdf((XX[:, 0] + 2.0) / 12.5); return logloss(p, dd.hwin.values), float(((p > 0.5) == (dd.hwin.values > 0.5)).mean())
    pl, pa = page_ll(dr, Xr); fl, fa, fls = loso(dr, Xr, per_season=True); nl, na, nls = loso(dr, Xr, [0, 1], per_season=True); _, _, pls = loso(dr, Xr, fixed=(2.0, 12.5), per_season=True)
    print(f'\n  2017-18 onward, each season held out: page constants log loss {pl:.4f} (accuracy {100*pa:.1f}%); fitted without rest {nl:.4f} ({100*na:.1f}%); fitted with rest {fl:.4f} ({100*fa:.1f}%)')
    print('  bootstrap over seasons (gain in log loss, positive = better):')
    bootstrap_report('   rest term (fitted with vs without)', list(nls - fls), 'll'); bootstrap_report('   fitted constants with rest vs the earlier fixed constants', list(pls - fls), 'll')
    _, _, b_new = loso(d, X, per_season=True); _, _, b_old = loso(d, design(d, 10, 0.4), per_season=True)
    v_blend = bootstrap_report(f'   blend K={K}, PW={PW} vs K=10, PW=0.4', list(b_old - b_new), 'll')
    if v_blend != 'ADOPT': print('   -> the blend change does not clear the bar; --write keeps K=10, PW=0.4'); K, PW = 10, 0.4; X = design(d, K, PW); Xr = X[recent]
    beta_r, sig_r = fit_margin(Xr, dr.margin.values)
    # ---- 3. availability
    print('\n== Availability (regulars who did not play; RAPM from the previous season) ==')
    yrs = [y for y in years if y >= 2019]; MV, MM, MVin, have = availability(d, acts, a.raw, yrs)
    dv = d[have].reset_index(drop=True); Xv = X[have]; MVv = MV[have]; MMv = MM[have]; MVinv = MVin[have]
    print(f'  {len(dv)} games {yrs[0]-1}-{str(yrs[0])[2:]} to {yrs[-1]-1}-{str(yrs[-1])[2:]}; games with at least one regular out on either side: {100*np.mean((MMv != 0)):.0f}%')
    b0, s0 = fit_margin(Xv, dv.margin.values); X2 = np.c_[Xv, MVv, MMv]; b2, s2 = fit_margin(X2, dv.margin.values)
    l0, a0, l0s = loso(dv, Xv, per_season=True); l2, a2, l2s = loso(dv, X2, per_season=True); l3, a3 = loso(dv, np.c_[Xv, MVinv, MMv])
    bootstrap_report('  bootstrap: availability vs none (gain in log loss)', list(l0s - l2s), 'll')
    print(f'  held out: without availability log loss {l0:.4f} ({100*a0:.1f}%); with (previous-season RAPM) {l2:.4f} ({100*a2:.1f}%); with (same-season RAPM, hindsight ceiling) {l3:.4f} ({100*a3:.1f}%)')
    repl = -b2[4] / b2[3] if b2[3] else float('nan')
    print(f'  coefficients: value {b2[3]:+.2f} per point of (RAPM x minutes share), minutes share {b2[4]:+.2f}; implied replacement level {repl:+.1f} per 100 possessions; SIG {s2:.2f}')
    print(f'  example: a +4 RAPM player at 34 minutes costs {-(b2[3]*4 + b2[4])*34/48:.1f} points of margin when out; a 0 RAPM player at 20 minutes {-(b2[4])*20/48:.1f}')
    if a.write:
        gm = {'K': int(K), 'PW': float(PW), 'GAP': round(float(beta_r[0]), 3), 'HCA': round(float(beta_r[1]), 2), 'B2B': round(float(beta_r[2]), 2), 'SIG': round(float(sig_r), 2),
              'avail': {'value': round(float(b2[3]), 3), 'mins': round(float(b2[4]), 3), 'repl': round(float(repl), 2), 'from': int(yrs[0])},
              'fit': (f'fit_gamemodel.py on the box scores of {years[0]-1}-{str(years[0])[2:]} to {years[-1]-1}-{str(years[-1])[2:]}: K and PW by held-out log loss over all seasons '
                      f'({base[0]:.4f} for the earlier K=10, PW=0.4; {ll:.4f} for the fit); GAP, HCA, B2B and SIG by least squares on the home margin over 2017-18 onward '
                      f'(held-out log loss {nl:.4f} without the rest term, {fl:.4f} with it, {pl:.4f} for the earlier constants); availability on {yrs[0]-1}-{str(yrs[0])[2:]} onward '
                      f'(held-out log loss {l0:.4f} without, {l2:.4f} with the previous-season RAPM of the regulars who sat out, {l3:.4f} with same-season RAPM)')}
        json.dump(gm, open(os.path.join(HERE, 'static', 'gamemodel.json'), 'w'), indent=1); print('\nwrote static/gamemodel.json:', json.dumps({k: v for k, v in gm.items() if k != 'fit'}))

if __name__ == '__main__': main()
