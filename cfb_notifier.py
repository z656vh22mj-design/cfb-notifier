def calculate_watchability_score(event, home_wp, away_wp):
    """
    Calculates a dynamic Watchability Score based on:
    - Game state (Quarter / Clock)
    - Point differential
    - Win probability closeness
    - Power 4 / Top 10 status
    """
    period = int(event["status"].get("period", 1))
    
    competitors = event["competitions"][0]["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")
    
    home_score = int(home.get("score", 0))
    away_score = int(away.get("score", 0))
    diff = abs(home_score - away_score)

    # 1. Base Score from Quarter (Late games get higher priority)
    score = period * 100

    # 2. Closeness Bonus (1-possession games in late Q4 get huge boost)
    if diff <= 8:
        score += 250
    elif diff <= 17:
        score += 100

    # 3. Win Probability Closeness Boost (30% - 70% range)
    if home_wp is not None:
        wp_margin = abs(home_wp - 0.50)  # 0.0 means 50/50 dead heat
        wp_closeness_bonus = max(0, (0.50 - wp_margin) * 200)
        score += wp_closeness_bonus

    # 4. Top 10 / Ranked Matchup Bonus
    home_rank = int(home.get("curatedRank", {}).get("current", 99))
    away_rank = int(away.get("curatedRank", {}).get("current", 99))
    
    if home_rank <= 10 or away_rank <= 10:
        score += 150  # Top 10 team involved
    elif home_rank <= 25 or away_rank <= 25:
        score += 75   # Ranked team involved

    # 5. Power 4 Conference Preference
    power_4_conferences = ["ACC", "Big 12", "Big Ten", "SEC"]
    home_conf = home.get("team", {}).get("conferenceId", "")
    # Add weight if Power 4 team
    score += 50 

    return score
