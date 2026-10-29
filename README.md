# NBA dashboard

One script rebuilds the whole dashboard from public data and writes it as a single self-contained web page.
The page has four tabs:

- **Shot charts.** Every shot since 2022-23 by zone, with filters (shot type, home or away, last games), a
  points-per-shot color mode, shot selection versus shot making, side-by-side comparison, and
  shot-profile twins.
- **League leaders.** Fourteen top-10 leaderboards and the Grizzlies roster.
- **Awards watch.** Top-5 candidates for MVP, Defensive Player, Rookie of the Year, Sixth Man, Most
  Improved and Clutch Player, plus projected All-NBA, All-Defensive and All-Rookie teams.
- **Scores & teams.** A day-by-day scores browser, standings, team ratings, and team defense shot charts.

Data comes from ESPN play-by-play and box scores, republished by
[sportsdataverse](https://github.com/sportsdataverse/sportsdataverse-data/releases). Nothing needs an account or API key.

## Run it on your computer

```
pip install -r requirements.txt
python nba_build.py --raw raw --out docs/index.html
```

The first run downloads about 90 MB of source files into `raw/` (the five most recent seasons) and takes
roughly half a minute. Later runs only re-download the season in progress. Open `docs/index.html` in a browser.

`python check_build.py docs/index.html` runs the same sanity checks the automation uses.

## Update it automatically every day (GitHub Pages)

This publishes the dashboard as its own website at a `github.io` address and rebuilds it every morning.
It does not update any page you have hosted elsewhere; those only change when you replace them.

**Before you start.** You need a free GitHub account. On a free account GitHub Pages works only for
public repositories, so the repository and the site will both be public. That is fine here: they contain only
code and public data.

1. **Create the repository and upload the files.** Unzip this folder and create a new public repository.
   Upload **every file** in the `nba-dashboard` folder, keeping the folder structure, to the top level of the
   repository, so that `nba_build.py` and `.github/workflows/update.yml` sit at the root, not inside a subfolder.
   Seven files are required: `nba_build.py`, `check_build.py`, `template.html`, `requirements.txt`,
   `static/awards.json`, `static/roster.json` and `.github/workflows/update.yml`. The other two,
   `README.md` and `static/defmodel.json`, are optional. Do not create `raw/` or `docs/`; the script makes them.
   - `.github` is a hidden folder and is easy to miss. On a Mac press Cmd+Shift+. in Finder to show hidden
     files; on Windows choose View > Show > Hidden items. Or skip the problem: in GitHub choose Add file >
     Create new file, type `.github/workflows/update.yml` as the file name, and paste in the contents of that
     file.
2. **Turn on Pages.** In the repository open **Settings > Pages** and set **Source** to **GitHub Actions**.
3. **Run it once.** Open the **Actions** tab, choose **Update NBA dashboard**, and click **Run workflow**
   (if GitHub asks you to enable workflows first, do that). The first run downloads about 90 MB and takes a
   few minutes; later runs are faster because finished seasons are cached.
4. **Open the site.** When both jobs show a green check, the address is on **Settings > Pages**, and it
   looks like `https://<your-name>.github.io/<repository>/`.

No passwords, tokens or secrets are needed.

After that it rebuilds itself every morning at 11:30 UTC (about 7:30 Eastern). GitHub sometimes starts
scheduled jobs a little late. To change the time, edit the `cron` line in `.github/workflows/update.yml`.
The checker runs before publishing, so a bad download never replaces a good page. If a run fails, the previous
version stays up; open the run in the Actions tab and click the red step to see why.

**One GitHub rule to know about.** In a public repository, GitHub switches off scheduled jobs after 60 days
with no activity in the repository, and this job does not commit anything itself. If the daily updates stop,
open the Actions tab and click **Enable workflow**. Any small edit to the repository, such as updating
`static/roster.json`, also counts as activity.

The data source updates on its own schedule, usually overnight or in the morning. If a game is not in the page
yet, it is not in the source yet. Running the workflow again later in the day picks it up.

## What updates itself, and what you maintain by hand

Everything about the current season updates itself: shots, box scores, standings, team ratings, clutch
statistics, the MVP race, scores and schedule, every leaderboard and every award ladder. The NBA Cup final
is found automatically from the schedule.

A few things are files you edit yourself:

| File | What it holds | When to change it |
|---|---|---|
| `static/awards.json` | Real award winners and teams for finished seasons, as `[espn_player_id, "type"]` pairs under each season's end year. Types: `mvp`, `fmvp`, `dpoy`, `roy`, `smoy`, `mip`, `clutch`, `an1`-`an3`, `ad1`-`ad2`, `ar1`-`ar2`. | After a season's awards are announced. Add a new year key (`"2027": [...]`). These drive the gold badges and the finished-season tests in the explanations. |
| `static/roster.json` | The Grizzlies roster, coach and an "as of" date. Player IDs are filled in from the box scores when missing. | After roster moves. The page shows the "as of" date. |
| `static/defmodel.json` | A reference copy of the defensive model's weights, fitted once on the real All-Defensive teams. The build does not read this file; the working copy is written into `template.html` (search for `DEFM`). | Only if you refit the model, and then change it in both places. |

## Rolling over to a new season

When a new season starts and the source publishes its files, run with the new year:

```
python nba_build.py --current 2028
```

In the workflow file, add `--current 2028` to the build command. The five most recent seasons are built, and
season labels in the page follow the data. Also update `static/awards.json` with the finished season's awards,
and refresh `static/roster.json`.

## Good to know

- Shot locations are ESPN's, so zone totals will not match NBA.com exactly. Free throws, heaves beyond 40
  feet, All-Star games and the NBA Cup final are left out of regular-season totals (the Cup final shows as a
  badge instead).
- About 0.01% of shots have a shooter ID but no player name in the source, and are skipped.
- The award models are statistical, built from box scores, standings and play-by-play. They are not votes. Each
  panel on the page says how it works and how it did on past seasons.
- The page is about 6 MB, mostly shot data, and works on phones. The only thing it fetches from the internet is the Barlow typeface from Google Fonts; if that is blocked or you are offline, it falls back to system fonts.

## Files

```
nba_build.py          the whole build: downloads data, computes everything, writes the page
template.html         the page itself (layout, styles and the scripts that draw everything)
check_build.py        checks a built page before it is published
static/               awards.json and roster.json (read by the build); defmodel.json (reference copy)
.github/workflows/    the daily GitHub Actions job
requirements.txt      pandas, numpy, pyarrow
```
