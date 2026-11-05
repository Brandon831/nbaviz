"""Add a season's All-Defensive voting points to static/votes.json from a saved Basketball-Reference awards page.

    python add_votes.py 2023 awards_2023.html          # the page saved from basketball-reference.com/awards/awards_2023.html

The page's "All-Defensive Teams" table lists every player who received a vote with points won and points possible.
Names are matched to ESPN ids in that season's box scores (raw/box<year>.parquet); anything that does not match exactly one
player is reported and must be fixed by hand. Entries look like {"2023": {"award": "alldef", "max": 200, "rows": [[pid, points], ...]}}.
Vote shares are a richer target than yes/no selections for fitting the ballot model (see README, 'Step 3')."""
import sys, re, json, os, html, unicodedata
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
# Basketball-Reference spellings that differ from ESPN's box-score names (normalized form -> ESPN's normalized form); checked by hand
ALIASES = {'darrell armstrong': 'darrel armstrong'}
def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower(); s = re.sub(r"[^a-z ]", "", s.replace('-', ' ').replace('.', '').replace("'", ''))
    return ' '.join(t for t in s.split() if t not in ('jr', 'sr', 'ii', 'iii', 'iv'))
def parse(text):
    """rows of (name, points won, points max) from the All-Defensive table, from either the raw HTML or a text/markdown copy of the page"""
    rows = []
    # 1) raw HTML: Basketball-Reference marks cells with data-stat attributes, and hides some tables inside HTML comments
    t = text.replace('<!--', '').replace('-->', '')
    seg = re.search(r'id="leading_all_defense".*?</table>', t, re.S)
    if seg:
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', seg.group(0), re.S):
            name = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', tr); won = re.search(r'data-stat="points_won"[^>]*>([\d.]+)', tr); mx = re.search(r'data-stat="points_max"[^>]*>([\d.]+)', tr)
            if name and won and mx: rows.append((html.unescape(name.group(1)).strip(), float(won.group(1)), float(mx.group(1))))
        if rows: return rows
    # 2) a text copy: markdown table rows like "| 1st | F | [Evan Mobley](...) | 23 | [CLE](...) | 199 | 200 | 0.995 | ..."
    seg = re.search(r'## All-Defensive Teams(.*?)All-Defensive Teams Table', text, re.S)
    if seg:
        for line in seg.group(1).splitlines():
            m = re.match(r'\|\s*\S+\s*\|\s*[A-Z-]*\s*\|\s*\[([^\]]+)\]\([^)]*\)\s*\|\s*\d+\s*\|\s*\[[A-Z]+\]\([^)]*\)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|', line)
            if m: rows.append((m.group(1).strip(), float(m.group(2)), float(m.group(3))))
    return rows
def main():
    year, path = int(sys.argv[1]), sys.argv[2]; raw = sys.argv[3] if len(sys.argv) > 3 else 'raw'
    rows = parse(open(path, encoding='utf-8', errors='ignore').read())
    if not rows: sys.exit('no All-Defensive voting table found in that file')
    sys.path.insert(0, HERE); import nba_build
    b = pd.read_parquet(nba_build.fetch(raw, 'box', year), columns=['athlete_id', 'athlete_display_name', 'season_type']); b = b[(b.season_type == 2) & b.athlete_display_name.notna()]   # downloads the box scores if they are not in raw/ yet
    by = {}
    for pid, n in b.drop_duplicates('athlete_id')[['athlete_id', 'athlete_display_name']].itertuples(index=False): by.setdefault(norm(n), []).append(int(pid))
    out = []; bad = []
    for name, won, mx in rows:
        n = norm(name); c = by.get(ALIASES.get(n, n), [])
        if len(c) == 1: out.append([c[0], won])
        else:
            last = n.split()[-1] if n else ''; near = sorted((k, v) for k, v in by.items() if k.split()[-1] == last)   # same last name, to make the fix easy
            bad.append(f"{name} ({len(c)} matches; same last name in the box scores: {', '.join(f'{k} {v}' for k, v in near) or 'none'})")
    if bad: sys.exit('no single match in the box scores for: ' + '; '.join(bad) + ' (ESPN sometimes uses a different form of the name; add it to ALIASES and run again)')
    vp = os.path.join(HERE, 'static', 'votes.json'); votes = json.load(open(vp)) if os.path.exists(vp) else {}
    votes[str(year)] = {'award': 'alldef', 'max': rows[0][2], 'rows': out}
    json.dump(dict(sorted(votes.items())), open(vp, 'w')); print(f'added {len(out)} vote-getters for {year-1}-{str(year)[2:]} (points out of {rows[0][2]:.0f})')
if __name__ == '__main__': main()
