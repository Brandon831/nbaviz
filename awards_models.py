"""The award models, in Python, over every season the build knows (the embedded ones and the archive).
nba_build.py uses this to fit the Most Improved regression on all finished seasons and to write the historical scorecard
shown on the About tab. The page's JavaScript implements the same models; they are checked against each other."""
import json, math
import numpy as np
F = 'pid name team gp min pts fgm fga tpm tpa ftm fta oreb dreb reb ast stl blk tov pf gst'.split()
HW = (5, 3, 2); GCAP = 60; K = 10; KT = 15; BETA = 0.2
MIP = {'cap': 16, 'prevfrac': 0.5, 'prevmpg': 10, 'minmpg': 24}

class Models:
    def __init__(self, shot, leaders, archive, awards, defmodel):
        """shot/leaders: the page's two data blocks; archive: {end-year: season payload} for older seasons; awards: static/awards.json; defmodel: static/defmodel.json"""
        self.AW = awards; self.DEF = defmodel
        cur = leaders['key']
        self.KEYS = sorted(set(archive) | set(leaders['hist']) | {cur})
        def src(k):
            if k in archive: return archive[k]['hist']
            return leaders if k == cur else leaders['hist'][k]
        self.SEAS = {k: {'players': [dict(zip(F, a)) for a in src(k)['players']], 'tg': src(k)['tg'], 'maxg': src(k)['maxg'], 'pos': src(k).get('pos', {})} for k in self.KEYS}
        self.use_rep = True
        self.TEAMS = {k: (archive[k]['teams'] if k in archive else leaders['teams'][k]) for k in self.KEYS}
        self.ONOFF = {k: (archive[k].get('onoff') if k in archive else (leaders.get('onoff') or {}).get(k)) or {} for k in self.KEYS}
        self.STAND = {k: (archive[k]['shot']['stand'] if k in archive else shot['seasons'][k]['stand']) for k in self.KEYS}
        self.TD = {k: self._tdef(k) for k in self.KEYS}
        self.cur = cur
    # ---- helpers
    @staticmethod
    def gs(p): return p['pts']+0.4*p['fgm']-0.7*p['fga']-0.4*(p['fta']-p['ftm'])+0.7*p['oreb']+0.3*p['dreb']+p['stl']+0.7*p['ast']+0.7*p['blk']-0.4*p['pf']-p['tov']
    def gp_ok(self, p, S): return p['pid'] != 99999999 and p['gp'] >= max(1, math.ceil(0.7 * S['tg'].get(p['team'], S['maxg'])))
    def prev_keys(self, k): i = self.KEYS.index(k); return self.KEYS[max(0, i-3):i][::-1]
    def record(self, k, team): s = self.STAND[k].get(team); return (s['w'], s['l']) if s else (0, 0)
    def team_T(self, k, team, blend):
        pk = self.prev_keys(k); q = 0.5
        if blend and pk:
            s = self.STAND[pk[0]].get(team)
            if s and s['w'] + s['l']: q = s['w'] / (s['w'] + s['l'])
        W, L = self.record(k, team); return (W + KT*q) / (W + L + KT)
    def blended(self, k, fn, blend, nohist):
        hist = {}
        if blend:
            for j, pk in enumerate(self.prev_keys(k)):
                for p in self.SEAS[pk]['players']:
                    if p['gp'] >= 1: hist.setdefault(p['pid'], []).append((HW[j]*min(p['gp'], GCAP)/GCAP, fn(pk, p)))
        def f(p):
            cur = fn(k, p)
            if not blend: return cur
            h = hist.get(p['pid'], []); ws = sum(w for w, _ in h); prior = nohist if not ws > 0 else sum(w*v for w, v in h)/ws
            w = p['gp'] / (p['gp'] + K); return w*cur + (1-w)*prior
        return f
    @staticmethod
    def sort_out(out): return sorted(out, key=lambda r: (-math.floor(r['score']*1e9+0.5), r['p']['name']))
    def _tdef(self, k):
        t = self.TEAMS[k]; lg = sum(v[0]*v[2] for v in t.values()) / sum(v[2] for v in t.values()); return {tm: lg - v[0] for tm, v in t.items()}
    # ---- the models
    def mvp(self, k, blend=True):
        S = self.SEAS[k]; f = self.blended(k, lambda kk, p: self.gs(p)/p['gp'], blend, 8.0)
        return self.sort_out([{'p': p, 'score': f(p) + BETA*(100*self.team_T(k, p['team'], blend) - 50)} for p in S['players'] if self.gp_ok(p, S) and p['min']/p['gp'] >= 25])
    def past_alldef(self, k, pid):
        """was the player on an All-Defensive team in any of the three previous seasons"""
        for j in (1, 2, 3):
            if any(q == pid and t in ('ad1', 'ad2') for q, t in self.AW.get(str(int(k) - j), [])): return 1
        return 0
    def rim(self, k, pid):
        o = self.ONOFF[k].get(str(pid))
        if not o or len(o) < 17 or o[11] < 50 or o[14] < 50: return [0.0, 0.0]
        w = o[1] / (o[1] + 500 * 60.0); return [(o[15]/o[14] - o[12]/o[11]) * w, ((o[16]/max(o[15], 1)) - (o[13]/max(o[12], 1))) * w]
    def has_rim(self, k):
        for o in self.ONOFF[k].values(): return len(o) >= 17
        return False
    def dscore(self, k, p):
        x = {'blk': p['blk']/p['gp'], 'stl': p['stl']/p['gp'], 'dreb': p['dreb']/p['gp'], 'mpg': p['min']/p['gp'], 'tdef': self.TD[k].get(p['team'], 0.0), 'rep': self.past_alldef(k, p['pid'])}
        if self.use_rep and 'rep' in self.DEF['cols']: D = self.DEF
        elif 'stats_rim' in self.DEF and self.has_rim(k): D = self.DEF['stats_rim']; x['rimds'], x['rimdfg'] = self.rim(k, p['pid'])
        else: D = self.DEF.get('stats', self.DEF)
        return sum(w*(x[c]-m)/s for c, m, s, w in zip(D['cols'], D['mu'], D['sd'], D['w']))
    def alldef(self, k, blend=False):
        """two guards, two forwards and a center per team through 2022-23 (the voting rule then); the ten best regardless of position from 2023-24"""
        lst = self.dpoy(k, blend)
        if int(k) > 2023: return lst[:10]
        pos = self.SEAS[k].get('pos', {}); teams = [{'G': 2, 'F': 2, 'C': 1}, {'G': 2, 'F': 2, 'C': 1}]; out = [[], []]
        for r in lst:
            g = pos.get(str(r['p']['pid']), 'F')
            for t in (0, 1):
                if teams[t][g] > 0: out[t].append(r); teams[t][g] -= 1; break
            if len(out[0]) + len(out[1]) == 10: break
        return out[0] + out[1]
    def dpoy(self, k, blend=False):
        S = self.SEAS[k]; f = self.blended(k, self.dscore, blend, 0.0)
        return self.sort_out([{'p': p, 'score': f(p)} for p in S['players'] if self.gp_ok(p, S) and p['min']/p['gp'] >= 20])
    def roy(self, k, frac=0.7):
        S = self.SEAS[k]; i = self.KEYS.index(k)
        if i == 0: return []
        seen = {p['pid'] for z in self.KEYS[:i] for p in self.SEAS[z]['players'] if p['gp'] >= 1}
        return self.sort_out([{'p': p, 'score': self.gs(p)/p['gp']} for p in S['players'] if p['pid'] not in seen and p['gp'] >= max(1, math.ceil(frac*S['tg'].get(p['team'], S['maxg']))) and p['min']/p['gp'] >= 15])
    def smoy(self, k, blend=True):
        S = self.SEAS[k]
        return self.sort_out([{'p': p, 'score': self.gs(p)/p['gp'] + BETA*(100*self.team_T(k, p['team'], blend) - 50)} for p in S['players'] if self.gp_ok(p, S) and p['min']/p['gp'] >= 15 and p['gst']/p['gp'] < 0.5])
    def per(self, p): return {'gs': self.gs(p)/p['gp'], 'mpg': p['min']/p['gp'], 'gp': p['gp']}
    def mip_fit(self, seasons=None):
        """the expected change in Game Score per game given last year's level, from all finished seasons with a season before them"""
        seasons = seasons or [k for k in self.KEYS[1:] if k != self.cur]; X = []; Y = []
        for k in seasons:
            i = self.KEYS.index(k); last = {p['pid']: self.per(p) for p in self.SEAS[self.KEYS[i-1]]['players'] if p['gp'] >= 40}
            for p in self.SEAS[k]['players']:
                b = last.get(p['pid'])
                if b and p['gp'] >= 40 and b['mpg'] >= 10: X.append(b['gs']); Y.append(self.per(p)['gs'] - b['gs'])
        b1, a = np.polyfit(np.array(X), np.array(Y), 1); return {'a': float(a), 'b': float(b1), 'n': len(X), 'seasons': len(seasons)}
    def mip(self, k, fit, resid=True):
        S = self.SEAS[k]; i = self.KEYS.index(k)
        if i == 0: return []
        prev = self.SEAS[self.KEYS[i-1]]; need = math.ceil(MIP['prevfrac'] * (prev['maxg'] or 82)); last = {p['pid']: self.per(p) for p in prev['players'] if p['gp'] >= 1}; out = []
        for p in S['players']:
            if not self.gp_ok(p, S) or p['min']/p['gp'] < MIP['minmpg']: continue
            bb = last.get(p['pid'])
            if not bb or bb['gp'] < need or bb['mpg'] < MIP['prevmpg'] or bb['gs'] >= MIP['cap']: continue
            d = self.per(p)['gs'] - bb['gs']; exp = fit['a'] + fit['b']*bb['gs']; out.append({'p': p, 'score': (d - exp) if resid else d})
        return self.sort_out(out)
    def clutch(self, k, rows):
        """rows: [pid, pts, fgm, fga, ftm, fta, ast, tov, games] clutch totals; same formula as the page"""
        S = self.SEAS[k]; by = {p['pid']: p for p in S['players']}; out = []
        for pid, pts, fgm, fga, ftm, fta, ast, tov, g in rows:
            p = by.get(pid)
            if not p or not self.gp_ok(p, S): continue
            out.append({'p': p, 'score': pts + 0.7*ast - tov - 0.7*(fga - fgm) - 0.4*(fta - ftm)})
        return self.sort_out(out)
    # ---- scoring against the real awards
    def winner(self, k, t): r = [pid for pid, tt in self.AW.get(k, []) if tt == t]; return r[0] if r else None
    @staticmethod
    def rank_of(lst, pid): ids = [r['p']['pid'] for r in lst]; return ids.index(pid)+1 if pid in ids else None
    def team_hits(self, lst, k, tiers):
        ids = [r['p']['pid'] for r in lst]; act = [{pid for pid, tt in self.AW.get(k, []) if tt == t} for t in tiers]; allp = set().union(*act)
        return [len(set(ids) & allp), sum(len(set(ids[i*5:i*5+5]) & act[i]) for i in range(len(tiers))), len(allp)]
    def backtest(self, fit):
        """one row per finished season with real awards: where each winner ranked and how many team selections the models found"""
        rows = []
        for k in self.KEYS:
            if k == self.cur or k not in self.AW: continue
            first = self.KEYS.index(k) == 0
            r = {'k': k, 'mvp': self.rank_of(self.mvp(k), self.winner(k, 'mvp')), 'dpoy': self.rank_of(self.dpoy(k), self.winner(k, 'dpoy')),
                 'smoy': self.rank_of(self.smoy(k), self.winner(k, 'smoy')),
                 'roy': None if first else self.rank_of(self.roy(k), self.winner(k, 'roy')), 'mip': None if first else self.rank_of(self.mip(k, fit), self.winner(k, 'mip')),
                 'an': self.team_hits(self.mvp(k)[:15], k, ['an1', 'an2', 'an3']), 'ad': self.team_hits(self.alldef(k), k, ['ad1', 'ad2']),
                 'ar': None if first else self.team_hits(self.roy(k, 0.5)[:10], k, ['ar1', 'ar2']),
                 'winners': {t: self.winner(k, t) for t in ('mvp', 'dpoy', 'roy', 'smoy', 'mip')}}
            rows.append(r)
        return rows
