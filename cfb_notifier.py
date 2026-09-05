import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

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
        print(f"Error fetching ESPN scoreboard: {e}")
        return None

def get_broadcast_network(competition):
    try:
        broadcasts = competition.get("broadcasts", [])
        if broadcasts:
            names = broadcasts[0].get("names", [])
            if names:
                return names[0]
    except Exception:
        pass
    return None

def get_game_win_probability(game_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={game_id}"
    try:
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        data = res.json()
        
        win_prob_list = data.get("winprobability", [])
        if win_prob_list:
            latest = win_prob_list[-1]
            home_wp = latest.get("homeWinPercentage", 0.5)
            away_wp = 1.0 - home_wp
            return home_wp, away_wp
    except Exception:
        pass
    
    return None, None

def parse_clock_to_seconds(clock_str):
    try:
        parts = clock_str.split(":")
        minutes = int(parts[0])
        seconds = int(parts[1]) if len(parts) > 1 else 0
        return (minutes * 60) + seconds
    except Exception:
        return 0

def calculate_watchability_score(event, diff, home_wp, away_wp):
    period = int(event["status"].get("period", 1))
    clock_str = event["status"].get("displayClock", "0:00")
    clock_seconds = parse_clock_to_seconds(clock_str)

    competitors = event["competitions"][0]["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")

    score = 0.0

    score += period * 100

    if diff <= 8:
        score += 300
    elif diff <= 17:
        score += 100

    if home_wp is not None:
        wp_margin = abs(home_wp - 0.50)
        wp_closeness_bonus = max(0.0, (0.50 - wp_margin) * 1000)
        score += wp_closeness_bonus

    if period >= 4 and diff <= 8:
        time_elapsed_pct = (900 - min(clock_seconds, 900)) / 900.0
        late_game_boost = 2000.0 + (time_elapsed_pct * 1500.0)
        if period > 4:
            late_game_boost += 1500.0
        score += late_game_boost

    home_rank = int(home.get("curatedRank", {}).get("current", 99))
    away_rank = int(away.get("curatedRank", {}).get("current", 99))
    
    min_rank = min(home_rank, away_rank)
    max_rank = max(home_rank, away_rank)

    if min_rank <= 10:
        score += 300
    elif min_rank <= 25:
        score += 100

    quarter_upset_weight = min(1.0, period * 0.25)

    if diff <= 8:
        if min_rank <= 10 and max_rank > 15:
            score += 2000.0 * quarter_upset_weight
        elif min_rank <= 25 and max_rank > 25:
            score += 400.0 * quarter_upset_weight

    try:
        odds = event["competitions"][0].get("odds", [])
        if odds:
            spread = abs(float(odds[0].get("spread", 0)))
            if diff <= 8:
                upset_bonus = (spread ** 2) * 1.5 * quarter_upset_weight
                score += upset_bonus
    except Exception:
        pass

    score += 50

    return int(score)

def calculate_playoff_impact(event):
    competitors = event["competitions"][0]["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")

    home_rank = int(home.get("curatedRank", {}).get("current", 99))
    away_rank = int(away.get("curatedRank", {}).get("current", 99))
    
    min_rank = min(home_rank, away_rank)
    impact_score = 0.0

    if min_rank <= 10:
        impact_score += 1000.0
    elif min_rank <= 25:
        impact_score += 500.0

    home_score = int(home.get("score", 0))
    away_score = int(away.get("score", 0))
    
    if home_score != away_score:
        winner = home if home_score > away_score else away
        loser = away if home_score > away_score else home
        
        winner_rank = int(winner.get("curatedRank", {}).get("current", 99))
        loser_rank = int(loser.get("curatedRank", {}).get("current", 99))
        
        if loser_rank <= 25 and winner_rank > 25:
            impact_score += 1200.0

    diff = abs(home_score - away_score)
    if diff <= 7:
        impact_score += 300.0

    return impact_score

def update_discord_dashboard(message_id, embed_payload):
    if not DISCORD_WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL secret.")
        return None

    if message_id:
        edit_url = f"{DISCORD_WEBHOOK_URL}/messages/{message_id}"
        res = requests.patch(edit_url, json=embed_payload, timeout=5)
        if res.status_code == 200:
            print("Dashboard updated successfully.")
            return message_id

    post_url = f"{DISCORD_WEBHOOK_URL}?wait=true"
    res = requests.post(post_url, json=embed_payload, timeout=5)
    if res.status_code in (200, 201):
        new_id = res.json().get("id")
        return new_id
    return None

def process_games():
    state = load_state()
    message_id = state.get("dashboard_message_id")

    data = get_live_scoreboard()
    if not data:
        return

    events = data.get("events", [])
    active_close_games = []
    completed_impact_games = []

    for event in events:
        status_state = event["status"]["type"]["state"]
        period = int(event["status"].get("period", 0))
        game_id = str(event["id"])

        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        home_name = home["team"]["abbreviation"]
        away_name = away["team"]["abbreviation"]
        
        home_rank = int(home.get("curatedRank", {}).get("current", 99))
        away_rank = int(away.get("curatedRank", {}).get("current", 99))
        
        home_disp = f"#{home_rank} {home_name}" if home_rank <= 25 else home_name
        away_disp = f"#{away_rank} {away_name}" if away_rank <= 25 else away_name

        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))
        diff = abs(home_score - away_score)

        tv_channel = get_broadcast_network(competition)
        tv_str = f" `[{tv_channel}]`" if tv_channel else ""

        if status_state == "in" and period > 0 and diff <= 17:
            clock = event["status"].get("displayClock", "0:00")
            clock_seconds = parse_clock_to_seconds(clock)

            home_wp, away_wp = get_game_win_probability(game_id)
            watch_score = calculate_watchability_score(event, diff, home_wp, away_wp)

            period_label = f"OT{period - 4}" if period > 4 else f"Q{period}"

            if period >= 4 and diff <= 8:
                icon = "🚨"
            elif period >= 3 and diff <= 8:
                icon = "🔥"
            else:
                icon = "🏈"

            game_str = f"{icon} **{period_label} {clock}**  |  **{away_disp}** {away_score} @ **{home_disp}** {home_score}{tv_str}\n└ *(Diff: {diff} pts)*  `[{watch_score} pts]`"

            active_close_games.append({
                "str": game_str,
                "watch_score": watch_score,
                "period": period,
                "diff": diff,
                "clock_seconds": clock_seconds
            })

        elif status_state == "post":
            impact_score = calculate_playoff_impact(event)
            
            if impact_score >= 300:
                if away_score > home_score:
                    final_str = f"🏁 **FINAL**  |  **{away_disp} {away_score}**, {home_disp} {home_score}"
                else:
                    final_str = f"🏁 **FINAL**  |  **{home_disp} {home_score}**, {away_disp} {away_score}"

                completed_impact_games.append({
                    "str": final_str,
                    "impact_score": impact_score
                })

    active_close_games.sort(
        key=lambda g: (-g["watch_score"], -g["period"], g["diff"], g["clock_seconds"])
    )

    completed_impact_games.sort(key=lambda g: -g["impact_score"])
    top_finals = completed_impact_games[:5]

    content_sections = []

    if active_close_games:
        live_text = "\n\n".join([g["str"] for g in active_close_games])
        content_sections.append(f"### 🔥 LIVE CLOSE GAMES\n{live_text}")
    else:
        content_sections.append("### 🔥 LIVE CLOSE GAMES\n*No active FBS games currently within 17 points.*")

    if top_finals:
        finals_text = "\n".join([g["str"] for g in top_finals])
        content_sections.append(f"### 🏆 KEY PLAYOFF FINALS\n{finals_text}")

    description_text = "\n\n---\n\n".join(content_sections)

    central_tz = ZoneInfo("America/Chicago")
    now_str = datetime.now(central_tz).strftime("%b %d, %Y at %I:%M %p %Z")

    embed_payload = {
        "embeds": [
            {
                "title": "🏈 ESPN FBS LIVE SCOREBOARD",
                "description": description_text,
                "color": 15158332 if active_close_games else 3447003,
                "footer": {
                    "text": f"Live updates every 5 mins • {len(active_close_games)} active close game(s) • Last updated: {now_str}"
                }
            }
        ]
    }

    new_message_id = update_discord_dashboard(message_id, embed_payload)
    if new_message_id:
        state["dashboard_message_id"] = new_message_id
        save_state(state)

if __name__ == "__main__":
    process_games()
