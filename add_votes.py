"""Add a season's award voting to static/votes.json from a saved Basketball-Reference awards page.

    python add_votes.py 2023 awards_2023.html          # the page saved from basketball-reference.com/awards/awards_2023.html

Every voting table on the page is read: MVP, Defensive Player, Rookie, Sixth Man, Most Improved and Clutch Player (each voter's
points for every player who received a vote, with the points possible), and the All-NBA, All-Defensive and All-Rookie team votes.
Names are matched to ESPN ids in that season's box scores (raw/box<year>.parquet); anything that does not match exactly one player
is reported, with the box-score names of the same surname, and must be added to ALIASES by hand. The file is laid out as
{"2023": {"mvp": {"max": 1000, "rows": [[pid, points], ...]}, "dpoy": {...}, "roy", "smoy", "mip", "clutch", "allnba", "alldef", "allrookie"}}.
Vote shares are the fitting target of the Defensive Player ballot model and calibrate the predicted vote shares on the Awards tab."""
import sys, re, json, os, html, unicodedata
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
# Basketball-Reference spellings that differ from ESPN's box-score names (normalized form -> ESPN's normalized form); checked by hand
ALIASES = {'darrell armstrong': 'darrel armstrong', 'walter herrmann': 'walter herrmann heinrich', 'gustavo ayon': 'gustavo alfonso ayon',
           'jeff taylor': 'jeffery taylor', 'marcelo huertas': 'marcelinho huertas', 'ron holland': 'ronald holland'}
# the page's table ids and the names used in votes.json
TABLES = {'mvp': 'mvp', 'dpoy': 'dpoy', 'roy': 'roy', 'smoy': 'smoy', 'mip': 'mip', 'clutch_poy': 'clutch', 'leading_all_nba': 'allnba', 'leading_all_defense': 'alldef', 'leading_all_rookie': 'allrookie'}
def norm(s):
    s = str(s).replace('\u0131', 'i').replace('\u00f8', 'o').replace('\u0142', 'l').replace('\u0111', 'd')   # letters that have no accent-stripped form (dotless i, o-slash, l-stroke, d-stroke)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower(); s = re.sub(r"[^a-z ]", "", s.replace('-', ' ').replace('.', '').replace("'", ''))
    return ' '.join(t for t in s.split() if t not in ('jr', 'sr', 'ii', 'iii', 'iv'))
def parse(text, table_id='leading_all_defense'):
    """rows of (name, points won, points max) from one voting table, from either the raw HTML or a text/markdown copy of the page"""
    rows = []
    # 1) raw HTML: Basketball-Reference marks cells with data-stat attributes, and hides some tables inside HTML comments
    t = text.replace('<!--', '').replace('-->', '')
    seg = re.search(r'<table[^>]*id="%s"[^>]*>.*?</table>' % re.escape(table_id), t, re.S)
    if seg:
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', seg.group(0), re.S):
            name = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', tr); won = re.search(r'data-stat="points_won"[^>]*>([\d.]+)', tr); mx = re.search(r'data-stat="points_max"[^>]*>([\d.]+)', tr)
            if name and won and mx: rows.append((html.unescape(name.group(1)).strip(), float(won.group(1)), float(mx.group(1))))
        if rows: return rows
    # 2) a text copy of the All-Defensive section: markdown rows like "| 1st | F | [Evan Mobley](...) | 23 | [CLE](...) | 199 | 200 | 0.995 | ..."
    if table_id == 'leading_all_defense':
        seg = re.search(r'## All-Defensive Teams(.*?)All-Defensive Teams Table', text, re.S)
        if seg:
            for line in seg.group(1).splitlines():
                m = re.match(r'\|\s*\S+\s*\|\s*[A-Z-]*\s*\|\s*\[([^\]]+)\]\([^)]*\)\s*\|\s*\d+\s*\|\s*\[[A-Z]+\]\([^)]*\)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|', line)
                if m: rows.append((m.group(1).strip(), float(m.group(2)), float(m.group(3))))
    return rows
def main():
    year, path = int(sys.argv[1]), sys.argv[2]; raw = sys.argv[3] if len(sys.argv) > 3 else 'raw'
    text = open(path, encoding='utf-8', errors='ignore').read()
    tables = {name: parse(text, tid) for tid, name in TABLES.items()}; tables = {n: r for n, r in tables.items() if r}
    if not tables: sys.exit('no voting table found in that file')
    sys.path.insert(0, HERE); import nba_build
    b = pd.read_parquet(nba_build.fetch(raw, 'box', year), columns=['athlete_id', 'athlete_display_name', 'season_type']); b = b[(b.season_type == 2) & b.athlete_display_name.notna()]   # downloads the box scores if they are not in raw/ yet
    by = {}
    for pid, nm in b.drop_duplicates('athlete_id')[['athlete_id', 'athlete_display_name']].itertuples(index=False): by.setdefault(norm(nm), []).append(int(pid))
    out = {}; bad = {}
    for name, rows in tables.items():
        got = []
        for nm, won, mx in rows:
            n = norm(nm); c = by.get(ALIASES.get(n, n), [])
            if len(c) == 1: got.append([c[0], won])
            elif nm not in bad:
                last = n.split()[-1] if n else ''; near = sorted((k, v) for k, v in by.items() if k.split()[-1] == last)   # same last name, to make the fix easy
                bad[nm] = f"{nm} ({len(c)} matches; same last name in the box scores: {', '.join(f'{k} {v}' for k, v in near) or 'none'})"
        out[name] = {'max': rows[0][2], 'rows': got}
    if bad: sys.exit('no single match in the box scores for: ' + '; '.join(bad.values()) + ' (ESPN sometimes uses a different form of the name; add it to ALIASES and run again)')
    vp = os.path.join(HERE, 'static', 'votes.json'); votes = json.load(open(vp)) if os.path.exists(vp) else {}
    old = votes.get(str(year)) or {}
    if 'rows' in old: old = {'alldef': {'max': old['max'], 'rows': old['rows']}}   # the earlier layout held the All-Defensive votes alone
    old.update(out); votes[str(year)] = old
    json.dump(dict(sorted(votes.items())), open(vp, 'w'), separators=(',', ':'))
    print(f"{year-1}-{str(year)[2:]}: " + ', '.join(f"{n} {len(v['rows'])} vote-getters of {v['max']:g}" for n, v in out.items()))
if __name__ == '__main__': main()
