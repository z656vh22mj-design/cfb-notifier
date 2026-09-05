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
        print(f"Error fetching ESPN scoreboard: {e}")
        return None

def get_game_win_probability(game_id):
    """
    Queries ESPN's game summary endpoint to extract live win percentages.
    """
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
    """
    Calculates dynamic watchability score heavily weighing late-game drama,
    Top 10 upsets, and dousing early-game false alarm upsets.
    """
    period = int(event["status"].get("period", 1))
    clock_str = event["status"].get("displayClock", "0:00")
    clock_seconds = parse_clock_to_seconds(clock_str)

    competitors = event["competitions"][0]["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")

    score = 0.0

    # 1. Base Score from Quarter
    score += period * 100

    # 2. Closeness Bonus
    if diff <= 8:
        score += 300
    elif diff <= 17:
        score += 100

    # 3. Live Win Probability Closeness Boost (Max +500 for dead-heat 50/50 games)
    if home_wp is not None:
        wp_margin = abs(home_wp - 0.50)
        wp_closeness_bonus = max(0.0, (0.50 - wp_margin) * 1000)
        score += wp_closeness_bonus

    # 4. EXTREME LATE-GAME DRAMA MULTIPLIER (Q4 / OT Close Games)
    # 4th Quarter 1-possession games scale up massively as time ticks down to 0:00
    if period >= 4 and diff <= 8:
        # Time factor: max 1.0 at 0:00, min ~0.1 at 15:00
        time_elapsed_pct = (900 - min(clock_seconds, 900)) / 900.0
        late_game_boost = 2000.0 + (time_elapsed_pct * 1500.0)  # +2000 to +3500 pts
        
        # Additional multiplier if OT
        if period > 4:
            late_game_boost += 1500.0
            
        score += late_game_boost

    # 5. Team Ranks & Upset Potential
    home_rank = int(home.get("curatedRank", {}).get("current", 99))
    away_rank = int(away.get("curatedRank", {}).get("current", 99))
    
    min_rank = min(home_rank, away_rank)
    max_rank = max(home_rank, away_rank)

    if min_rank <= 10:
        score += 300
    elif min_rank <= 25:
        score += 100

    # Upset potential scaling dampener for early quarters (Q1 = 25%, Q2 = 50%, Q3 = 75%, Q4 = 100%)
    quarter_upset_weight = min(1.0, period * 0.25)

    # TOP 10 UPSET ALERT
    if diff <= 8:
        if min_rank <= 10 and max_rank > 15:
            score += 2000.0 * quarter_upset_weight
        elif min_rank <= 25 and max_rank > 25:
            score += 400.0 * quarter_upset_weight

    # Point Spread Upset Potential Bonus (Quadratic Scaling dampening in early Qs)
    try:
        odds = event["competitions"][0].get("odds", [])
        if odds:
            spread = abs(float(odds[0].get("spread", 0)))
            if diff <= 8:
                upset_bonus = (spread ** 2) * 1.5 * quarter_upset_weight
                score += upset_bonus
    except Exception:
        pass

    # 6. Power 4 Preference
    score += 50

    return int(score)

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

    for event in events:
        status_state = event["status"]["type"]["state"]
        period = int(event["status"].get("period", 0))

        # Ignore non-active games and pre-game kickoff delays (Q0)
        if status_state != "in" or period == 0:
            continue

        game_id = str(event["id"])
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
            clock_seconds = parse_clock_to_seconds(clock)

            # Fetch Win Probability for backend watchability sorting
            home_wp, away_wp = get_game_win_probability(game_id)
            watch_score = calculate_watchability_score(event, diff, home_wp, away_wp)

            period_label = f"OT{period - 4}" if period > 4 else f"Q{period}"

            # Dynamic urgency icon
            if period >= 4 and diff <= 8:
                icon = "🚨"
            elif period >= 3 and diff <= 8:
                icon = "🔥"
            else:
                icon = "🏈"

            # Two-line format
            game_str = f"{icon} **{period_label} {clock}**  |  **{away_name}** {away_score} @ **{home_name}** {home_score}\n└ *(Diff: {diff} pts)*  `[{watch_score} pts]`"

            active_close_games.append({
                "str": game_str,
                "watch_score": watch_score,
                "period": period,
                "diff": diff,
                "clock_seconds": clock_seconds
            })

    # Sort by Watchability Score DESCENDING
    active_close_games.sort(
        key=lambda g: (-g["watch_score"], -g["period"], g["diff"], g["clock_seconds"])
    )

    if active_close_games:
        description_text = "\n\n".join([g["str"] for g in active_close_games])
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
