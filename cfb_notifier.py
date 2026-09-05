import os
import requests

CFBD_API_KEY = os.environ.get("CFBD_API_KEY")
PUSHCUT_API_KEY = os.environ.get("PUSHCUT_API_KEY")

def get_live_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching scoreboard: {e}")
        return None

def extract_underdog(event):
    try:
        competitions = event.get("competitions", [])[0]
        odds = competitions.get("odds", [])[0]
        details = odds.get("details", "")
        
        if "EVEN" in details or not details:
            return None

        fav_abbrev = details.split()[0]
        home_team = competitions["competitors"][0]
        away_team = competitions["competitors"][1]

        if home_team["team"]["abbreviation"] == fav_abbrev:
            return away_team["team"]["displayName"]
        else:
            return home_team["team"]["displayName"]
    except (IndexError, KeyError):
        return None

def send_pushcut_alert(title, text):
    url = f"https://api.pushcut.io/{PUSHCUT_API_KEY}/notifications/CFB%20Alert"
    payload = {
        "title": title,
        "text": text
    }
    try:
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        print(f"ALERT SENT: {title}")
    except Exception as e:
        print(f"Error sending Pushcut alert: {e}")

def process_games():
    data = get_live_scoreboard()
    if not data:
        print("No active scoreboard data found.")
        return

    events = data.get("events", [])
    
    for event in events:
        status = event["status"]["type"]["state"]
        if status != "in":
            continue

        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        home_name = home["team"]["displayName"]
        away_name = away["team"]["displayName"]
        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        underdog_name = extract_underdog(event)
        
        diff = abs(home_score - away_score)
        is_close_game = diff <= 17

        underdog_leading = False
        if underdog_name:
            if home_name == underdog_name and home_score > away_score:
                underdog_leading = True
            elif away_name == underdog_name and away_score > home_score:
                underdog_leading = True

        if is_close_game or underdog_leading:
            clock = event["status"].get("displayClock", "0:00")
            period = event["status"].get("period", 1)

            reasons = []
            if is_close_game:
                reasons.append(f"Diff: {diff} pts")
            if underdog_leading:
                reasons.append(f"Underdog Leading ({underdog_name})")

            reason_str = " | ".join(reasons)
            alert_title = f"🏈 CFB Alert [{reason_str}]"
            alert_body = f"{away_name} {away_score} @ {home_name} {home_score} (Q{period} - {clock})"

            send_pushcut_alert(alert_title, alert_body)

if __name__ == "__main__":
    process_games()
