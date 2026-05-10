#!/usr/bin/env python3
"""
MLB Sharp Model v7 — Bill Walters matched-pair philosophy
6 symmetric dimensions. Each scoring function: both teams in, single net score out.
positive = home edge, negative = away edge
"""

import requests
import os
from datetime import date, datetime, timedelta

# ── League Averages (2024 MLB baseline) ────────────────────────────────────────
LG = {
    'rs_g':   4.40,
    'ops':    0.714,
    'iso':    0.150,
    'sp_era': 4.35,
    'sp_kbb': 0.110,
    'sp_hr9': 1.10,
    'bp_era': 4.35,
    'bp_kbb': 0.120,
    'bp_hr9': 1.05,
    'obp':    0.315,
    'lg_fip': 4.10,
}

FIP_CONST = 3.10   # FIP constant (MLB baseline)
FIP_C     = 100    # Bayesian regression IP floor

WEIGHTS = {
    'p1_rsg_sp':   0.20,
    'p2_ops_sp':   0.20,
    'p3_iso_sp':   0.08,
    'p4_rsg_bp':   0.10,
    'p5_ops_bp':   0.10,
    'p6_iso_bp':   0.06,
    'pythagorean': 0.15,
    'last_10':     0.08,
    'rest':        0.03,
}

# Home field is structural, not a weighted input.
# 0.535 = historical MLB home win rate baseline.
# MATCHUP_MULTIPLIER calibrated May 7 2026 — revisit after full season sample.
STRUCTURAL_HOME_BASELINE = 0.535
MATCHUP_MULTIPLIER       = 0.60

SEASON = date.today().year
BASE   = "https://statsapi.mlb.com/api/v1"


# ── Utilities ──────────────────────────────────────────────────────────────────

def api_get(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [API] {e}")
        return {}

def fv(d, key, fallback=0.0):
    try:
        return float(d.get(key, fallback) or fallback)
    except (ValueError, TypeError):
        return float(fallback)

def net_score(h, a):
    denom = h + a
    if denom < 1e-9:
        return 0.0
    return (h - a) / denom

def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


# ── Data Fetchers ──────────────────────────────────────────────────────────────

def fetch_team_hitting(team_id):
    url = f"{BASE}/teams/{team_id}/stats?stats=season&group=hitting&season={SEASON}"
    d = api_get(url)
    try:
        return d['stats'][0]['splits'][0]['stat']
    except (KeyError, IndexError):
        return {}

def fetch_team_pitching(team_id):
    url = f"{BASE}/teams/{team_id}/stats?stats=season&group=pitching&season={SEASON}"
    d = api_get(url)
    try:
        return d['stats'][0]['splits'][0]['stat']
    except (KeyError, IndexError):
        return {}

def fetch_pitcher_stats(pitcher_id):
    if not pitcher_id:
        return {}
    url = f"{BASE}/people/{pitcher_id}/stats?stats=season&group=pitching&season={SEASON}"
    d = api_get(url)
    try:
        return d['stats'][0]['splits'][0]['stat']
    except (KeyError, IndexError):
        return {}

def fetch_last_n_games(team_id, n=10):
    end   = date.today().strftime('%Y-%m-%d')
    start = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    url   = (f"{BASE}/schedule?sportId=1&teamId={team_id}"
             f"&startDate={start}&endDate={end}"
             f"&hydrate=linescore,team&gameType=R")
    d = api_get(url)
    results = []
    try:
        for de in reversed(d.get('dates', [])):
            for game in de.get('games', []):
                if game.get('status', {}).get('abstractGameState') != 'Final':
                    continue
                ls  = game.get('linescore', {}).get('teams', {})
                hid = game['teams']['home']['team']['id']
                if hid == team_id:
                    rs = fv(ls.get('home', {}), 'runs')
                    ra = fv(ls.get('away', {}), 'runs')
                else:
                    rs = fv(ls.get('away', {}), 'runs')
                    ra = fv(ls.get('home', {}), 'runs')
                results.append((rs, ra))
                if len(results) >= n:
                    return results
    except Exception as e:
        print(f"  [last10 fetch error team={team_id}] {e}")
    return results

def fetch_last_game_date(team_id):
    end   = date.today().strftime('%Y-%m-%d')
    start = (date.today() - timedelta(days=7)).strftime('%Y-%m-%d')
    url   = (f"{BASE}/schedule?sportId=1&teamId={team_id}"
             f"&startDate={start}&endDate={end}&gameType=R")
    d = api_get(url)
    last = None
    try:
        for de in d.get('dates', []):
            for game in de.get('games', []):
                if game.get('status', {}).get('abstractGameState') == 'Final':
                    gd = datetime.strptime(de['date'], '%Y-%m-%d').date()
                    if last is None or gd > last:
                        last = gd
    except Exception as e:
        print(f"  [rest fetch error team={team_id}] {e}")
    return last


# ── Derived Metrics ────────────────────────────────────────────────────────────

def get_offense_metrics(team_id):
    hs   = fetch_team_hitting(team_id)
    gp   = max(fv(hs, 'gamesPlayed', 1), 1)
    rs_g = fv(hs, 'runs') / gp
    obp  = fv(hs, 'obp',  LG['obp'])
    ops  = fv(hs, 'ops',  LG['ops'])
    slg  = fv(hs, 'slg',  0.0)
    avg  = fv(hs, 'avg',  0.0)
    iso  = round(slg - avg, 4) if slg > 0 and avg > 0 else LG['iso']
    return {'rs_g': round(rs_g, 3), 'obp': round(float(obp), 3), 'ops': round(float(ops), 3), 'iso': iso}

def get_sp_metrics(pitcher_id):
    ss  = fetch_pitcher_stats(pitcher_id)
    ip  = fv(ss, 'inningsPitched')
    bf  = fv(ss, 'battersFaced', ip * 3.2)
    k   = fv(ss, 'strikeOuts')
    bb  = fv(ss, 'baseOnBalls')
    hbp = fv(ss, 'hitBatsmen')
    hr  = fv(ss, 'homeRuns')
    kbb = (k - bb) / max(bf, 1) if bf > 0 else LG['sp_kbb']
    hr9 = (hr / ip) * 9 if ip > 5 else LG['sp_hr9']
    if ip > 0:
        fip_raw = (13 * hr + 3 * (bb + hbp) - 2 * k) / ip + FIP_CONST
        fip_adj = (ip * fip_raw + FIP_C * LG['lg_fip']) / (ip + FIP_C)
    else:
        fip_adj = LG['lg_fip']
    gs = int(fv(ss, 'gamesStarted'))
    return {
        'fip_adj':  round(fip_adj, 2),
        'k_bb_pct': round(kbb, 4),
        'hr_per_9': round(hr9, 3),
        'games_started': gs,
    }

def get_bullpen_metrics(team_id, sp_id):
    ts    = fetch_team_pitching(team_id)
    ss    = fetch_pitcher_stats(sp_id)
    t_ip  = fv(ts, 'inningsPitched')
    t_k   = fv(ts, 'strikeOuts')
    t_bb  = fv(ts, 'baseOnBalls')
    t_hbp = fv(ts, 'hitBatsmen')
    t_hr  = fv(ts, 'homeRuns')
    t_bf  = fv(ts, 'battersFaced', t_ip * 3.2)
    s_ip  = fv(ss, 'inningsPitched')
    s_k   = fv(ss, 'strikeOuts')
    s_bb  = fv(ss, 'baseOnBalls')
    s_hbp = fv(ss, 'hitBatsmen')
    s_hr  = fv(ss, 'homeRuns')
    s_bf  = fv(ss, 'battersFaced', s_ip * 3.2)
    bp_ip  = t_ip  - s_ip
    bp_k   = t_k   - s_k
    bp_bb  = t_bb  - s_bb
    bp_hbp = t_hbp - s_hbp
    bp_hr  = t_hr  - s_hr
    bp_bf  = t_bf  - s_bf
    if bp_ip < 10 or bp_bf < 10:
        return {'fip_adj': LG['lg_fip'], 'k_bb_pct': LG['bp_kbb'], 'hr_per_9': LG['bp_hr9']}
    fip_raw = (13 * bp_hr + 3 * (bp_bb + bp_hbp) - 2 * bp_k) / bp_ip + FIP_CONST
    fip_adj = (bp_ip * fip_raw + FIP_C * LG['lg_fip']) / (bp_ip + FIP_C)
    return {
        'fip_adj':  round(fip_adj, 3),
        'k_bb_pct': round((bp_k - bp_bb) / max(bp_bf, 1), 4),
        'hr_per_9': round((bp_hr / bp_ip) * 9, 3),
    }


# ── Scoring Functions ──────────────────────────────────────────────────────────

def score_sp_pairs(ho, ao, hsp, asp):
    h1 = ho['rs_g'] * (max(asp['fip_adj'], 0.5) / LG['lg_fip'])
    a1 = ao['rs_g'] * (max(hsp['fip_adj'], 0.5) / LG['lg_fip'])
    p1 = net_score(h1, a1)

    h2 = ho['ops'] / (1.0 + max(asp['k_bb_pct'], 0.0) * 2.5)
    a2 = ao['ops'] / (1.0 + max(hsp['k_bb_pct'], 0.0) * 2.5)
    p2 = net_score(h2, a2)

    h3 = ho['iso'] * (asp['hr_per_9'] / max(LG['sp_hr9'], 0.1))
    a3 = ao['iso'] * (hsp['hr_per_9'] / max(LG['sp_hr9'], 0.1))
    p3 = net_score(h3, a3)

    return {'p1': clamp(p1), 'p2': clamp(p2), 'p3': clamp(p3)}


def score_bullpen_pairs(ho, ao, hbp, abp):
    h4 = ho['rs_g'] * (max(abp['fip_adj'], 0.5) / LG['lg_fip'])
    a4 = ao['rs_g'] * (max(hbp['fip_adj'], 0.5) / LG['lg_fip'])
    p4 = net_score(h4, a4)

    h5 = ho['ops'] / (1.0 + max(abp['k_bb_pct'], 0.0) * 2.5)
    a5 = ao['ops'] / (1.0 + max(hbp['k_bb_pct'], 0.0) * 2.5)
    p5 = net_score(h5, a5)

    h6 = ho['iso'] * (abp['hr_per_9'] / max(LG['bp_hr9'], 0.1))
    a6 = ao['iso'] * (hbp['hr_per_9'] / max(LG['bp_hr9'], 0.1))
    p6 = net_score(h6, a6)

    return {'p4': clamp(p4), 'p5': clamp(p5), 'p6': clamp(p6)}


def score_pythagorean(home_id, away_id):
    def pyth(tid):
        hs = fetch_team_hitting(tid)
        ts = fetch_team_pitching(tid)
        gp = max(fv(hs, 'gamesPlayed', 1), 1)
        rs = fv(hs, 'runs') / gp
        ra = fv(ts, 'runs')
        ra = (ra / gp) if ra > 0 else (fv(ts, 'earnedRuns') / gp * 1.10)
        if rs <= 0 or ra <= 0:
            return 0.5
        return (rs ** 1.83) / (rs ** 1.83 + ra ** 1.83)
    try:
        hp = pyth(home_id)
        ap = pyth(away_id)
        return clamp(net_score(hp, ap))
    except Exception as e:
        print(f"  [pyth error] {e}")
        return 0.0


def score_last_10(home_id, away_id):
    def l10(tid):
        games = fetch_last_n_games(tid, 10)
        if not games:
            return 0.5
        wins  = sum(1 for rs, ra in games if rs > ra)
        rdiff = sum(rs - ra for rs, ra in games)
        wpct  = wins / len(games)
        rd_norm = (clamp(rdiff / (len(games) * 5)) + 1) / 2
        return 0.60 * wpct + 0.40 * rd_norm
    try:
        return clamp(net_score(l10(home_id), l10(away_id)))
    except Exception as e:
        print(f"  [last10 error] {e}")
        return 0.0


def score_rest(home_id, away_id):
    try:
        today  = date.today()
        h_last = fetch_last_game_date(home_id)
        a_last = fetch_last_game_date(away_id)
        h_rest = (today - h_last).days if h_last else 1
        a_rest = (today - a_last).days if a_last else 1
        return clamp((h_rest - a_rest) * 0.15)
    except Exception as e:
        print(f"  [rest error] {e}")
        return 0.0


# ── HTML Builder ───────────────────────────────────────────────────────────────

def build_html(results, today_str):
    import json

    def sr(label, val, hi=False):
        c = 'stat-line highlight' if hi else 'stat-line'
        return ("<div class='" + c + "'>"
                "<span>" + label + "</span>"
                "<span>" + str(val) + "</span></div>")

    cards = ''
    for i, r in enumerate(results):
        ap   = round(r['model_a'] * 100, 1)
        hp   = round(r['model_h'] * 100, 1)
        pick = r['home_name'] if r['model_h'] > r['model_a'] else r['away_name']

        def col(side, i=i, r=r, ap=ap, hp=hp):
            ia  = (side == 'away')
            nm  = r['away_name'] if ia else r['home_name']
            sp  = r['away_sp']   if ia else r['home_sp']
            sm  = r['asp']       if ia else r['hsp']
            bm  = r['abp']       if ia else r['hbp']
            om  = r['ao']        if ia else r['ho']
            pct = ap             if ia else hp
            tag = 'AWAY'         if ia else 'HOME'
            cc  = 'away-col'     if ia else 'home-col'
            pc  = 'away-color'   if ia else 'home-color'
            idx = 'a'            if ia else 'h'
            era  = sm.get('fip_adj', 'N/A')
            kbb  = str(round(sm.get('k_bb_pct', 0) * 100, 1)) + '%'
            hr9  = sm.get('hr_per_9', 'N/A')
            bera = bm.get('fip_adj', 'N/A')
            bkbb = str(round(bm.get('k_bb_pct', 0) * 100, 1)) + '%'
            rpg  = om.get('rs_g', 'N/A')
            ops  = om.get('ops',  'N/A')
            iso  = om.get('iso',  'N/A')
            return (
                "<div class='team-col " + cc + "'>"
                + "<div class='side-tag'>" + tag + "</div>"
                + "<div class='team-title'>" + nm + "</div>"
                + "<div class='section-hdr'>Starting Pitcher</div>"
                + sr('SP', sp)
                + sr('FIP*', era)
                + sr('K-BB%', kbb, True)
                + sr('HR/9', hr9)
                + "<div class='section-hdr'>Bullpen</div>"
                + sr('BP FIP*', bera, True)
                + sr('BP K-BB%', bkbb)
                + "<div class='section-hdr'>Offense</div>"
                + sr('Runs/G', rpg)
                + sr('OPS', ops, True)
                + sr('ISO', iso)
                + "<div class='big-prob " + pc + "'>" + str(pct) + "%</div>"
                + "<div class='odds-row'><label>ML Odds:</label>"
                + "<input type='number' id='" + idx + "o" + str(i)
                + "' class='odds-box' placeholder='-110' oninput='calc(" + str(i) + ")'></div>"
                + "<div class='calc-line'>Implied: <span id='" + idx + "i" + str(i) + "'>&#8212;</span></div>"
                + "<div class='calc-line'>Edge: <b id='" + idx + "e" + str(i) + "'>&#8212;</b></div>"
                + "</div>"
            )

        cards += (
            "<div class='game-card'>"
            + "<div class='matchup-header'>"
            + "<span class='away-label'>" + r['away_name'] + "</span>"
            + "<span class='vs'>@</span>"
            + "<span class='home-label'>" + r['home_name'] + "</span>"
            + "<span class='pick-badge'>Model Favorite: " + pick + "</span>"
            + "</div>"
            + "<div class='two-col'>" + col('away') + col('home') + "</div>"
            + "<div class='verdict-bar' id='vb" + str(i) + "' style='display:none'></div>"
            + "</div>"
        )

    probs_js = json.dumps([{
        'a': r['model_a'], 'h': r['model_h'],
        'an': r['away_name'], 'hn': r['home_name']
    } for r in results])

    css = (
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;"
        "background:#0d1117;color:#e6edf3;padding:16px}"
        "h1{font-size:22px;font-weight:800;margin-bottom:4px}"
        ".sub{font-size:12px;color:#8b949e;margin-bottom:14px}"
        ".game-card{background:#161b22;border:1px solid #30363d;"
        "border-radius:12px;padding:16px;margin-bottom:14px}"
        ".matchup-header{display:flex;align-items:center;gap:8px;flex-wrap:wrap;"
        "margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid #30363d}"
        ".away-label{font-weight:700;color:#f85149;font-size:16px}"
        ".home-label{font-weight:700;color:#58a6ff;font-size:16px}"
        ".vs{color:#8b949e;font-size:12px}"
        ".pick-badge{margin-left:auto;background:#1f6feb;color:#fff;"
        "font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px}"
        ".two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}"
        ".team-col{background:#0d1117;border-radius:8px;padding:12px}"
        ".away-col{border-top:3px solid #f85149}"
        ".home-col{border-top:3px solid #58a6ff}"
        ".side-tag{font-size:10px;font-weight:700;letter-spacing:.08em;"
        "color:#8b949e;margin-bottom:2px}"
        ".team-title{font-size:13px;font-weight:700;margin-bottom:8px}"
        ".section-hdr{font-size:10px;font-weight:700;text-transform:uppercase;"
        "letter-spacing:.06em;color:#8b949e;margin:10px 0 4px;"
        "padding-top:8px;border-top:1px solid #21262d}"
        ".stat-line{display:flex;justify-content:space-between;font-size:11px;"
        "padding:3px 0;color:#8b949e;border-bottom:1px solid #21262d}"
        ".stat-line span:last-child{color:#e6edf3;font-weight:600}"
        ".stat-line.highlight{background:#161b22;border-radius:4px;"
        "padding:3px 6px;border-bottom:none;margin:2px 0}"
        ".stat-line.highlight span{color:#e3b341 !important;font-weight:700}"
        ".big-prob{font-size:30px;font-weight:800;text-align:center;"
        "margin:12px 0 10px;letter-spacing:-1px}"
        ".away-color{color:#f85149}"
        ".home-color{color:#58a6ff}"
        ".odds-row{display:flex;align-items:center;gap:6px;margin-bottom:5px}"
        ".odds-row label{font-size:11px;color:#8b949e;white-space:nowrap}"
        ".odds-box{flex:1;padding:6px 10px;border:1px solid #30363d;"
        "border-radius:6px;font-size:14px;font-weight:700;"
        "background:#1c2128;color:#e3b341;width:100%}"
        ".odds-box:focus{outline:none;border-color:#58a6ff}"
        ".calc-line{font-size:12px;color:#8b949e;padding:2px 0}"
        ".verdict-bar{margin-top:14px;padding:12px 16px;border-radius:8px;"
        "font-size:13px;font-weight:700;text-align:center}"
        ".v-good{background:#1a4731;color:#3fb950;border:1px solid #2ea043}"
        ".v-mid{background:#2d2208;color:#e3b341;border:1px solid #9e6a03}"
        ".v-bad{background:#3d1c1c;color:#f85149;border:1px solid #b62324}"
        "@media(max-width:600px){.two-col{grid-template-columns:1fr}}"
    )

    js = (
        "var P=" + probs_js + ";"
        "function imp(o){return o<0?Math.abs(o)/(Math.abs(o)+100):100/(o+100);}"
        "function edge(id,v){var el=document.getElementById(id);"
        "el.textContent=(v>=0?'+':'-')+(v*100).toFixed(1)+'%';"
        "el.style.color=v>=0.05?'#3fb950':v>=0.02?'#e3b341':'#f85149';}"
        "function calc(i){"
        "var ao=parseFloat(document.getElementById('ao'+i).value);"
        "var ho=parseFloat(document.getElementById('ho'+i).value);"
        "var ap=P[i].a,hp=P[i].h;"
        "if(!isNaN(ao)&&ao!=0){var ai=imp(ao);"
        "document.getElementById('ai'+i).textContent=(ai*100).toFixed(1)+'%';"
        "edge('ae'+i,ap-ai);}"
        "if(!isNaN(ho)&&ho!=0){var hi_=imp(ho);"
        "document.getElementById('hi'+i).textContent=(hi_*100).toFixed(1)+'%';"
        "edge('he'+i,hp-hi_);}"
        "if(!isNaN(ao)&&!isNaN(ho)&&ao!=0&&ho!=0){"
        "var ae=ap-imp(ao),he=hp-imp(ho);"
        "var best=ae>he?ae:he,bn=ae>he?P[i].an:P[i].hn;"
        "var vb=document.getElementById('vb'+i);vb.style.display='block';"
        "if(best>=0.05){vb.className='verdict-bar v-good';"
        "vb.textContent='VALUE BET: '+bn+' -- Edge: +'+(best*100).toFixed(1)+'%';}"
        "else if(best>=0.02){vb.className='verdict-bar v-mid';"
        "vb.textContent='MARGINAL: '+bn+' -- '+(best*100).toFixed(1)+'% -- Caution';}"
        "else{vb.className='verdict-bar v-bad';"
        "vb.textContent='NO EDGE -- Skip this game';}}}"
    )

    return (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>MLB Model V7 - " + today_str + "</title>"
        "<style>" + css + "</style>"
        "</head><body>"
        "<h1>MLB Model V7</h1>"
        "<p class='sub'>" + today_str + " -- "
        + str(len(results)) + " games -- Enter Vegas odds to calculate edge</p>"
        + cards
        + "<script>" + js + "</script>"
        "</body></html>"
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    today_str = date.today().strftime("%Y-%m-%d")
    print("=" * 50)
    print("  MLB Sharp Model V6  --  " + today_str)
    print("=" * 50)
    url = (BASE + "/schedule?sportId=1&date=" + today_str
           + "&hydrate=probablePitcher,team")
    data = api_get(url)
    all_games = []
    for d in data.get("dates", []):
        all_games.extend(d.get("games", []))
    if not all_games:
        print("  No games today.")
        return
    print("  " + str(len(all_games)) + " games. Scoring all...")
    results = []
    for g in all_games:
        try:
            away_id      = g["teams"]["away"]["team"]["id"]
            home_id      = g["teams"]["home"]["team"]["id"]
            away_name    = g["teams"]["away"]["team"].get("name", "Away")
            home_name    = g["teams"]["home"]["team"].get("name", "Home")
            away_sp_id   = g["teams"]["away"].get("probablePitcher", {}).get("id")
            home_sp_id   = g["teams"]["home"].get("probablePitcher", {}).get("id")
            away_sp_name = g["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")
            home_sp_name = g["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
            print("  " + away_name + " @ " + home_name)
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
            print("    -> " + away_name + " " + "{:.1%}".format(model_a)
                  + "  |  " + home_name + " " + "{:.1%}".format(model_h))
            results.append({
                "away_name": away_name, "home_name": home_name,
                "away_sp":   away_sp_name, "home_sp": home_sp_name,
                "model_h":   model_h, "model_a": model_a,
                "composite": composite,
                "sp": sp_s, "bp": bp_s,
                "ao": ao,   "ho": ho,
                "asp": asp, "hsp": hsp,
                "abp": abp, "hbp": hbp,
            })
        except Exception as e:
            print("  [SKIP] " + str(e))
            continue

    report_path = os.path.expanduser(
        "~/Desktop/MLB_Models/MLB_Model_V7_" + today_str + ".html")
    with open(report_path, "w") as f:
        f.write(build_html(results, today_str))
    print("Report: " + report_path)
    os.system("open -a Safari '" + report_path + "'")

if __name__ == '__main__':
    run()
