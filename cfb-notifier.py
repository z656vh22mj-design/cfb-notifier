import time
import requests

# ===================================================================
# REPLACE THE KEYS BELOW WITH YOUR ACTUAL KEYS INSIDE THE QUOTES
# ===================================================================
CFBD_API_KEY = "Bk6miwLpABvIv3wIH9gAmzMTGiG1VC8EMG1wkkPxbH5X+7/ajeEclNCOPH4eOakE"
PUSHCUT_API_KEY = "KX3pNHRCsvh-iRT5o4Kwe"
# ===================================================================

POLL_INTERVAL_SECONDS = 60
notified_states = {}

def get_live_scoreboard():
    url = "https://api.collegefootballdata.com/scoreboard"
    headers = {
        "Authorization": f"Bearer {CFBD_API_KEY}",
        "accept": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error checking scoreboard: {e}")
        return None

def send_pushcut_alert(title, text):
    url = f"https://api.pushcut.io/{PUSHCUT_API_KEY}/notifications/CFB%20Alert"
    payload = {
        "title": title,
        "text": text,
        "isTimeSensitive": True
    }
    try:
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        print(f"Alert sent: {title}")
    except Exception as e:
        print(f"Error sending push notification: {e}")

def process_games():
    games = get_live_scoreboard()
    if not games:
        print("No live games currently active.")
        return

    for game in games:
        game_id = game.get("id")
        status = game.get("status", "")
        if status != "in_progress":
            continue

        home_team = game.get("homeTeam", {}).get("name", "Home")
        away_team = game.get("awayTeam", {}).get("name", "Away")
        
        home_score = game.get("homeTeam", {}).get("points")
        away_score = game.get("awayTeam", {}).get("points")

        if home_score is None or away_score is None:
            continue

        home_score = int(home_score)
        away_score = int(away_score)

        last_score = notified_states.get(game_id)
        current_score = (home_score, away_score)
        if last_score == current_score:
            continue

        betting = game.get("betting", {})
        spread = betting.get("spread")
        
        underdog_name = None
        if spread is not None:
            if spread < 0:
                underdog_name = away_team
            elif spread > 0:
                underdog_name = home_team

        diff = abs(home_score - away_score)
        is_close_game = diff <= 17

        underdog_leading = False
        if underdog_name:
            if home_team == underdog_name and home_score > away_score:
                underdog_leading = True
            elif away_team == underdog_name and away_score > home_score:
                underdog_leading = True

        if is_close_game or underdog_leading:
            period = game.get("period", 1)
            clock = game.get("clock", "0:00")
            
            reasons = []
            if is_close_game:
                reasons.append(f"Diff: {diff} pts")
            if underdog_leading:
                reasons.append(f"Underdog Leading ({underdog_name})")

            reason_str = " | ".join(reasons)
            alert_title = f"🏈 CFB Alert [{reason_str}]"
            alert_body = f"{away_team} {away_score} @ {home_team} {home_score} (Q{period} - {clock})"

            send_pushcut_alert(alert_title, alert_body)

        notified_states[game_id] = current_score

if __name__ == "__main__":
    print("Cloud CFB Score Checker active...")
    while True:
        process_games()
        time.sleep(POLL_INTERVAL_SECONDS)
