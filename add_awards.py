"""Add a finished season's award winners to static/awards.json from a file of names.

    python add_awards.py 2027 winners.json

winners.json looks like {"mvp": ["Name"], "dpoy": ["Name"], "roy": ["Name"], "smoy": ["Name"], "mip": ["Name"], "fmvp": ["Name"], "clutch": ["Name"],
 "an1": [5 names], "an2": [...], "an3": [...], "ad1": [...], "ad2": [...], "ar1": [...], "ar2": [...]}
Names are matched to ESPN ids in that season's box scores (raw/box<year>.parquet); anything that does not match exactly one player is reported
and must be fixed by hand. The season must not already be in awards.json."""
import sys, json, os, re, unicodedata
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace('-', ' ').replace('.', '').replace("'", ''))
    return ' '.join(t for t in s.split() if t not in ('jr', 'sr', 'ii', 'iii', 'iv'))
def main():
    year, names_path = int(sys.argv[1]), sys.argv[2]; raw = sys.argv[3] if len(sys.argv) > 3 else 'raw'
    names = json.load(open(names_path)); path = os.path.join(HERE, 'static', 'awards.json'); aw = json.load(open(path))
    if str(year) in aw: sys.exit(f'{year} is already in awards.json; remove it first if you mean to replace it')
    b = pd.read_parquet(os.path.join(raw, f'box{year}.parquet'), columns=['athlete_id', 'athlete_display_name', 'season_type']); b = b[(b.season_type == 2) & b.athlete_display_name.notna()]
    cnt = b.groupby('athlete_id').size(); by = {}
    for pid, n in b.drop_duplicates('athlete_id')[['athlete_id', 'athlete_display_name']].itertuples(index=False): by.setdefault(norm(n), []).append(int(pid))
    rows = []; bad = []
    for t, lst in names.items():
        for n in lst:
            c = by.get(norm(n), [])
            if len(c) == 1: rows.append([c[0], t])
            elif len(c) > 1: pid = max(c, key=lambda p: cnt.get(p, 0)); rows.append([pid, t]); print(f'  {n}: several ids {c}, took the one with most games ({pid})')
            else: bad.append((t, n))
    if bad: sys.exit('no match in the box scores for: ' + ', '.join(f'{n} ({t})' for t, n in bad) + '. Fix the names (ESPN sometimes uses a later name, e.g. Metta World Peace) and run again.')
    aw[str(year)] = rows; json.dump(dict(sorted(aw.items())), open(path, 'w'), separators=(',', ':'))
    print(f'added {len(rows)} entries for {year-1}-{str(year)[2:]} to static/awards.json')
if __name__ == '__main__': main()
