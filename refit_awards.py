"""Scores the award models against the real voting in static/votes.json, fits what can be fitted, and writes static/awardfit.json.

    python refit_awards.py            # report only
    python refit_awards.py --write    # also write static/awardfit.json (read by nba_build.py, awards_models.py and the page)

Needs the cached finished seasons (raw/season<year>.json) from a `--history 2003` build.

For each award with a ladder in awards_models.py (MVP, Defensive Player, Rookie, Sixth Man, Most Improved) and voting on file:
  - how the model's end-of-season ranking (no blending with earlier seasons) relates to the vote: where the real winner ranks,
    Spearman rank correlation among the vote-getters, and the share of all voting points that fall inside the model's eligible pool
  - a vote-share temperature tau: the within-season softmax p_i = exp(score_i/tau) / sum_j exp(score_j/tau) over the eligible pool
    that best reproduces the vote shares (points-weighted log-likelihood, each season weighted equally). The page uses it to turn
    each ladder's scores into a predicted share of the vote.
  - for MVP and Sixth Man, the team-record weight beta (score = Game Score per game + beta * (100 * T - 50)) is fitted jointly with
    tau, and tested by leaving each season out: beta chosen on the other seasons, winner and correlation scored on the held-out one.
Two-era Defensive Player ballot model: from 2017-18 the build has defensive RAPM and opponent rim shooting on/off. A vote-share fit
that adds them is compared, on those seasons held out one at a time, with the six-feature fit used on the page."""
import argparse, json, os, sys
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import awards_models, refit_defmodel as R
from bootstrap import bootstrap_report

def softmax_ll(scores_by_season, tau):
    """points-weighted log-likelihood of the vote shares under the within-season softmax, each season weighted 1"""
    ll = 0.0
    for s, q in scores_by_season:
        z = s / tau; z = z - z.max(); p = np.exp(z); p /= p.sum(); ll += q @ np.log(p + 1e-300)
    return ll

def fit_tau(scores_by_season):
    r = minimize_scalar(lambda lt: -softmax_ll(scores_by_season, np.exp(lt)), bounds=(-4, 5), method='bounded'); return float(np.exp(r.x))

def pool_rows(M, award, k, votes, beta=None, mipfit=None):
    """(scores, vote points, pids, points-in-pool share) for the award's eligible pool in season k"""
    if award == 'mvp': lst = mvp_with_beta(M, k, beta)
    elif award == 'smoy': lst = smoy_with_beta(M, k, beta)
    elif award == 'dpoy': lst = M.dpoy(k, False)
    elif award == 'roy': lst = M.roy(k)
    elif award == 'mip': lst = M.mip(k, mipfit)
    pts = {pid: p for pid, p in votes[k][award]['rows']}
    sc = np.array([r['score'] for r in lst], float); pid = np.array([r['p']['pid'] for r in lst]); pv = np.array([pts.get(p, 0.0) for p in pid], float)
    cover = pv.sum() / max(sum(pts.values()), 1e-9)
    return sc, pv, pid, cover

def mvp_with_beta(M, k, beta):
    S = M.SEAS[k]
    return M.sort_out([{'p': p, 'score': M.gs(p)/p['gp'] + beta*(100*M.team_T(k, p['team'], False) - 50)} for p in S['players'] if M.gp_ok(p, S) and p['min']/p['gp'] >= 25])

def smoy_with_beta(M, k, beta):
    S = M.SEAS[k]
    return M.sort_out([{'p': p, 'score': M.gs(p)/p['gp'] + beta*(100*M.team_T(k, p['team'], False) - 50)} for p in S['players'] if M.gp_ok(p, S) and p['min']/p['gp'] >= 15 and p['gst']/p['gp'] < 0.5])

def season_metrics(sc, pv):
    """winner rank (the vote leader's rank in the model), Spearman among vote-getters"""
    order = np.argsort(-sc, kind='stable'); rank = np.empty(len(sc), int); rank[order] = np.arange(1, len(sc) + 1)
    w = int(np.argmax(pv)) if pv.max() > 0 else None; g = pv > 0
    return (int(rank[w]) if w is not None else None), (spearmanr(sc[g], pv[g]).correlation if g.sum() > 2 else np.nan)

def fit_beta_tau(M, award, seasons, votes):
    """beta on a grid, tau optimised for each, by the softmax log-likelihood"""
    best = None
    for beta in np.round(np.arange(0.0, 0.81, 0.02), 2):
        rows = []
        for k in seasons:
            sc, pv, _, _ = pool_rows(M, award, k, votes, beta=beta)
            if pv.sum() > 0: rows.append((sc, pv / pv.sum()))
        tau = fit_tau(rows); ll = softmax_ll(rows, tau)
        if best is None or ll > best[2]: best = (float(beta), tau, ll)
    return best

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', default='raw'); ap.add_argument('--write', action='store_true'); a = ap.parse_args()
    M = R.load_models(a.raw); votes = json.load(open(os.path.join(HERE, 'static', 'votes.json')))
    mipfit = M.mip_fit(); fit = {}
    print('seasons with voting on file:', ', '.join(f"{k} ({len(votes[k])} tables)" for k in sorted(votes)))
    # ---- 1. each model against its voting, as the page runs it today
    print('\n== The models against the real vote (end-of-season rankings, no blending) ==')
    print(f"{'award':8s} {'seasons':>7s} {'winner #1':>9s} {'top 3':>6s} {'median rank':>11s} {'rho (voters)':>12s} {'points in pool':>14s} {'tau':>7s}")
    for award in ('mvp', 'dpoy', 'roy', 'smoy', 'mip'):
        seasons = [k for k in M.KEYS if k in votes and award in votes[k] and k in M.AW]
        if award in ('roy', 'mip'): seasons = [k for k in seasons if M.KEYS.index(k) > 0]
        ranks = []; rhos = []; covers = []; rows = []
        for k in seasons:
            sc, pv, _, cover = pool_rows(M, award, k, votes, beta=awards_models.BETA, mipfit=mipfit)
            r1, rho = season_metrics(sc, pv); ranks.append(r1); rhos.append(rho); covers.append(cover)
            if pv.sum() > 0: rows.append((sc, pv / pv.sum()))
        tau = fit_tau(rows); fit[award] = {'tau': round(tau, 4), 'seasons': len(seasons)}
        rk = [r for r in ranks if r is not None]
        print(f"{award:8s} {len(seasons):>7d} {sum(1 for r in rk if r == 1):>5d}/{len(seasons):<3d} {sum(1 for r in rk if r <= 3):>6d} {np.median(rk):>11.1f} {np.nanmean(rhos):>12.3f} {np.mean(covers):>13.0%} {tau:>7.3f}")
    # ---- 2. the team-record weight for MVP and Sixth Man, held out season by season
    print('\n== Team-record weight beta (score = Game Score per game + beta * (100*T - 50)); the page uses 0.2 ==')
    for award in ('mvp', 'smoy'):
        seasons = [k for k in M.KEYS if k in votes and award in votes[k] and k in M.AW]
        res = {'page (beta=0.2)': [], 'fitted beta (held out)': []}; chosen = []
        for k in seasons:
            others = [s for s in seasons if s != k]; beta_k, _, _ = fit_beta_tau(M, award, others, votes); chosen.append(beta_k)
            for name, beta in (('page (beta=0.2)', awards_models.BETA), ('fitted beta (held out)', beta_k)):
                sc, pv, _, _ = pool_rows(M, award, k, votes, beta=beta); res[name].append(season_metrics(sc, pv))
        beta_all, tau_all, _ = fit_beta_tau(M, award, seasons, votes); fit[award].update({'beta': beta_all, 'tau': round(fit_tau([(pool_rows(M, award, k, votes, beta=beta_all)[0], pool_rows(M, award, k, votes, beta=beta_all)[1] / max(pool_rows(M, award, k, votes, beta=beta_all)[1].sum(), 1e-9)) for k in seasons]), 4)})
        print(f"{award}: beta fitted on all {len(seasons)} seasons = {beta_all:.2f} (held-out choices ranged {min(chosen):.2f} to {max(chosen):.2f}), tau = {fit[award]['tau']:.3f}")
        for name, r in res.items():
            rk = [x[0] for x in r if x[0] is not None]
            print(f"   {name:24s} winner #1 in {sum(1 for x in rk if x == 1)}/{len(seasons)}, top 3 in {sum(1 for x in rk if x <= 3)}, median rank {np.median(rk):.1f}, rho among voters {np.nanmean([x[1] for x in r]):.3f}")
        r0, r1 = res['page (beta=0.2)'], res['fitted beta (held out)']
        v1 = bootstrap_report(f'   bootstrap: fitted beta vs 0.2, rank correlation', [b[1] - a_[1] for a_, b in zip(r0, r1)], 'rho')
        v2 = bootstrap_report(f'   bootstrap: fitted beta vs 0.2, winner ranked first', [int(b[0] == 1) - int(a_[0] == 1) for a_, b in zip(r0, r1)], 'win')
        fit[award]['verdict'] = v1 if v1 == 'ADOPT' or v2 == 'ADOPT' else ('SMALL' if 'SMALL' in (v1, v2) else 'NOISE')
        if fit[award]['verdict'] == 'NOISE':
            print(f'   -> the fitted beta is not distinguishable from 0.2 over these seasons; --write keeps 0.2 for {award}'); fit[award]['beta'] = 0.2
            fit[award]['tau'] = round(fit_tau([(pr[0], pr[1] / max(pr[1].sum(), 1e-9)) for pr in (pool_rows(M, award, k, votes, beta=0.2) for k in seasons)]), 4)   # the temperature goes with the weight in use
    # ---- 3. two-era Defensive Player ballot model
    print('\n== Two-era Defensive Player ballot model (adds defensive RAPM and opponent rim shooting on/off from 2017-18) ==')
    all_seasons = [k for k in M.KEYS if k in M.AW and int(k) >= 2004]; vote_seasons = [k for k in all_seasons if k in votes and 'alldef' in votes[k]]
    alld = {k: votes[k]['alldef'] for k in vote_seasons}
    K, P, X, Y, PTS, SH = R.design(M, all_seasons, alld); mu = X.mean(0); sd = X.std(0); Z = (X - mu) / sd
    recent = [k for k in vote_seasons if M.has_rim(k) and int(k) >= 2018]   # lineups (and so RAPM and rim on/off) are rebuilt from 2017-18; two earlier seasons have a single game of them
    extra = []
    for k, pid in zip(K, P):
        if k in recent:
            rd, rf = M.rim(k, pid); r = M.RAPM[k].get(str(pid)); extra.append([-r[1] if r else 0.0, rd, rf])
        else: extra.append([0.0, 0.0, 0.0])
    E = np.array(extra, float); rec = np.isin(K, recent); mu9 = np.r_[mu, E[rec].mean(0)]; sd9 = np.r_[sd, E[rec].std(0)]
    Z9 = np.c_[Z, (E - E[rec].mean(0)) / E[rec].std(0)]
    cols9 = R.COLS + ['drapm', 'rimds', 'rimdfg']
    res = {'six features (fitted on the other 22 seasons)': [], 'nine features (fitted on the other recent seasons)': []}; w9s = []
    for k in recent:
        tr6 = (K != k) & np.isin(K, vote_seasons); w6 = R.fit_share(Z[tr6], SH[tr6], 0.1)
        tr9 = (K != k) & rec; w9 = R.fit_share(Z9[tr9], SH[tr9], 0.1); w9s.append(w9)
        for name, D in (('six features (fitted on the other 22 seasons)', {'cols': R.COLS, 'mu': mu.tolist(), 'sd': sd.tolist(), 'w': list(map(float, w6))}),
                        ('nine features (fitted on the other recent seasons)', {'cols': cols9, 'mu': mu9.tolist(), 'sd': sd9.tolist(), 'w': list(map(float, w9))})):
            res[name].append(evaluate9(M, k, D, K, P, X, E, PTS))
    M.DEF = json.load(open(os.path.join(HERE, 'static', 'defmodel.json')))
    print(f"{len(recent)} seasons with the extra features: {', '.join(recent)}")
    for name, r in res.items():
        hits = sum(x['hits'] for x in r); d1 = sum(1 for x in r if x['dpoy'] == 1); d3 = sum(1 for x in r if x['dpoy'] is not None and x['dpoy'] <= 3)
        print(f"   {name:52s} selections found {hits}/{10*len(recent)} ({100*hits/(10*len(recent)):.0f}%), DPOY #1 in {d1}, top 3 in {d3}, rho among voters {np.nanmean([x['rho'] for x in r]):.3f}")
    w9 = R.fit_share(Z9[rec], SH[rec], 0.1)
    print('   nine-feature weights on all recent seasons: ' + ', '.join(f'{c} {w:+.3f}' for c, w in zip(cols9, w9)))
    r6, r9 = res['six features (fitted on the other 22 seasons)'], res['nine features (fitted on the other recent seasons)']
    v_sel = bootstrap_report('   bootstrap: nine vs six features, selections found', [b['hits'] - a_['hits'] for a_, b in zip(r6, r9)], 'sel')
    v_rho = bootstrap_report('   bootstrap: nine vs six features, rank correlation', [b['rho'] - a_['rho'] for a_, b in zip(r6, r9)], 'rho')
    two_era_ok = 'ADOPT' in (v_sel, v_rho)
    if not two_era_ok: print('   -> the recent-era block does not clear the bar; --write leaves defmodel.json without it')
    fit['two_era'] = {'recent_seasons': recent, 'six': {'hits': sum(x['hits'] for x in res['six features (fitted on the other 22 seasons)'])}, 'nine': {'hits': sum(x['hits'] for x in res['nine features (fitted on the other recent seasons)'])},
                      'nine_weights': {'cols': cols9, 'mu': mu9.tolist(), 'sd': sd9.tolist(), 'w': list(map(float, w9))}}
    if a.write:
        out = {k: v for k, v in fit.items() if k != 'two_era'}
        out['note'] = ('tau: within-season softmax temperature turning each ladder\u2019s scores into a predicted share of the vote, fitted on the real voting '
                       'in static/votes.json by refit_awards.py; beta: the team-record weight of the MVP and Sixth Man scores, fitted the same way. The page reads this block as L.awardfit.')
        json.dump(out, open(os.path.join(HERE, 'static', 'awardfit.json'), 'w'), indent=1); print('\nwrote static/awardfit.json:', json.dumps(out))
        dm = json.load(open(os.path.join(HERE, 'static', 'defmodel.json')))
        if not two_era_ok: dm.pop('recent', None); json.dump(dm, open(os.path.join(HERE, 'static', 'defmodel.json'), 'w')); print('removed the recent-era block from static/defmodel.json'); return fit
        dm['recent'] = dict(fit['two_era']['nine_weights'], **{'from': int(recent[0]), 'fit': f"fractional logistic regression on All-Defensive vote shares of {int(recent[0])-1}-{recent[0][2:]} to {int(recent[-1])-1}-{recent[-1][2:]} with defensive RAPM and opponent rim shooting on/off added to the six ballot features, C=0.1; held out season by season it found {fit['two_era']['nine']['hits']} of {10*len(recent)} selections against {fit['two_era']['six']['hits']} for the six-feature fit"})
        json.dump(dm, open(os.path.join(HERE, 'static', 'defmodel.json'), 'w')); print('wrote the recent-era block into static/defmodel.json')
    return fit

def evaluate9(M, k, D, K, P, X, E, PTS):
    """score season k with weights D over the six features plus, when D has nine columns, the three recent-era features"""
    M.DEF = D
    if len(D['cols']) > 6:
        # the Models.dscore path handles only the six ballot features; score directly from the design rows
        i = K == k; sc = np.array([sum(w*(x-m)/s for x, m, s, w in zip(list(row) + list(e), D['mu'], D['sd'], D['w'])) for row, e in zip(X[i], E[i])])
        S = M.SEAS[k]; by = {p['pid']: p for p in S['players']}; lst = M.sort_out([{'p': by[pid], 'score': float(s)} for pid, s in zip(P[i], sc)])
        M.DEF = {'cols': D['cols'], 'mu': D['mu'], 'sd': D['sd'], 'w': D['w']}
        # the All-Defensive teams from this ranking (positional rule through 2022-23), via a temporary dpoy override
        orig = M.dpoy; M.dpoy = lambda kk, blend=False: lst
        try: hits = M.team_hits(M.alldef(k), k, ['ad1', 'ad2'])[0]; dp = M.rank_of(lst, M.winner(k, 'dpoy'))
        finally: M.dpoy = orig
        pv = PTS[i]; g = pv > 0
        return {'hits': hits, 'dpoy': dp, 'rho': spearmanr(sc[g], pv[g]).correlation if g.sum() > 2 else np.nan}
    r = R.evaluate(M, k, D, K, P, X, PTS, True); return {'hits': r['hits'], 'dpoy': r['dpoy'], 'rho': r['rho_voters']}

if __name__ == '__main__': main()
