# Florent Code League

Florent Code League is a competitive programming competition in which participants write Python bots to battle each other on a 2D grid map. Your bot controls a team of units — a Core base, the Builder Bots it spawns, and any turrets they build — and the goal is simple: destroy the opponent's Core before they destroy yours.
How it works

    Write your bot. Implement a Player class in Python. The engine calls your run() method once per turn for each unit, passing a Controller object that exposes the full game API.
    Test locally. Use the fcode CLI to run matches on your machine and watch replays in the visualiser.
    Submit. Upload your bot via fcode submit. It is automatically entered into the ladder and matched against other submitted bots.
    Climb the ladder. Win matches, accumulate rating, and compete for the top spot on the leaderboard.

The game

The match is played on a rectangular grid map. Each team starts with one Core — a large, stationary base unit. From the Core you spawn Builder Bots that move around the map, construct turrets and infrastructure, harvest resources, and attack the enemy.

Games last at most 1000 rounds. A team wins immediately by destroying the enemy Core. If neither Core is destroyed by then, the winner is decided by tiebreakers, in order: most titanium collected, then most harvesters, then most titanium stored, then a coin flip.

There are two resources. Titanium pays for every unit and building you create: your team earns a passive income every 4 rounds, supplemented by Harvesters you build on titanium ore. Voltium is a rare ore that is the only source of ammunition for your Gunners and Sentinels: teams start with none, and the only way to get it is to harvest it.
Competition structure

Matches are run as a best-of-seven series, and each series updates both teams' ladder rating. You can submit as many times as you like — only your active submission plays ladder matches. See Submitting Your Bot, Matches & Scheduling, and Ladder & Rating for details.
Ready to begin?

Head to Quick Start to install the CLI and run your first match in under five minutes.

Quick Start

Get up and running in four steps.
Prerequisites

    Python 3.12 or 3.13 (Python 3.14 is not supported)
    pip (bundled with Python)
    A registered account on the platform

Step 1 — Install the CLI

pip install fcode
fcode --version

Step 2 — Authenticate and scaffold a project

fcode login
fcode starter

fcode login opens a browser window to link the CLI to your platform account — if no browser opens (common in WSL), open the link it prints instead. fcode starter scaffolds a project in the current directory: an fcode.toml, a starter bot at bots/starter/main.py (press Enter when it asks "Create a starter bot?"), and a maps/ folder that it fills with the current competition map pool.

Log in before scaffolding — maps are downloaded from the platform, not bundled with the CLI. If you scaffold while logged out, run fcode maps sync afterwards to fetch them.
Step 3 — Run a local match

fcode run starter starter

fcode run takes two bots — pass the starter twice for a mirror match. A replay file replay.replay26 is written to the current directory when the match finishes.

Watch the replay in the visualiser:

fcode watch replay.replay26

Step 4 — Submit

fcode submit bots/starter

Your bot is queued for ladder matches. Check the Matches page on the platform to track results.

Next steps:

    CLI reference — full guide to each command
    Game Rules — Overview — understand the map, units, and win conditions
    Controller API Reference — every method available inside run()

Submitting Your Bot
Two ways to submit

    CLI: fcode submit <path> — accepts a bot directory, a single .py file, or a .zip archive. See Submitting (CLI) and the CLI reference.
    Web: Open the Submissions page and upload a .zip directly from your browser.

Both paths run the same validation and enter the same ladder queue — there is no difference in how your bot is judged based on which one you use.
Bot requirements

    Must contain main.py, either at the root of the zip or inside exactly one top-level directory.
    main.py must define a top-level class Player.
    Pure Python only — no native extensions.
    Plain, readable Python only. Code that builds or loads other code at run time (exec, eval, compile, marshal, importlib, __import__, builtins, types.CodeType) is rejected at upload, for submissions and test runs alike. re.compile() and decoding your own data tables are fine.

Upload limits

    5MB max archive size
    50MB max decompressed size
    500 max files
    No native extensions (.so, .pyd, .dylib, .dll) — these bypass the sandbox's Python-level restrictions and are rejected outright
    No path traversal (e.g. ../) in archive entry names

Submission lifecycle

Each upload is validated immediately and moves through these statuses:
Status	Meaning
processing	Upload received, validation/audit in progress.
ready	Passed validation, available to activate and play ladder matches.
flagged	Passed structural validation but held for automated security audit before becoming ready.
rejected	Failed the security audit.
error	Failed structural validation (bad zip, missing main.py, over a limit, etc.) — see the error message for the specific cause.
Versions and the active submission

Every upload gets an incrementing version number. You can submit as often as you like — there's no limit on the number of submissions, and old versions are kept.

Only one version is active at a time, and only your active submission plays ladder matches. Set the active version with fcode submission activate VERSION or the Set as Active option on the web Submissions page.
Submission freezes

Admins can freeze submissions platform-wide (for example, to lock in a snapshot before a tournament's qualifier round). While frozen, uploads and active-submission changes are disabled; the Submissions page shows a banner when this is in effect.

Matches & Scheduling
Series structure

Each ladder match is a best-of-seven series. The two bots play seven individual games; the team that wins four or more games wins the series. Series results (not individual game results) affect ladder ratings.

All seven games in a series are played to completion regardless of the intermediate score — there are no early series terminations.

Unrated challenges (fcode match unrated) and remote test matches (fcode match test) also play seven games, or one game per map if you choose the maps yourself (up to seven).
Map selection

Maps for each series are drawn at random from the current competition map pool. Different games in the same series may use different maps. The map pool is announced at the start of the competition and may be updated between rounds.

The current map pool is listed on the Maps page, with each map's dimensions and symmetry. Download them into your project with fcode maps sync.
Remote infrastructure

Ladder matches and remote test matches (fcode match test) run on AWS Graviton3 instances. This is the same hardware used for all ranked games, so performance measured in remote tests is representative of what you will see on the ladder.

Local matches (fcode run) run on your own machine and may differ in speed — always profile CPU usage on remote tests before submitting.
Replays

Every game produces a .replay26 replay file. Replays for all your games are available on the Matches page. Open one directly from the platform with:

fcode watch --match <match-id>

or download the file and open it locally with fcode watch <file>.replay26.

Replays include the full round-by-round state of the map, unit HP, resource counts, and any indicator overlays (ct.draw_indicator_line / ct.draw_indicator_dot) your bot drew.
Scheduling

The scheduler runs every 20 minutes. Your bot is automatically paired after submission — you do not need to initiate matches manually. The first match after a new submission may take up to 20 minutes to appear.
Who you play against

Each time the scheduler runs, all teams with a ready submission are sorted by rating. Every team's place in that list is shifted by a random amount of up to 10 places up or down, and each team is paired with the nearest team in the shifted list. Most of your matches are against teams near you on the leaderboard, but you will regularly meet teams quite a bit higher or lower.

    Each team plays at most one ladder match per scheduler run.
    Teams that played each other in the last hour are only paired again if there is no one else left.
    With an odd number of teams, one team sits out that run.
    A coin flip decides which team plays as A and which as B.

Ladder & Rating
Elo rating

Every team has a ladder rating, starting at 1500. After each rated series, both teams' ratings are updated using the Elo rating system with a fixed K-factor of 48.

The outcome fed into the formula rewards both winning the series and how clearly you won it: winning the series counts for half, and your share of the games counts for the other half. A narrow 4-3 win counts as an outcome of 0.79, a 7-0 sweep as a full 1.0, and a 3-4 loss as 0.21.

expectedA = 1 / (1 + 10^((ratingB - ratingA) / 400))  
seriesA   = 1 if A won the series, 0 if A lost, 0.5 if tied  
outcome   = 0.5 * seriesA + 0.5 * scoreA / (scoreA + scoreB)   // e.g. 4-3 → 0.79  
delta     = 48 * (outcome - expectedA)

Whatever one team gains, the other loses, so the average rating stays at 1500. A single series moves a rating by at most 48 points.
Examples

Your rating change after a series, depending on the rating gap:  
Your rating	Win 7-0	Win 4-3	Lose 3-4  
400 higher	+4.4	−5.9	−33.4  
100 higher	+17.3	+7.0	−20.4  
Equal to opponent	+24.0	+13.7	−13.7  
100 lower	+30.7	+20.4	−7.0  
400 lower	+43.6	+33.4	+5.9

Beating a stronger team pays off the most. When you're far above your opponent, the formula expects a clear win, so a narrow win can still cost rating.
What affects rating

    Ladder matches — the automatic best-of-seven series the scheduler pairs you into (see Matches & Scheduling) — are rated and update both teams' Elo.
    Unrated challenges (fcode match unrated) and remote test matches (fcode match test) never affect rating — they exist purely for testing against real hardware.

Rating history and rank

Every rated match records a snapshot of each team's rating and leaderboard rank at that point in time, which powers the rating-over-time graphs on the platform. Rank is simply your position when all teams are sorted by current rating, recomputed after every rated match.
Climbing badge

Teams that have played at least 100 matches and gained 100+ rating points within the last 6 hours are shown with a "climbing" badge on the leaderboard for the following hour — a way to highlight teams on a hot streak.

Installation

The fcode CLI is the primary tool for working with Florent Code League. It handles authentication, local match running, replay viewing, and bot submission.
Requirements

    Python 3.12 or 3.13. Python 3.14 is not supported. Check your version:

python --version

    pip, which is bundled with all standard Python distributions.

Install

pip install fcode

Verify the installation:

fcode --version

Virtual environments

It is good practice to install fcode inside a virtual environment:

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install fcode

Authenticate

Link the CLI to your platform account:

fcode login

A browser window opens where you approve the connection within 2 minutes. If no browser opens (common in WSL), the CLI prints a link instead — open it in a browser on the same computer. Once authorised, your credentials are stored in ~/.fcode/credentials.json. A login lasts at least 30 days and is extended while you keep using the CLI; if it expires, commands print Session expired. Run: fcode login — just log in again.

fcode logout

Updating

pip install --upgrade fcode

It is recommended to update before each competition to ensure you have the latest engine version.

Your First Bot
Scaffold a starter project

fcode starter

This scaffolds a project in the current directory — an fcode.toml, a working starter bot at bots/starter/main.py, and a maps/ folder holding the current competition map pool (downloaded from the platform, so log in first). Open bots/starter/main.py — the structure looks like this:

from fcode import Controller, Direction, EntityType

class Player:
    def __init__(self):
        pass  # initialise per-unit state here

    def run(self, ct: Controller) -> None:
        pass  # called once per round for each of your units

How the engine calls your bot

The engine creates one Player instance per unit at the start of the match. Every round, it calls run() on each living unit in the order that unit was spawned (the Core acts first, since it exists from round one), passing a fresh Controller object.

    __init__ is for per-unit persistent state (e.g. a movement target the unit is working toward).
    run() is where all game actions happen. Everything goes through the Controller argument (ct).
    For state shared across all your bots, use the Global Communication Store.

A minimal working bot

This starter bot demonstrates the two most common unit types:

from fcode import Controller, Direction, EntityType
import random

class Player:
    def __init__(self):
        self.move_dir = Direction.NORTH

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()

        if etype == EntityType.CORE:
            self._run_core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self._run_builder(ct)

    def _run_core(self, ct: Controller) -> None:
        # Spawn a Builder Bot on any adjacent passable tile
        for pos in ct.get_nearby_tiles(dist_sq=2):
            if ct.can_spawn(pos):
                ct.spawn_builder(pos)
                return

    def _run_builder(self, ct: Controller) -> None:
        # Try to keep moving; bounce off walls. Builder bots move only in
        # the four cardinal directions.
        if ct.can_move(self.move_dir):
            ct.move(self.move_dir)
        else:
            self.move_dir = random.choice(
                [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
            )

What's available in run()

The Controller exposes methods for:

    Sensing — read the map, find nearby units and buildings, check tile types
    Acting — move, build, attack, heal, spawn units
    Information — query your own HP, position, team, round number, resources
    Debugging — draw indicator lines and dots in the visualiser

See the full Controller API Reference for every method.

Running Matches
Local matches

fcode run takes two bots. Run the starter against itself for a mirror match:

fcode run starter starter

Run two different bots (each is a path, or a name resolved against your bots/ folder):

fcode run starter opponent

When the match finishes, a replay file (replay.replay26) is written to the current directory. The match result and final round are printed to the terminal.
Specifying a map

The map is an optional third argument — a path, or a name resolved against your maps/ folder:

fcode run starter starter arena

Omitting the map uses the first map in your maps/ folder. Add --map-random to pick a random one instead.

Your maps/ folder is filled by fcode starter and kept current with fcode maps sync. The pool changes during the competition, so re-run sync if a map name isn't found:

fcode maps list   # pool vs what you have locally
fcode maps sync   # download anything missing or changed

Time limits

Local runs enforce no per-turn time limit by default, so you can iterate without a slow turn killing your bot. Pass --tle MS to enforce one — --tle 10 matches the ladder:

fcode run starter opponent --tle 10

    --tle only works on Linux. It relies on Linux-specific per-thread CPU clocks. On macOS and Windows the flag is accepted and shown in the run banner, but no limit is enforced and ct.get_cpu_time_elapsed() returns 0. Use a remote test match (below) to check timing there.

Even on Linux, a local --tle run measures your own machine, which is not the hardware the ladder uses. Treat it as a rough signal and confirm with fcode match test before submitting.
Tracking progress

While a match runs, the engine prints a Completed turn N line every 100 turns. Use --mark to change how often — handy for telling a hung run apart from a merely slow one:

fcode run starter opponent --mark 10   # a line every 10 turns
fcode run starter opponent --mark 1    # every turn
fcode run starter opponent --mark 0    # silence them

Markers go to stderr, so they never mix into --json output and you can drop them with 2>/dev/null.
Watching replays

Open a replay in the browser-based visualiser:

fcode watch replay.replay26

The visualiser shows the full match turn by turn, with unit health bars, resource counters, and indicator overlays drawn by ct.draw_indicator_line() / ct.draw_indicator_dot().
Remote test matches

Test two local bots against each other on the server before submitting:

fcode match test starter opponent

You can append one or more map names (one per game); omit them for 7 random maps. Remote test matches run on the same AWS Graviton3 hardware as ranked ladder matches, giving you an accurate picture of performance. Results, including replays, are available on the Matches page.

Rate limit: 5 per 20 minutes per account, shared with unrated challenges (see below).
Unrated challenges

Challenge another team's submission directly on the server — a scrimmage that doesn't affect either team's ladder rating:

fcode match unrated <opponent-team-id>

Use fcode team search to find team IDs. By default both teams play with their active submission (or their latest ready one if no active submission is set); pass --match <match-id> to instead play against whichever submission the opponent had in a specific past match. Add one or more --map flags to choose maps (up to 7); omit for 7 random maps:

fcode match unrated <opponent-team-id> --map arena --map fortress

Results, including replays, are available on the Matches page, same as any other match.

Rate limit: 5 per 20 minutes per account, shared with remote test matches — each unrated challenge and each fcode match test run counts against the same 20-minute bucket.
Tips

    Use ct.get_cpu_time_elapsed() inside run() to detect if your bot is approaching the 10 ms per-round CPU limit.
    Pass --seed N to fcode run to reproduce the exact same match deterministically while you iterate.

Submitting
Submit your bot

fcode submit bots/starter

fcode submit accepts a bot folder (containing main.py), a single .py file, or a .zip. A single .py file is uploaded as main.py, so it must define class Player. Your submission is uploaded, validated, and entered into the ladder queue. The CLI prints the new version number and submission ID when the upload succeeds.

You can submit at any time — there is no limit on the number of submissions. See Submitting Your Bot for upload limits, validation rules, and how submission versions/activation work.

Manage past submissions with fcode submission list, fcode submission activate VERSION, fcode submission rename VERSION NAME, and fcode submission download VERSION — see the CLI reference for details.
Submitting a multi-file bot

If your bot spans multiple files, put them in one folder with main.py as the entry point (it must define class Player), and submit the folder — the CLI zips it for you:

fcode submit bots/my_bot      # contains main.py, utils.py, strategy.py

Every .py file in the folder can be imported from main.py by its name, e.g. import utils. If you zip it yourself instead, main.py must be at the root of the zip or inside a single top-level folder.
After you submit

Your bot is automatically paired against other submitted bots — see Matches & Scheduling for how pairing, series, and scoring work. Track results on the Matches page.
Troubleshooting
Problem	Cause	Fix
Zip must contain main.py at the root (or in a single top-level directory)	No main.py in the upload	Name your entry file main.py, or submit the bot folder
main.py must define a Player class	main.py has no class Player	Add a top-level class Player with a run(self, ct) method
SyntaxError on submission	Python version mismatch	Verify you are using Python 3.12 or 3.13
Bot disqualified mid-match	CPU time exceeded 10 ms	Profile with ct.get_cpu_time_elapsed() and optimise
Upload rejected (size / file count / native extension)	Archive fails platform validation	See Upload limits

CLI Reference
Global flags
Flag	Description
--version	Print the installed fcode version and exit.
--help	Show help for the command or subcommand.
JSON output for scripts

Commands that print data accept --json to print machine-readable JSON instead of formatted text, so you can use fcode from scripts. Each command below shows [--json] in its usage line if it supports it.

fcode status --json
fcode match list --mine --json

If a command fails, it exits with code 1. Errors the command detects itself are printed as {"error": "..."}, but errors returned by the platform (for example an expired login) are printed as plain text, so check the exit code rather than parsing the output.
fcode login

Authenticate the CLI with your Florent Code League account.

fcode login [--yes]

Opens a browser window for OAuth approval, which you have 2 minutes to complete. If no browser opens (common in WSL), open the link it prints instead. Credentials are stored in ~/.fcode/credentials.json.
Flag	Description
--yes, -y	If you're already logged in, log in again without asking "Log in again?" (useful in scripts).
fcode logout

Remove stored credentials.

fcode logout

fcode starter

Scaffold a new project: an fcode.toml, a .gitignore, bots/ and maps/ folders, and (if you choose) a starter bot at bots/starter/main.py. If you are logged in, the current map pool is downloaded into maps/. Files that already exist are skipped, so it is safe to run again.

fcode starter [DIRECTORY] [--yes] [--bot | --no-bot]

Argument / Flag	Default	Description
DIRECTORY	current directory	Where to create the project. Created if it doesn't exist.
--bot / --no-bot	ask	Create (or skip) the starter bot without being asked "Create a starter bot?".
--yes, -y	off	Accept the default answers (creates the starter bot). Needed when running from a script.
fcode maps

List and download the competition map pool. Maps are not bundled with the CLI — the pool is set on the platform and can change during the competition.

fcode maps list [--json]   # pool contents, and whether each map is present locally
fcode maps sync            # download anything missing or out of date into maps/

sync only adds and updates. A map dropped from the pool stays on disk, so you keep practising against it.
fcode run

Run a local match between two bots.

fcode run BOT_A BOT_B [MAP] [--replay FILE] [--seed N] [--watch] [--map-random] [--tle MS] [--mark N] [--json]

Argument / Flag	Default	Description
BOT_A	—	First bot — a path, or a name resolved against your bots/ folder.
BOT_B	—	Second bot. Pass the same value as BOT_A for a mirror match.
MAP	first map	Optional map — a path or a name resolved against your maps/ folder. Omitted uses the first map in maps/.
--replay FILE	replay.replay26	Path for the output replay file (default from fcode.toml).
--seed N	from config	Deterministic match seed.
--watch	off	Open the visualiser automatically when the match finishes.
--map-random	off	Pick a random map from maps/ when no map is given.
--tle MS	0 (disabled)	Linux only. Enforce a per-turn CPU time limit locally, in milliseconds. The ladder server always enforces 10 ms; local runs don't unless you pass this.
--mark N	100	Print a Completed turn N progress line to stderr every N turns while the match runs. --mark 1 reports every turn; --mark 0 disables the markers.

    --tle only enforces anything on Linux. CPU-time enforcement relies on Linux-specific per-thread CPU clocks, so on macOS and Windows the flag is accepted and echoed in the run banner but no limit is applied — a bot that would time out on the ladder finishes its turn normally, and ct.get_cpu_time_elapsed() reports 0. Use fcode match test to check timing on the same hardware the ladder uses.

fcode watch

Open a replay in the browser-based visualiser.

fcode watch REPLAY
fcode watch --match MATCH_ID [--game N]

Argument / Flag	Description
REPLAY	Path to a local .replay26 replay file.
--match MATCH_ID	Open a match's replay from the platform instead of a local file.
--game N	Game number within the match (for --match).
fcode map-editor

Open the map editor to create or edit .map26 files.

fcode map-editor
fcode map-editor --platform

Flag	Description
--platform	Open the map editor on the platform in your browser instead of running it locally.
fcode submit

Submit a bot to the ladder. Shorthand for fcode submission upload.

fcode submit PATH [--name NAME]

Argument / Flag	Description
PATH	A bot directory (containing main.py), a .py file, or a .zip archive.
--name, -n NAME	Optional name for this submission.
fcode submission

Manage bot submissions: upload, list, activate, rename, and download.
submission upload

fcode submission upload PATH [--name NAME] [--json]

Argument / Flag	Description
PATH	A bot directory (containing main.py), a .py file, or a .zip archive.
--name, -n NAME	Optional name for this submission.

Identical to fcode submit.
submission list

fcode submission list [--json]

Lists all of your team's submissions with version, name, status, and which one is active.
submission activate

fcode submission activate VERSION [--json]

Argument	Description
VERSION	Version number of the submission to make active on the ladder.
submission rename

fcode submission rename VERSION NAME [--json]

Argument	Description
VERSION	Version number of the submission to rename.
NAME	New name for the submission.
submission download

fcode submission download [VERSION] [--output FILE]

Argument / Flag	Default	Description
VERSION	active/ready submission	Version number to download. Omitted downloads your currently active (or most recent ready) submission.
--output, -o FILE	v<VERSION>.zip	Output file path for the downloaded archive.
fcode match

View, list, and manage matches. Running fcode match MATCH_ID without naming a subcommand is shorthand for fcode match info MATCH_ID.
match info

fcode match info MATCH_ID [--json]

Shows detailed match info: status, teams, score, rating changes, and a per-game breakdown.
match list

fcode match list [--type ladder|unrated] [--team TEAM] [--mine] [--limit N] [--cursor CURSOR] [--json]

Flag	Default	Description
--type ladder|unrated	all types	Filter by match type.
--team TEAM	—	Filter by team name or team ID.
--mine	off	Show only your own team's matches.
--limit N	20	Number of matches to show (max 100).
--cursor CURSOR	—	Pagination cursor from a previous page.
match unrated

fcode match unrated OPPONENT_ID [--match SOURCE_MATCH_ID] [--map MAP_NAME] [--json]

Argument / Flag	Description
OPPONENT_ID	Team ID to request an unrated match against.
--match SOURCE_MATCH_ID	Use the opponent's submission from this specific match instead of their currently active one.
--map MAP_NAME	Map to play (repeatable, up to 7). Omitted picks random maps.

Requests a friendly, non-rated match against another team using your currently active submission.

Rate limit: 5 matches per 20 minutes per account, shared with match test.
match test

Run a remote test match between two local bots on the server, with time-limit enforcement.

fcode match test BOT_A BOT_B [MAPS...] [--json]

Argument	Description
BOT_A, BOT_B	Each is a directory (containing main.py), a .py file, or a .zip.
MAPS...	Optional map names, one per game. Omitted runs 7 random maps.

Rate limit: 5 matches per 20 minutes per account, shared with match unrated.
match replay

fcode match replay MATCH_ID [--game N] [--output FILE]

Argument / Flag	Default	Description
MATCH_ID	—	Match to download replays from.
--game, -g N	all games	Game number to download, starting at 1. Omitted downloads all games in the match.
--output, -o FILE	<matchId>_game_<N>.replay26	Output file path. Only used when a single game is downloaded (e.g. with --game); otherwise each game keeps the default name.
match watch

fcode match watch MATCH_ID [--game N]

Argument / Flag	Description
MATCH_ID	Match to open in the browser-based visualiser.
--game, -g N	Game number within the match.

Shorthand for fcode watch --match MATCH_ID [--game N].
match tests

fcode match tests [--limit N] [--json]

Flag	Default	Description
--limit N	20	Number of test runs to show.

Lists your recent fcode match test runs.
fcode team

Search teams and view team profiles.
team search

fcode team search QUERY [--json]

Argument	Description
QUERY	Search text matched against team names.
team info

fcode team info TEAM_ID [--json]

Argument	Description
TEAM_ID	Team to show — name, rating, match count, and members.
fcode ladder

Show the ladder rankings.

fcode ladder [--limit N] [--around] [--json]

Flag	Default	Description
--limit N	20	Number of teams to show.
--around	off	Center the list on your own team's rank (±5), instead of starting from the top.
fcode status

Show your current ladder rating, rank, active submission, and recent match record.

fcode status [--json]

## Game Rules

Overview
Win condition

Destroy the opponent's Core. The Core is each team's single base unit; losing it immediately ends the match as a loss.

If neither Core is destroyed by the end of round 1000, the winner is decided by tiebreakers, in order: most titanium collected, then most harvesters, then most titanium stored, then a coin flip.
The map

Matches are played on a rectangular grid ranging from 8×8 to 30×30 tiles. Each tile has one of the following environment types:
Environment	Description
EMPTY	Traversable by Builder Bots and buildings.
WALL	Impassable — blocks all movement and line-of-sight.
ORE_TITANIUM	Ore tile; a Harvester built here generates extra titanium.
ORE_VOLTIUM	Rare ore tile; a Harvester built here generates Voltium, the only source of ammunition.

WALL tiles join up into stone walls: each one is drawn depending on which neighbouring tiles are also walls.
Single wall piece: a grey stone wall on its own
Single
End wall piece: a grey stone wall with one neighbour
End
Straight wall piece: a grey stone wall with two opposite neighbours
Straight
Corner wall piece: a grey stone wall with two neighbours at a right angle
Corner
T-junction wall piece: a grey stone wall with three neighbours
T-junction
Cross wall piece: a grey stone wall with four neighbours
Cross

Maps are symmetric and chosen from the competition map pool at random for each match.
Islands

On some maps the board is broken into two floating islands, with a strip of empty sky (the pit) running straight across the middle, either north to south or east to west. Each team starts on its own island.

    Nobody walks across. A Builder Bot can never step from one island to the other, however narrow the pit is. ct.can_move() returns False for that step.
    A narrow pit can be thrown over. A Launcher can throw a Builder Bot across a pit of up to 2 tiles (GameConstants.PIT_CROSSABLE_TILES), and the bot lands on the far island.
    A wide pit cannot. Thrown over anything wider, the bot falls into the sky and is lost. The throw is still legal, so check first.
    The pit is real tiles. It is a band of Environment.VOID tiles right across the board, as many columns (or rows) as the pit is wide, so distance over it is ordinary distance: a wide pit costs a shot, a throw or a line of sight that much range.
    Nothing can stand, be built or land on a void tile: ct.is_tile_passable() and ct.is_tile_empty() are False there.
    Nothing touches across the pit. Anything that works on neighbouring tiles (building, attacking, healing, destroying, a Launcher's pick-up, a Spike, a Core's spawn, conveyors) stops at the edge, because the tiles across are no longer neighbours.
    Vision and shots do cross, if they have the range: a void tile is open air and blocks nothing, so Gunners and Sentinels can fire over the pit at targets close enough.

Ask the board about its pit with ct.get_pit(), ct.pit_separates(a, b) and ct.pit_crossable() (see Map & Match):

pit = ct.get_pit()  # None on a whole board, else (axis, at, width): void tiles at..at+width-1
if pit is not None and not ct.pit_crossable():
    # The islands are out of reach of each other: no rush can land.
    ...

Units and buildings

Every entity on the map belongs to a Team (A or B) and has an EntityType. There are two overlapping categories:

    Units — the Core, Builder Bots, and turrets (Gunner, Sentinel, Launcher, Spike). Each runs its own instance of your bot code and uses CPU time every round.
    Buildings — everything immovable: the Core, turrets, conveyors, splitters, harvesters, barriers and mines.

The Core and turrets are both a unit and a building — Builder Bots are the only unit that isn't also a building, and conveyors/splitters/harvesters/barriers/mines are the only buildings that aren't also units.
Unit cap

Each team may have at most 50 living units at any time — this includes the Core, Builder Bots, and turrets. Attempts to spawn a Builder Bot (or build a turret) when the cap is reached will fail.
Turn order

Each round, every living unit executes its run() method in the order it was spawned — the Core (spawned first) always acts before any Builder Bot or turret built later in the match. Within a round, resource changes made by one unit are immediately visible to the next unit that acts.
CPU time limit

Each unit has 10 ms of CPU time per round, plus a banked extra-time buffer of up to 5% of that limit (unused time is banked; overuse is debited from the bank). If run() exceeds the available time, execution is interrupted immediately and the unit does not resume where it left off — run() is simply called again fresh next round. Use ct.get_cpu_time_elapsed() inside run() to monitor usage.
Uncaught exceptions

A CPU-time interruption only costs that unit a single round — run() is called again next round as normal. An uncaught exception is not recoverable in the same way: if run() raises anything it doesn't catch (a GameError or otherwise), the engine logs the traceback to the replay and permanently removes that unit from the match. It will never act again for the rest of the match. Wrap risky calls in try/except (see GameError) if a unit should keep playing through an error instead of being destroyed.
Round limit

Matches end after 1000 rounds if neither Core has been destroyed.

Core
The Core, orange team: a large square base in black armour with orange lights
Orange team (Team A)
The Core, blue team: a large square base in grey-white metal with blue panels
Blue team (Team B)
Overview

The Core is a large, stationary base unit. Each team begins the match with exactly one Core placed on the map. It cannot be moved or rebuilt — if it is destroyed, the match is immediately lost.
Stats
Property	Value
HP	500
Footprint	2×2 tiles
Vision radius²	36
Spawn range²	2 (adjacent ring, including diagonals)
Abilities
Spawn Builder Bot

The Core can spawn a Builder Bot on any passable tile within its spawn range — a tile orthogonally or diagonally adjacent to its 2×2 footprint (not the footprint itself).

if etype == EntityType.CORE:
    for pos in ct.get_nearby_tiles(dist_sq=2):
        if ct.can_spawn(pos):
            ct.spawn_builder(pos)
            break

Spawning costs titanium (see ct.get_builder_bot_cost()). The new bot becomes active in the same round it is spawned.
Convert ammunition

The Core converts your team's Voltium into ammunition at 2 ammunition per Voltium. Titanium cannot be converted. Turrets fire directly from this shared ammo balance — see Turrets.

if etype == EntityType.CORE:
    if ct.get_global_ammo() < 20:
        amount = min(10, ct.get_global_voltium())
        if amount > 0 and ct.can_convert_ammo(amount):
            ct.convert_ammo(amount)

    convert_ammo(amount) spends amount Voltium from your team balance and adds 2 * amount ammunition. The number you pass is the Voltium spent, not the ammo gained; can_convert_ammo(amount) is the legality check. Check your Voltium with ct.get_global_voltium().
    At most one conversion per team per turn.
    Converted ammunition is usable the same turn.
    Converting does not use the Core's action cooldown — it never costs you a spawn.
    Teams start with 0 ammunition, and there is no passive ammo income — conversion is the only source, and Voltium only comes from Harvesters on ORE_VOLTIUM tiles.

Notes

    The Core counts toward the 50-unit cap, like every other unit.
    The Core has no movement or attack actions — its active abilities are spawning Builder Bots and converting ammunition.
    Passive income (10 titanium every 4 rounds) is granted to each team directly and isn't tied to the Core or any other unit.

Builder Bot
The Builder Bot, orange team: a small four-legged robot with an arm, black with orange lights
Orange team (Team A)
The Builder Bot, blue team: a small four-legged robot with an arm, white-grey with blue panels
Blue team (Team B)
Overview

Builder Bots are your team's mobile workforce. They are the only entities that can move freely across the map, and they are responsible for constructing and repairing all buildings.
Stats
Property	Value
HP	40
Cost	30 Ti
Vision radius²	20
Action range	Orthogonally adjacent tile only (Build, Attack, Heal, Destroy — no radius)
Move cooldown	1 round
Action cooldown	1 round
Passable terrain

Passable:

    EMPTY tiles
    ORE_TITANIUM and ORE_VOLTIUM tiles, even before a Harvester is built there
    Conveyor tiles, either team
    Splitter tiles, either team

Impassable:

    WALL tiles
    Tiles occupied by another Builder Bot
    Harvester tiles, either team
    Barrier tiles, either team
    Core tiles, either team — including your own; the Core's 2×2 footprint is never bot-passable, even for its own team
    Turret tiles (Gunner, Sentinel, Launcher, or Spike), either team

Abilities
Move

Move one tile in one of the 4 cardinal directions — NORTH, SOUTH, EAST, or WEST. Builder Bots cannot move diagonally: can_move(<diagonal>) returns False, and calling move(<diagonal>) raises a GameError ("Cannot move diagonally: builder bots move only in cardinal directions (N/E/S/W)"). Moving triggers a move cooldown. A successful move or action blocks the other for the rest of that round — building on a tile and walking onto it now takes two separate rounds.

(This restricts only Builder Bot movement; diagonal directions are still valid for turret facing and building orientation. Vision radius still includes diagonal tiles — Build, Attack, Heal, and Destroy do not, see below.)

To step toward a target, use Position.cardinal_direction_to(target), which always returns a legal cardinal step (or CENTRE if already there). Use Direction.is_cardinal() to test whether a direction is a legal move.

target = ct.get_position().cardinal_direction_to(goal)
if ct.can_move(target):
    ct.move(target)

Build

Construct a building on any orthogonally adjacent tile — NORTH, SOUTH, EAST, or WEST of the Builder Bot's current position. Diagonal tiles and its own tile are not valid build targets. Each build type has its own can_build_* check. Building triggers an action cooldown. A successful move or action blocks the other for the rest of that round — building on a tile and walking onto it now takes two separate rounds.

for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
    target = ct.get_position().add(d)
    if ct.can_build_gunner(target, Direction.EAST):
        ct.build_gunner(target, Direction.EAST)
        break

Attack

Builder Bots can attack the building on any orthogonally adjacent tile — NORTH, SOUTH, EAST, or WEST of their current position. Diagonal tiles and their own tile are not valid targets. This is mainly useful for sabotage: since Builder Bots can walk onto enemy Conveyor/Splitter tiles, you can walk up next to (or onto, then fire at a neighboring tile of) an enemy's logistics chain and damage it. Costs 2 Ti per hit for 2 damage.

for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
    target = ct.get_position().add(d)
    if ct.can_fire(target):
        ct.fire(target)
        break

Heal

Builder Bots can heal all friendly entities on any orthogonally adjacent tile — NORTH, SOUTH, EAST, or WEST of their current position. Diagonal tiles and their own tile are not valid targets. Heals 4 HP for 1 Ti — if a friendly Builder Bot is standing on a friendly building on the target tile, both are healed in the same call.

for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
    target = ct.get_position().add(d)
    if ct.can_heal(target):
        ct.heal(target)
        break

Destroy

Builder Bots can destroy an allied building on any orthogonally adjacent tile — NORTH, SOUTH, EAST, or WEST of their current position. Diagonal tiles and their own tile are not valid targets. Unlike Build, Attack, and Heal, Destroy costs no titanium and does not use the action cooldown — you can destroy any number of allied buildings this way in a single round.

for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
    target = ct.get_position().add(d)
    if ct.can_destroy(target):
        ct.destroy(target)
        break

Self-destruct

Destroy this Builder Bot. Self-destructing deals zero damage to anything nearby — it's not a weapon, just a way to free up your unit cap or retreat a doomed bot before it can be destroyed.

ct.self_destruct()

Unit cap

Builder Bots count toward the 50-unit team cap. When the cap is reached, the Core cannot spawn additional bots until an existing one is destroyed or self-destructs.

Turrets

Turrets are stationary combat buildings constructed by Builder Bots. Like every other unit, each turret runs its own instance of your bot code once per round.

Gunners and Sentinels fire from your team's global ammunition balance — each shot deducts its ammo cost (4 for a Gunner, 10 for a Sentinel) directly from the shared pool. Turrets hold no ammo themselves, don't accept resources from conveyors, and never need feeding. Ammunition is produced at the Core by converting Voltium with convert_ammo(), 2 ammunition per Voltium; any unit can check the balance with ct.get_global_ammo(). Launchers and Spikes use no ammo.

Gunners have a facing direction set at build time and adjustable with ct.rotate() — Sentinels also face a fixed direction set at build time, but cannot rotate afterward. The Launcher and the Spike have no facing direction at all.
Gunner
The Gunner, orange team: a compact turret with a short barrel on a round base, black with orange trim
Orange team (Team A)
The Gunner, blue team: a compact turret with a short barrel on a round base, white-grey with blue trim
Blue team (Team B)

A rapid-firing turret that fires a narrow forward ray.
Property	Value
HP	25
Cost	20 Ti
Damage	7
Ammo per shot	4
Fire pattern	Forward ray (single tile width)
Reload	1 round
Vision / attack radius²	13

The line stops at the first targetable tile (a builder bot or a building) in its facing direction; empty tiles don't block it, but walls do (and aren't themselves targetable). It is the cheapest turret to build and the only one that can rotate after being built, which makes it good at holding a corridor whose threat direction changes. It is also the most fragile turret and the least ammo-efficient one, and each Gunner adds +20% to your cost scale — the same tax as a Sentinel — so massing them gets expensive quickly.
Sentinel
The Sentinel, orange team: a long cannon on a pedestal, black with orange trim
Orange team (Team A)
The Sentinel, blue team: a long cannon on a pedestal, white with blue stripes
Blue team (Team B)

A durable long-range turret that fires an obstacle-piercing line.
Property	Value
HP	40
Cost	30 Ti
Damage	18
Ammo per shot	10
Fire pattern	Single-tile-wide straight facing line (same width as Gunner, but longer and unblockable)
Reload	2 rounds
Vision / attack radius²	32

Sentinels hit a single tile-wide line along their facing direction, just like a Gunner's shot — but the line reaches much further (vision/attack r²=32 vs. Gunner's 13) and, unlike a Gunner's, is never blocked by walls or units in the way. Each shot costs a large lump of ammunition, but per point of damage a Sentinel is slightly cheaper to run than a Gunner, and it out-damages one over time: 18 every 2 rounds against 7 every round. It is also the toughest turret at 40 HP, so digging one out with Builder Bots takes 20 hits. Facing is fixed at build time; Sentinels cannot rotate.
Launcher
The Launcher, orange team: a square platform with an orange-trimmed launch pad
Orange team (Team A)
The Launcher, blue team: a square platform with a glowing blue launch pad and a raised arm
Blue team (Team B)

A utility turret that picks up and throws Builder Bots.
Property	Value
HP	30
Cost	20 Ti
Action	Picks up an adjacent (including diagonal) Builder Bot from either team and throws it to any bot-passable tile in range
Pickup radius²	2 (adjacent, incl. diagonal)
Throw radius²	26 (measured from the Launcher, not the bot)
Reload	1 round

The Launcher does not deal direct damage and needs no ammo. Its value is rapid redeployment — it can throw a Builder Bot up to sqrt(26) tiles away in one action, enabling surprise attacks or fast base expansion. It works on Builder Bots from either team: as well as moving your own bots, you can grab an enemy bot that wanders adjacent and fling it somewhere harmless. It has no facing direction and cannot rotate.

On a board broken into islands, the Launcher is the only way across. It throws a Builder Bot over a pit of up to 2 tiles and the bot lands on the far island, as long as the landing tile is within its range (the pit's tiles count towards the distance). Over a wider pit the throw is still legal, but the bot falls into the sky and is lost. A bot thrown onto an enemy Mine sets it off.

# Only throw across the pit when the bot will land.
if not ct.pit_separates(bot_pos, target) or ct.pit_crossable():
    if ct.can_launch(bot_pos, target):
        ct.launch(bot_pos, target)

Spike
The Spike, orange team: a dome with eight housings, black with orange lights, spikes fully out on all sides
Orange team (Team A)
The Spike, blue team: a dome with eight housings, white-grey with blue lights, spikes fully out on all sides
Blue team (Team B)

A close-range turret whose spikes hit every enemy around it at once.
Property	Value
HP	40
Cost	20 Ti
Damage	12 to every enemy in reach
Ammo per shot	0
Attack pattern	The 8 surrounding tiles, diagonals included (radius² 2)
Reload	4 rounds
Vision radius²	8
Placement	Not on a tile touching an enemy Core

Call ct.fire(target) with any of the 8 surrounding tiles as target: the spikes come out on all sides at once, not only toward target. On each surrounding tile an enemy Builder Bot takes the hit; with no enemy bot there, an enemy building on the tile is hit instead. Your own bots and buildings are never hit, so a Spike can sit right next to your base. An enemy Core touching the Spike on two tiles is still hit only once.

The Spike needs no ammo, but its long reload means a strike has to count. It is built to guard choke points and key buildings against Builder Bots that walk up to them. It has no facing direction and cannot rotate.

A Spike may not be built on a tile touching an enemy Core, diagonals included. That is the 4x4 block with the 2x2 Core in the middle (squared distance 2 or less from the nearest Core tile, GameConstants.SPIKE_ENEMY_CORE_EXCLUSION_RADIUS_SQ). Because a Spike only reaches its own 8 surrounding tiles, it can no longer hit an enemy Core at all, or sit on the ring the Core spawns Builder Bots on. ct.can_build_spike() returns False on those tiles and ct.build_spike() raises GameError. Spikes beside your own Core are unaffected, and Gunners, Sentinels and Launchers have no such restriction.

# Spike turn: strike as soon as any enemy is in reach.
me = ct.get_team()
for tile in ct.get_attackable_tiles():
    for occupant in (ct.get_tile_builder_bot_id(tile), ct.get_tile_building_id(tile)):
        if occupant is not None and ct.get_team(occupant) != me:
            if ct.can_fire(tile):
                ct.fire(tile)
            break

Rotating turrets

Only the Gunner can rotate after placement:

if ct.can_rotate(Direction.WEST):
    ct.rotate(Direction.WEST)

Rotation costs exactly 10 Ti and triggers a 1-round action cooldown. Sentinels, Launchers, and Spikes have no rotate() — their orientation (or lack of one) is fixed for their lifetime.

Conveyors
Overview

Conveyors are infrastructure buildings that automatically move resources from one tile to the next each round, without consuming CPU time. They allow you to build supply chains from ore tiles to your Core.

Resources travel along a conveyor chain in stacks of 10 titanium per step per round.
Conveyor types
Basic Conveyor
The Conveyor, orange team: a flat belt with orange arrows showing which way it moves resources
Orange team (Team A)
The Conveyor, blue team: a flat belt with blue arrows showing which way it moves resources
Blue team (Team B)

Moves resources one tile in a fixed direction. Accepts a stack from any of its three non-output (cardinal) sides and sends it onward in the direction it's pointing.
Property	Value
Base cost	3 Ti (scales +1% per conveyor built)
Direction	Set at build time
Holds	1 stack (10 Ti) at a time

ct.build_conveyor(pos, Direction.EAST)

Splitter
The Splitter, orange team: a flat square pad with orange arrows pointing out in three directions
Orange team (Team A)
The Splitter, blue team: a flat square pad with blue arrows pointing out in three directions
Blue team (Team B)

A splitter has three possible output directions — the direction it's facing plus the two directions adjacent to it (i.e. every cardinal direction except the one directly behind it). It only accepts input from the back (the tile opposite its facing direction).

It does not split a stack in half: each round it sends its entire held stack (10 Ti) to whichever of its three outputs was used least recently, rotating through all three over time.
Property	Value
Base cost	6 Ti (scales +1% per splitter built)
Accepts from	Back only
Outputs to	3 directions (facing + two adjacent), least-recently-used first
Holds	1 stack (10 Ti) at a time

Splitters are useful for routing a single harvester chain along multiple paths back to your Core.
Building conveyors
```
# Check and build a conveyor at pos pointing East
if ct.can_build_conveyor(pos, Direction.EAST):
    ct.build_conveyor(pos, Direction.EAST)
```
Destroying conveyors

Use ct.destroy() to remove a conveyor you no longer need:

if ct.can_destroy(pos):
    ct.destroy(pos)

This returns any resources currently in transit on that tile to your team's balance.

Harvester
The Harvester, orange team: a boxy machine on four legs, black with orange lights
Orange team (Team A)
The Harvester, blue team: a boxy machine on four legs, white-grey with blue trim
Blue team (Team B)
Overview

Harvesters are buildings that generate resources from ore. A Builder Bot constructs a Harvester on an ORE_TITANIUM tile (it produces titanium) or an ORE_VOLTIUM tile (it produces Voltium, the ammo ore), and from then on it periodically outputs that resource to an adjacent building without any further action from your bots. Harvesters are buildings, not units — they don't count toward the 50-unit cap and consume no CPU time.
Stats
Property	Value
HP	30
Base cost	20 Ti (scales +5% per Harvester built)
Output	10 Ti or 10 Voltium every 4 rounds
Blocks movement	Yes
Blocks LOS	No
Output behavior

Every 4 rounds, a Harvester outputs one stack (10 Ti) to an adjacent building, prioritizing whichever of its 4 cardinal output directions was used least recently — the same round-robin pattern used by Splitters. The first output happens immediately on the round the Harvester is built, not after waiting a full 4 rounds.
Building

Harvesters can only be built on ore tiles, ORE_TITANIUM or ORE_VOLTIUM. The ore decides what the Harvester produces; the cost is the same:

if ct.get_tile_env(pos) in (Environment.ORE_TITANIUM, Environment.ORE_VOLTIUM):
    if ct.can_build_harvester(pos):
        ct.build_harvester(pos)

Notes

    Harvesters are buildings, not units — they don't count toward the 50-unit cap.
    They have no move or action cooldown of their own; their output timer runs independently of your bots' CPU budget.
    Use ct.destroy() to remove a Harvester you no longer need, same as a Conveyor or Splitter.

Other Buildings
Barrier

Orange team (Team A)
Single barrier piece, orange team (black with orange lights): a barrier on its own
Single
End barrier piece, orange team (black with orange lights): a barrier with one neighbour
End
Straight barrier piece, orange team (black with orange lights): a barrier with two opposite neighbours
Straight
Corner barrier piece, orange team (black with orange lights): a barrier with two neighbours at a right angle
Corner
T-junction barrier piece, orange team (black with orange lights): a barrier with three neighbours
T-junction
Cross barrier piece, orange team (black with orange lights): a barrier with four neighbours
Cross

Blue team (Team B)
Single barrier piece, blue team (white-grey with turquoise lights): a barrier on its own
Single
End barrier piece, blue team (white-grey with turquoise lights): a barrier with one neighbour
End
Straight barrier piece, blue team (white-grey with turquoise lights): a barrier with two opposite neighbours
Straight
Corner barrier piece, blue team (white-grey with turquoise lights): a barrier with two neighbours at a right angle
Corner
T-junction barrier piece, blue team (white-grey with turquoise lights): a barrier with three neighbours
T-junction
Cross barrier piece, blue team (white-grey with turquoise lights): a barrier with four neighbours
Cross

Barriers block movement, allowing you to create choke points and funnel enemy Builder Bots into kill zones.
Property	Value
HP	30
Cost	3 Ti
Effect	Makes the tile impassable
Blocks LOS	Yes

Barriers cannot be placed on wall tiles. An enemy can destroy a barrier with sufficient firepower, so reinforce them with turrets.

Barriers next to each other join up visually, like walls: the game picks the right piece (single, end, straight, corner, T-junction or cross) from which neighbouring tiles hold your own barriers. This only changes how they look — every barrier is still its own 1-tile building with its own HP.

if ct.can_build_barrier(pos):
    ct.build_barrier(pos)

Mine
The Mine, orange team: a small round charge set into the floor, black with orange lights
Orange team (Team A)
The Mine, blue team: a small round charge set into the floor, white-grey with turquoise lights
Blue team (Team B)

A Mine is a cheap, hidden trap. A Builder Bot lays it on an orthogonally adjacent tile, and the first enemy Builder Bot to arrive on that tile takes 40 damage, which kills a full-health Builder Bot outright. The Mine is destroyed when it goes off.
Property	Value
HP	5
Cost	6 Ti (+1% cost scale per Mine)
Damage	40, once, to the first enemy bot on it
Blocks moving	No, bots of both teams can walk over it
Unit cap	Does not count (a Mine is not a unit)
Visibility	Hidden from the other team

    Hidden. The other team's units never sense a Mine: get_nearby_entities() leaves it out, get_tile_building_id() returns None for its tile and is_tile_empty() reports the tile as empty. Your own team sees its Mines as normal buildings.
    What sets it off. An enemy Builder Bot ending up on the tile in any way: walking onto it, being thrown onto it by a Launcher, or being spawned onto it by its Core.
    Never your own team. Your own Builder Bots walk over your Mines safely, as often as they like.
    One use. After it goes off the tile is empty again, and the next bot to step there is unharmed.
    The bot's turn ends. If a Builder Bot dies on a Mine during its own move(), its turn ends there, the same way as after self_destruct(). Code after the move() call does not run.

pos = ct.get_position().add(Direction.NORTH)
if ct.can_build_mine(pos):
    ct.build_mine(pos)

Resources
Titanium
A titanium ore tile: a pile of grey-silver rocks
Titanium ore tile

Titanium pays for everything you build. It is a shared team balance — all your units draw from and deposit into the same pool.

titanium = ct.get_global_resources()

Voltium
A Voltium ore tile: purple crystals on dark rocks
Voltium ore tile

Voltium is the ammo ore. It pays for nothing except ammunition: the Core converts Voltium into ammunition at 2 ammunition per Voltium, and titanium cannot be converted. Teams start with 0 Voltium and there is no passive Voltium income.

voltium = ct.get_global_voltium()

Voltium is rare. It appears on ORE_VOLTIUM tiles, usually a few near the middle of the map, mirrored so both teams get the same. You harvest it exactly like titanium: build a Harvester on an ORE_VOLTIUM tile and carry the stacks home with conveyors. No Voltium means no ammunition, so your Gunners and Sentinels stop firing (Launchers and Spikes need no ammo).
Income sources
Passive income

All teams receive 10 titanium every 4 rounds passively, regardless of map control.
Harvesters

Builder Bots can construct Harvesters on ORE_TITANIUM tiles to generate titanium (or on ORE_VOLTIUM tiles to generate Voltium) — see Harvester for full mechanics. There is no cap on the number of Harvesters (they're buildings, not units, so they don't count against the 50-unit cap either). Controlling more ore tiles compounds your income advantage over the match.
Cost scaling

All build costs scale upward as you build more entities — not as a function of elapsed rounds. Each conveyor/splitter/barrier built adds +1% to your team's scale factor, each harvester +5%, each launcher/spike +10%, and each builder bot/gunner/sentinel +20%; destroying an entity removes its contribution again. A team that builds nothing stays at scale 1.0 indefinitely, no matter how many rounds pass.

scale = ct.get_scale_percent()  # 1.0 with nothing built; rises only as you build

Query the current cost of any specific action:

titanium_cost = ct.get_gunner_cost()

Implication: early expansion is disproportionately valuable. Units and buildings bought in the early game cost less than identical purchases later. Build aggressively early and consolidate your position before costs make expansion prohibitive.
Economic strategy notes

    Harvesters on ore tiles pay back their build cost within a few dozen rounds at typical scale values.
    Destroying an enemy Harvester denies them income for the rest of the match. On a Voltium Harvester, that also cuts their ammunition supply.
    Movement itself is free — Builder Bots can walk over any open tile without building anything — so titanium can go entirely toward Harvesters, turrets, and other buildings.

Reference
Entity stats
Units
Entity	HP	Cost (Ti)	Vision radius²	Action radius²	Spawn radius²	Move cooldown
Core	500	—	36	—	2 (adjacent ring)	—
Builder Bot	40	30	20	— (Build/Attack/Heal/Destroy are all orthogonally adjacent only)	—	1
Turrets
Entity	HP	Cost (Ti)	Vision radius²	Attack radius²	Damage	Ammo/shot	Reload
Gunner	25	20	13	13	7	4	1
Sentinel	40	30	32	32	18	10	2
Launcher	30	20	26	26 (throw) / 2 (pickup)	—	—	1
Spike	40	20	8	2 (all 8 neighbours)	12	—	4

Spikes carry one extra placement rule: a Spike may not be built on a tile touching an enemy Core (the 4x4 block around it). See Turrets.
Infrastructure
Entity	HP	Cost (Ti)	Blocks movement	Blocks LOS
Harvester	30	20 (base)	Yes	No
Barrier	30	3 (base)	Yes	Yes
Basic Conveyor	20	3 (base)	No	No
Splitter	20	6 (base)	No	No
Mine	5	6 (base)	No	No

A Mine is hidden from the other team and deals 40 damage to the first enemy Builder Bot on its tile. See Mine.

All costs above are base costs — the effective cost scales up with the number of entities your team has built (see Cost scaling).
Game constants
Constant	Value
Round limit	1000
Unit cap (per team)	50 (includes the Core)
CPU time limit (per unit per round)	10 ms (+5% banked extra time)
Passive titanium income	10 Ti / 4 rounds
Global Communication Store slots	16
Map size range	8×8 – 30×30
Series length	Best of 7
Widest pit a Launcher can throw over	2 tiles (PIT_CROSSABLE_TILES)
Cost scaling

All build costs are multiplied by the current scale factor:

effective_cost = base_cost × scale_factor

The scale factor starts at 1.0 and increases additively as entities are built (conveyor/splitter/barrier/mine +1%, harvester +5%, launcher/spike +10%, builder bot/gunner/sentinel +20% each — removed again on destruction), not as a function of elapsed rounds. Use ct.get_scale_percent() to read the current value. Use ct.get_<entity>_cost() methods to read the already-scaled current cost of any specific build action.

Controller API Reference

The Controller object (ct) is passed to your run() method every round. All game interactions go through it.
Movement
Method	Returns	Description
ct.move(direction)	None	Move one tile in the given direction. Builder Bots may only move in a cardinal direction (N/S/E/W); a diagonal direction raises. Raises on any failure.
ct.can_move(direction)	bool	True if the tile is passable and unoccupied. Always False for a diagonal direction.

Compass convention: (0, 0) is the map's northwest corner — x increases eastward, y increases southward, so NORTH is (0, −1), toward row 0. In the visualiser's isometric view north renders up-right on screen (straight up in the square view); the corner compass always shows the current orientation.

Builder Bots move only in the four cardinal directions: NORTH, SOUTH, EAST, WEST. Passing a diagonal (NORTHEAST, NORTHWEST, SOUTHEAST, SOUTHWEST) to ct.move() raises a GameError, and ct.can_move() returns False for it. To turn a target into a legal move, use pos.cardinal_direction_to(target), which always returns a cardinal step (or CENTRE if already there). Diagonal directions remain valid for turret facing and building orientation.

from fcode import Direction

# Step toward a target using a legal cardinal direction.
move_dir = ct.get_position().cardinal_direction_to(target)
if move_dir != Direction.CENTRE and ct.can_move(move_dir):
    ct.move(move_dir)

Building & Construction

Builder Bots can construct buildings on an orthogonally adjacent tile — NORTH, SOUTH, EAST, or WEST of the bot's current position. Diagonal tiles and its own tile are not valid build targets. ct.destroy() follows the same orthogonal-adjacency rule. All build methods raise if the build is not possible.
Method	Returns	Description
ct.spawn_builder(pos)	int (unit id)	Spawn a Builder Bot at pos (Core only).
ct.can_spawn(pos)	bool	True if Core can spawn a bot at pos.
ct.build_harvester(pos)	None	Build a Harvester on an orthogonally adjacent ore tile.
ct.can_build_harvester(pos)	bool	Check if Harvester can be built.
ct.build_conveyor(pos, direction)	None	Build a conveyor in the given direction.
ct.can_build_conveyor(pos, direction)	bool	Check if a conveyor can be built.
ct.build_splitter(pos, direction)	None	Build a Splitter facing direction (accepts only from the back).
ct.can_build_splitter(pos, direction)	bool	Check if a Splitter can be built.
ct.build_barrier(pos)	None	Build a Barrier (no facing direction).
ct.can_build_barrier(pos)	bool	Check if a Barrier can be built.
ct.build_gunner(pos, direction)	None	Build a Gunner turret facing direction.
ct.can_build_gunner(pos, direction)	bool	Check if a Gunner can be built.
ct.build_sentinel(pos, direction)	None	Build a Sentinel turret.
ct.can_build_sentinel(pos, direction)	bool	Check if a Sentinel can be built.
ct.build_launcher(pos)	None	Build a Launcher turret (no facing direction).
ct.can_build_launcher(pos)	bool	Check if a Launcher can be built.
ct.build_spike(pos)	None	Build a Spike turret (no facing direction). Not allowed on a tile touching an enemy Core.
ct.can_build_spike(pos)	bool	Check if a Spike can be built. False on a tile touching an enemy Core.
ct.build_mine(pos)	int (entity id)	Lay a Mine, a hidden trap (no facing direction). See Mine.
ct.can_build_mine(pos)	bool	Check if a Mine can be built.
ct.destroy(pos)	None	Destroy the allied building at pos (orthogonally adjacent).
ct.can_destroy(pos)	bool	Check if the building at pos can be destroyed.
ct.build(entity_type, pos, extra=None)	None	Generic build. extra is a Direction, required for conveyor/splitter/gunner/sentinel, unused otherwise.
ct.can_build(entity_type, pos, extra=None)	bool	Generic legality check for the above.
Combat
Method	Returns	Description
ct.fire(target)	None	Fire at target position (turrets only). Gunners and Sentinels spend from your team's global ammunition balance (4 and 10 per shot respectively); Launchers and Spikes use no ammo. A Spike takes any of its 8 surrounding tiles as target and hits every enemy around it.
ct.can_fire(target)	bool	Check if this unit can fire at target (including having enough global ammunition).
ct.can_fire_from(pos, direction, turret_type, target)	bool	Hypothetical version of can_fire: whether a turret of turret_type (EntityType.GUNNER, SENTINEL, LAUNCHER, or SPIKE) at pos facing direction could hit target. Uses current map occupancy/walls but ignores ammo and cooldown. Only tiles in this unit's vision count as occupied.
ct.get_attackable_tiles()	list[Position]	List of tiles this unit can currently attack (raw pattern — ignores ammo, cooldown, and occupancy). Raises if this unit is not a turret.
ct.get_attackable_tiles_from(pos, direction, turret_type)	list[Position]	Hypothetical version of get_attackable_tiles for a turret of turret_type at pos facing direction. Launchers and Spikes ignore direction.
ct.get_gunner_target()	Position | None	Closest targetable tile in a Gunner's facing line, or None if nothing is in range. Gunner only — raises on any other unit.
ct.heal(pos)	None	Heal all friendly entities (building and/or Builder Bot) on pos by 4 HP for 1 Ti.
ct.can_heal(pos)	bool	Check if healing is possible.
ct.self_destruct()	None	Destroy this Builder Bot. Deals zero damage — not a weapon.
ct.rotate(direction)	None	Rotate a Gunner to face direction (10 Ti, 1-round cooldown). Gunner only — errors on any other unit.
ct.can_rotate(direction)	bool	Check if rotation is possible (Gunner only).
ct.can_launch(bot_pos, target)	bool	Check if this Launcher can pick up the bot at bot_pos (either team; must be adjacent, incl. diagonal) and throw it to target (within throw range, bot-passable).
ct.launch(bot_pos, target)	None	Pick up the Builder Bot at bot_pos (either team) and throw it to target (Launcher only).
Vision & Sensing
Method	Returns	Description
ct.get_nearby_tiles(dist_sq=None)	list[Position]	Tiles within vision (or dist_sq if specified).
ct.get_nearby_entities(dist_sq=None)	list[int]	IDs of entities within range.
ct.get_nearby_buildings(dist_sq=None)	list[int]	IDs of buildings within range.
ct.get_nearby_units(dist_sq=None)	list[int]	IDs of mobile units within range.
ct.is_in_vision(pos)	bool	True if pos is within this unit's vision radius.
ct.get_tile_env(pos)	Environment	Environment type of a tile (EMPTY, WALL, ORE_TITANIUM, ORE_VOLTIUM, VOID).
ct.get_tile_building_id(pos)	int | None	ID of the building at pos, or None.
ct.get_tile_builder_bot_id(pos)	int | None	ID of the Builder Bot at pos, or None.
ct.is_tile_empty(pos)	bool	True if no unit or building occupies pos.
ct.is_tile_passable(pos)	bool	True if a Builder Bot can stand on pos.
ct.get_stored_resource(id=None)	ResourceType | None	Resource type held by a conveyor or splitter (this unit or id), or None if empty. Raises if the entity has no storage.
ct.get_stored_resource_id(id=None)	int | None	ID of the resource stack held by a conveyor or splitter (distinct from entity IDs), or None if empty. Raises if the entity has no storage.
Unit Information
Method	Returns	Description
ct.get_position(id=None)	Position	Position of this unit (or id if given).
ct.get_entity_type(id=None)	EntityType	Type of this unit (or id if given).
ct.get_hp(id=None)	int	Current HP of this unit (or id).
ct.get_max_hp(id=None)	int	Maximum HP.
ct.get_direction(id=None)	Direction	Facing direction (turrets).
ct.get_id()	int	This unit's ID.
ct.get_team(id=None)	Team	Team of this unit (or id).
ct.get_vision_radius_sq(id=None)	int	Vision radius squared.
ct.get_action_cooldown()	int	Rounds until this unit can act again.
ct.get_move_cooldown()	int	Rounds until this unit can move again.
ct.can_act()	bool	True if the action cooldown is clear.
ct.get_unit_count()	int	Total number of your team's units.

For Builder Bots, acting and moving are mutually exclusive per round — a successful build/attack/heal blocks that round's move (and vice versa), so get_action_cooldown() and get_move_cooldown() reflect only their own trigger even though can_move()/can_build_*()/can_fire()/can_heal() already account for both. If can_move() returns False, use ct.can_act() to check directly whether that's because your last action locked movement this round, rather than inferring it from get_action_cooldown() > 0.
Communication Store

Each team has 16 private integer slots shared by all of its units.
Method	Returns	Description
ct.read_store(index)	int	Read the value at index (0–15) from your team's store, as of the start of this round.
ct.write_store(index, value)	None	Buffer a write of value to index (0–15). Takes effect at the start of next round, visible to all units.
Resources & Economy
Method	Returns	Description
ct.get_global_resources()	int	Current titanium balance for your team.
ct.get_global_voltium()	int	Current Voltium balance for your team. Voltium is the ammo ore; it only pays for convert_ammo. Teams start with 0.
ct.get_global_ammo()	int	Current ammunition balance for your team. Teams start with 0 ammo and there is no passive ammo income.
ct.convert_ammo(amount)	None	Spend amount global Voltium and gain 2 * amount ammunition. Core only — at most once per team per turn, usable the same turn, and does not use the Core's action cooldown.
ct.can_convert_ammo(amount)	bool	Check if the Core can convert amount Voltium into ammunition this turn.
ct.get_scale_percent()	float	Current cost scale factor (increases as your team builds entities, not over time).
ct.get_builder_bot_cost()	int	Titanium cost to spawn a Builder Bot.
ct.get_harvester_cost()	int	Titanium cost to build a Harvester.
ct.get_gunner_cost()	int	Titanium cost to build a Gunner.
ct.get_sentinel_cost()	int	Titanium cost to build a Sentinel.
ct.get_launcher_cost()	int	Titanium cost to build a Launcher.
ct.get_spike_cost()	int	Titanium cost to build a Spike.
ct.get_mine_cost()	int	Titanium cost to build a Mine.
ct.get_conveyor_cost()	int	Titanium cost to build a conveyor.
ct.get_splitter_cost()	int	Titanium cost to build a Splitter.
ct.get_barrier_cost()	int	Titanium cost to build a Barrier.
```
# Core turn: keep ammunition topped up from whatever Voltium has come home.
if ct.get_global_ammo() < 20:
    amount = min(10, ct.get_global_voltium())
    if amount > 0 and ct.can_convert_ammo(amount):
        ct.convert_ammo(amount)
```
Map & Match
Method	Returns	Description
ct.get_map_width()	int	Map width in tiles.
ct.get_map_height()	int	Map height in tiles.
ct.get_current_round()	int	Current round number (0-indexed — 0 on the first round).
ct.get_pit()	tuple[str, int, int] | None	The pit this board is broken across, or None on a whole board. Returns (axis, at, width): axis is "x" (east and west islands) or "y" (north and south), at is the first column (or row) of the pit and width how many there are, so the pit's tiles run from at to at + width - 1. See Islands.
ct.pit_separates(a, b)	bool	True if tiles a and b are on opposite islands.
ct.pit_crossable()	bool	True if a Launcher can throw a bot over this board's pit (width at most 2). False when there is no pit; use get_pit() to tell the two apart.
ct.get_cpu_time_elapsed()	int	Microseconds of CPU time used this turn.
Debugging
Method	Returns	Description
ct.draw_indicator_line(pos_a, pos_b, r, g, b)	None	Draw a coloured line in the visualiser.
ct.draw_indicator_dot(pos, r, g, b)	None	Draw a coloured dot in the visualiser.
ct.resign(message=None)	None	Forfeit the match immediately.

Types & Enums

All types are importable directly from fcode:

from fcode import Controller, Team, EntityType, Environment, ResourceType, Direction, Position, GameError

Team

Identifies which side a unit belongs to.
Value	Description
Team.A	Team A
Team.B	Team B

if ct.get_team() == Team.A:
    # we are team A

EntityType

The type of a unit or building.
Value	Category	Description
CORE	Base	Team base unit
BUILDER_BOT	Mobile	Mobile worker
GUNNER	Turret	Forward-ray turret
SENTINEL	Turret	Long-range line turret
LAUNCHER	Turret	Bot-throwing utility turret
SPIKE	Turret	Hits every adjacent enemy, no ammo
HARVESTER	Building	Generates titanium or Voltium from ore tiles
CONVEYOR	Building	Basic resource conveyor
SPLITTER	Building	Rotates resource flow between 3 outputs
BARRIER	Building	Blocks movement and LOS

etype = ct.get_entity_type()
if etype == EntityType.GUNNER:
    # handle as a turret

Environment

The terrain type of a tile, returned by ct.get_tile_env().
Value	Description
Environment.EMPTY	Traversable ground
Environment.WALL	Impassable wall
Environment.ORE_TITANIUM	Titanium ore deposit (passable, Harvester-buildable)
Environment.ORE_VOLTIUM	Voltium ore deposit, the ammo ore (passable, Harvester-buildable)
ResourceType

A resource carried through the map, returned by ct.get_stored_resource() for a conveyor or splitter.
Value	Description
ResourceType.TITANIUM	Titanium — pays for every unit and building
ResourceType.VOLTIUM	Voltium — the ammo ore; only converts into ammunition

if ct.get_stored_resource(building_id) == ResourceType.VOLTIUM:
    # this conveyor or splitter is carrying Voltium

Direction

The 8 compass directions plus centre. Used for movement, building, and turret orientation.

    Builder Bot movement is cardinal-only. A Builder Bot may only ct.move() in a cardinal direction — NORTH, SOUTH, EAST, or WEST. The four diagonals (NORTHEAST, NORTHWEST, SOUTHEAST, SOUTHWEST) are still valid values, and remain usable for turret facing and building orientation, but passing one to ct.move() raises a GameError (and ct.can_move() returns False). Use Direction.is_cardinal() to test a direction, or Position.cardinal_direction_to() to pick a legal move.

Value	Description
Direction.NORTH	Up
Direction.SOUTH	Down
Direction.EAST	Right
Direction.WEST	Left
Direction.NORTHEAST	Up-right
Direction.NORTHWEST	Up-left
Direction.SOUTHEAST	Down-right
Direction.SOUTHWEST	Down-left
Direction.CENTRE	No movement (current tile)
Method	Returns	Description
direction.is_cardinal()	bool	True only for NORTH, SOUTH, EAST, WEST (a legal Builder Bot move).
Position

A 2D grid coordinate.

pos = Position(x=3, y=7)

Attribute / Method	Returns	Description
pos.x	int	Column (0-indexed from left)
pos.y	int	Row (0-indexed from top)
pos.add(direction)	Position	Returns the adjacent position in direction.
pos.distance_squared(other)	int	Squared Euclidean distance to other. Avoids floating point.
pos.direction_to(other)	Direction	The direction from pos toward other. May be a diagonal, so it is not always a legal Builder Bot move.
pos.cardinal_direction_to(other)	Direction	A legal cardinal step from pos toward other (or CENTRE if already there). Prefer this for choosing a move.

my_pos = ct.get_position()
target = Position(10, 5)
dist_sq = my_pos.distance_squared(target)         # e.g. 50
dir_to = my_pos.direction_to(target)              # e.g. Direction.NORTHEAST (may be diagonal)
move_dir = my_pos.cardinal_direction_to(target)   # e.g. Direction.NORTH (always a legal move)

GameError

Raised when an action is not valid (e.g. moving into a wall, building without sufficient titanium).

from fcode import GameError

try:
    ct.move(Direction.NORTH)
except GameError as e:
    # handle gracefully
    pass

Prefer using can_* checks before acting to avoid catching exceptions in the hot path.

Letting an exception escape run() uncaught is fatal to the unit. This applies to GameError and any other exception. Unlike a CPU-time interruption — which just skips that unit's turn and calls run() again fresh next round (see CPU time limit) — an uncaught exception permanently destroys the unit. It will never run again for the rest of the match.

Global Communication Store

The Global Communication Store gives all your bots a shared blackboard: 16 integer slots that persist across turns. Use it to coordinate strategy without hard-coding locations.
API
Method	Returns	Description
ct.read_store(slot)	int	Read the value in slot slot (0–15).
ct.write_store(slot, value)	None	Write value to slot slot (0–15).

# Read what last turn's bots wrote
attack_x = ct.read_store(0)
attack_y = ct.read_store(1)

# Write a new value for next turn
ct.write_store(0, target.x)
ct.write_store(1, target.y)

Slots

There are 16 slots, indexed 0 to 15. All values start at 0 and accept any non-negative integer. Reading slot 16 or above raises an error.
Timing: writes are buffered

Writes are not applied immediately. They are committed at the end of the round, and the new values become readable for all your bots in the next round.
Round	Event
N	Bot A calls write_store(0, 42)
N	Bot B calls read_store(0) → still reads 0 (last round's value)
N+1	Bot B calls read_store(0) → now reads 42

This means every bot sees a consistent snapshot of the store for the entire round, regardless of execution order. Design your communication protocol around this one-round delay.
Team isolation

Each team has its own store. Your writes are invisible to the opponent, and you cannot read theirs.
Usage patterns
Scouting target

Designate fixed slots for a shared attack target:

# Any bot that finds the enemy core sets slots 0 and 1
if found_enemy_core:
    ct.write_store(0, enemy_pos.x)
    ct.write_store(1, enemy_pos.y)

# All bots read the target at the start of run()
target_x = ct.read_store(0)
target_y = ct.read_store(1)
if target_x > 0 and target_y > 0:
    move_toward(ct, Position(target_x, target_y))

Unit census

Count units by type to decide when to expand:

# Each Builder Bot increments a counter
current = ct.read_store(2)
ct.write_store(2, current + 1)  # buffered, so safe from race conditions

Because writes are buffered you need to be careful: read_store(2) + 1 reads the last round's total, so you're incrementing from the previous turn's count. This is consistent and race-free — just account for the lag.
Status flags

Use individual slots as boolean flags:

SLOT_UNDER_ATTACK = 3

if enemy_nearby:
    ct.write_store(SLOT_UNDER_ATTACK, 1)

if ct.read_store(SLOT_UNDER_ATTACK) == 1:
    # enter defensive mode
    pass

Tips

    Assign slot numbers as named constants at the top of your file to avoid magic numbers
    The one-round delay is a feature, not a bug — it guarantees every bot sees the same store state throughout a round
    There is no lock or mutex; the buffered write model makes concurrent updates safe by design

