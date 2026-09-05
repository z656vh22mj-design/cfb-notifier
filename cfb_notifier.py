import os
import json
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATE_FILE = "game_state.json"

def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_current_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"Error saving state: {e}")

def get_live_scoreboard():
    # Fetch live FBS college football games from ESPN
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching scoreboard: {e}")
        return None

def send_discord_alert(title, text):
    if not DISCORD_WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL secret.")
        return

    payload = {
        "embeds": [
            {
                "title": title,
                "description": text,
                "color": 3447003  # Blue embed color
            }
        ]
    }
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        res.raise_for_status()
        print(f"ALERT SENT: {title}")
    except Exception as e:
        print(f"Error sending Discord alert: {e}")

def process_games():
    data = get_live_scoreboard()
    if not data:
        print("No active scoreboard data found.")
        return

    previous_state = load_previous_state()
    current_state = {}

    events = data.get("events", [])
    
    for event in events:
        status = event["status"]["type"]["state"]
        if status != "in":
            continue

        game_id = str(event["id"])
        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        home_name = home["team"]["displayName"]
        away_name = away["team"]["displayName"]
        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        # Record current state for next run
        current_state[game_id] = {
            "home_score": home_score,
            "away_score": away_score
        }

        diff = abs(home_score - away_score)

        # Detect score changes between runs
        if game_id in previous_state:
            prev_home = previous_state[game_id]["home_score"]
            prev_away = previous_state[game_id]["away_score"]
            score_changed = (home_score != prev_home) or (away_score != prev_away)
        else:
            # First time detecting this active game
            score_changed = True

        # Condition: Trigger if a score changed AND point difference is 17 or less
        if score_changed and diff <= 17:
            clock = event["status"].get("displayClock", "0:00")
            period = event["status"].get("period", 1)

            alert_title = f"🏈 Score Update ({diff}-pt game)"
            alert_body = (
                f"**{away_name}** {away_score} @ **{home_name}** {home_score}\n"
                f"*Quarter {period} - {clock}*\n"
                f"Differential: **{diff} points** ($\le 17$)"
            )

            send_discord_alert(alert_title, alert_body)

    save_current_state(current_state)

if __name__ == "__main__":
    process_games()
