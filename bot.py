"""Alerte SMS quand un rendez-vous de conciliateur de justice se libère (Paris, RDV DAJ).

Le site (Lutece) écrit les créneaux directement dans le HTML :
    window.lutece_appointment_solrsearchapp_points = [ ... ];
Liste vide + message "Aucun rendez-vous..." = rien de dispo.
"""
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

URL = ("https://rdvdaj.apps.paris.fr/rdvdaj/jsp/site/Portal.jsp"
       "?page=appointmentsearch&view=search&category=C_Conciliateur")
NO_SLOT_MARKER = "Aucun rendez-vous n'est actuellement disponible"
STATE_FILE = pathlib.Path(os.environ.get("STATE_FILE", "state.json"))
SNAPSHOT_DIR = pathlib.Path(os.environ.get("SNAPSHOT_DIR", "snapshots"))

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})\b")
TIME_RE = re.compile(r"\b(\d{1,2})\s*[h:]\s*(\d{2})\b")


# ---------- Récupération et lecture de la page ----------

def fetch(url=URL):
    r = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (alerte personnelle conciliateur, 1 requete / 10 min)"})
    r.raise_for_status()
    return r.text


def extract_js_array(html, var_name):
    """Récupère le tableau JS window.<var_name> = [...] en équilibrant les crochets."""
    m = re.search(re.escape(var_name) + r"\s*=\s*\[", html)
    if not m:
        return None
    start = m.end() - 1
    depth, in_str, esc, quote = 0, False, False, ""
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        elif c in "\"'":
            in_str, quote = True, c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    return None


def parse_js_literal(raw):
    """JSON strict d'abord, puis tolérance (clés sans guillemets, quotes simples, virgule finale)."""
    try:
        return json.loads(raw)
    except Exception:
        pass
    fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', raw)
    fixed = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", lambda m: json.dumps(m.group(1)), fixed)
    fixed = re.sub(r",\s*([\]}])", r"\1", fixed)
    try:
        return json.loads(fixed)
    except Exception:
        return None


def flatten(obj, prefix=""):
    """Aplatis un objet imbriqué en {chemin.clé: valeur}."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def pick(flat, keywords):
    for key, val in flat.items():
        k = key.lower()
        if any(w in k for w in keywords) and val not in (None, ""):
            return str(val)
    return None


def describe_point(point):
    """Transforme un point de la carte en (jour, heure, lieu), au mieux."""
    flat = flatten(point) if isinstance(point, (dict, list)) else {"value": point}
    text_blob = " ".join(str(v) for v in flat.values())

    lieu = pick(flat, ["name", "nom", "title", "titre", "label", "place", "lieu"])
    adresse = pick(flat, ["address", "adresse"])
    if adresse and adresse != lieu:
        lieu = f"{lieu}, {adresse}" if lieu else adresse

    jour = pick(flat, ["date", "day", "jour", "first", "slot", "creneau"])
    heure = pick(flat, ["hour", "heure", "time", "starting"])
    if jour:
        dm = DATE_RE.search(jour)
        tm = TIME_RE.search(jour)
        if not heure and tm:
            heure = f"{int(tm.group(1)):02d}h{tm.group(2)}"
        if dm:
            jour = dm.group(1)
    if not jour:
        dm = DATE_RE.search(text_blob)
        jour = dm.group(1) if dm else None
    if not heure:
        tm = TIME_RE.search(text_blob)
        heure = f"{int(tm.group(1)):02d}h{tm.group(2)}" if tm else None

    # Lien de réservation éventuel (souvent un champ url / link avec id_form)
    lien = pick(flat, ["url", "link", "lien", "href"])
    if lien and lien.startswith("jsp/"):
        lien = "https://rdvdaj.apps.paris.fr/rdvdaj/" + lien
    return {"jour": jour, "heure": heure, "lieu": BeautifulSoup(lieu or "", "html.parser").get_text(" ", strip=True) or None,
            "lien": lien, "paris": dans_paris(text_blob)}


# ---------- Filtre Paris intra muros (75001 à 75020, + 75116) ----------

CP_RE = re.compile(r"\b(\d{5})\b")
CP_PARIS = {f"750{n:02d}" for n in range(1, 21)} | {"75116"}
ARR_RE = re.compile(
    r"(mairie\s+(du|de\s+la)?\s*\d{1,2}\s*(er|e|è|ème|eme)\b"
    r"|paris\s*\d{1,2}\s*(er|e|è|ème|eme)?\b"
    r"|\d{1,2}\s*(er|e|ème|eme)\s+arrondissement"
    r"|paris\s+centre)", re.I)


def dans_paris(texte):
    """True = Paris intra muros, False = ailleurs, None = impossible à dire."""
    cps = set(CP_RE.findall(texte or ""))
    if cps:
        return bool(cps & CP_PARIS)
    if ARR_RE.search(texte or ""):
        return True
    return None


def analyse(html):
    raw_points = extract_js_array(html, "lutece_appointment_solrsearchapp_points")
    points = parse_js_literal(raw_points) if raw_points else None
    marker_present = NO_SLOT_MARKER in html

    slots = []
    if isinstance(points, list):
        slots = [describe_point(p) for p in points]
        # On écarte ce qui est clairement hors Paris ; on garde le doute (lieu illisible)
        slots = [s for s in slots if s["paris"] is not False]
        if not slots:
            return False, [], raw_points
    elif raw_points and raw_points.strip() not in ("[]", "[\n]") and re.sub(r"\s", "", raw_points) != "[]":
        # Tableau présent mais illisible : on signale quand même
        slots = [{"jour": None, "heure": None, "lieu": None, "lien": None}]

    available = bool(slots) or not marker_present
    return available, slots, raw_points


# ---------- Mémoire (pour ne pas renvoyer 50 fois le même SMS) ----------

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"notified": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def slot_id(s):
    return hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()[:12]


# ---------- SMS ----------

def build_message(slots):
    lines = ["Conciliateur : créneau dispo !"]
    for s in slots[:5]:
        lieu = s.get("lieu") or "lieu ?"
        if s.get("paris") is None and s.get("lieu"):
            lieu += " (à vérifier : Paris ?)"
        parts = [s.get("jour") or "jour ?", s.get("heure") or "heure ?", lieu]
        lines.append(" · ".join(parts))
    if len(slots) > 5:
        lines.append(f"+ {len(slots) - 5} autre(s)")
    lien = next((s["lien"] for s in slots if s.get("lien")), None)
    lines.append(lien or URL)
    return "\n".join(lines)


def send_sms(text):
    if os.environ.get("FREE_USER") and os.environ.get("FREE_PASS"):
        r = requests.get("https://smsapi.free-mobile.fr/sendmsg", timeout=30, params={
            "user": os.environ["FREE_USER"], "pass": os.environ["FREE_PASS"], "msg": text})
        r.raise_for_status()
        return "free"
    if os.environ.get("TWILIO_SID"):
        sid = os.environ["TWILIO_SID"]
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", timeout=30,
                          auth=(sid, os.environ["TWILIO_TOKEN"]),
                          data={"From": os.environ["TWILIO_FROM"], "To": os.environ["SMS_TO"], "Body": text})
        r.raise_for_status()
        return "twilio"
    print("[aucun service SMS configuré] message :\n" + text)
    return None


# ---------- Historique : à quelle heure la Ville publie-t-elle les créneaux ? ----------

def log_history(slots):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    path = pathlib.Path("historique.csv")
    now = datetime.now(ZoneInfo("Europe/Paris"))
    new_file = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if new_file:
            f.write("detecte_le;jour_semaine;jour_rdv;heure_rdv;lieu\n")
        for s in slots:
            f.write(f"{now:%Y-%m-%d %H:%M};{now:%A};{s.get('jour') or ''};{s.get('heure') or ''};"
                    f"{(s.get('lieu') or '').replace(';', ',')}\n")


# ---------- Programme principal ----------

def main():
    if os.environ.get("TEST_SMS") == "true":
        print("Service utilisé :", send_sms("Test bot conciliateur : les SMS fonctionnent.\n" + URL))
    html =pathlib.Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else fetch()
    available, slots, raw = analyse(html)
    state = load_state()

    if not available:
        print("Aucun créneau.")
        if state.get("notified"):
            state["notified"] = []   # on réarme : le prochain créneau sera notifié
            save_state(state)
        return

    # Garde une copie de la page pour affiner le parseur si besoin
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    (SNAPSHOT_DIR / "derniere_page_avec_creneaux.html").write_text(html)

    if not slots:
        slots = [{"jour": None, "heure": None, "lieu": None, "lien": None}]
    new = [s for s in slots if slot_id(s) not in state["notified"]]
    print(f"{len(slots)} créneau(x) trouvé(s), {len(new)} nouveau(x).")
    for s in slots:
        print("  ", s)
    if new:
        log_history(new)
        send_sms(build_message(new))
        state["notified"] = sorted(set(state["notified"]) | {slot_id(s) for s in new})
        save_state(state)


if __name__ == "__main__":
    main()
