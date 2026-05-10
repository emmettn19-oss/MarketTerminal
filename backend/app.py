#!/usr/bin/env python3
# Razor Flask API v1 -- imports from mlb_model_v7.py

import sys
import os
import sqlite3
import requests
from datetime import date, datetime, timezone
from flask import Flask, jsonify
from flask_cors import CORS

sys.path.insert(0, os.path.expanduser("~/Desktop/MLB_Models"))
from mlb_model_v7 import (
    api_get, get_offense_metrics, get_sp_metrics, get_bullpen_metrics,
    score_sp_pairs, score_bullpen_pairs, score_pythagorean,
    score_last_10, score_rest, clamp,
    STRUCTURAL_HOME_BASELINE, MATCHUP_MULTIPLIER, WEIGHTS, BASE, SEASON
)

ODDS_API_KEY = "6e88c0c9fcb990743801cfab80f2a3ed"
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"

ABBREV = {'Arizona Diamondbacks':'ARI','Atlanta Braves':'ATL','Baltimore Orioles':'BAL','Boston Red Sox':'BOS','Chicago Cubs':'CHC','Chicago White Sox':'CWS','Cincinnati Reds':'CIN','Cleveland Guardians':'CLE','Colorado Rockies':'COL','Detroit Tigers':'DET','Houston Astros':'HOU','Kansas City Royals':'KC','Los Angeles Angels':'LAA','Los Angeles Dodgers':'LAD','Miami Marlins':'MIA','Milwaukee Brewers':'MIL','Minnesota Twins':'MIN','New York Mets':'NYM','New York Yankees':'NYY','Oakland Athletics':'OAK','Athletics':'OAK','Philadelphia Phillies':'PHI','Pittsburgh Pirates':'PIT','San Diego Padres':'SD','San Francisco Giants':'SF','Seattle Mariners':'SEA','St. Louis Cardinals':'STL','Tampa Bay Rays':'TB','Texas Rangers':'TEX','Toronto Blue Jays':'TOR','Washington Nationals':'WSH'}

ABBREV = {'Arizona Diamondbacks':'ARI','Atlanta Braves':'ATL','Baltimore Orioles':'BAL','Boston Red Sox':'BOS','Chicago Cubs':'CHC','Chicago White Sox':'CWS','Cincinnati Reds':'CIN','Cleveland Guardians':'CLE','Colorado Rockies':'COL','Detroit Tigers':'DET','Houston Astros':'HOU','Kansas City Royals':'KC','Los Angeles Angels':'LAA','Los Angeles Dodgers':'LAD','Miami Marlins':'MIA','Milwaukee Brewers':'MIL','Minnesota Twins':'MIN','New York Mets':'NYM','New York Yankees':'NYY','Oakland Athletics':'OAK','Athletics':'OAK','Philadelphia Phillies':'PHI','Pittsburgh Pirates':'PIT','San Diego Padres':'SD','San Francisco Giants':'SF','Seattle Mariners':'SEA','St. Louis Cardinals':'STL','Tampa Bay Rays':'TB','Texas Rangers':'TEX','Toronto Blue Jays':'TOR','Washington Nationals':'WSH'}
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "razor.db")

app = Flask(__name__)
CORS(app)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS line_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT, timestamp TEXT, away_ml INTEGER, home_ml INTEGER, away_implied REAL, home_implied REAL)")
    conn.commit()
    conn.close()

def store_snapshot(game_id, away_ml, home_ml, away_imp, home_imp):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO line_snapshots (game_id, timestamp, away_ml, home_ml, away_implied, home_implied) VALUES (?, ?, ?, ?, ?, ?)",
        (game_id, datetime.utcnow().isoformat(), away_ml, home_ml, away_imp, home_imp))
    conn.commit()
    conn.close()

def get_snapshots(game_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT timestamp, away_ml, home_ml, away_implied, home_implied FROM line_snapshots WHERE game_id=? ORDER BY timestamp", (game_id,))
    rows = c.fetchall()
    conn.close()
    return [{"timestamp": r[0], "away_ml": r[1], "home_ml": r[2], "away_implied": r[3], "home_implied": r[4]} for r in rows]

def ml_to_implied(ml):
    try:
        ml = float(ml)
        if ml < 0:
            return abs(ml) / (abs(ml) + 100)
        return 100 / (ml + 100)
    except Exception:
        return None

def fetch_odds():
    if not ODDS_API_KEY or ODDS_API_KEY == "YOUR_KEY_HERE":
        return {}
    try:
        params = {"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h", "oddsFormat": "american", "dateFormat": "iso"}
        r = requests.get(ODDS_API_URL, params=params, timeout=10)
        r.raise_for_status()
        odds_data = r.json()
        odds_map = {}
        for game in odds_data:
            away = game.get("away_team", "")
            home = game.get("home_team", "")
            game_id = game.get("id", "")
            key = away + "@" + home
            for bookmaker in game.get("bookmakers", []):
                if bookmaker.get("key") == "draftkings":
                    for market in bookmaker.get("markets", []):
                        if market.get("key") == "h2h":
                            outcomes = market.get("outcomes", [])
                            away_ml = None
                            home_ml = None
                            for o in outcomes:
                                if o["name"] == away:
                                    away_ml = o["price"]
                                elif o["name"] == home:
                                    home_ml = o["price"]
                            if away_ml and home_ml:
                                odds_map[key] = {"game_id": game_id, "away_ml": away_ml, "home_ml": home_ml}
                            break
                    break
        return odds_map
    except Exception as e:
        print("[Odds API] " + str(e))
        return {}

def score_game(g):
    away_id      = g["teams"]["away"]["team"]["id"]
    home_id      = g["teams"]["home"]["team"]["id"]
    away_name    = g["teams"]["away"]["team"].get("name", "Away")
    home_name    = g["teams"]["home"]["team"].get("name", "Home")
    away_sp_id   = g["teams"]["away"].get("probablePitcher", {}).get("id")
    home_sp_id   = g["teams"]["home"].get("probablePitcher", {}).get("id")
    away_sp_name = g["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")
    home_sp_name = g["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
    game_id      = str(g.get("gamePk", ""))
    game_time    = g.get("gameDate", "")
    ao  = get_offense_metrics(away_id)
    ho  = get_offense_metrics(home_id)
    asp = get_sp_metrics(away_sp_id)
    hsp = get_sp_metrics(home_sp_id)
    abp = get_bullpen_metrics(away_id, away_sp_id)
    hbp = get_bullpen_metrics(home_id, home_sp_id)
    sp_s  = score_sp_pairs(ho, ao, hsp, asp)
    bp_s  = score_bullpen_pairs(ho, ao, hbp, abp)
    py_s  = score_pythagorean(home_id, away_id)
    l10_s = score_last_10(home_id, away_id)
    rs_s  = score_rest(home_id, away_id)
    W = WEIGHTS
    composite = clamp(
        sp_s["p1"] * W["p1_rsg_sp"] +
        sp_s["p2"] * W["p2_ops_sp"] +
        sp_s["p3"] * W["p3_iso_sp"] +
        bp_s["p4"] * W["p4_rsg_bp"] +
        bp_s["p5"] * W["p5_ops_bp"] +
        bp_s["p6"] * W["p6_iso_bp"] +
        py_s       * W["pythagorean"] +
        l10_s      * W["last_10"] +
        rs_s       * W["rest"]
    )
    model_h = round(clamp(STRUCTURAL_HOME_BASELINE + composite * MATCHUP_MULTIPLIER, 0.30, 0.75), 4)
    model_a = round(1 - model_h, 4)
    return {
        "gameId": game_id,
        "gameTime": game_time,
        "awayTeam": ABBREV.get(away_name, away_name[:3].upper()),
        "homeTeam": ABBREV.get(home_name, home_name[:3].upper()),
        "awayTeamFull": away_name,
        "homeTeamFull": home_name,
        "awayPitcher": away_sp_name,
        "homePitcher": home_sp_name,
        "modelProb": {"away": model_a, "home": model_h},
        "composite": round(composite, 4),
        "spReliable": asp.get("games_started", 0) >= 3 and hsp.get("games_started", 0) >= 3,
        "moneyline": None,
        "impliedProb": None,
        "fairProb": None,
        "edge": None,
        
    }

@app.route("/games")
def get_games():
    today_str = date.today().strftime("%Y-%m-%d")
    url = BASE + "/schedule?sportId=1&date=" + today_str + "&hydrate=probablePitcher,team"
    data = api_get(url)
    all_games = []
    for d in data.get("dates", []):
        all_games.extend(d.get("games", []))
    odds_map = fetch_odds()
    results = []
    for g in all_games:
        try:
            result = score_game(g)
            key = result["awayTeamFull"] + "@" + result["homeTeamFull"]
            if key in odds_map:
                o = odds_map[key]
                away_ml = o["away_ml"]
                home_ml = o["home_ml"]
                away_imp = ml_to_implied(away_ml)
                home_imp = ml_to_implied(home_ml)
                total = away_imp + home_imp
                away_fair = away_imp / total
                home_fair = home_imp / total
                result["moneyline"] = {"away": away_ml, "home": home_ml}
                result["impliedProb"] = {"away": round(away_imp, 4), "home": round(home_imp, 4)}
                result["fairProb"] = {"away": round(away_fair, 4), "home": round(home_fair, 4)}
                result["edge"] = {
                    "away": round(result["modelProb"]["away"] - away_fair, 4),
                    "home": round(result["modelProb"]["home"] - home_fair, 4)
                }
                store_snapshot(o["game_id"], away_ml, home_ml, away_imp, home_imp)
            results.append(result)
        except Exception as e:
            print("[SKIP] " + str(e))
            continue
    now = datetime.now(timezone.utc)
    results = [g for g in results if datetime.fromisoformat(g["gameTime"].replace("Z", "+00:00")) > now]
    results.sort(key=lambda r: max(r["edge"]["away"], r["edge"]["home"]) if r["edge"] else 0, reverse=True)
    return jsonify(results)

@app.route("/games/<game_id>/history")
def get_game_history(game_id):
    return jsonify(get_snapshots(game_id))

@app.route("/health")
def health():
    return jsonify({"status": "ok", "date": date.today().strftime("%Y-%m-%d"), "version": "v7"})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=True)
