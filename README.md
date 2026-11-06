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
- **The Grindhouse** (named after the favorite team's arena: The Garden for Boston, The Blender for New Orleans, and so on;
  the nicknames are a map near the top of the hub script in `template.html`). Home base for the favorite team, Memphis unless
  you pick another one on this tab; the choice is kept in the browser. The favorite team is highlighted in every table, gets the roster card on League Leaders, and opens here by default.
  It shows only the favorite team: standing, next game with win chance, a matchup preview (where it shoots
  against how the opponent defends each zone), results, rotation with on/off, lineups, and the season trend.
- **About.** How fresh the data is, what is here, how well the award models reproduce past seasons, and the limits.

**Older seasons.** With `--history 2003` the build also writes one data file per season back to 2002-03 into a
`data/` folder beside the page (about 1 to 1.6 MB each, 25 MB in all). The page embeds the last five seasons and
lists the older ones in the season menus of the Shot charts, Team stats (including lineups and the defense chart)
and Player Stats tabs; picking one fetches its file, so the page itself stays small. The Awards Watch, League Scoreboard, Projections and
Grindhouse tabs cover the last five seasons only. Each archived season's menu entry shows its download size, and a
note under the menu says where ESPN's old data is thin: substitution records are too thin to rebuild lineups before
2017-18 (from 2017-18 to 2019-20 about 85% of games can be rebuilt, after inferring the few substitutions ESPN logged with a missing name from the box score; 99% from 2020-21) (about 65% of games from then, 99% from 2020-21), and shot descriptions before 2012-13 use only a few
types, so the shot-type filters are coarse there. Old franchises appear under today's codes (Seattle as OKC, New
Jersey as BKN; Charlotte has no games before 2004-05). The daily workflow passes `--history 2003`; finished
seasons are computed once and cached in `raw/season<year>.json`, so later runs only rebuild the season in progress.

**Armando "NBA" Venegas** is a synthetic player in every season, archived ones included: the average of every player with data that season (box-score
totals averaged across players, and a systematic sample of the league's shots sized to the average player's attempts). He can be
searched, charted and compared like anyone, and is rebuilt with every update, but he is left out of league baselines, leaderboards,
award ladders and team figures. Any column heading in a table can be clicked to sort by it.

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
| `static/awards.json` | Real award winners and teams for every finished season since 2002-03 (add a season with `python add_awards.py 2027 winners.json`; from July the About tab reminds you when the latest season is missing), as `[espn_player_id, "type"]` pairs under each season's end year. Types: `mvp`, `fmvp`, `dpoy`, `roy`, `smoy`, `mip`, `clutch`, `an1`-`an3`, `ad1`-`ad2`, `ar1`-`ar2`. | After a season's awards are announced. Add a new year key (`"2027": [...]`). These drive the gold badges and the finished-season tests in the explanations. |
| `static/roster.json` | The Grizzlies roster, coach and an "as of" date. Player IDs are filled in from the box scores when missing. | After roster moves. The page shows the "as of" date. |
| `static/defmodel.json` | The defensive model's weights: the ballot model fitted on All-Defensive vote shares (`static/votes.json`), plus the box-score-only and defense-index fits on the real teams. The build reads it for the scorecard and the season tracker; the page's copy is the `DEFM` line in `template.html`, and `check_models.py` fails if the two differ. | Only if you refit the model (`python refit_defmodel.py --write`), and then update the `DEFM` line too. |
| `static/votes.json` | Every award's voting points for every vote-getter, from Basketball-Reference's awards pages (`python add_votes.py 2027 awards_2027.html`). The ballot model, the MVP and Sixth Man weights and the vote-share temperatures are fitted on these. | After a season's voting is published, if you want to refit. |
| `static/awardfit.json` | The fitted team-record weights and vote-share temperatures (`python refit_awards.py --write`). The build embeds it; the page and `awards_models.py` read it from the leaders block. | Only when you refit. |
| `static/gamemodel.json` | The fitted win-chance constants and availability coefficients (`python fit_gamemodel.py --write`). The build embeds it; the page reads it as `L.gamemodel`. | Only when you refit, perhaps once a season. |

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
and the Most Improved rules were refitted on all seasons with leave-one-season-out testing. The Defensive Player panel offers three rankings: the
**ballot model** (box score, team defence and voting history, fitted on the full All-Defensive voting of every season rather than the ten
selections; voting history raised the share of real selections found from 51% to 59% in that test, and the vote-share fit added two more, 138 of 230), the **defense index** (box score, team defence, rim deterrence and defensive adjusted plus-minus from the rebuilt lineup stints,
no voting history), and **adjusted plus-minus** alone. Adjusted plus-minus is a ridge regression (penalty 2,000, chosen by holding
stints out) of points per 100 possessions on the ten players on the floor, computed per season from 2017-18 on; it is also on the
Player Stats tab. Voters follow blocks, steals and reputation far more than measured impact, which is why the views are side by side. The All-Defensive teams follow the positional
rule used through 2022-23 (two guards, two forwards, one center per team). The projections break standings ties with the league's
tiebreakers (head-to-head, division winner, conference record, then point differential via the team rating). Clutch Player of the Year
only exists from 2022-23.

## The ballot model is fitted on vote shares (step 3 of the defensive-model work, done)

`static/votes.json` holds full All-Defensive voting points per player (every vote-getter, not just the ten selections) for every season
from 2003-04 to 2025-26, taken from Basketball-Reference's awards pages: 23 seasons, 950 vote-getters in all, 868 of them among the
players the Defensive Player ladder considers. The ballot model's weights are a fractional logistic regression on each player's share
of the points possible (0 for a player with no vote), with the same six features and the same regularisation (C=0.1) as the earlier
yes/no fit on the ten selections, so the page's `dscore` is unchanged apart from the weights.

`python refit_defmodel.py` reruns the comparison (it needs the cached seasons from a `--history 2003` build). Holding each season out in
turn and scoring it with a model fitted on the other 22, the vote-share fit found 138 of 230 real All-Defensive selections against 136
for the yes/no fit, ranked the same 13 of 23 Defensive Players of the Year first, and correlated with the vote points at 0.647 against
0.645 among the vote-getters (Spearman; 0.576 for both over every eligible player). The gain is small, and a within-season softmax on
the points, a square-root share and a linear fit all landed in the same 136 to 141 band, as did the yes/no fit with weaker
regularisation: the six features carry about as much as the vote can tell them, and a better ballot model would need new inputs rather
than a new target. The vote-share weights are a near-uniform rescaling of the yes/no ones (team defence counts a little less relative
to steals and blocks). The defense index and adjusted plus-minus views were not refitted.

To add a season, save `https://www.basketball-reference.com/awards/awards_<year>.html` from your browser and run
`python add_votes.py <year> <saved file>` (it reads the hidden table from the HTML, matches names to ESPN ids, and reports any it cannot
match, listing the box-score names with the same surname; add the spelling to `ALIASES` in the script, as was done for Darrell
Armstrong, whom ESPN lists as Darrel; the table now also covers Herrmann, Ayón, Jeff Taylor, Marcelo Huertas and Ron Holland). Each season's points should add up to 7.5 times the points possible (every voter gives 15);
2005-06, 2008-09 and 2010-11 are off by a few points on the source pages themselves.

## The rule for model changes: bigger than the noise between seasons

Every fitting script now ends with a bootstrap over seasons (`bootstrap.py`): a change is tested by holding each season out, which gives
one gain per season; the script resamples those seasons and prints the mean gain with a 95% interval and a verdict. ADOPT means the
interval excludes zero and the mean clears a threshold a reader could notice (log loss 0.002, rank correlation 0.02, half a selection
per season, a tenth of a winner per season); SMALL means consistent but below that; NOISE means the interval includes zero. `--write`
only adopts changes that come out ADOPT and keeps the simpler constant otherwise. Under this rule the recent refits kept the Sixth Man
weight (0.14, rank correlation +0.043 [+0.024, +0.065]), the two-era Defensive Player ballot model (rank correlation +0.054 [+0.017,
+0.089], though its selections-found gain of +0.56 per season [-0.22, +1.44] is not distinguishable from noise), the rest term (+0.002
of log loss [+0.001, +0.003]) and the availability adjustment (+0.010 [+0.006, +0.014]); it reverted the MVP weight to 0.2 (+0.002
[-0.004, +0.010]) and the blend to K=10, PW=0.4 (+0.001 [+0.000, +0.001], consistent but negligible). Refit at most once a season.

## Every award is scored against its real voting

`static/votes.json` now holds every voting table from the Basketball-Reference awards pages (MVP, Defensive Player, Rookie, Sixth Man,
Most Improved, Clutch Player, All-NBA, All-Defensive and All-Rookie) for every season from 2003-04 to 2025-26 (add a season with
`python add_votes.py <year> <saved page>`). `python refit_awards.py`
scores each ladder against its vote (where the real winner ranks, Spearman correlation among the vote-getters, the share of voting
points that fall inside the model's eligible pool), fits a within-season softmax temperature per award so that a ladder's scores can
be read as predicted vote shares, and fits the team-record weight of the MVP and Sixth Man scores. `--write` stores the result in
`static/awardfit.json`, which the build embeds as `leaders.awardfit`; `awards_models.py` and the page read it from there, and
`check_models.py` fails if they disagree. Results on the 23 seasons: the MVP ladder ranks the real winner first in 16 of 23
(correlation 0.74 among vote-getters), Rookie 22 of 23 (0.76), Sixth Man 14 of 23 (15 with the fitted weight), Defensive Player 13 of
23, Most Improved 9 of 23. The fit put the MVP weight at 0.22 per point of winning percentage, but the gain over 0.2 is noise, so
0.2 stays; the Sixth Man weight is 0.14 (held out, correlation 0.59 to 0.64, a real gain). The Awards cards show the predicted share of
the vote as the headline number, with the raw score in the detail line.

**Two-era ballot model.** From 2017-18, when lineups can be rebuilt, the Defensive Player ballot model adds defensive RAPM and
opponent rim shooting on/off to the six ballot features (`defmodel.json` → `recent`, fitted by `refit_awards.py`). Held out one
season at a time over 2017-18 to 2025-26, the nine-feature fit found 57 of 90 All-Defensive selections against 52 for the six-feature
fit, and its rank correlation with the vote rose from 0.61 to 0.66. Seasons before 2017-18 keep the six-feature weights. The page's
`DEFM_RECENT` constant holds the recent-era block.

## The game model: fitted constants, rest and availability

Every win chance on the page (the Grindhouse next game and schedule, the Projections simulation) comes from `static/gamemodel.json`,
fitted by `python fit_gamemodel.py --write` on the box scores in `raw/` (needs the cached seasons from a `--history 2003` build). The
model: strength = this season's net rating blended with PW of last season's, this season weighted n/(n+K); expected home margin =
GAP x (strength gap) + HCA - B2B x (home on a back-to-back) + B2B x (away on a back-to-back) + availability; win chance = Phi(margin / SIG).
Fitted on 27,278 games of 2003-04 to 2025-26 with each season held out. The blend stays at K=10, PW=0.4: the fit preferred K=15,
PW=0.5, but by 0.001 of log loss, below the bar. On 2017-18 onward, GAP 0.97, HCA 1.9 (home court has fallen from 3.5 points in 2003-04
to about 1.7), B2B 2.4 points, SIG 13.7. The rest term improved the held-out log loss by 0.002, consistently across seasons.

**Availability.** The build fetches ESPN's injury report (`injuries_from_espn`, embedded as `leaders.injuries`; `--no-injuries` skips
it) and the page prices each listing: cost = minutes share x (value x RAPM + mins), with value -0.28 and mins -1.97 fitted on which
regulars actually sat out each game from 2018-19 on (RAPM from the previous season). So a missing regular costs about 2 points of
margin per full game of minutes almost regardless of who he is, plus 0.24 per point of RAPM; knowing who sat out improved the held-out
log loss from 0.6226 to 0.6131 (0.6106 with same-season RAPM, the hindsight ceiling). Live, a listing is weighted by status (Out 1,
Doubtful 0.8, Questionable or Day-To-Day 0.5, Probable 0.15, hand-set until measured), fades over the following days unless a return
date is given (Out: full for 3 days then to zero by day 21; shorter statuses by day 5), and is scaled by how much of the team's rating
was earned with the player on the floor, so a player out all season does not count twice.

**Checking the live plumbing.** The status weights and the fade are the least-evidenced part of the model, so the daily build saves
each day's report to `logs/injuries/<date>.json` (the workflow commits it) and, once the log covers 60 days, prints a reminder and
shows one on the About tab. Then `python check_injuries.py` compares every listing with whether the player recorded minutes in his
team's next game: the share who did not play, by status, is the weight to use, and the script also measures how long an "Out" listing
holds and how often players beat ESPN's return date. `--write` stores the measured weights in `static/gamemodel.json` (`avail.status`),
which the page reads on the next build. The Projections tab lists the report with each player's cost; the
Grindhouse next-game panel itemizes the margin. If the feed cannot be read the page says so on the About tab and assumes full rosters;
`check_build.py` reports that as a note rather than a failure, so a feed outage does not block the daily publish.

## Shot Charts: shot quality, difference map, career arc

- **FG% vs. expected** (a fourth zone coloring): expected FG% is the league's conversion rate on the same kind of shot (zone, shot
  type, catch-and-shoot or off the dribble), computed in the page from the season's shots; the KPI tile shows the player's FG% above
  that expectation, which separates shot-making from shot selection.
- **Difference map**: with a comparison on, "Comparison view" switches the second court to A minus B by zone for the metric in use.
- **Career arc**: a sparkline under the player's name shows the MVP formula's score for every season with 20+ games (`shot.arc`,
  computed by the build), best season filled, the season on screen ringed; clicking a dot shows that season.
- On narrow screens the filter row is folded behind a "Filters and comparison" button; it opens itself when a filter or comparison is
  active. Hovering a best-season checkbox prefetches that archived season.
- The About scorecard is shaded by rank (warm for winners found, cool for misses), with a key under the table.
- The season tracker on the Awards tab can plot each race as the model's predicted share of the vote day by day (a checkbox under
  the chart) instead of rank; the snapshots carry the share as a third value where the award has a fitted temperature.
- Most Improved was checked against its voting too: 11.4% of its real points fall outside the model's pool, spread across five
  rules (previous Game Score of 16 or more 3.5%, previous season under half the games 2.9%, under 70% of games 2.5%, previous
  season under 10 minutes 1.2%, under 24 minutes 1.1%). The biggest misses are established stars the cap excludes on purpose
  (Gilgeous-Alexander 2022-23, Durant 2009-10, Curry 2015-16), so the rules were left alone.

## Best-season checkboxes on the Shot Charts tab

The build computes, for every player on file, the season the MVP formula rated highest (`best_seasons` in `nba_build.py`, embedded
in the shot block as `best`). Each season is scored on its own, Game Score per game plus the team-record term with no blending, among
the seasons where the player met the MVP ladder's minimums (70% of the team's games and 25 minutes a game); players who never met them
get the best of their seasons with at least 20 games, flagged so the tooltip says so. The current season counts once teams have played
20 games. "Show <name>'s Best Season" under the Season menu jumps to that season (loading it if archived) and follows the player while
checked; the same checkbox under the second-player picker draws the comparison chart from that player's best season while the first
chart keeps the selected season. `check_build.py` fails if the map is missing or points at a season the page does not have.

## Known data quirks (from the November 2026 review)

- Basketball-Reference's All-Rookie voting table omits rookies traded during the season (Derrick Favors 2010-11; Buddy Hield and Yogi
  Ferrell 2016-17, both real selections), so `votes.json` is short those rows and the All-Rookie totals for 2010-11, 2014-15 and
  2016-17 fall below the ballot arithmetic. Nothing on the page uses All-Rookie votes; `awards.json` is correct.
- ESPN lists a handful of fringe players as active with 0:00 minutes. A game now counts as played only with minutes on the floor
  (every games-played count in the build uses that rule).
- Standings are built from the box scores, which always carry the final score; the play-by-play stops short of the final in many
  early-season games (316 of them in 2002-03, 28 with the wrong winner) and lacks a few games altogether (Chicago at the Clippers,
  2025-26). The play-by-play now only fills in a game the box scores do not have. Spot checks against the record books pass (Spurs
  and Mavericks 60-22 in 2002-03, Pacers 61-21 in 2003-04, Warriors 73-9 in 2015-16). The cached season files carry
  ARCHIVE_VERSION 9 for this, so a fresh build rebuilds them.
- The two unscheduled games per team in November are the NBA Cup placeholders; the projections count them at the team's average chance.

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
check_models.py       runs the page's own award ladders in node and checks them against awards_models.py (needs node)
smoke_test.js         loads a built page in jsdom and drives the new controls, failing on any runtime error (needs node and jsdom)
awards_models.py      the award models in Python, for the scorecard and the season tracker
refit_defmodel.py     refits the ballot model on vote shares and tests it season by season (--write updates static/defmodel.json)
add_awards.py         adds a season's real awards to static/awards.json; add_votes.py adds a season's full award voting to static/votes.json
refit_awards.py       scores every award model against its voting, fits the MVP/Sixth Man weights and vote-share temperatures (static/awardfit.json) and the recent-era ballot block
fit_gamemodel.py      fits the win-chance model (blend, home court, rest, spread, availability) from the box scores (static/gamemodel.json)
bootstrap.py          the seasons bootstrap and ADOPT/SMALL/NOISE verdict used by the three fitting scripts
check_injuries.py     compares the logged injury reports with who actually dressed and measures the status weights (run after 60 days of logs)
logs/injuries/        one JSON per day of ESPN's injury report, written by the build and committed by the workflow
static/               awards.json, roster.json, defmodel.json, awardfit.json, gamemodel.json and votes.json (all read by the build or the refits)
.github/workflows/    the daily GitHub Actions job
requirements.txt      pandas, numpy, pyarrow
```
