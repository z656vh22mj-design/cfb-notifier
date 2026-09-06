import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Configuration & Settings
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
CENTRAL_TZ = ZoneInfo("America/Chicago")
ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"

def get_cst_now():
    """Returns formatted string of current time in Central Time."""
    return datetime.now(CENTRAL_TZ).strftime("%m/%d %I:%M %p CST")

def parse_utc_to_cst(utc_date_str):
    """Converts ESPN's UTC ISO date string into Central Time format."""
    try:
        utc_dt = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
        cst_dt = utc_dt.astimezone(CENTRAL_TZ)
        return cst_dt.strftime("%-m/%-d - %-I:%M %p CST")
    except Exception:
        return utc_date_str

def calculate_watchability(game):
    """Calculates a watchability score based on rankings, clock, and score differential."""
    status = game["status"]["type"]["state"]
    competition = game["competitions"][0]
    
    # Only score live or scheduled games
    if status == "post":
        return 0

    home = competition["competitors"][0]
    away = competition["competitors"][1]

    home_score = int(home.get("score", 0))
    away_score = int(away.get("score", 0))
    diff = abs(home_score - away_score)

    home_rank = home.get("curatedRank", {}).get("current", 99)
    away_rank = away.get("curatedRank", {}).get("current", 99)

    # Base value for ranked matchups
    score = 0
    if home_rank <= 25:
        score += (26 - home_rank) * 15
    if away_rank <= 25:
        score += (26 - away_rank) * 15

    # Live game multipliers based on tight score differentials
    if status == "in":
        period = game["status"].get("period", 1)
        score += 300  # Live game base bonus
        
        if diff <= 7:
            score += 400
        elif diff <= 14:
            score += 200

        if period >= 3 and diff <= 8:
            score += 300
        if period == 4 and diff <= 7:
            score += 500

    return score

def format_game_string(game):
    """Formats individual game details cleanly for Discord display."""
    status = game["status"]["type"]["state"]
    detail = game["status"]["type"]["shortDetail"]
    competition = game["competitions"][0]

    home = competition["competitors"][0]
    away = competition["competitors"][1]

    home_name = home["team"]["abbreviation"]
    away_name = away["team"]["abbreviation"]

    home_rank = f"#{home['curatedRank']['current']} " if home.get("curatedRank", {}).get("current", 99) <= 25 else ""
    away_rank = f"#{away['curatedRank']['current']} " if away.get("curatedRank", {}).get("current", 99) <= 25 else ""

    broadcast = ""
    if competition.get("broadcasts") and competition["broadcasts"][0].get("names"):
        broadcast = f" [{competition['broadcasts'][0]['names'][0]}]"

    if status == "in":
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")
        diff = abs(int(home_score) - int(away_score))
        watch_score = calculate_watchability(game)

        return (
            f"🏈 `{detail}` | {away_rank}{away_name} {away_score} @ {home_rank}{home_name} {home_score}{broadcast}\n"
            f"└ *(Diff: {diff} pts)* [{watch_score} pts]"
        )

    elif status == "pre":
        start_cst = parse_utc_to_cst(game["date"])
        return f"⏰ `{start_cst}` | {away_rank}{away_name} @ {home_rank}{home_name}{broadcast}"

    elif status == "post":
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")
        return f"🏁 `FINAL` | {away_rank}{away_name} {away_score}, {home_rank}{home_name} {home_score}"

    return ""

def fetch_and_notify():
    response = requests.get(ESPN_API_URL)
    if response.status_code != 200:
        print(f"Failed to fetch ESPN data: {response.status_code}")
        return

    data = response.json()
    events = data.get("events", [])

    live_games = []
    upcoming_games = []
    final_games = []

    for event in events:
        state = event["status"]["type"]["state"]
        formatted_str = format_game_string(event)

        if state == "in":
            watch_score = calculate_watchability(event)
            if watch_score >= 800:  # Priority threshold for high watchability
                live_games.append(formatted_str)
        elif state == "pre":
            home_rank = event["competitions"][0]["competitors"][0].get("curatedRank", {}).get("current", 99)
            away_rank = event["competitions"][0]["competitors"][1].get("curatedRank", {}).get("current", 99)
            if home_rank <= 25 or away_rank <= 25:  # Featured upcoming ranked games
                upcoming_games.append(formatted_str)
        elif state == "post":
            home_rank = event["competitions"][0]["competitors"][0].get("curatedRank", {}).get("current", 99)
            away_rank = event["competitions"][0]["competitors"][1].get("curatedRank", {}).get("current", 99)
            if home_rank <= 25 or away_rank <= 25:
                final_games.append(formatted_str)

    # Build Discord Markdown Output
    lines = ["### 🔥 LIVE GAMES"]
    lines.extend(live_games if live_games else ["No close live games above score threshold."])

    lines.append("\n---")
    lines.append("### 📆 BIG UPCOMING GAMES")
    lines.extend(upcoming_games[:3] if upcoming_games else ["No upcoming ranked matchups today."])

    lines.append("\n---")
    lines.append("### 🏆 KEY PLAYOFF FINALS")
    lines.extend(final_games[:10] if final_games else ["No completed key matchups."])

    payload_text = "\n".join(lines)

    # Send to Discord Webhook
    if DISCORD_WEBHOOK_URL:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": payload_text})
        if res.status_code in [200, 204]:
            print(f"[{get_cst_now()}] Successfully pushed updates to Discord in CST.")
        else:
            print(f"Discord Webhook Failed: {res.status_code} - {res.text}")
    else:
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")

if __name__ == "__main__":
    fetch_and_notify()
