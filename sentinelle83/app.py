from __future__ import annotations
import argparse, hashlib, json, math, re, sqlite3, time, unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DB_PATH = ROOT / "data" / "sentinelle83.db"
LOG_PATH = ROOT / "logs" / "sentinelle83.log"

FIRE_TERMS = ["incendie","depart de feu","départ de feu","feu de foret","feu de forêt","feu de vegetation","feu de végétation","fumee","fumée","flammes","evacuation","évacuation","canadair","dash","largage","reprise de feu"]
IGNORE_TERMS = ["prevention","prévention","exercice","sensibilisation","debroussaillement","débroussaillement","emploi du feu","risque incendie","fermeture des massifs","acces aux massifs","accès aux massifs"]

@dataclass
class Item:
    source: str
    title: str
    text: str
    url: str
    published: str = ""

def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()

def log(message):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    print(line)
    ROOT.joinpath("logs").mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def init_db():
    ROOT.joinpath("data").mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, source TEXT NOT NULL)")
    con.commit()
    return con

def make_id(item):
    raw = f"{item.source}|{item.title}|{item.url}|{item.text[:600]}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()

def fetch(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/149 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r

def parse_rss(source):
    soup = BeautifulSoup(fetch(source["url"]).content, "xml")
    out = []
    for node in soup.find_all("item")[:40]:
        title = node.title.get_text(" ", strip=True) if node.title else ""
        desc = node.description.get_text(" ", strip=True) if node.description else ""
        link = node.link.get_text(strip=True) if node.link else source["url"]
        pub = node.pubDate.get_text(strip=True) if node.pubDate else ""
        out.append(Item(source["name"], title, f"{title} {desc}", link, pub))
    return out

def parse_html(source):
    soup = BeautifulSoup(fetch(source["url"]).text, "html.parser")
    for tag in soup(["script","style","noscript","svg"]):
        tag.decompose()
    out, seen_urls = [], set()
    for node in soup.select("article, .views-row, .fr-card, [role='article'], h2, h3"):
        text = node.get_text(" ", strip=True)
        if len(text) < 25:
            continue
        link_node = node.find("a", href=True)
        link = urljoin(source["url"], link_node["href"]) if link_node else source["url"]
        if link in seen_urls:
            continue
        seen_urls.add(link)
        title_node = node.find(["h1","h2","h3"])
        title = title_node.get_text(" ", strip=True) if title_node else text[:150]
        out.append(Item(source["name"], title, text[:5000], link))
    return out

def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2*r*math.asin(math.sqrt(a))

def analyze(item, config):
    text = normalize(f"{item.title} {item.text}")
    fire_hits = [x for x in FIRE_TERMS if normalize(x) in text]
    ignore_hits = [x for x in IGNORE_TERMS if normalize(x) in text]
    if not fire_hits:
        return None
    if ignore_hits and not any(x in text for x in ["depart de feu","incendie en cours","evacuation"]):
        return None
    ref = config["reference"]
    places = []
    for name, coords in config["locations"].items():
        if normalize(name) in text:
            d = haversine(ref["latitude"], ref["longitude"], coords[0], coords[1])
            places.append({"name": name, "distance_km": round(d, 1)})
    if not places:
        return None
    nearest = min(places, key=lambda x: x["distance_km"])
    if nearest["distance_km"] > float(config["alert_radius_km"]):
        return None
    return {"nearest": nearest, "keywords": fire_hits}

def send_telegram(config, message):
    token = config["telegram"].get("bot_token","").strip()
    chat_id = str(config["telegram"].get("chat_id","")).strip()
    if not token or not chat_id:
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": message, "disable_web_page_preview": False},
                      timeout=20)
    r.raise_for_status()
    return True

def build_message(item, result):
    n = result["nearest"]
    excerpt = re.sub(r"\s+", " ", item.text).strip()
    if len(excerpt) > 550:
        excerpt = excerpt[:547] + "..."
    return (f"🔥 ALERTE INCENDIE POSSIBLE\n\n📍 {n['name']}\n📏 Environ {n['distance_km']} km de Fréjus\n"
            f"📰 Source : {item.source}\n🔎 Mots détectés : {', '.join(result['keywords'][:6])}\n\n"
            f"{excerpt}\n\n{item.url}\n\nVérifie les consignes officielles. Urgence : 18 ou 112.")

def run_cycle(config, con, show_existing=False):
    first_db = con.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0
    alerts = 0
    for source in config["sources"]:
        if not source.get("enabled", True):
            continue
        try:
            items = parse_rss(source) if source.get("type") == "rss" else parse_html(source)
            log(f"{source['name']} : {len(items)} élément(s) lus")
        except Exception as exc:
            log(f"ERREUR {source['name']} : {exc}")
            continue
        for item in items:
            ident = make_id(item)
            seen = con.execute("SELECT 1 FROM seen WHERE id=?", (ident,)).fetchone() is not None
            result = analyze(item, config)
            if not seen:
                con.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?)",
                            (ident, datetime.now(timezone.utc).isoformat(), item.source))
                con.commit()
            if seen or not result or (first_db and not show_existing):
                continue
            message = build_message(item, result)
            print("\n" + "="*72 + "\n" + message + "\n" + "="*72)
            try:
                if send_telegram(config, message):
                    log("Notification Telegram envoyée")
            except Exception as exc:
                log(f"Échec Telegram : {exc}")
            alerts += 1
    return alerts

def test_alert(config):
    item = Item("TEST LOCAL","Départ de feu fictif à Fréjus","Ceci est une alerte de test. Aucun incendie réel.","https://www.var.gouv.fr/")
    result = {"nearest":{"name":"Fréjus","distance_km":0.0},"keywords":["départ de feu"]}
    message = build_message(item, result)
    print(message)
    if send_telegram(config, message):
        log("Notification Telegram de test envoyée")


def show_status(config):
    """Affiche l'état actuel de Sentinelle83."""
    print("=" * 54)
    print("🚒 SENTINELLE83")
    print()
    print("Version : 0.1.1")
    print()

    active_sources = [
        source for source in config.get("sources", [])
        if source.get("enabled", True)
    ]

    print("Sources :")
    for source in config.get("sources", []):
        state = "✅ activée" if source.get("enabled", True) else "⏸ désactivée"
        print(f"  {source['name']} : {state}")

    telegram = config.get("telegram", {})
    telegram_ready = bool(
        telegram.get("bot_token", "").strip()
        and str(telegram.get("chat_id", "")).strip()
    )

    print()
    print(f"Telegram : {'✅ configuré' if telegram_ready else '❌ non configuré'}")
    print(f"Rayon d’alerte : {config.get('alert_radius_km', '?')} km")
    print(
        f"Intervalle : "
        f"{int(config.get('interval_seconds', 300)) // 60} minute(s)"
    )
    print(f"Sources actives : {len(active_sources)}")

    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            count = con.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
            con.close()
            print(f"Éléments mémorisés : {count}")
        except sqlite3.Error:
            print("Éléments mémorisés : base illisible")
    else:
        print("Éléments mémorisés : 0")

    if LOG_PATH.exists():
        lines = LOG_PATH.read_text(
            encoding="utf-8",
            errors="ignore"
        ).splitlines()

        if lines:
            print(f"Dernière activité : {lines[-1]}")
        else:
            print("Dernière activité : aucune")
    else:
        print("Dernière activité : aucune")

    print("=" * 54)

def main():
    p = argparse.ArgumentParser(description="Sentinelle83")
    p.add_argument("--once", action="store_true")
    p.add_argument("--test-alert", action="store_true")
    p.add_argument("--show-existing", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--status", action="store_true", help="Afficher l’état du programme")
    args = p.parse_args()
    config = load_config()
    if args.status:
        show_status(config)
        return 0
    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
    if args.test_alert:
        test_alert(config)
        return 0
    con = init_db()
    if args.once:
        log(f"Contrôle terminé : {run_cycle(config, con, args.show_existing)} alerte(s)")
        return 0
    log("Sentinelle83 démarrée")
    try:
        while True:
            log(f"Cycle terminé : {run_cycle(config, con)} alerte(s)")
            time.sleep(max(60, int(config.get("interval_seconds", 300))))
    except KeyboardInterrupt:
        log("Arrêt demandé")
        return 0
