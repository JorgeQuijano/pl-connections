#!/usr/bin/env python3
"""Crawl Transfermarkt for big-4 European league squads + per-player club history.

Leagues: Premier League (eng), Bundesliga (deu), Serie A (ita), La Liga (esp).

Two phases:
  1) crawl  — fetch squad pages + per-player youth/history into data/raw/ (resumable)
              and write data/leagues/{key}.json (club registry: ids, observed names, squad size)
  2) assemble — rebuild the final dataset from raw cache + registries, computing
              involvements against a full club-name registry (order-independent)

Usage:
  .venv/bin/python scripts/crawl.py crawl --leagues eng,deu,ita,esp
  .venv/bin/python scripts/crawl.py crawl --leagues ita --limit 3   # smoke test
  .venv/bin/python scripts/crawl.py assemble --out data/pl-connections.json
"""
import argparse, json, os, re, sys, time, unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, "data", "raw")
LEAGUE_DIR = os.path.join(BASE, "data", "leagues")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SEASON = 2026

# League definitions: club ids for the 26/27 season (TM competition ids GB1/L1/IT1/ES1).
LEAGUES = [
    {"key": "eng", "name": "Premier League", "clubs": [11, 29, 31, 148, 281, 289, 399, 405, 631, 677,
                                                         703, 762, 873, 931, 985, 989, 990, 1148, 1237, 3008]},
    {"key": "deu", "name": "Bundesliga", "clubs": [3, 15, 16, 18, 24, 27, 33, 39, 41, 60,
                                                    64, 79, 86, 89, 127, 167, 533, 23826]},
    {"key": "ita", "name": "Serie A", "clubs": [5, 12, 46, 130, 252, 398, 410, 416, 430, 506,
                                                 607, 800, 1005, 1025, 1047, 1390, 2919, 6195, 6574, 8970]},
    {"key": "esp", "name": "La Liga", "clubs": [13, 131, 150, 331, 367, 368, 418, 621, 630, 681,
                                                 714, 897, 940, 1049, 1050, 1084, 1108, 1531, 3368, 3709]},
]
# Display-name overrides (squad-page h1 is the fallback; override where h1 is verbose/odd).
NAMES = {11: "Arsenal", 29: "Everton", 31: "Liverpool", 148: "Tottenham Hotspur",
         281: "Manchester City", 289: "Sunderland", 399: "Leeds United", 405: "Aston Villa",
         631: "Chelsea", 677: "Ipswich Town", 703: "Nottingham Forest", 762: "Newcastle United",
         873: "Crystal Palace", 931: "Fulham", 985: "Manchester United", 989: "Bournemouth",
         990: "Coventry City", 1148: "Brentford", 1237: "Brighton & Hove Albion", 3008: "Hull City",
         3: "FC Köln", 15: "Bayer Leverkusen", 16: "Borussia Dortmund", 18: "Borussia Mönchengladbach",
         24: "Eintracht Frankfurt", 27: "Bayern Munich", 33: "Schalke 04", 39: "Mainz 05",
         41: "Hamburger SV", 60: "SC Freiburg", 64: "Elversberg", 79: "VfB Stuttgart",
         86: "Werder Bremen", 89: "Union Berlin", 127: "SC Paderborn", 167: "FC Augsburg",
         533: "TSG Hoffenheim", 23826: "RB Leipzig",
         5: "AC Milan", 12: "AS Roma", 46: "Inter Milan", 130: "Parma", 252: "Genoa",
         398: "Lazio", 410: "Udinese", 416: "Torino", 430: "Fiorentina", 506: "Juventus",
         607: "Venezia", 800: "Atalanta", 1005: "Lecce", 1025: "Bologna", 1047: "Como",
         1390: "Cagliari", 2919: "Monza", 6195: "Napoli", 6574: "Sassuolo", 8970: "Frosinone",
         13: "Atlético Madrid", 131: "Barcelona", 150: "Real Betis", 331: "Osasuna",
         367: "Rayo Vallecano", 368: "Sevilla", 418: "Real Madrid", 621: "Athletic Bilbao",
         630: "Racing Santander", 681: "Real Sociedad", 714: "Espanyol", 897: "Deportivo La Coruña",
         940: "Celta Vigo", 1049: "Valencia", 1050: "Villarreal", 1084: "Málaga",
         1108: "Alavés", 1531: "Elche", 3368: "Levante", 3709: "Getafe"}

YOUTH_MARKERS = re.compile(
    r"\b(u\d{2}|u\d{2}s?|yth\.?|youth|academy|reserves?|res\.?|i[ivx]?|b team|ii|b|junior|sub-19|sub-20|sub-21|sub-23)\b|(-19|-21|-23)$",
    re.I)

POS_GROUP = {
    "Goalkeeper": "GK", "Defender": "DF", "Right-Back": "DF", "Centre-Back": "DF", "Left-Back": "DF",
    "Midfielder": "MF", "Defensive Midfield": "MF", "Central Midfield": "MF",
    "Attacking Midfield": "MF", "Right Midfield": "MF", "Left Midfield": "MF",
    "Attack": "FW", "Right Winger": "FW", "Left Winger": "FW", "Centre-Forward": "FW",
    "Second Striker": "FW", "Striker": "FW",
}

# Known alternate spellings/abbreviations -> canonical display name (normalized keys).
DISPLAY_ALIAS = {
    "chelsea fc": "Chelsea", "chelsea u18": "Chelsea", "chelsea u21": "Chelsea",
    "chelsea u23": "Chelsea", "chelsea u19": "Chelsea", "chelsea youth": "Chelsea",
    "arsenal fc": "Arsenal", "arsenal u21": "Arsenal", "arsenal u18": "Arsenal", "arsenal u23": "Arsenal",
    "liverpool fc": "Liverpool", "liverpool u21": "Liverpool", "liverpool u18": "Liverpool",
    "manchester city u21": "Manchester City", "manchester city u18": "Manchester City", "manchester city u23": "Manchester City",
    "man city": "Manchester City", "manchester united u21": "Manchester United", "manchester united u18": "Manchester United",
    "manchester united u23": "Manchester United", "man utd": "Manchester United", "manchester united fc": "Manchester United",
    "tottenham": "Tottenham Hotspur", "tottenham hotspur u21": "Tottenham Hotspur", "spurs": "Tottenham Hotspur",
    "newcastle": "Newcastle United", "newcastle united u21": "Newcastle United", "newcastle united u18": "Newcastle United",
    "aston villa u21": "Aston Villa", "aston villa fc": "Aston Villa",
    "everton fc": "Everton", "fulham fc": "Fulham",
    "west ham united": "West Ham United", "west ham": "West Ham United", "west ham u18": "West Ham United",
    "leeds": "Leeds United", "leeds united u21": "Leeds United",
    "afc sunderland": "Sunderland", "sunderland afc": "Sunderland",
    "ipswich": "Ipswich Town", "nottingham": "Nottingham Forest",
    "nottm forest": "Nottingham Forest", "nott m forest": "Nottingham Forest",
    "nottingham forest fc": "Nottingham Forest", "nott m forest u21": "Nottingham Forest",
    "nott m forest u18": "Nottingham Forest", "nott m forest u23": "Nottingham Forest",
    "crystal palace u21": "Crystal Palace", "afc bournemouth": "Bournemouth",
    "coventry": "Coventry City", "brentford fc": "Brentford",
    "brighton": "Brighton & Hove Albion", "brighton & hove albion fc": "Brighton & Hove Albion",
    "hull": "Hull City",
    "fc bayern munchen": "Bayern Munich", "bayern": "Bayern Munich", "fc bayern": "Bayern Munich",
    "bayern munchen": "Bayern Munich", "bayern munich u19": "Bayern Munich", "bayern munich ii": "Bayern Munich",
    "bayern munich u17": "Bayern Munich", "borussia dortmund u19": "Borussia Dortmund", "bvb dortmund": "Borussia Dortmund",
    "rb leipzig": "RB Leipzig", "rasenballsport leipzig": "RB Leipzig", "bayer 04 leverkusen": "Bayer Leverkusen",
    "bayer leverkusen": "Bayer Leverkusen", "borussia monchengladbach": "Borussia Mönchengladbach",
    "eintracht frankfurt": "Eintracht Frankfurt", "vfb stuttgart": "VfB Stuttgart", "vfl wolfsburg": "Wolfsburg",
    "1 fc koln": "FC Köln", "fc koln": "FC Köln", "1 fc union berlin": "Union Berlin", "fc union berlin": "Union Berlin",
    "1 fsv mainz 05": "Mainz 05", "fc schalke 04": "Schalke 04", "hamburger sv": "Hamburger SV",
    "sc freiburg": "SC Freiburg", "sv werder bremen": "Werder Bremen", "fc augsburg": "FC Augsburg",
    "tsg 1899 hoffenheim": "TSG Hoffenheim", "tsg hoffenheim": "TSG Hoffenheim", "sc paderborn 07": "SC Paderborn",
    "sv 07 elversberg": "Elversberg",
    "ac milan": "AC Milan", "ac mailand": "AC Milan", "ac milan u19": "AC Milan", "ac milan primavera": "AC Milan",
    "inter": "Inter Milan", "inter milan": "Inter Milan", "inter u19": "Inter Milan", "inter u20": "Inter Milan",
    "as roma": "AS Roma", "as rom": "AS Roma", "ssc napoli": "Napoli", "ssc neapel": "Napoli", "napoli": "Napoli",
    "juventus": "Juventus", "juventus fc": "Juventus", "juventus u19": "Juventus", "juventus next gen": "Juventus",
    "juventus u23": "Juventus", "atalanta": "Atalanta", "atalanta bc": "Atalanta", "atalanta u23": "Atalanta",
    "ss lazio": "Lazio", "lazio rom": "Lazio", "acf fiorentina": "Fiorentina", "ac florenz": "Fiorentina",
    "us lecce": "Lecce", "torino fc": "Torino", "fc turin": "Torino", "genoa cfc": "Genoa", "genua cfc": "Genoa",
    "cagliari calcio": "Cagliari", "ac monza": "Monza", "bologna fc 1909": "Bologna", "fc bologna": "Bologna",
    "parma calcio 1913": "Parma", "udinese calcio": "Udinese", "venezia fc": "Venezia", "como 1907": "Como",
    "us sassuolo": "Sassuolo", "frosinone calcio": "Frosinone",
    "real madrid": "Real Madrid", "real madrid cf": "Real Madrid", "real madrid u19": "Real Madrid",
    "real madrid castilla": "Real Madrid", "fc barcelona": "Barcelona", "fc barcelona u19": "Barcelona",
    "barcelona atletic": "Barcelona", "barca atletic": "Barcelona", "atletico madrid": "Atlético Madrid",
    "atletico de madrid": "Atlético Madrid", "atletico madrid u19": "Atlético Madrid", "atletico": "Atlético Madrid",
    "athletic bilbao": "Athletic Bilbao", "real sociedad": "Real Sociedad", "real betis": "Real Betis",
    "real betis balompie": "Real Betis", "betis": "Real Betis", "sevilla fc": "Sevilla", "fc sevilla": "Sevilla",
    "valencia cf": "Valencia", "fc valencia": "Valencia", "villarreal cf": "Villarreal",
    "celta de vigo": "Celta Vigo", "deportivo alaves": "Alavés", "deportivo la coruna": "Deportivo La Coruña",
    "malaga cf": "Málaga", "fc malaga": "Málaga", "ca osasuna": "Osasuna", "osasuna": "Osasuna",
    "rayo vallecano": "Rayo Vallecano", "getafe cf": "Getafe", "fc getafe": "Getafe", "espanyol": "Espanyol",
    "elche cf": "Elche", "fc elche": "Elche", "ud levante": "Levante", "levante ud": "Levante",
    "racing santander": "Racing Santander",
    # short forms used by TM history rows (deu/ita/esp) -> canonical display
    "monchengladbach": "Borussia Mönchengladbach", "dortmund": "Borussia Dortmund",
    "hoffenheim": "TSG Hoffenheim", "mainz": "Mainz 05", "augsburg": "FC Augsburg",
    "stuttgart": "VfB Stuttgart", "frankfurt": "Eintracht Frankfurt", "elversberg": "Elversberg",
    "sv elversberg": "Elversberg", "hamburg": "Hamburger SV",
    "bremen": "Werder Bremen", "freiburg": "SC Freiburg", "paderborn": "SC Paderborn",
    "leipzig": "RB Leipzig", "leverkusen": "Bayer Leverkusen", "koln": "FC Köln",
    "milan": "AC Milan", "rom": "AS Roma", "roma": "AS Roma", "fiorentina": "Fiorentina",
    "bologna": "Bologna", "genoa": "Genoa", "torino": "Torino", "cagliari": "Cagliari",
    "parma": "Parma", "como": "Como", "sassuolo": "Sassuolo", "frosinone": "Frosinone",
    "madrid": "Real Madrid", "sevilla": "Sevilla", "villarreal": "Villarreal",
    "bilbao": "Athletic Bilbao", "sociedad": "Real Sociedad", "alaves": "Alavés",
    "levante": "Levante", "celta": "Celta Vigo", "malaga": "Málaga",
    "deportivo": "Deportivo La Coruña",
}


def norm_key(raw_name):
    s = unicodedata.normalize("NFKD", raw_name.lower()).encode("ascii", "ignore").decode().strip()
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canon_club(raw_name, registry):
    """Map a raw club name from TM rows -> canonical display name.

    registry: {club_id: display_name} for all league clubs. Chain:
    known alias (normalized) -> registry exact match (suffix-stripped youth levels) -> raw.
    """
    raw_name = str(raw_name or "")
    raw_name = re.sub(r"\s*\([^()]*\d[^()]*\)\s*$", "", raw_name)  # 'Chelsea FC (-2007)' -> 'Chelsea FC'
    if not raw_name.strip():
        return None
    key = norm_key(raw_name)
    if key in DISPLAY_ALIAS:
        return DISPLAY_ALIAS[key]
    # exact registry match
    if registry:
        hit = registry.get(key)
        if hit:
            return hit
    # youth-level rows: strip trailing youth tokens, retry registry/alias
    tokens = key.split()
    stripped = key
    while tokens and tokens[-1] in {"u15", "u16", "u17", "u18", "u19", "u20", "u21", "u22", "u23",
                                    "u17s", "u18s", "u19s", "u21s", "yth", "yth.", "youth", "academy",
                                    "reserves", "res.", "ii", "b", "i", "iii", "junior", "b team"}:
        tokens = tokens[:-1]
        stripped = " ".join(tokens)
        if stripped in DISPLAY_ALIAS:
            return DISPLAY_ALIAS[stripped]
        if registry and stripped in registry:
            return registry[stripped]
    return raw_name.strip()


class Crawler:
    UAS = [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]

    def __init__(self, delay=1.1):
        self.delay = delay
        self._n = 0
        self._fresh_session()

    def _fresh_session(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": self.UAS[self._n % len(self.UAS)],
                               "Accept-Language": "en,en-US;q=0.9",
                               "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"})
        self._n += 1

    def rotate(self):
        try:
            self.s.close()
        except Exception:
            pass
        self._fresh_session()
        time.sleep(3)

    def get(self, url, referer="https://www.transfermarkt.com/"):
        for attempt in range(5):
            try:
                r = self.s.get(url, headers={"Referer": referer}, timeout=30)
                if r.status_code in (403, 405, 429, 509) and attempt < 4:
                    self.rotate()
                    time.sleep(15 * (attempt + 1) + 5 * attempt)
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException:
                if attempt == 4:
                    raise
                self.rotate()
                time.sleep(6 * (attempt + 1))
        raise RuntimeError(f"failed: {url}")

    def squad(self, club_id):
        """Squad page -> (display name from h1, [players]). Neutral /-/ URL, no slug needed."""
        url = f"https://www.transfermarkt.com/-/kader/verein/{club_id}/saison_id/{SEASON}"
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        name = NAMES.get(club_id)
        if not name:
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
        players = []
        for row in soup.select("tr.odd, tr.even"):
            hl = row.select_one("td.hauptlink a[href*='profil/spieler']")
            if not hl:
                continue
            pid = hl["href"].rsplit("/", 1)[-1]
            tds = row.find_all("td")
            pname = hl.get_text(strip=True)
            pos = ""
            try:
                idx = tds.index(hl.find_parent("td"))
                if idx + 1 < len(tds):
                    pos = tds[idx + 1].get_text(strip=True)
            except ValueError:
                pass
            players.append({"id": pid, "name": pname, "position": pos})
        return name or NAMES.get(club_id, str(club_id)), players

    def youth_affiliations(self, player_id):
        url = f"https://www.transfermarkt.com/-/profil/spieler/{player_id}"
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        out = []
        for h2 in soup.select("h2.content-box-headline"):
            if h2.get_text(strip=True).lower() == "youth clubs":
                div = h2.find_next_sibling("div", class_="content")
                if div:
                    for chunk in div.get_text(" ", strip=True).split(","):
                        chunk = chunk.strip()
                        m = re.search(r"\s*\(([^()]*)\)\s*$", chunk)
                        if m:
                            name = chunk[: m.start()].strip()
                            inside = m.group(1).replace("\u2013", "-").strip()
                            nums = re.findall(r"\d{4}", inside)
                            if nums and inside[:1].isdigit():
                                fr, to = int(nums[0]), int(nums[-1]) if len(nums) > 1 else None
                            elif nums:
                                fr, to = None, int(nums[-1])
                            else:
                                fr = to = None
                            out.append({"club": name, "from": fr, "to": to})
                        else:
                            out.append({"club": chunk, "from": None, "to": None})
        return out

    def transfer_history(self, player_id):
        return self.get(f"https://www.transfermarkt.com/ceapi/transferHistory/list/{player_id}").json().get("transfers", [])

    def player(self, pid):
        cache = os.path.join(RAW_DIR, f"{pid}.json")
        if os.path.exists(cache):
            return json.load(open(cache))
        rec = {"id": pid, "youth": self.youth_affiliations(pid)}
        time.sleep(self.delay)
        rec["history"] = self.transfer_history(pid)
        os.makedirs(RAW_DIR, exist_ok=True)
        json.dump(rec, open(cache, "w"))
        return rec


def involvement_summary(player, registry):
    inv = {}
    for y in player.get("youth", []):
        c = canon_club(y["club"], registry)
        if not c:
            continue
        e = inv.setdefault(c, {"roles": set(), "years": None, "first": None, "last": None})
        e["roles"].add("academy")
        if y.get("from"):
            e["years"] = f"{y['from']}-{y['to'] or ''}"
    for tr in player.get("history", []):
        to = tr.get("to")
        to = to.get("clubName", "") if isinstance(to, dict) else str(to or "")
        to = re.sub(r"\s*\([^()]*\d[^()]*\)\s*$", "", to)
        c = canon_club(to, registry)
        if not c:
            continue
        e = inv.setdefault(c, {"roles": set(), "years": None, "first": None, "last": None})
        e["roles"].add("academy" if YOUTH_MARKERS.search(norm_key(to)) else "senior")
        d = tr.get("dateUnformatted") or tr.get("date")
        if isinstance(d, dict):
            d = d.get("date") or d.get("dateUnformatted")
        if isinstance(d, str) and d:
            dt = d[:10]
            if e["first"] is None or dt < e["first"]:
                e["first"] = dt
            if e["last"] is None or dt > e["last"]:
                e["last"] = dt
    out = []
    for club, e in inv.items():
        if len(e["roles"]) == 2:
            role = "both"
        elif e["roles"] == {"senior"}:
            role = "senior"
        else:
            role = "academy"
        out.append({"club": club, "role": role, "years": e["years"],
                    "firstDate": e["first"], "lastDate": e["last"]})
    return out


def cmd_crawl(args):
    league_keys = args.leagues.split(",") if args.leagues else [L["key"] for L in LEAGUES]
    os.makedirs(LEAGUE_DIR, exist_ok=True)
    cw = Crawler(delay=args.delay)
    membership = {}
    mf = os.path.join(BASE, "data", "membership.json")
    if os.path.exists(mf):
        membership = json.load(open(mf))
    grand_total = grand_err = 0
    for key in league_keys:
        lg = next(L for L in LEAGUES if L["key"] == key)
        print(f"===== {lg['name']} ({key}) =====", flush=True)
        clubs_meta, players, errors = [], [], []
        for club_id in lg["clubs"]:
            try:
                name, squad = cw.squad(club_id)
            except Exception as e:
                print(f"[club {club_id}] squad failed: {e}", flush=True)
                errors.append({"club": club_id, "error": str(e)})
                continue
            if args.limit:
                squad = squad[: args.limit]
            clubs_meta.append({"id": club_id, "name": name, "squadSize": len(squad)})
            for p in squad:
                try:
                    cw.player(p["id"])  # populate raw cache (no-op if cached)
                    membership[p["id"]] = {"clubId": club_id, "clubName": name, "league": key,
                                           "name": p["name"], "position": p["position"]}
                    players.append(p["id"])
                    print(f"  {p['name'][:28]:28} {p['position'][:16]}", flush=True)
                except Exception as e:
                    print(f"  ! {p['name']} ({p['id']}) failed: {e}", flush=True)
                    errors.append({"club": club_id, "player": p["id"], "error": str(e)})
                time.sleep(args.delay)
        json.dump({"league": key, "name": lg["name"], "clubs": clubs_meta,
                   "crawledAt": datetime.now(timezone.utc).isoformat()},
                  open(os.path.join(LEAGUE_DIR, f"{key}.json"), "w"), ensure_ascii=False, indent=1)
        json.dump(membership, open(mf, "w"))
        print(f"{key}: {len(players)} players, {len(errors)} errors", flush=True)
        grand_total += len(players)
        grand_err += len(errors)
    print(f"DONE: {grand_total} players total, {grand_err} errors (raw cache in {RAW_DIR})")


def cmd_assemble(args):
    registry = {}  # normalized display name -> display name, across all league registries
    leagues = []
    for fname in sorted(os.listdir(LEAGUE_DIR)):
        if not fname.endswith(".json"):
            continue
        m = json.load(open(os.path.join(LEAGUE_DIR, fname)))
        for c in m["clubs"]:
            registry[norm_key(c["name"])] = c["name"]
        leagues.append({"key": m["league"], "name": m["name"], "clubs": m["clubs"]})
    if not registry:
        print("no league registries found — run `crawl` first")
        sys.exit(1)
    order = {L["key"]: i for i, L in enumerate(LEAGUES)}
    expected = {L["key"]: len(L["clubs"]) for L in LEAGUES}
    complete = [l for l in leagues if expected.get(l["key"], 0) == len(l["clubs"])]
    for l in leagues:
        if l not in complete:
            print(f"WARN: league {l['key']} incomplete ({len(l['clubs'])}/{expected.get(l['key'])} clubs) — excluded")
    leagues = sorted(complete, key=lambda l: order.get(l["key"], 99))
    if not leagues:
        print("no complete leagues — run `crawl` first")
        sys.exit(1)

    mf = os.path.join(BASE, "data", "membership.json")
    if not os.path.exists(mf):
        print("data/membership.json missing — run `crawl` first")
        sys.exit(1)
    membership = json.load(open(mf))
    known = {c["id"] for lg in leagues for c in lg["clubs"]}

    players, errors = [], []
    for pid, mem in membership.items():
        try:
            rawf = os.path.join(RAW_DIR, f"{pid}.json")
            if not os.path.exists(rawf) or mem["clubId"] not in known:
                continue
            rec = json.load(open(rawf))
            inv = involvement_summary(rec, registry)
            players.append({"id": pid, "name": mem["name"], "position": mem.get("position", ""),
                            "group": POS_GROUP.get(mem.get("position", ""), "?"),
                            "league": mem["league"],
                            "club": {"id": mem["clubId"], "name": mem["clubName"]},
                            "involvements": inv})
        except Exception as e:
            errors.append({"player": pid, "error": str(e)})
    out = {"meta": {"season": f"{SEASON}/{SEASON+1}", "leagues": leagues,
                    "crawledAt": datetime.now(timezone.utc).isoformat(),
                    "source": "transfermarkt.com"},
           "players": players, "errors": errors}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"OK: {len(players)} players, {len(errors)} errors -> {args.out}")


def main():
    ap = argparse.ArgumentParser(description="big-4 league football crawler")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("crawl", help="fetch squads + player history into raw cache")
    pc.add_argument("--leagues", help="comma list of league keys (default: all)")
    pc.add_argument("--limit", type=int, help="max players per club (smoke test)")
    pc.add_argument("--delay", type=float, default=1.1)
    pc.set_defaults(fn=cmd_crawl)
    pa = sub.add_parser("assemble", help="rebuild final dataset from cache")
    pa.add_argument("--out", default=os.path.join(BASE, "data", "pl-connections.json"))
    pa.set_defaults(fn=cmd_assemble)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
