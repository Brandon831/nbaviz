# NBA dashboard

One script rebuilds the whole dashboard from public data and writes it as a single self-contained web page.
The page has nine tabs, in this order:

- **League Scoreboard.** A day-by-day scores browser and the standings. Click any finished game for its box score, a
  score-margin chart and both teams' shot maps; back-to-backs are tagged.
- **Shot Charts.** Every shot since 2022-23 by zone, with filters (shot type, catch-and-shoot style or off the dribble, home or away, last games), a
  points-per-shot color mode, shot selection versus shot making, side-by-side comparison, and
  shot-profile twins.
- **League Leaders.** Fourteen top-10 leaderboards and the Grizzlies roster.
- **Awards Watch.** Top-5 candidates for MVP, Defensive Player, Rookie of the Year, Sixth Man, Most
  Improved and Clutch Player, plus projected All-NBA, All-Defensive and All-Rookie teams, and a day-by-day tracker
  of each race this season (the ladders are recomputed after every game date, so you can see who drops in and out).
- **Player Stats.** About 40 player statistics (per game, per 36, shooting, usage and other rates, Game Score, and
  on/off ratings) plotted against each other for every player in a season, with filters, presets, a Random
  button, highlighting and a sortable table.
- **Team Stats.** All 30 teams plotted on any two of 42 team statistics (offensive against defensive rating,
  last-10 net rating against season net rating, and so on) over the whole season, the latest games, or home
  and road games, with preset charts, a Random button and a sortable table. The highlighted team is drawn
  in its own colors, which come from ESPN's data. Below the table, the most-used five-man lineups or two-man
  duos for any team (a switch picks which); at the bottom, a defense shot chart shows where opponents shoot against any team and how well.
- **Projections.** Projected wins and playoff odds for all 30 teams from simulating the rest of the season, how hard
  each team's remaining schedule is (including back-to-backs left), and a live backtest of the projection model.
- **The Grindhouse.** The Grizzlies' home base (any team can be picked): standing, next game with win chance, a matchup preview (where it shoots
  against how the opponent defends each zone), results, rotation with on/off, lineups, and the season trend.
- **About.** How fresh the data is, what is here, how well the award models reproduce past seasons, and the limits.

**Older seasons.** With `--history 2003` the build also writes one data file per season back to 2002-03 into a
`data/` folder beside the page (about 1 to 1.6 MB each, 25 MB in all). The page embeds the last five seasons and
lists the older ones in the season menus of the Shot charts, Team stats (including lineups and the defense chart)
and Player Stats tabs; picking one fetches its file, so the page itself stays small. The Awards Watch, League Scoreboard, Projections and
Grindhouse tabs cover the last five seasons only. Each archived season's menu entry shows its download size, and a
note under the menu says where ESPN's old data is thin: substitution records are too thin to rebuild lineups before
2017-18 (about 65% of games from then, 99% from 2020-21), and shot descriptions before 2012-13 use only a few
types, so the shot-type filters are coarse there. Old franchises appear under today's codes (Seattle as OKC, New
Jersey as BKN; Charlotte has no games before 2004-05). The daily workflow passes `--history 2003`; finished
seasons are computed once and cached in `raw/season<year>.json`, so later runs only rebuild the season in progress.

Most charts and tables have **Save chart as image** and **Download table (CSV)** buttons. On your own site (not
on the Claude-hosted page) there are also **Copy link** buttons that save the current view in the address.

Data comes from ESPN play-by-play and box scores, republished by
[sportsdataverse](https://github.com/sportsdataverse/sportsdataverse-data/releases). Nothing needs an account or API key.

## Run it on your computer

The first run downloads about 500 MB of source files (all seasons since 2002-03) and takes several minutes;
later runs reuse them.

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

Everything about the current season updates itself: shots, box scores, standings, team statistics, clutch
statistics, the MVP race, scores and schedule, every leaderboard and every award ladder. The NBA Cup final
is found automatically from the schedule.

A few things are files you edit yourself:

| File | What it holds | When to change it |
|---|---|---|
| `static/awards.json` | Real award winners and teams for every finished season since 2002-03, as `[espn_player_id, "type"]` pairs under each season's end year. Types: `mvp`, `fmvp`, `dpoy`, `roy`, `smoy`, `mip`, `clutch`, `an1`-`an3`, `ad1`-`ad2`, `ar1`-`ar2`. | After a season's awards are announced. Add a new year key (`"2027": [...]`). These drive the gold badges and the finished-season tests in the explanations. |
| `static/roster.json` | The Grizzlies roster, coach and an "as of" date. Player IDs are filled in from the box scores when missing. | After roster moves. The page shows the "as of" date. |
| `static/defmodel.json` | A reference copy of the defensive model's weights, fitted once on the real All-Defensive teams. The build does not read this file; the working copy is written into `template.html` (search for `DEFM`). | Only if you refit the model, and then change it in both places. |

## Rolling over to a new season

When a new season starts and the source publishes its files, run with the new year:

```
python nba_build.py --current 2028 --history 2003
```

In the workflow file, add `--current 2028` to the build command. The five most recent seasons are built, and
season labels in the page follow the data. Also update `static/awards.json` with the finished season's awards,
and refresh `static/roster.json`.

## The award models and their track record

`awards_models.py` holds the award models in Python. With `--history`, the build runs them on every finished season
since 2002-03 against the real winners in `static/awards.json`, fits the Most Improved regression on all of those
seasons, and writes the results into the page: the About tab shows a season-by-season scorecard. The models were tuned
on 2022-23 to 2025-26, so earlier seasons are an out-of-sample test. The defensive weights (`static/defmodel.json`)
and the Most Improved rules were refitted on all seasons with leave-one-season-out testing. Clutch Player of the Year
only exists from 2022-23.

## Good to know

- Shot locations are ESPN's, so zone totals will not match NBA.com exactly. Free throws, heaves beyond 40
  feet, All-Star games and the NBA Cup final are left out of regular-season totals (the Cup final shows as a
  badge instead).
- About 0.01% of shots have a shooter ID but no player name in the source, and are skipped.
- The award models are statistical, built from box scores, standings and play-by-play. They are not votes. Each
  panel on the page says how it works and how it did on past seasons.
- On/off ratings and lineups are rebuilt from substitution records: events are put in order by period and game
  clock, the five starters come from the box score, and a game is used only if every player's rebuilt minutes agree
  with the box score (about 97% of games). Against ESPN's own plus-minus the rebuilt figures correlate 0.99 or
  better. Finished seasons are cached in `raw/` as `lineups<year>.json`; if you ever change the reconstruction code,
  change the version number inside `lineup_data` so old caches are ignored.
- The schedule file can end before the real season does (in 2026-27 it lists 80 games per team where 82 are
  played), so the projections fill the rest in as games against an average opponent and say so on the page.
- ESPN's box scores occasionally omit a player's line (seven games in 2025-26, all involving Chicago). Team
  points on the page use the official scores; figures built from player lines are slightly low in those games.
- `python nba_build.py --built-at 2026-11-02T20:00:00Z` fixes the timestamp shown on the About tab, so two builds
  can be compared byte for byte.
- The page is about 7.2 MB, mostly shot data, and works on phones. The only thing it fetches from the internet is the Barlow typeface from Google Fonts; if that is blocked or you are offline, it falls back to system fonts.

## Files

```
nba_build.py          the whole build: downloads data, computes everything, writes the page and the data/ season files
template.html         the page itself (layout, styles and the scripts that draw everything)
check_build.py        checks a built page before it is published
static/               awards.json and roster.json (read by the build); defmodel.json (reference copy)
.github/workflows/    the daily GitHub Actions job
requirements.txt      pandas, numpy, pyarrow
```
