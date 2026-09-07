#!/usr/bin/env python3
"""Crawl Transfermarkt for current PL squads + per-player club history (youth + senior).

Output: JSON dataset at data/pl-connections.json
  players[]: {id, name, position, group, club: {id,name},
              youth: [{club, from, to}],           // parsed "Youth clubs" box
              history: [{from, to, date, season, fee}],  // ceapi transfer history (incl youth levels)
              involvements: [{club, role: senior|academy, years, firstDate, lastDate}]}
Usage:
  python scripts/crawl.py                      # all 20 PL clubs
  python scripts/crawl.py --clubs 631,11,281   # subset (spike)
  python scripts/crawl.py --limit 5            # quick smoke test per club
"""
import argparse, json, os, re, sys, time, unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, "data", "raw")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# PL 26/27 participants (from competition page season links, Sep 2026 snapshot)
CLUBS = {
    11:  ("Arsenal", "arsenal-fc"),
    29:  ("Everton", "fc-everton"),
    31:  ("Liverpool", "liverpool-fc"),
    148: ("Tottenham Hotspur", "tottenham-hotspur"),
    281: ("Manchester City", "manchester-city"),
    289: ("Sunderland", "afc-sunderland"),
    399: ("Leeds United", "leeds-united"),
    405: ("Aston Villa", "aston-villa"),
    631: ("Chelsea", "fc-chelsea"),
    677: ("Ipswich Town", "ipswich-town"),
    703: ("Nottingham Forest", "nottingham-forest"),
    762: ("Newcastle United", "newcastle-united"),
    873: ("Crystal Palace", "crystal-palace"),
    931: ("Fulham", "fc-fulham"),
    985: ("Manchester United", "manchester-united"),
    989: ("Bournemouth", "afc-bournemouth"),
    990: ("Coventry City", "coventry-city"),
    1148: ("Brentford", "fc-brentford"),
    1237: ("Brighton & Hove Albion", "brighton-amp-hove-albion"),
    3008: ("Hull City", "hull-city"),
}
SEASON = 2026

YOUTH_MARKERS = re.compile(
    r"\b(u\d{2}|u\d{2}s?|yth\.?|youth|academy|reserves?|res\.?|i[ivx]?|b team|ii|b|junior|sub-19|sub-20|sub-21|sub-23)\b|(-19|-21|-23)$",
    re.I)

POS_GROUP = {
    "Goalkeeper": "GK",
    "Defender": "DF", "Right-Back": "DF", "Centre-Back": "DF", "Left-Back": "DF",
    "Midfielder": "MF", "Defensive Midfield": "MF", "Central Midfield": "MF",
    "Attacking Midfield": "MF", "Right Midfield": "MF", "Left Midfield": "MF",
    "Attack": "FW", "Right Winger": "FW", "Left Winger": "FW", "Centre-Forward": "FW",
    "Second Striker": "FW", "Striker": "FW",
}
DISPLAY_ALIAS = {  # raw row names -> canonical club display names we care about
    "chelsea": "Chelsea", "chelsea youth": "Chelsea", "chelsea u18": "Chelsea", "chelsea u21": "Chelsea",
    "chelsea u23": "Chelsea", "chelsea u19": "Chelsea", "chelsea fc": "Chelsea",
    "arsenal": "Arsenal", "arsenal fc": "Arsenal", "arsenal youth": "Arsenal", "arsenal u21": "Arsenal",
    "arsenal u18": "Arsenal", "arsenal u23": "Arsenal", "arsenal u19": "Arsenal",
    "liverpool": "Liverpool", "liverpool fc": "Liverpool", "liverpool youth": "Liverpool",
    "liverpool u21": "Liverpool", "liverpool u18": "Liverpool", "liverpool u23": "Liverpool",
    "manchester city": "Manchester City", "man city": "Manchester City", "manchester city u21": "Manchester City",
    "manchester city u18": "Manchester City", "manchester city u23": "Manchester City",
    "manchester united": "Manchester United", "man utd": "Manchester United", "manchester united u21": "Manchester United",
    "manchester united u18": "Manchester United", "manchester united u23": "Manchester United",
    "tottenham hotspur": "Tottenham Hotspur", "tottenham": "Tottenham Hotspur", "tottenham hotspur u21": "Tottenham Hotspur",
    "tottenham hotspur u18": "Tottenham Hotspur", "spurs": "Tottenham Hotspur",
    "newcastle united": "Newcastle United", "newcastle": "Newcastle United", "newcastle united u21": "Newcastle United",
    "newcastle united u18": "Newcastle United",
    "aston villa": "Aston Villa", "aston villa u21": "Aston Villa", "aston villa u18": "Aston Villa",
    "everton": "Everton", "everton fc": "Everton", "everton u21": "Everton", "everton u18": "Everton",
    "fulham": "Fulham", "fulham fc": "Fulham", "fulham u21": "Fulham", "fulham u18": "Fulham",
    "west ham united": "West Ham United", "west ham": "West Ham United", "west ham yth.": "West Ham United",
    "west ham u18": "West Ham United", "west ham u21": "West Ham United", "west ham u23": "West Ham United",
    "leeds united": "Leeds United", "leeds": "Leeds United", "leeds united u21": "Leeds United",
    "leeds united u18": "Leeds United", "leeds united u23": "Leeds United",
    "sunderland": "Sunderland", "afc sunderland": "Sunderland", "sunderland afc": "Sunderland", "sunderland u21": "Sunderland", "sunderland u18": "Sunderland",
    "ipswich town": "Ipswich Town", "ipswich": "Ipswich Town", "ipswich town u21": "Ipswich Town", "ipswich town u18": "Ipswich Town",
    "nottingham forest": "Nottingham Forest", "nottingham": "Nottingham Forest", "nottingham forest u21": "Nottingham Forest",
    "nottingham forest u18": "Nottingham Forest", "nottm forest": "Nottingham Forest",
    "nott m forest": "Nottingham Forest", "nott m forest u21": "Nottingham Forest",
    "nott m forest u18": "Nottingham Forest", "nott m forest u23": "Nottingham Forest",
    "nott m forest u19": "Nottingham Forest", "nottingham forest fc": "Nottingham Forest",
    "crystal palace": "Crystal Palace", "crystal palace u21": "Crystal Palace", "crystal palace u18": "Crystal Palace",
    "bournemouth": "Bournemouth", "afc bournemouth": "Bournemouth", "bournemouth u21": "Bournemouth", "bournemouth u18": "Bournemouth",
    "coventry city": "Coventry City", "coventry": "Coventry City", "coventry city u21": "Coventry City", "coventry city u18": "Coventry City",
    "brentford": "Brentford", "brentford fc": "Brentford", "brentford u21": "Brentford", "brentford u18": "Brentford",
    "brighton & hove albion": "Brighton & Hove Albion", "brighton & hove albion fc": "Brighton & Hove Albion", "brighton": "Brighton & Hove Albion",
    "brighton & hove albion u21": "Brighton & Hove Albion", "brighton u18": "Brighton & Hove Albion", "brighton u21": "Brighton & Hove Albion",
    "hull city": "Hull City", "hull": "Hull City", "hull city u21": "Hull City", "hull city u18": "Hull City",
}
NONPL = {"england", "england u21", "wales", "scotland", "ireland", "benfica lisbon", "benfica lisbon u23"}


class Crawler:
    def __init__(self, delay=1.1):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
        self.delay = delay

    def get(self, url, referer="https://www.transfermarkt.com/"):
        for attempt in range(4):
            try:
                r = self.s.get(url, headers={"Referer": referer}, timeout=30)
                if r.status_code in (429, 509, 403) and attempt < 3:
                    time.sleep(20 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                time.sleep(4 * (attempt + 1))
        raise RuntimeError(f"failed: {url}")

    def squad(self, club_id, slug):
        """Return list of {id, name, position} from the kader page."""
        url = f"https://www.transfermarkt.com/{slug}/kader/verein/{club_id}/saison_id/{SEASON}"
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        players = []
        for row in soup.select("tr.odd, tr.even"):
            hl = row.select_one("td.hauptlink a[href*='profil/spieler']")
            if not hl:
                continue
            pid = hl["href"].rsplit("/", 1)[-1]
            tds = row.find_all("td")
            name = hl.get_text(strip=True)
            pos = ""
            try:
                idx = tds.index(hl.find_parent("td"))
                if idx + 1 < len(tds):
                    pos = tds[idx + 1].get_text(strip=True)
            except ValueError:
                pass
            players.append({"id": pid, "name": name, "position": pos})
        return players

    def youth_affiliations(self, player_id):
        """Parse the 'Youth clubs' info box from the profil page."""
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
        url = f"https://www.transfermarkt.com/ceapi/transferHistory/list/{player_id}"
        d = self.get(url).json()
        return d.get("transfers", [])

    def player(self, pid):
        """Fetch + normalize one player's history. Raw results cached under data/raw/."""
        cache = os.path.join(RAW_DIR, f"{pid}.json")
        if os.path.exists(cache):
            return json.load(open(cache))
        youth = self.youth_affiliations(pid)
        time.sleep(self.delay)
        hist = self.transfer_history(pid)
        rec = {"id": pid, "youth": youth, "history": hist}
        os.makedirs(RAW_DIR, exist_ok=True)
        json.dump(rec, open(cache, "w"))
        return rec


def club_str(x):
    """ceapi rows may give club as string or dict with clubName."""
    if isinstance(x, dict):
        return str(x.get("clubName", ""))
    return str(x or "")


def canon_club(raw_name):
    """Canonicalize a raw row/club name -> display name (youth levels collapse onto parent)."""
    raw_name = club_str(raw_name)
    # drop trailing parenthetical year/date ranges that slipped into names (e.g. 'Chelsea FC (-2007)')
    raw_name = re.sub(r"\s*\([^()]*\d[^()]*\)\s*$", "", raw_name)
    key = unicodedata.normalize("NFKD", raw_name.lower()).encode("ascii", "ignore").decode().strip()
    key = re.sub(r"[^a-z0-9& ]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    if key in DISPLAY_ALIAS:
        return DISPLAY_ALIAS[key]
    if key in NONPL:
        return None
    # unknown club: strip youth marker for a friendlier label
    if YOUTH_MARKERS.search(key):
        return None
    return raw_name.strip()


def row_role(raw_name):
    """senior vs academy for a transfer-history row destination."""
    raw_name = club_str(raw_name)
    key = unicodedata.normalize("NFKD", raw_name.lower()).encode("ascii", "ignore").decode().strip()
    return "academy" if YOUTH_MARKERS.search(key) else "senior"


def involvement_summary(player):
    """Collapse youth box + transfer history into per-club involvements."""
    inv = {}  # club -> {role_prio, years, dates:[]}
    # youth affiliations box -> academy
    for y in player.get("youth", []):
        c = canon_club(y["club"])
        if not c:
            continue
        e = inv.setdefault(c, {"roles": set(), "years": None, "first": None, "last": None})
        e["roles"].add("academy")
        if y.get("from"):
            e["years"] = f"{y['from']}-{y['to'] or ''}"
    # transfer history rows -> destination club (academy row or senior row)
    for tr in player.get("history", []):
        to = club_str(tr.get("to"))
        c = canon_club(to)
        if not c:
            continue
        e = inv.setdefault(c, {"roles": set(), "years": None, "first": None, "last": None})
        e["roles"].add(row_role(to))
        d = tr.get("dateUnformatted") or tr.get("date")
        if isinstance(d, dict):
            d = d.get("date") or d.get("dateUnformatted")
        if isinstance(d, str) and d:
            try:
                dt = d[:10]
                if e["first"] is None or dt < e["first"]:
                    e["first"] = dt
                if e["last"] is None or dt > e["last"]:
                    e["last"] = dt
            except Exception:
                pass
    out = []
    for club, e in inv.items():
        role = "senior" if "senior" in e["roles"] else "academy"
        if e["roles"] == {"academy", "senior"}:
            role = "both"
        out.append({"club": club, "role": role, "years": e["years"],
                    "firstDate": e["first"], "lastDate": e["last"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clubs", help="comma list of club ids (default: all 20)")
    ap.add_argument("--limit", type=int, help="max players per club (smoke test)")
    ap.add_argument("--delay", type=float, default=1.1)
    ap.add_argument("--out", default=os.path.join(BASE, "data", "pl-connections.json"))
    args = ap.parse_args()

    club_ids = [int(c) for c in args.clubs.split(",")] if args.clubs else list(CLUBS)
    cw = Crawler(delay=args.delay)
    meta = {"season": f"{SEASON}/{SEASON+1}", "crawledAt": datetime.now(timezone.utc).isoformat(),
            "source": "transfermarkt.com", "clubs": []}
    players, errors = [], []

    for club_id in club_ids:
        name, slug = CLUBS[club_id]
        print(f"[club] {name} ({club_id})", flush=True)
        try:
            squad = cw.squad(club_id, slug)
        except Exception as e:
            print(f"  ! squad failed: {e}", flush=True); errors.append((club_id, "squad", str(e))); continue
        if args.limit:
            squad = squad[: args.limit]
        meta["clubs"].append({"id": club_id, "name": name, "squadSize": len(squad)})
        for p in squad:
            try:
                rec = cw.player(p["id"])
                p.update(rec)
                p["club"] = {"id": club_id, "name": name}
                p["involvements"] = involvement_summary(p)
                p["group"] = POS_GROUP.get(p.get("position", ""), "?")
                # drop bulky raw fields
                p.pop("youth", None); p.pop("history", None)
                players.append(p)
                print(f"  {p['name'][:28]:28} {p.get('position','')[:16]:16} inv={len(p['involvements'])}", flush=True)
            except Exception as e:
                print(f"  ! {p.get('name')} ({p.get('id')}) failed: {e}", flush=True)
                errors.append((club_id, p.get("id"), str(e)))
            time.sleep(args.delay)

    out = {"meta": meta, "players": players, "errors": errors}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"\nOK: {len(players)} players, {len(errors)} errors -> {args.out}")


if __name__ == "__main__":
    main()
