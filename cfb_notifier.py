import os
import json
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATE_FILE = "game_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"Error saving state: {e}")

def get_live_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"Error fetching ESPN data: {e}")
        return None

def parse_clock_to_seconds(clock_str):
    """
    Converts MM:SS clock string to total seconds remaining in the quarter.
    """
    try:
        parts = clock_str.split(":")
        minutes = int(parts[0])
        seconds = int(parts[1]) if len(parts) > 1 else 0
        return (minutes * 60) + seconds
    except Exception:
        return 0

def update_discord_dashboard(message_id, embed_payload):
    if not DISCORD_WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL.")
        return None

    if message_id:
        edit_url = f"{DISCORD_WEBHOOK_URL}/messages/{message_id}"
        res = requests.patch(edit_url, json=embed_payload, timeout=5)
        if res.status_code == 200:
            print("Dashboard updated successfully.")
            return message_id
        else:
            print(f"Failed to edit message (Status {res.status_code}). Creating new message...")

    post_url = f"{DISCORD_WEBHOOK_URL}?wait=true"
    res = requests.post(post_url, json=embed_payload, timeout=5)
    if res.status_code in (200, 201):
        new_id = res.json().get("id")
        print(f"New dashboard created. Message ID: {new_id}")
        return new_id
    else:
        print(f"Error posting dashboard: {res.status_code} - {res.text}")
        return None

def process_games():
    state = load_state()
    message_id = state.get("dashboard_message_id")

    data = get_live_scoreboard()
    if not data:
        return

    events = data.get("events", [])
    active_close_games = []

    for event in events:
        status_state = event["status"]["type"]["state"]
        if status_state != "in":
            continue

        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        home_name = home["team"]["abbreviation"]
        away_name = away["team"]["abbreviation"]
        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        diff = abs(home_score - away_score)

        if diff <= 17:
            clock = event["status"].get("displayClock", "0:00")
            period = int(event["status"].get("period", 1))
            clock_seconds = parse_clock_to_seconds(clock)

            period_label = f"OT{period - 4}" if period > 4 else f"Q{period}"

            game_str = f"`{period_label} {clock:>5}`  **{away_name}** {away_score:>2} @ **{home_name}** {home_score:<2}  *(Diff: {diff} pts)*"
            
            active_close_games.append({
                "str": game_str,
                "period": period,
                "diff": diff,
                "clock_seconds": clock_seconds
            })

    # Sort logic:
    # 1. period DESCENDING (-g["period"]) -> Q4 before Q3
    # 2. diff ASCENDING (g["diff"]) -> 0-pt diff before 13-pt diff
    # 3. time DESCENDING (-g["clock_seconds"]) -> 15:00 remaining before 02:00 remaining
    active_close_games.sort(key=lambda g: (-g["period"], g["diff"], g["clock_seconds"]))

    if active_close_games:
        description_text = "\n".join([g["str"] for g in active_close_games])
        footer_text = f"Live updates every 5 mins • {len(active_close_games)} close game(s) active"
        color = 15158332
    else:
        description_text = "*No active FBS games currently within 17 points.*"
        footer_text = "Live updates every 5 mins • Standby"
        color = 3447003

    embed_payload = {
        "embeds": [
            {
                "title": "🏈 ESPN FBS LIVE SCOREBOARD",
                "description": description_text,
                "color": color,
                "footer": {"text": footer_text}
            }
        ]
    }

    new_message_id = update_discord_dashboard(message_id, embed_payload)
    if new_message_id:
        state["dashboard_message_id"] = new_message_id
        save_state(state)

if __name__ == "__main__":
    process_games()
