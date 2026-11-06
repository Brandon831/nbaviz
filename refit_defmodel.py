"""Refits the ballot model of the Defensive Player panel and tests it by holding each season out in turn.

    python refit_defmodel.py                  # compare the binary fit (real All-Defensive selections) with the vote-share fit (static/votes.json)
    python refit_defmodel.py --write          # also write the chosen fit into static/defmodel.json (ballot weights only)

Needs the finished seasons cached in raw/season<year>.json, which `python nba_build.py --history 2003` writes (or build_payloads from a
console: nba_build.season_payload('raw', year)). The design matrix is the one awards_models.Models.dscore uses (blocks, steals and
defensive rebounds per game, minutes per game, team defence against the league, and whether the player made an All-Defensive team
in the previous three seasons), over the players the Defensive Player ladder considers (70% of team games and 20 minutes a game).

Two targets are compared on the same held-out seasons:
  binary       1 if the player made an All-Defensive team, else 0 (logistic regression, C=0.1): the model the page has used so far
  vote share   the player's All-Defensive voting points divided by the points possible, 0 for players who got no vote
               (fractional logistic regression, same C): every vote-getter contributes, not just the ten selections
Scores reported per held-out season: real All-Defensive selections found by the model's ten picks (positional rule through 2022-23),
where the real Defensive Player of the Year ranked, and Spearman rank correlation between the model score and the vote points,
both among the players who received votes and among every eligible player (non-vote-getters count as 0 points)."""
import argparse, json, os, sys
import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import awards_models
from bootstrap import bootstrap_report

def load_models(raw, first=2003, last=2026):
    """awards_models.Models over the cached finished seasons first..last, with `last` playing the part of the embedded season"""
    pay = {}
    for y in range(first, last + 1):
        c = json.load(open(os.path.join(raw, f'season{y}.json')))['data']; pay[str(y)] = c
    cur = pay[str(last)]; k = str(last)
    leaders = dict(cur['hist']); leaders.update({'key': k, 'hist': {}, 'teams': {k: cur['teams']}, 'rapm': {k: cur.get('rapm') or {}}, 'onoff': {k: cur.get('onoff') or {}}})
    shot = {'seasons': {k: cur['shot']}}
    archive = {y: pay[y] for y in pay if y != k}
    awards = json.load(open(os.path.join(HERE, 'static', 'awards.json'))); defm = json.load(open(os.path.join(HERE, 'static', 'defmodel.json')))
    return awards_models.Models(shot, leaders, archive, awards, defm)

COLS = ['blk', 'stl', 'dreb', 'mpg', 'tdef', 'rep']
def design(M, seasons, votes):
    """one row per eligible player-season: features, selected flag, vote points, vote share, season key, pid"""
    rows = []
    for k in seasons:
        S = M.SEAS[k]; vt = votes.get(k); pts = {pid: p for pid, p in vt['rows']} if vt else {}; mx = vt['max'] if vt else None
        sel = {pid for pid, t in M.AW.get(k, []) if t in ('ad1', 'ad2')}
        for p in S['players']:
            if not (M.gp_ok(p, S) and p['min'] / p['gp'] >= 20): continue
            x = [p['blk']/p['gp'], p['stl']/p['gp'], p['dreb']/p['gp'], p['min']/p['gp'], M.TD[k].get(p['team'], 0.0), M.past_alldef(k, p['pid'])]
            rows.append((k, p['pid'], x, int(p['pid'] in sel), float(pts.get(p['pid'], 0.0)), (pts.get(p['pid'], 0.0) / mx) if mx else np.nan))
    K = np.array([r[0] for r in rows]); P = np.array([r[1] for r in rows]); X = np.array([r[2] for r in rows], float)
    return K, P, X, np.array([r[3] for r in rows]), np.array([r[4] for r in rows]), np.array([r[5] for r in rows])

def fit_binary(Z, y, C=0.1):
    m = LogisticRegression(C=C, max_iter=5000, tol=1e-8); m.fit(Z, y); return m.coef_[0].copy()

def fit_share(Z, s, C=0.1):
    """fractional logistic regression: each row counts as a 1 with weight s and as a 0 with weight 1-s"""
    ZZ = np.vstack([Z, Z]); yy = np.r_[np.ones(len(Z)), np.zeros(len(Z))]; ww = np.r_[s, 1 - s] + 1e-12
    m = LogisticRegression(C=C, max_iter=5000, tol=1e-8); m.fit(ZZ, yy, sample_weight=ww); return m.coef_[0].copy()

def fit_softmax(Z, pts, keys, lam=1.0):
    """within-season softmax (conditional logit): a season's voting points are spread over its eligible players in proportion to
    exp(score); maximises the points-weighted log-likelihood (each season normalised to weight 1) with an L2 penalty lam*|w|^2/2"""
    from scipy.optimize import minimize
    groups = [np.where(keys == k)[0] for k in np.unique(keys)]; sh = [pts[g] / pts[g].sum() for g in groups]
    def f(w):
        val = 0.5 * lam * (w @ w); grad = lam * w
        for g, q in zip(groups, sh):
            z = Z[g] @ w; z -= z.max(); p = np.exp(z); p /= p.sum()
            val -= q @ np.log(p + 1e-300); grad += Z[g].T @ (p - q)
        return val, grad
    r = minimize(f, np.zeros(Z.shape[1]), jac=True, method='L-BFGS-B', options={'maxiter': 2000, 'gtol': 1e-9}); return r.x

def fit_ridge(Z, s, lam=1.0):
    Zc = np.c_[Z, np.ones(len(Z))]; A = Zc.T @ Zc + lam * np.diag([1]*Z.shape[1] + [0]); return np.linalg.solve(A, Zc.T @ s)[:-1]

def evaluate(M, k, D, K, P, X, pts, votes_present):
    """scores for season k under the model weights D"""
    M.DEF = D
    hits = M.team_hits(M.alldef(k), k, ['ad1', 'ad2'])[0]
    dp = M.rank_of(M.dpoy(k), M.winner(k, 'dpoy'))
    out = {'hits': hits, 'dpoy': dp}
    if votes_present:
        i = K == k; sc = np.array([sum(w*(x-m)/s for x, m, s, w in zip(row, D['mu'], D['sd'], D['w'])) for row in X[i]]); pv = pts[i]
        out['rho_all'] = spearmanr(sc, pv).correlation; g = pv > 0; out['rho_voters'] = spearmanr(sc[g], pv[g]).correlation if g.sum() > 2 else np.nan
        # how the ten with the most points (positionless) are found, as a check that is independent of the positional rule
        top = set(P[i][np.argsort(-pv)[:10]]); mine = set(P[i][np.argsort(-sc)[:10]]); out['top10'] = len(top & mine)
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', default='raw'); ap.add_argument('--write', action='store_true', help='write the vote-share weights into static/defmodel.json')
    ap.add_argument('--C', type=float, default=0.1); ap.add_argument('--grid', action='store_true', help='also try other C values and a linear fit')
    a = ap.parse_args()
    M = load_models(a.raw); votes = {k: v['alldef'] for k, v in json.load(open(os.path.join(HERE, 'static', 'votes.json'))).items() if 'alldef' in v}   # votes.json holds every award; the ballot model uses the All-Defensive table
    all_seasons = [k for k in M.KEYS if k in M.AW and int(k) >= 2004]; vote_seasons = [k for k in all_seasons if k in votes]
    K, P, X, Y, PTS, SH = design(M, all_seasons, votes)
    mu = X.mean(0); sd = X.std(0); Z = (X - mu) / sd
    print(f'design: {len(X)} player-seasons over {len(all_seasons)} seasons, {Y.sum()} selections; votes for {len(vote_seasons)} seasons: {", ".join(vote_seasons)}')
    cur = M.DEF; dm = np.abs(np.array(cur['mu']) - mu).max(); ds = np.abs(np.array(cur['sd']) - sd).max()
    print(f'standardisation against static/defmodel.json: max |mu diff| {dm:.2e}, max |sd diff| {ds:.2e}')
    w_bin_all = fit_binary(Z, Y, a.C); print('binary refit on all seasons vs stored weights: max |w diff| %.2e' % np.abs(w_bin_all - np.array(cur['w'])).max())
    mk = lambda w: {'cols': COLS, 'mu': mu.tolist(), 'sd': sd.tolist(), 'w': list(map(float, w))}
    variants = {'binary (C=%g)' % a.C: ('bin', a.C), 'vote share (C=%g)' % a.C: ('share', a.C)}
    if a.grid:
        for C in (0.03, 0.3, 1.0): variants['binary (C=%g)' % C] = ('bin', C); variants['vote share (C=%g)' % C] = ('share', C)
        variants['vote share, linear ridge'] = ('ridge', 1.0)
        for C in (0.1, 0.3): variants['sqrt vote share (C=%g)' % C] = ('sqrt', C)
        for lam in (0.03, 0.1, 0.3, 1.0): variants['softmax within season (lam=%g)' % lam] = ('softmax', lam)
    res = {v: {} for v in variants}; res['deployed binary (in sample)'] = {}
    for k in vote_seasons:
        tr_all = K != k; tr_v = tr_all & np.isin(K, vote_seasons)
        for name, (kind, C) in variants.items():
            if kind == 'bin': w = fit_binary(Z[tr_all], Y[tr_all], C)
            elif kind == 'share': w = fit_share(Z[tr_v], SH[tr_v], C)
            elif kind == 'sqrt': w = fit_share(Z[tr_v], np.sqrt(SH[tr_v]), C)
            elif kind == 'softmax': w = fit_softmax(Z[tr_v], PTS[tr_v], K[tr_v], C)
            else: w = fit_ridge(Z[tr_v], SH[tr_v], C)
            res[name][k] = evaluate(M, k, mk(w), K, P, X, PTS, True)
        res['deployed binary (in sample)'][k] = evaluate(M, k, cur, K, P, X, PTS, True)
    M.DEF = cur
    # ---- report
    nsel = 10 * len(vote_seasons)
    print(f'\nLeave-one-season-out over the {len(vote_seasons)} seasons with votes (the binary model is fitted on the other {len(all_seasons)-1} seasons with awards, the vote-share model on the other {len(vote_seasons)-1} seasons with votes):')
    print(f"{'model':34s} {'selections found':>18s} {'DPOY #1':>8s} {'DPOY top3':>10s} {'rho (voters)':>13s} {'rho (all)':>10s} {'top10 by pts':>13s}")
    for name, r in res.items():
        hits = sum(v['hits'] for v in r.values()); d1 = sum(1 for v in r.values() if v['dpoy'] == 1); d3 = sum(1 for v in r.values() if v['dpoy'] is not None and v['dpoy'] <= 3)
        rv = np.nanmean([v['rho_voters'] for v in r.values()]); ra = np.nanmean([v['rho_all'] for v in r.values()]); t10 = sum(v['top10'] for v in r.values())
        print(f'{name:34s} {hits:>7d}/{nsel:<4d} ({100*hits/nsel:4.1f}%) {d1:>8d} {d3:>10d} {rv:>13.3f} {ra:>10.3f} {t10:>7d}/{nsel}')
    print('\nPer season (selections found of 10 | DPOY rank | rho among voters):')
    names = list(res); print(' ' * 8 + ''.join(f'{n[:30]:>32s}' for n in names))
    for k in vote_seasons:
        print(f'{int(k)-1}-{k[2:]} ' + ''.join(f"{res[n][k]['hits']:>14d} | {str(res[n][k]['dpoy']):>3s} | {res[n][k]['rho_voters']:5.2f}   " for n in names))
    # ---- is the vote-share fit's gain over the yes/no fit bigger than the noise between seasons?
    bn, vs_ = 'binary (C=%g)' % a.C, 'vote share (C=%g)' % a.C
    print('\nBootstrap over seasons (gain of the vote-share fit over the yes/no fit):')
    bootstrap_report('  selections found', [res[vs_][k]['hits'] - res[bn][k]['hits'] for k in vote_seasons], 'sel')
    bootstrap_report('  rank correlation among voters', [res[vs_][k]['rho_voters'] - res[bn][k]['rho_voters'] for k in vote_seasons], 'rho')
    bootstrap_report('  real DPOY ranked first', [int(res[vs_][k]['dpoy'] == 1) - int(res[bn][k]['dpoy'] == 1) for k in vote_seasons], 'win')
    # ---- the final fits, on every season
    w_share_all = fit_share(Z[np.isin(K, vote_seasons)], SH[np.isin(K, vote_seasons)], a.C)
    print('\nweights (standardised features):'); print(f"{'':10s}" + ''.join(f'{c:>9s}' for c in COLS))
    print(f"{'binary':10s}" + ''.join(f'{v:9.3f}' for v in w_bin_all)); print(f"{'share':10s}" + ''.join(f'{v:9.3f}' for v in w_share_all))
    if a.write:
        dm = json.load(open(os.path.join(HERE, 'static', 'defmodel.json')))
        dm['cols'] = COLS; dm['mu'] = mu.tolist(); dm['sd'] = sd.tolist(); dm['w'] = list(map(float, w_share_all))
        nv = int((SH[np.isin(K, vote_seasons)] > 0).sum())
        dm['fit'] = (f'fractional logistic regression on All-Defensive vote shares (voting points divided by points possible, 0 without a vote) of '
                     f'{int(vote_seasons[0])-1}-{vote_seasons[0][2:]} to {int(vote_seasons[-1])-1}-{vote_seasons[-1][2:]} ({int(np.isin(K, vote_seasons).sum())} player-seasons, {nv} vote-getters, {int(Y[np.isin(K, vote_seasons)].sum())} selections), C={a.C}; '
                     f'rep = selected to an All-Defensive team in any of the previous three seasons; the binary fit on the same seasons was w = {[round(float(v), 4) for v in w_bin_all]}')
        json.dump(dm, open(os.path.join(HERE, 'static', 'defmodel.json'), 'w')); print('wrote static/defmodel.json (ballot weights); the stats and stats_rim blocks are unchanged')

if __name__ == '__main__': main()
