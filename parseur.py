#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parseur.py
----------
Coeur d'analyse des fichiers .log : parsing robuste ligne a ligne + fonctions
d'analyse (statistiques, regroupement d'erreurs, timeline, temps de reponse).

Aucune dependance externe : bibliotheque standard uniquement.
Module testable independamment de l'interface (voir test_parseur.py).
"""

import json
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

try:
    import pty
    import signal
    _PTY_OK = hasattr(os, "fork")
except ImportError:  # Windows : pas de pty
    pty = None
    signal = None
    _PTY_OK = False


def _dossier_vendor():
    """Dossier des binaires embarques (plink/pscp), compatible PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "vendor", "windows")


def _localiser_outil(noms):
    """Cherche un outil d'abord parmi les binaires embarques, puis dans le PATH."""
    dossier = _dossier_vendor()
    for nom in noms:
        chemin = os.path.join(dossier, nom)
        if os.path.exists(chemin):
            return chemin
    for nom in noms:
        chemin = shutil.which(nom)
        if chemin:
            return chemin
    return None


def _plink():
    return _localiser_outil(["plink.exe", "plink"])


def _pscp():
    return _localiser_outil(["pscp.exe", "pscp"])


# Choix du backend SSH selon la plateforme :
#   - "pty"   : Unix/macOS, mot de passe pilote via pseudo-terminal (natif).
#   - "plink" : Windows, via plink.exe/pscp.exe (PuTTY) embarques ou dans le PATH.
if _PTY_OK:
    SSH_BACKEND = "pty"
elif os.name == "nt":
    plink_path = _plink()
    pscp_path = _pscp()
    if plink_path and pscp_path:
        SSH_BACKEND = "plink"
    else:
        SSH_BACKEND = None
        # Debug pour Windows
        if os.name == "nt":
            import sys
            print(f"[PARSEUR DEBUG] Windows détecté mais plink/pscp manquants", file=sys.stderr)
            print(f"  plink: {plink_path}", file=sys.stderr)
            print(f"  pscp: {pscp_path}", file=sys.stderr)
else:
    SSH_BACKEND = None

SSH_DISPONIBLE = SSH_BACKEND is not None


# ===========================================================================
#  CONSTANTES / EXPRESSIONS REGULIERES
# ===========================================================================
NIVEAUX = ["FATAL", "CRITICAL", "CRIT", "ERROR", "ERR", "SEVERE",
           "WARNING", "WARN", "NOTICE", "INFO", "DEBUG", "TRACE", "VERBOSE"]

NORM_NIVEAU = {
    "FATAL": "FATAL", "CRITICAL": "FATAL", "CRIT": "FATAL", "SEVERE": "FATAL",
    "ERROR": "ERROR", "ERR": "ERROR",
    "WARNING": "WARN", "WARN": "WARN", "NOTICE": "WARN",
    "INFO": "INFO", "DEBUG": "DEBUG", "TRACE": "TRACE", "VERBOSE": "TRACE",
}

RE_TIMESTAMP = re.compile(
    r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
    r"|(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2}\s*[+-]\d{4})"
    r"|(\d{2}/\d{2}/\d{4}[ :]\d{2}:\d{2}:\d{2})"
    r"|([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"
    r"|(\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b)"
)

RE_NIVEAU = re.compile(r"\b(" + "|".join(NIVEAUX) + r")\b", re.IGNORECASE)
RE_METHODE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b")
RE_URL = re.compile(r"https?://[^\s\"'<>\\)]+")
RE_CHEMIN = re.compile(r'"(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+([^\s"]+)\s+HTTP'
                       r'|(?<!\S)(/[A-Za-z0-9_\-./]+(?:\?[^\s"]*)?)')
RE_STATUT_KV = re.compile(r"(?:status(?:_?code)?|httpStatus|responseStatus|code)"
                          r"\D{0,3}([1-5]\d{2})", re.IGNORECASE)
RE_STATUT_ACCES = re.compile(r'"\s+([1-5]\d{2})\s')
RE_STATUT_FLECHE = re.compile(r"(?:->|=>|\u2192)\s*([1-5]\d{2})\b")
RE_MOTS_ERREUR = re.compile(
    r"\b(error|errors|exception|fail|failed|failure|fatal|panic|traceback|"
    r"timeout|refused|denied|unhandled|crash|oom)\b", re.IGNORECASE)

# Pour normaliser un message d'erreur (regroupement) : on remplace les parties
# variables (nombres, uuid, hexa, dates) par des jetons.
RE_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                     re.IGNORECASE)
RE_HEXA = re.compile(r"\b0x[0-9a-f]+\b", re.IGNORECASE)
RE_NOMBRE = re.compile(r"\b\d[\d.,:]*\b")
RE_TEMPS_MS = re.compile(r"([\d.]+)\s*(ms|millis|s|sec|secondes?|m|min)?", re.IGNORECASE)

CLES_NIVEAU = ("level", "lvl", "severity", "levelname", "loglevel")
CLES_MESSAGE = ("message", "msg", "text", "error", "description", "event")
CLES_URL = ("url", "uri", "path", "request", "requesturl", "endpoint",
            "target", "route")
CLES_METHODE = ("method", "httpmethod", "http_method", "verb",
                "requestmethod", "reqmethod")
CLES_STATUT = ("status", "statuscode", "status_code", "responsestatus",
               "response_status", "httpstatus", "http_code", "httpcode",
               "code", "resp_status")
CLES_TEMPS = ("time", "timestamp", "@timestamp", "ts", "datetime", "date",
              "eventtime", "asctime", "log_timestamp")
CLES_APP = ("appname", "app", "application", "applicationname", "app_name",
            "appid", "service", "servicename", "service_name", "component",
            "module", "logger", "source")
RE_APP = re.compile(
    r"""['"]?app[_ ]?name['"]?\s*[:=]\s*['"]?([A-Za-z0-9_.\-]+)"""
    r"""|['"]?application(?:[_ ]?name)?['"]?\s*[:=]\s*['"]?([A-Za-z0-9_.\-]+)"""
    r"""|['"]?service(?:[_ ]?name)?['"]?\s*[:=]\s*['"]?([A-Za-z0-9_.\-]+)""",
    re.IGNORECASE)


# ===========================================================================
#  LISTE D'EXCLUSION (ignore.txt)
# ===========================================================================
MOTIFS_IGNORES = []


def _chemin_ignore():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ignore.txt")


def charger_ignores():
    """(Re)charge la liste d'exclusion depuis ignore.txt (si present)."""
    global MOTIFS_IGNORES
    motifs = []
    chemin = _chemin_ignore()
    if os.path.exists(chemin):
        try:
            with open(chemin, "r", encoding="utf-8", errors="replace") as f:
                for ligne in f:
                    ligne = ligne.strip()
                    if ligne and not ligne.startswith("#"):
                        motifs.append(ligne.lower())
        except OSError:
            pass
    MOTIFS_IGNORES = motifs
    return motifs


def lire_ignore_brut():
    """Retourne le contenu texte complet d'ignore.txt (pour edition UI)."""
    chemin = _chemin_ignore()
    if os.path.exists(chemin):
        try:
            with open(chemin, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""
    return ("# Un motif par ligne. Les lignes contenant un de ces motifs ne\n"
            "# seront pas considerees comme erreurs/avertissements.\n"
            "# Les lignes commencant par # sont des commentaires.\n")


def ecrire_ignore_brut(contenu):
    """Ecrit le contenu d'ignore.txt puis recharge la liste."""
    with open(_chemin_ignore(), "w", encoding="utf-8") as f:
        f.write(contenu)
    return charger_ignores()


def est_ignoree(brut_bas):
    """Vrai si la ligne (deja en minuscules) contient un motif a exclure."""
    return any(motif in brut_bas for motif in MOTIFS_IGNORES)


# ===========================================================================
#  OUTILS JSON / TEMPS
# ===========================================================================
def extraire_json(texte):
    """Retourne le premier objet JSON valide trouve dans la ligne, ou None."""
    decodeur = json.JSONDecoder()
    i = texte.find("{")
    while i != -1:
        try:
            obj, _ = decodeur.raw_decode(texte[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        i = texte.find("{", i + 1)
    return None


def _jget(bas, cles):
    for c in cles:
        if c in bas and bas[c] not in (None, ""):
            return bas[c]
    return None


def _coerce_json(valeur):
    """Si la valeur est une chaine contenant du JSON, la decode ; sinon None."""
    if isinstance(valeur, (dict, list)):
        return valeur
    if isinstance(valeur, str):
        s = valeur.strip()
        if s and s[0] in "{[":
            try:
                return json.loads(s)
            except (json.JSONDecodeError, ValueError):
                return None
    return None


_FORMATS_TEMPS = (
    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y:%H:%M:%S",
)


def parse_temps(texte):
    """Convertit une chaine horodatage en datetime, ou None si impossible."""
    if not texte:
        return None
    s = str(texte).strip()
    # Retire un eventuel suffixe de fuseau pour les formats simples.
    s2 = s.replace("Z", "").strip()
    s2 = re.sub(r"([+-]\d{2}:?\d{2})$", "", s2).strip()
    s2 = s2.replace(",", ".")
    for fmt in _FORMATS_TEMPS:
        try:
            return datetime.strptime(s2, fmt)
        except ValueError:
            continue
    # ISO 8601 generique
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_duree_ms(valeur):
    """Convertit un temps d'execution ('123ms', '1.2s', 1500) en millisecondes."""
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    m = RE_TEMPS_MS.search(str(valeur))
    if not m:
        return None
    try:
        nombre = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    unite = (m.group(2) or "ms").lower()
    if unite in ("s", "sec", "seconde", "secondes"):
        return nombre * 1000.0
    if unite in ("m", "min"):
        return nombre * 60000.0
    return nombre  # ms / millis par defaut


# ===========================================================================
#  PARSING D'UNE LIGNE
# ===========================================================================
def parser_ligne(no, ligne):
    """Analyse une ligne brute et retourne un enregistrement structure (dict)."""
    brut = ligne.rstrip("\n")
    obj = extraire_json(brut)
    bas = {str(k).lower(): v for k, v in obj.items()} if obj else {}

    msg_obj = _coerce_json(obj.get("message")) if obj else None
    bas_msg = ({str(k).lower(): v for k, v in msg_obj.items()}
               if isinstance(msg_obj, dict) else {})

    def champ(cles):
        v = _jget(bas_msg, cles)
        if v in (None, ""):
            v = _jget(bas, cles)
        return v

    # niveau
    niveau = champ(CLES_NIVEAU)
    if not niveau:
        m = RE_NIVEAU.search(brut)
        niveau = m.group(1) if m else None
    niveau = NORM_NIVEAU.get(str(niveau).upper(), str(niveau).upper()) if niveau else ""

    # horodatage
    temps = champ(CLES_TEMPS)
    if not temps:
        m = RE_TIMESTAMP.search(brut)
        temps = next((g for g in m.groups() if g), "") if m else ""
    temps = str(temps)

    # methode HTTP
    methode = champ(CLES_METHODE)
    if methode:
        methode = str(methode).upper()
    else:
        m = RE_METHODE.search(brut)
        methode = m.group(1) if m else ""

    # url / chemin
    url = champ(CLES_URL)
    if not url:
        m = RE_URL.search(brut)
        if m:
            url = m.group(0)
        else:
            m = RE_CHEMIN.search(brut)
            if m:
                url = m.group(1) or m.group(2)
    url = str(url) if url else ""

    # statut HTTP
    statut = champ(CLES_STATUT)
    if statut is None:
        m = (RE_STATUT_KV.search(brut) or RE_STATUT_FLECHE.search(brut)
             or RE_STATUT_ACCES.search(brut))
        statut = m.group(1) if m else None
    try:
        statut = int(statut) if statut is not None and str(statut).strip() != "" else None
    except (ValueError, TypeError):
        statut = None

    # app name (priorite au message.app_name)
    app = _jget(bas_msg, CLES_APP)
    if not app:
        app = _jget(bas, CLES_APP)
    if not app:
        m = RE_APP.search(brut)
        if m:
            app = next((g for g in m.groups() if g), None)
    app = str(app) if app else ""

    # request / response / execution_time
    request = _coerce_json(bas_msg.get("request")) if bas_msg else None
    if request is None and bas_msg.get("request") not in (None, ""):
        request = bas_msg.get("request")
    response = _coerce_json(bas_msg.get("response")) if bas_msg else None
    if response is None and bas_msg.get("response") not in (None, ""):
        response = bas_msg.get("response")
    execution_time = (bas_msg.get("execution_time")
                      or bas_msg.get("executiontime")) if bas_msg else None
    duree_ms = parse_duree_ms(execution_time)

    # message lisible
    message = _jget(bas_msg, ("msg", "text", "description", "event"))
    if not message and bas_msg:
        if request is not None:
            message = (request if isinstance(request, str)
                       else json.dumps(request, ensure_ascii=False))
        elif url:
            message = f"{methode} {url}".strip()
    if not message:
        message = _jget(bas, CLES_MESSAGE)
        if isinstance(message, (dict, list)) or (
                isinstance(message, str) and message.strip()[:1] in "{["):
            message = None
    if not message:
        sans_json = brut
        if obj:
            deb = brut.find("{")
            if deb != -1:
                sans_json = brut[:deb].strip()
        message = sans_json.strip() or brut.strip()
    message = str(message)

    # categorisation
    ignore = est_ignoree(brut.lower())
    est_api = bool(methode or url or statut is not None)
    est_erreur = (not ignore) and (
        niveau in ("ERROR", "FATAL")
        or (statut is not None and statut >= 400)
        or (not niveau and bool(RE_MOTS_ERREUR.search(brut)))
    )
    est_avert = (not ignore) and (niveau == "WARN")

    return {
        "no": no,
        "brut": brut,
        "temps": temps,
        "dt": parse_temps(temps),
        "niveau": niveau,
        "methode": methode,
        "statut": statut,
        "url": url,
        "message": message,
        "app": app,
        "json": obj,
        "request": request,
        "response": response,
        "execution_time": execution_time,
        "duree_ms": duree_ms,
        "api": est_api,
        "erreur": est_erreur,
        "avert": est_avert,
        "ignore": ignore,
    }


def analyser_fichier(chemin, progression=None, doit_continuer=None):
    """Lit et parse un fichier ligne par ligne (streaming).

    progression(lignes_traitees, octets_lus, octets_total) : callback optionnel.
    doit_continuer() -> bool : si fournie et renvoie False, l'analyse s'arrete.
    Retourne la liste des enregistrements.
    """
    charger_ignores()
    taille = 0
    try:
        taille = os.path.getsize(chemin)
    except OSError:
        taille = 0
    enregs = []
    octets = 0
    with open(chemin, "r", encoding="utf-8", errors="replace") as f:
        for no, ligne in enumerate(f, 1):
            octets += len(ligne.encode("utf-8", "ignore"))
            if ligne.strip():
                enregs.append(parser_ligne(no, ligne))
            if progression and (no % 2000 == 0):
                progression(no, octets, taille)
                if doit_continuer and not doit_continuer():
                    break
    if progression:
        progression(len(enregs), taille, taille)
    return enregs


# ===========================================================================
#  ANALYSE / STATISTIQUES
# ===========================================================================
def _percentile(valeurs, p):
    """Percentile (0-100) d'une liste de nombres deja non vide."""
    if not valeurs:
        return None
    s = sorted(valeurs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    bas = int(k)
    haut = min(bas + 1, len(s) - 1)
    frac = k - bas
    return s[bas] + (s[haut] - s[bas]) * frac


def calculer_stats(enregs):
    """Retourne un dictionnaire de statistiques globales et par application."""
    total = len(enregs)
    n_err = sum(1 for r in enregs if r["erreur"])
    n_avert = sum(1 for r in enregs if r["avert"])
    n_api = sum(1 for r in enregs if r["api"])

    # repartition des statuts par classe (2xx..5xx)
    classes = Counter()
    for r in enregs:
        s = r["statut"]
        if s is not None:
            classes[f"{s // 100}xx"] += 1

    # repartition par niveau
    niveaux = Counter(r["niveau"] for r in enregs if r["niveau"])

    # par application : volume + temps de reponse
    durees_app = defaultdict(list)
    volume_app = Counter()
    err_app = Counter()
    for r in enregs:
        a = r["app"] or "(inconnue)"
        volume_app[a] += 1
        if r["erreur"]:
            err_app[a] += 1
        if r["duree_ms"] is not None:
            durees_app[a].append(r["duree_ms"])

    apps = []
    for a, n in volume_app.most_common():
        d = durees_app.get(a, [])
        apps.append({
            "app": a,
            "total": n,
            "erreurs": err_app.get(a, 0),
            "moy_ms": (sum(d) / len(d)) if d else None,
            "p95_ms": _percentile(d, 95) if d else None,
            "max_ms": max(d) if d else None,
        })

    toutes_durees = [r["duree_ms"] for r in enregs if r["duree_ms"] is not None]
    return {
        "total": total,
        "erreurs": n_err,
        "avert": n_avert,
        "api": n_api,
        "classes_statut": dict(classes),
        "niveaux": dict(niveaux),
        "apps": apps,
        "duree_globale": {
            "n": len(toutes_durees),
            "moy_ms": (sum(toutes_durees) / len(toutes_durees)) if toutes_durees else None,
            "p95_ms": _percentile(toutes_durees, 95) if toutes_durees else None,
            "max_ms": max(toutes_durees) if toutes_durees else None,
        },
    }


def signature_erreur(message):
    """Normalise un message pour regrouper les erreurs similaires."""
    s = message or ""
    s = RE_UUID.sub("<id>", s)
    s = RE_HEXA.sub("<hex>", s)
    s = RE_NOMBRE.sub("<n>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200]


def grouper_erreurs(enregs, limite=50):
    """Regroupe les erreurs par signature. Retourne une liste triee par compte."""
    groupes = defaultdict(lambda: {"compte": 0, "exemple": None, "nos": []})
    for r in enregs:
        if not r["erreur"]:
            continue
        sig = signature_erreur(r["message"])
        g = groupes[sig]
        g["compte"] += 1
        if g["exemple"] is None:
            g["exemple"] = r["message"]
        if len(g["nos"]) < 50:
            g["nos"].append(r["no"])
    items = [{"signature": k, **v} for k, v in groupes.items()]
    items.sort(key=lambda x: x["compte"], reverse=True)
    return items[:limite]


def timeline(enregs, buckets=60):
    """Decoupe la periode couverte en tranches et compte total/erreurs.

    Retourne (liste de tranches, debut, fin). Chaque tranche :
    {label, debut, total, erreurs}. Si aucun horodatage exploitable -> ([], None, None).
    """
    dates = [r["dt"] for r in enregs if r["dt"] is not None]
    if not dates:
        return [], None, None
    debut, fin = min(dates), max(dates)
    span = (fin - debut).total_seconds()
    if span <= 0:
        return ([{"label": debut.strftime("%Y-%m-%d %H:%M:%S"), "debut": debut,
                  "total": len(enregs),
                  "erreurs": sum(1 for r in enregs if r["erreur"])}], debut, fin)
    pas = span / buckets
    tranches = [{"debut": None, "total": 0, "erreurs": 0} for _ in range(buckets)]
    for r in enregs:
        if r["dt"] is None:
            continue
        idx = int((r["dt"] - debut).total_seconds() / pas)
        idx = min(idx, buckets - 1)
        t = tranches[idx]
        t["total"] += 1
        if r["erreur"]:
            t["erreurs"] += 1
    from datetime import timedelta
    for i, t in enumerate(tranches):
        t["debut"] = debut + timedelta(seconds=pas * i)
        t["label"] = t["debut"].strftime("%H:%M:%S")
    return tranches, debut, fin


# ===========================================================================
#  TELECHARGEMENT SSH / SCP  (stdlib only, via pseudo-terminal)
# ===========================================================================
class ErreurSSH(Exception):
    """Echec d'une operation SSH/SCP (message lisible pour l'utilisateur)."""


def _interpreter_erreur_ssh(sortie, code):
    """Traduit la sortie brute de scp en message clair."""
    s = (sortie or "").lower()
    if "permission denied" in s or "authentication failed" in s:
        return "Authentification refusée : utilisateur (LDAP) ou mot de passe incorrect."
    if "could not resolve hostname" in s or "name or service not known" in s \
            or "nodename nor servname" in s:
        return "Hôte introuvable (nom ou DNS invalide)."
    if "connection refused" in s:
        return "Connexion refusée (port fermé ou service SSH arrêté)."
    if "connection timed out" in s or "operation timed out" in s:
        return "Délai de connexion dépassé (hôte injoignable)."
    if "no such file" in s or "not a regular file" in s:
        return "Fichier distant introuvable (vérifiez le chemin)."
    if "host key verification failed" in s:
        return "Vérification de la clé d'hôte échouée."
    derniere = ""
    for ligne in (sortie or "").strip().splitlines():
        ligne = ligne.strip()
        if ligne and "password" not in ligne.lower():
            derniere = ligne
    return f"Échec du transfert (code {code}). {derniere}".strip()


def _executer_pty(cmd, motdepasse, timeout, on_log=None, doit_continuer=None,
                  max_mdp=1):
    """Lance `cmd` sur un pseudo-terminal et repond au(x) prompt(s) de mot de passe.

    Retourne (code_retour, sortie_complete). Unix/macOS uniquement.
    - max_mdp : nombre de fois ou l'on accepte de renvoyer le mot de passe
      (utile pour un rebond bastion -> hote interne qui le redemande).
    - doit_continuer : callable -> False pour interrompre la session.
    """
    pid, fd = pty.fork()
    if pid == 0:  # processus enfant
        try:
            os.execvp(cmd[0], cmd)
        except Exception:
            os._exit(127)
    # processus parent : on pilote le pty
    sortie = []
    buf = ""
    mdp_envoyes = 0
    debut = time.time()
    try:
        while True:
            if doit_continuer is not None and not doit_continuer():
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                os.waitpid(pid, 0)
                return 130, "".join(sortie) + "\n[interrompu]"
            if time.time() - debut > timeout:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                os.waitpid(pid, 0)
                return 124, "".join(sortie) + "\nconnection timed out"
            try:
                pret, _, _ = select.select([fd], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not pret:
                continue
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            texte = data.decode("utf-8", "replace")
            sortie.append(texte)
            if on_log:
                on_log(texte)
            buf += texte
            bas = buf.lower()
            if mdp_envoyes < max_mdp and "password" in bas and bas.rstrip().endswith(":"):
                os.write(fd, (motdepasse + "\n").encode())
                mdp_envoyes += 1
                buf = ""
            elif "(yes/no" in bas or "yes/no/[fingerprint]" in bas:
                os.write(fd, b"yes\n")
                buf = ""
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    return code, "".join(sortie)


def _executer_subprocess(cmd, motdepasse, timeout, on_log=None,
                         doit_continuer=None, max_mdp=3):
    """Backend Windows : pilote plink/pscp via des tubes (pas de pty).

    plink/pscp realisent leur propre authentification avec l'option -pw ; ce
    driver repond en plus au prompt de mot de passe du rebond interne (sshclient
    lance a travers le pty distant) et accepte les cles d'hote inconnues ('y').
    Lecture octet par octet pour detecter les prompts sans retour a la ligne.
    """
    import threading
    import queue as _queue
    
    # Debug: log la commande
    cmd_str = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
    if on_log:
        on_log(f"[DEBUG] Lancement: {cmd_str}\n")
    
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as e:
        msg = f"command not found: {cmd[0]}"
        if on_log:
            on_log(f"[ERROR] {msg}\n")
        return 127, msg
    except Exception as e:
        msg = f"Erreur Popen: {e}"
        if on_log:
            on_log(f"[ERROR] {msg}\n")
        return 127, msg

    file_attente = _queue.Queue()
    lecteur_actif = [True]  # Flag pour arrêter le lecteur

    def _lecteur():
        try:
            while lecteur_actif[0]:
                try:
                    octet = proc.stdout.read(1)
                except Exception:
                    break
                if not octet:
                    break
                file_attente.put(octet)
        finally:
            file_attente.put(None)

    thread_lecteur = threading.Thread(target=_lecteur, daemon=True)
    thread_lecteur.start()

    sortie = []
    buf = ""
    mdp_envoyes = 0
    cle_acceptee = False
    debut = time.time()
    fini = False

    def _ecrire(donnees):
        try:
            proc.stdin.write(donnees)
            proc.stdin.flush()
        except (OSError, ValueError) as e:
            if on_log:
                on_log(f"[DEBUG] Erreur ecriture stdin: {e}\n")

    while not fini:
        if doit_continuer is not None and not doit_continuer():
            proc.kill()
            return 130, "".join(sortie) + "\n[interrompu]"
        
        elapsed = time.time() - debut
        if elapsed > timeout:
            proc.kill()
            return 124, "".join(sortie) + f"\n[timeout après {elapsed:.1f}s]"
        
        try:
            octet = file_attente.get(timeout=0.5)
        except _queue.Empty:
            # Vérifier si le processus est terminé
            if proc.poll() is not None:
                fini = True
            continue
        
        if octet is None:
            fini = True
            continue
        
        texte = octet.decode("utf-8", "replace")
        sortie.append(texte)
        if on_log:
            on_log(texte)
        
        buf += texte
        bas = buf.lower()
        
        # Détecter prompts et répondre
        if mdp_envoyes < max_mdp and "password" in bas and bas.rstrip().endswith(":"):
            if on_log:
                on_log(f"[DEBUG] Prompt password détecté (#{mdp_envoyes+1}), envoi mot de passe\n")
            _ecrire((motdepasse + "\n").encode())
            mdp_envoyes += 1
            buf = ""
        elif not cle_acceptee and ("(y/n" in bas or "store key in cache" in bas):
            if on_log:
                on_log(f"[DEBUG] Prompt clé d'hôte détecté, envoi 'y'\n")
            _ecrire(b"y\n")
            cle_acceptee = True
            buf = ""
        elif len(buf) > 8192:
            buf = buf[-2048:]
    
    lecteur_actif[0] = False
    proc.wait()
    return proc.returncode or 0, "".join(sortie)


def _executer(cmd, motdepasse, timeout, on_log=None, doit_continuer=None,
              max_mdp=1):
    """Lance la commande SSH/SCP avec le backend adapte a la plateforme."""
    if SSH_BACKEND == "plink":
        return _executer_subprocess(cmd, motdepasse, timeout, on_log=on_log,
                                    doit_continuer=doit_continuer, max_mdp=max_mdp)
    return _executer_pty(cmd, motdepasse, timeout, on_log=on_log,
                         doit_continuer=doit_continuer, max_mdp=max_mdp)


def telecharger_scp(hote, utilisateur, chemin_distant, destination, motdepasse,
                    port=22, timeout=120, on_log=None):
    """Telecharge un fichier distant via scp en authentification par mot de passe.

    Le mot de passe est fourni sur un pseudo-terminal (pas de sshpass requis).
    Force l'authentification par mot de passe (LDAP) et accepte automatiquement
    les nouvelles cles d'hote. Leve ErreurSSH en cas d'echec.
    """
    if not SSH_DISPONIBLE:
        raise ErreurSSH("Le téléchargement SSH par mot de passe n'est pas "
                        "disponible : installez PuTTY (plink/pscp) sur Windows.")
    if not (hote and utilisateur and chemin_distant and motdepasse):
        raise ErreurSSH("Hôte, utilisateur, chemin distant et mot de passe "
                        "sont obligatoires.")
    if SSH_BACKEND == "plink":
        cmd = [
            _pscp(), "-pw", motdepasse, "-P", str(port),
            f"{utilisateur}@{hote}:{chemin_distant}",
            destination,
        ]
    else:
        cmd = [
            "scp",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "PubkeyAuthentication=no",
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "NumberOfPasswordPrompts=1",
            "-o", f"ConnectTimeout={int(min(timeout, 30))}",
            "-P", str(port),
            f"{utilisateur}@{hote}:{chemin_distant}",
            destination,
        ]
    code, sortie = _executer(cmd, motdepasse, timeout, on_log)
    if code != 0:
        if os.path.exists(destination) and os.path.getsize(destination) == 0:
            try:
                os.remove(destination)
            except OSError:
                pass
        raise ErreurSSH(_interpreter_erreur_ssh(sortie, code))
    if not os.path.exists(destination) or os.path.getsize(destination) == 0:
        raise ErreurSSH("Le fichier téléchargé est vide ou absent.")
    return destination


# ---------------------------------------------------------------------------
#  Acces via bastion ADEO (rebond) : connexion au bastion puis lancement du
#  script de collecte des logs. Sortie streamee en direct pour observation.
# ---------------------------------------------------------------------------
BASTION_HOTE = "ubastion.adeo.com"
BASTION_INTERNE = "bastion@pfrlmisrefb02.int.adeo.com"
BASTION_SCRIPT = "/home/bastion/bin/scp_all_log.sh"
BASTION_APP_LOG = "/home1/{base}/APP_LOG"


def _double_quote(valeur):
    """Quote une valeur pour survivre a DEUX shells (bastion puis hote interne)."""
    return shlex.quote(shlex.quote(valeur if valeur is not None else ""))


def commande_bastion(ldap, motdepasse, caisse=None, magasin=None, date=None):
    """Construit la commande ssh vers le bastion qui lance le script de collecte.

    Le dossier APP_LOG est vide avant chaque collecte pour ne recuperer que les
    fichiers du run courant. Le script scp_all_log.sh est appele avec :
      $1 = mot de passe, $2 = caisse, $3 = magasin, $4 = date, $5 = ldap.
    """
    # accepte l'identifiant seul (10100168) ou complet (10100168@ubastion.adeo.com)
    cible = ldap if "@" in ldap else f"{ldap}@{BASTION_HOTE}"
    base = ldap.split("@")[0]
    args = " ".join(_double_quote(v)
                    for v in (motdepasse, caisse, magasin, date, base))
    interne = (f"sshclient {BASTION_INTERNE} -t -o StrictHostKeyChecking=no "
               f"-o HostKeyAlgorithms=+ssh-rsa "
               f"sh {BASTION_SCRIPT} {args}")
    appdir = BASTION_APP_LOG.format(base=base)
    # nettoyage du dossier puis lancement du script
    distant = f"rm -rf {appdir} 2>/dev/null; mkdir -p {appdir}; {interne}"
    if SSH_BACKEND == "plink":
        # plink gere l'auth du bastion via -pw ; le prompt du rebond interne
        # (sshclient) est alimente sur stdin par le driver, la cle d'hote par 'y'.
        return [
            _plink(), "-ssh", "-t", "-pw", motdepasse,
            cible,
            distant,
        ]
    return [
        "ssh", "-tt",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "HostKeyAlgorithms=+ssh-rsa",
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "NumberOfPasswordPrompts=3",
        cible,
        distant,
    ]


def session_bastion(ldap, motdepasse, on_log=None, caisse=None, magasin=None,
                    date=None, timeout=300, doit_continuer=None):
    """Se connecte au bastion (LDAP + mot de passe) et lance le script de collecte.

    La sortie est transmise au fur et a mesure via on_log(texte).
    Retourne (code_retour, transcription_complete).
    """
    if not SSH_DISPONIBLE:
        raise ErreurSSH("Le SSH par mot de passe n'est pas disponible : "
                        "installez PuTTY (plink/pscp) sur Windows.")
    if not (ldap and motdepasse):
        raise ErreurSSH("Identifiant LDAP et mot de passe obligatoires.")
    cmd = commande_bastion(ldap, motdepasse, caisse, magasin, date)
    return _executer(cmd, motdepasse, timeout, on_log=on_log,
                     doit_continuer=doit_continuer, max_mdp=3)


def lister_fichiers(dossier):
    """Liste (triee) tous les fichiers presents sous `dossier`."""
    fichiers = []
    for racine, _dirs, noms in os.walk(dossier):
        for n in noms:
            fichiers.append(os.path.join(racine, n))
    fichiers.sort()
    return fichiers


def recuperer_logs_bastion(ldap, motdepasse, destination_dir, on_log=None,
                           timeout=300, doit_continuer=None):
    """Rapatrie tout le dossier APP_LOG du bastion vers destination_dir (local).

    Retourne (fichiers, avertissement). En cas d'echec partiel de scp, renvoie
    quand meme les fichiers deja recuperes avec un message d'avertissement, pour
    ne pas bloquer la lecture. Leve ErreurSSH seulement si rien n'a ete recupere.
    """
    if not SSH_DISPONIBLE:
        raise ErreurSSH("Le SSH par mot de passe n'est pas disponible : "
                        "installez PuTTY (plink/pscp) sur Windows.")
    if not (ldap and motdepasse):
        raise ErreurSSH("Identifiant LDAP et mot de passe obligatoires.")
    cible = ldap if "@" in ldap else f"{ldap}@{BASTION_HOTE}"
    base = ldap.split("@")[0]
    distant = BASTION_APP_LOG.format(base=base)
    os.makedirs(destination_dir, exist_ok=True)
    if SSH_BACKEND == "plink":
        cmd = [
            _pscp(), "-r", "-pw", motdepasse,
            f"{cible}:{distant}/",
            destination_dir,
        ]
    else:
        cmd = [
            "scp", "-r",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "-o", "PubkeyAuthentication=no",
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "NumberOfPasswordPrompts=3",
            f"{cible}:{distant}/.",
            destination_dir,
        ]
    code, sortie = _executer(cmd, motdepasse, timeout, on_log=on_log,
                             doit_continuer=doit_continuer, max_mdp=3)
    fichiers = lister_fichiers(destination_dir)
    avertissement = ""
    if code != 0:
        if fichiers:
            # echec partiel : on garde ce qui est arrive
            avertissement = _interpreter_erreur_ssh(sortie, code)
        else:
            raise ErreurSSH(_interpreter_erreur_ssh(sortie, code))
    if not fichiers:
        raise ErreurSSH("Aucun fichier récupéré dans le dossier APP_LOG du bastion.")
    return fichiers, avertissement
