# Madden ratings for the NFL Team Grades injury number

- `launch.csv` (season, pfr, ovr): each season's Madden launch rating by Pro Football Reference id. Season = NFL season (2026 = Madden NFL 27). Used for every past game in the backtest.
- `current.csv` (ea_id, name, pos, birthdate, ovr, iteration): EA's latest in-season ratings. Used only for the upcoming week. Updated by the Tuesday and Sunday "NFL Team Grades update" runs.
- `history/`: one copy of the ratings per EA update, so in-season ratings can be backtested later.
- `nfl_weekly.py`: backup copy of the model script (the runs use the copy on the Claude NFL Team Grades page).

Sources: 2014-2025 launch ratings from github.com/theedgepredictor/nfl-madden-data (stage files), Madden NFL 27 launch ratings from github.com/zachxwalton/madden-ratings-breakdown, in-season updates from ea.com/games/madden-nfl/ratings.
