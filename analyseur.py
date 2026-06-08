#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyseur de fichiers .log  -  interface graphique (Tkinter)
============================================================
Charge un fichier .log (potentiellement enorme) de maniere asynchrone, le parse
via parseur.py et offre :
  - filtres (categorie, niveau, classe de statut HTTP, application multi-selection,
    URL, plage horaire) ;
  - recherche texte ou regex (sensible a la casse en option), incluant le contenu
    request/response decode ;
  - tableau virtuel (insertion par lots, pas de blocage UI) ;
  - panneau de details avec coloration JSON et copie ciblee ;
  - statistiques (volumes, temps de reponse moy/p95, repartition des statuts) ;
  - regroupement des erreurs similaires + mini timeline ;
  - export .log / .jsonl / .csv et export du resume ;
  - edition de la liste d'exclusion (ignore.txt) depuis l'UI ;
  - persistance (taille fenetre, dernier dossier, fichiers recents).

Bibliotheque standard uniquement.  Lancement : python3 analyseur.py
"""

import sys
import os
import csv
import json
import re
import time
import threading
import queue
from collections import Counter
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Debug: log le demarrage si lance via PyInstaller
if getattr(sys, 'frozen', False):
    import logging
    logging.basicConfig(
        filename=os.path.expanduser("~/.analyseur_debug.log"),
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    _logger = logging.getLogger("analyseur")
else:
    _logger = None

def _log_debug(msg):
    if _logger:
        _logger.debug(msg)

import parseur


CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".analyseur_config.json")


def charger_config():
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def sauver_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ===========================================================================
#  COULEURS / THEME
# ===========================================================================
COULEURS = {
    "fond": "#f4f6fa", "carte": "#ffffff", "bordure": "#e1e5ee",
    "primaire": "#4f6ef7", "primaire_h": "#3f5ae0",
    "texte": "#1f2733", "texte_doux": "#7a8499",
    "entete": "#eef1fb", "ligne_paire": "#f7f9fd", "selection": "#dbe3ff",
    "barre": "#ffffff", "surlignage": "#fff2b2",
    "rouge": "#c0392b", "orange": "#b9770e", "vert": "#1e874b",
    "sidebar": "#1f2733", "sidebar_actif": "#34405a", "sidebar_txt": "#c7cedb",
    # coloration JSON
    "js_cle": "#7c4dff", "js_txt": "#1e874b", "js_num": "#b9770e",
    "js_bool": "#c0392b", "js_ponct": "#7a8499",
}

LOT_INSERTION = 400   # nombre de lignes inserees par cycle (tableau virtuel)


# ===========================================================================
#  APPLICATION
# ===========================================================================
class AnalyseurApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = charger_config()
        self.title("Analyseur de fichiers .log")
        self.geometry(self.cfg.get("geometrie", "1240x760"))
        self.minsize(960, 600)
        self.configure(bg=COULEURS["fond"])

        self.enregistrements = []
        self.vue = []
        self.categorie = "tout"
        self.niveaux_actifs = set()
        self.classes_actives = set()      # {'2xx','4xx',...}
        self.url_filtre = None
        self.apps_actives = set()         # multi-selection d'applications
        self.chemin = None
        self.recents = self.cfg.get("recents", [])

        self._file_progress = queue.Queue()
        self._insertion_token = 0
        self._tri_col = None
        self._tri_sens = False
        self.labels_app = {}

        parseur.charger_ignores()
        self._init_theme()
        self._construire_interface()

        self.bind("<Control-o>", lambda e: self.ouvrir())
        self.bind("<Command-o>", lambda e: self.ouvrir())
        self.bind("<Control-f>", lambda e: self.entry_rech.focus_set())
        self.bind("<Command-f>", lambda e: self.entry_rech.focus_set())
        self.protocol("WM_DELETE_WINDOW", self._quitter)
        
        # macOS: gérer clic sur Dock (FocusIn quand l'app retrouve le focus)
        if sys.platform == "darwin":
            self.bind("<FocusIn>", lambda e: self.deiconify() if self.state() == "withdrawn" else None)

        dossier = self.cfg.get("dossier")
        if dossier and os.path.isdir(dossier):
            self._dernier_dossier = dossier
        else:
            self._dernier_dossier = os.path.expanduser("~")

    # -------------------------------------------------- theme
    def _init_theme(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        from tkinter import font as tkfont
        self.police = "Helvetica Neue" if "Helvetica Neue" in tkfont.families() else "Helvetica"
        self.mono = "Menlo" if "Menlo" in tkfont.families() else "Courier"
        c = COULEURS
        p = self.police

        s.configure(".", background=c["fond"], foreground=c["texte"], font=(p, 12))
        s.configure("TFrame", background=c["fond"])
        s.configure("Barre.TFrame", background=c["barre"])
        s.configure("TLabel", background=c["fond"], foreground=c["texte"])
        s.configure("Barre.TLabel", background=c["barre"], foreground=c["texte"])
        s.configure("Doux.TLabel", background=c["barre"], foreground=c["texte_doux"],
                    font=(p, 11))
        s.configure("Accent.TButton", background=c["primaire"], foreground="white",
                    font=(p, 12, "bold"), borderwidth=0, padding=(16, 9))
        s.map("Accent.TButton", background=[("active", c["primaire_h"])])
        s.configure("Outil.TButton", background=c["entete"], foreground=c["texte"],
                    font=(p, 11), borderwidth=0, padding=(10, 6))
        s.map("Outil.TButton", background=[("active", c["selection"]),
                                           ("disabled", c["fond"])],
              foreground=[("disabled", "#bcc4d6")])
        s.configure("TEntry", fieldbackground=c["carte"], bordercolor=c["bordure"],
                    padding=6)
        s.configure("TMenubutton", background=c["entete"], foreground=c["texte"],
                    font=(p, 11), padding=(8, 5))
        s.configure("Treeview", background=c["carte"], fieldbackground=c["carte"],
                    foreground=c["texte"], rowheight=26, borderwidth=0, font=(p, 11))
        s.configure("Treeview.Heading", background=c["entete"], foreground=c["texte"],
                    font=(p, 11, "bold"), relief="flat", padding=7)
        s.map("Treeview.Heading", background=[("active", c["selection"])])
        s.map("Treeview", background=[("selected", c["selection"])],
              foreground=[("selected", c["texte"])])
        s.configure("Statut.TLabel", background=c["entete"], foreground=c["texte_doux"],
                    font=(p, 11))
        s.configure("TCheckbutton", background=c["barre"], foreground=c["texte"])
        s.configure("Mini.Horizontal.TProgressbar", troughcolor=c["entete"],
                    background=c["primaire"])

    # -------------------------------------------------- interface
    def _construire_interface(self):
        c = COULEURS
        barre = ttk.Frame(self, style="Barre.TFrame", padding=(16, 12))
        barre.pack(side=tk.TOP, fill=tk.X)
        tk.Frame(self, bg=c["bordure"], height=1).pack(side=tk.TOP, fill=tk.X)

        ttk.Button(barre, text="📂  Ouvrir", style="Accent.TButton",
                   command=self.ouvrir).pack(side=tk.LEFT)
        self.mb_recents = ttk.Menubutton(barre, text="Récents ▾", style="TMenubutton")
        self.menu_recents = tk.Menu(self.mb_recents, tearoff=0)
        self.mb_recents.configure(menu=self.menu_recents)
        self.mb_recents.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(barre, text="🔐  SSH", style="Outil.TButton",
                   command=self._ouvrir_ssh).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(barre, text="📋 Info", style="Outil.TButton",
                   command=self._afficher_info_caisse).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(barre, text="📁", style="Barre.TLabel",
                  font=(self.police, 13)).pack(side=tk.LEFT, padx=(8, 2))
        self.combo_fichiers = ttk.Combobox(barre, state="disabled", width=26,
                                            font=(self.mono, 10))
        self.combo_fichiers.set("Fichiers récupérés…")
        self.combo_fichiers.bind("<<ComboboxSelected>>", self._on_combo_fichier)
        self.combo_fichiers.pack(side=tk.LEFT)

        info = ttk.Frame(barre, style="Barre.TFrame")
        info.pack(side=tk.LEFT, padx=16)
        self.lbl_fichier = ttk.Label(info, text="Aucun fichier ouvert",
                                     style="Barre.TLabel", font=(self.police, 13, "bold"))
        self.lbl_fichier.pack(anchor="w")
        self.lbl_sous = ttk.Label(info, text="Ouvrez un fichier .log pour l'analyser",
                                  style="Doux.TLabel")
        self.lbl_sous.pack(anchor="w")

        # boutons outils (droite)
        outils = ttk.Frame(barre, style="Barre.TFrame")
        outils.pack(side=tk.RIGHT)
        ttk.Button(outils, text="🧩 Erreurs groupées", style="Outil.TButton",
                   command=self._ouvrir_groupes).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(outils, text="💾 Exporter", style="Outil.TButton",
                   command=self._exporter).pack(side=tk.LEFT)

        # Deuxieme barre : recherche + options + plage horaire
        barre2 = ttk.Frame(self, style="Barre.TFrame", padding=(16, 8))
        barre2.pack(side=tk.TOP, fill=tk.X)
        tk.Frame(self, bg=c["bordure"], height=1).pack(side=tk.TOP, fill=tk.X)

        ttk.Label(barre2, text="🔎", style="Barre.TLabel",
                  font=(self.police, 14)).pack(side=tk.LEFT, padx=(0, 6))
        self.var_rech = tk.StringVar()
        self.var_rech.trace_add("write", lambda *a: self._rafraichir_differe())
        self.entry_rech = ttk.Entry(barre2, textvariable=self.var_rech, width=34,
                                    font=(self.police, 12))
        self.entry_rech.pack(side=tk.LEFT, ipady=3)

        self.var_regex = tk.BooleanVar(value=False)
        self.var_casse = tk.BooleanVar(value=False)
        ttk.Checkbutton(barre2, text="regex", variable=self.var_regex,
                        command=self._rafraichir).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(barre2, text="Aa", variable=self.var_casse,
                        command=self._rafraichir).pack(side=tk.LEFT, padx=(4, 0))
        self.lbl_regex = ttk.Label(barre2, text="", style="Doux.TLabel")
        self.lbl_regex.pack(side=tk.LEFT, padx=(8, 0))

        # plage horaire : accepte l'heure seule (10:13:50) ou la date+heure.
        plage = ttk.Frame(barre2, style="Barre.TFrame")
        plage.pack(side=tk.RIGHT)
        ttk.Label(plage, text="de", style="Doux.TLabel").pack(side=tk.LEFT)
        self.var_de = tk.StringVar()
        ttk.Entry(plage, textvariable=self.var_de, width=18,
                  font=(self.mono, 10)).pack(side=tk.LEFT, padx=4)
        ttk.Label(plage, text="à", style="Doux.TLabel").pack(side=tk.LEFT)
        self.var_a = tk.StringVar()
        ttk.Entry(plage, textvariable=self.var_a, width=18,
                  font=(self.mono, 10)).pack(side=tk.LEFT, padx=4)
        self.var_de.trace_add("write", lambda *a: self._rafraichir_differe())
        self.var_a.trace_add("write", lambda *a: self._rafraichir_differe())
        ttk.Button(plage, text="⤓ plage", style="Outil.TButton",
                   command=self._remplir_plage).pack(side=tk.LEFT, padx=(2, 2))
        ttk.Button(plage, text="✕", style="Outil.TButton",
                   command=self._vider_plage).pack(side=tk.LEFT)

        # barre de progression (cachee par defaut)
        self.barre_prog = ttk.Progressbar(self, style="Mini.Horizontal.TProgressbar",
                                          mode="determinate")

        # Corps
        corps = ttk.Frame(self, style="TFrame")
        corps.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(corps, bg=c["sidebar"], width=250)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        self._construire_sidebar_scroll()

        centre = ttk.Frame(corps, style="TFrame")
        centre.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        paned = ttk.PanedWindow(centre, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        cadre_tab = ttk.Frame(paned, style="TFrame")
        paned.add(cadre_tab, weight=3)
        self._construire_tableau(cadre_tab)

        cadre_det = tk.Frame(paned, bg=c["carte"], highlightbackground=c["bordure"],
                             highlightthickness=1)
        paned.add(cadre_det, weight=2)
        self._construire_details(cadre_det)

        self.lbl_statut = ttk.Label(self, anchor="w", style="Statut.TLabel",
                                    padding=(12, 6), text="Prêt.")
        self.lbl_statut.pack(side=tk.BOTTOM, fill=tk.X)

        self._maj_menu_recents()

    # -------------------------------------------------- sidebar defilante
    def _construire_sidebar_scroll(self):
        c = COULEURS
        self.sb_canvas = tk.Canvas(self.sidebar, bg=c["sidebar"],
                                   highlightthickness=0, bd=0, width=232)
        sb_scroll = ttk.Scrollbar(self.sidebar, orient="vertical",
                                  command=self.sb_canvas.yview)
        self.sb_canvas.configure(yscrollcommand=sb_scroll.set)
        sb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.sb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.sidebar_contenu = tk.Frame(self.sb_canvas, bg=c["sidebar"])
        self._sb_window = self.sb_canvas.create_window(
            (0, 0), window=self.sidebar_contenu, anchor="nw")

        def _maj_scrollregion(_e=None):
            self.sb_canvas.configure(scrollregion=self.sb_canvas.bbox("all"))
            self.sb_canvas.itemconfigure(self._sb_window,
                                         width=self.sb_canvas.winfo_width())
        self.sidebar_contenu.bind("<Configure>", _maj_scrollregion)
        self.sb_canvas.bind("<Configure>", _maj_scrollregion)

        def _molette(event):
            if event.delta:
                pas = int(-event.delta / 120) if abs(event.delta) >= 120 else (
                    -1 if event.delta > 0 else 1)
                self.sb_canvas.yview_scroll(pas, "units")
            return "break"

        def _molette_lin(event):
            self.sb_canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"

        self._molette = _molette
        self._molette_lin = _molette_lin
        self._lier_molette(self.sb_canvas)
        self._lier_molette(self.sidebar_contenu)
        self._construire_sidebar()

    def _lier_molette(self, widget):
        widget.bind("<MouseWheel>", self._molette, add="+")
        widget.bind("<Button-4>", self._molette_lin, add="+")
        widget.bind("<Button-5>", self._molette_lin, add="+")
        for enfant in widget.winfo_children():
            self._lier_molette(enfant)

    def _nouvelle_fenetre(self, titre, geom):
        """Cree un Toplevel au premier plan, focus, fermable par Echap."""
        top = tk.Toplevel(self)
        top.title(titre)
        top.geometry(geom)
        top.configure(bg=COULEURS["fond"])
        top.transient(self)
        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        top.lift()
        top.attributes("-topmost", True)
        top.after(200, lambda: top.attributes("-topmost", False))
        top.focus_force()
        return top

    def _scroller_widget(self, widget):
        """Lie la molette pour faire defiler un widget scrollable (Text/Treeview)."""
        def w(event):
            if event.delta:
                pas = (int(-event.delta / 120) if abs(event.delta) >= 120
                       else (-1 if event.delta > 0 else 1))
                widget.yview_scroll(pas, "units")
            return "break"

        def wl(event):
            widget.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"
        widget.bind("<MouseWheel>", w, add="+")
        widget.bind("<Button-4>", wl, add="+")
        widget.bind("<Button-5>", wl, add="+")

    def _titre_section(self, parent, texte):
        tk.Label(parent, text=texte, bg=COULEURS["sidebar"],
                 fg=COULEURS["texte_doux"], font=(self.police, 10, "bold"),
                 anchor="w", padx=16).pack(fill=tk.X, pady=(18, 6))

    def _construire_sidebar(self):
        c = COULEURS
        parent = self.sidebar_contenu
        tk.Label(parent, text="CATÉGORIES", bg=c["sidebar"], fg=c["texte_doux"],
                 font=(self.police, 10, "bold"), anchor="w", padx=16
                 ).pack(fill=tk.X, pady=(16, 6))
        self.btns_cat = {}
        for cle, icone, libelle in [("tout", "📋", "Tout"), ("erreurs", "❌", "Erreurs"),
                                    ("avert", "⚠️", "Avertissements"),
                                    ("api", "🌐", "Appels API")]:
            b = tk.Label(parent, text=f"  {icone}  {libelle}", bg=c["sidebar"],
                         fg=c["sidebar_txt"], font=(self.police, 12), anchor="w",
                         padx=12, pady=9, cursor="hand2")
            b.pack(fill=tk.X, padx=8, pady=1)
            b.bind("<Button-1>", lambda e, k=cle: self._choisir_categorie(k))
            self.btns_cat[cle] = b

        self._titre_section(parent, "NIVEAUX")
        self.cadre_niveaux = tk.Frame(parent, bg=c["sidebar"])
        self.cadre_niveaux.pack(fill=tk.X)

        self._titre_section(parent, "STATUTS HTTP")
        self.cadre_statuts = tk.Frame(parent, bg=c["sidebar"])
        self.cadre_statuts.pack(fill=tk.X)

        self._titre_section(parent, "APPLICATIONS  (multi)")
        self.cadre_apps = tk.Frame(parent, bg=c["sidebar"])
        self.cadre_apps.pack(fill=tk.X)

        self._titre_section(parent, "URLS LES PLUS APPELÉES")
        self.cadre_urls = tk.Frame(parent, bg=c["sidebar"])
        self.cadre_urls.pack(fill=tk.X, pady=(0, 12))

    def _construire_tableau(self, parent):
        cols = ("no", "temps", "app", "niveau", "methode", "statut", "duree", "url", "message")
        titres = {"no": "#", "temps": "Heure", "app": "Application", "niveau": "Niveau",
                  "methode": "Méth.", "statut": "Statut", "duree": "Durée",
                  "url": "URL / Chemin", "message": "Message"}
        larg = {"no": 55, "temps": 155, "app": 130, "niveau": 65, "methode": 60,
                "statut": 60, "duree": 75, "url": 230, "message": 300}
        self.tab = ttk.Treeview(parent, columns=cols, show="headings",
                                selectmode="browse")
        for col in cols:
            self.tab.heading(col, text=titres[col],
                             command=lambda cc=col: self._trier(cc))
            anchor = "center" if col in ("no", "niveau", "methode", "statut", "duree") else "w"
            self.tab.column(col, width=larg[col], anchor=anchor,
                            stretch=(col in ("url", "message")))
        vsb = ttk.Scrollbar(parent, orient="vertical", command=self.tab.yview)
        hsb = ttk.Scrollbar(parent, orient="horizontal", command=self.tab.xview)
        self.tab.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tab.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        self.tab.tag_configure("err", foreground=COULEURS["rouge"])
        self.tab.tag_configure("warn", foreground=COULEURS["orange"])
        self.tab.tag_configure("ignore", foreground="#aab2c0")
        self.tab.tag_configure("pair", background=COULEURS["ligne_paire"])
        self.tab.bind("<<TreeviewSelect>>", self._on_select)

    def _construire_details(self, parent):
        c = COULEURS
        haut = tk.Frame(parent, bg=c["entete"])
        haut.pack(fill=tk.X)
        tk.Label(haut, text="🔎  Détail de la ligne sélectionnée", bg=c["entete"],
                 fg=c["texte"], font=(self.police, 12, "bold"), anchor="w",
                 padx=12, pady=8).pack(side=tk.LEFT)
        for txt, cmd in [("Copier brut", lambda: self._copier("brut")),
                         ("Copier JSON", lambda: self._copier("json")),
                         ("Copier request", lambda: self._copier("request")),
                         ("Copier response", lambda: self._copier("response"))]:
            ttk.Button(haut, text=txt, style="Outil.TButton",
                       command=cmd).pack(side=tk.RIGHT, padx=(4, 8), pady=4)

        self.txt_detail = tk.Text(parent, wrap="word", bg=c["carte"], fg=c["texte"],
                                  font=(self.mono, 11), relief="flat", padx=12, pady=10,
                                  height=8)
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.txt_detail.yview)
        self.txt_detail.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.txt_detail.pack(fill=tk.BOTH, expand=True)
        t = self.txt_detail
        t.tag_configure("cle", foreground=c["primaire"], font=(self.mono, 11, "bold"))
        t.tag_configure("titre", foreground=c["texte_doux"], font=(self.mono, 11, "bold"))
        t.tag_configure("js_cle", foreground=c["js_cle"])
        t.tag_configure("js_txt", foreground=c["js_txt"])
        t.tag_configure("js_num", foreground=c["js_num"])
        t.tag_configure("js_bool", foreground=c["js_bool"])
        t.tag_configure("js_ponct", foreground=c["js_ponct"])

    # -------------------------------------------------- ouverture asynchrone
    def ouvrir(self, chemin=None):
        if not chemin:
            chemin = filedialog.askopenfilename(
                title="Choisir un fichier .log",
                initialdir=getattr(self, "_dernier_dossier", os.path.expanduser("~")),
                filetypes=[("Fichiers log", "*.log *.txt *.out *.json"),
                           ("Tous les fichiers", "*.*")])
        if not chemin or not os.path.exists(chemin):
            if chemin:
                messagebox.showwarning("Introuvable", f"Fichier introuvable :\n{chemin}")
            return
        self.chemin = chemin
        self._dernier_dossier = os.path.dirname(chemin)
        parseur.charger_ignores()

        self.barre_prog.pack(side=tk.TOP, fill=tk.X)
        self.barre_prog["value"] = 0
        self.lbl_statut.config(text="Analyse en cours…")

        self._file_progress = queue.Queue()
        self._chargement_actif = True

        def tache():
            def progression(lignes, octets, total):
                self._file_progress.put(("prog", lignes, octets, total))
            try:
                enregs = parseur.analyser_fichier(
                    chemin, progression=progression,
                    doit_continuer=lambda: self._chargement_actif)
                self._file_progress.put(("fini", enregs))
            except Exception as e:  # noqa
                self._file_progress.put(("erreur", str(e)))

        threading.Thread(target=tache, daemon=True).start()
        self.after(60, self._surveiller_chargement)

    def _surveiller_chargement(self):
        try:
            while True:
                msg = self._file_progress.get_nowait()
                if msg[0] == "prog":
                    _, lignes, octets, total = msg
                    if total:
                        self.barre_prog["value"] = min(100, octets * 100 / total)
                    self.lbl_statut.config(text=f"Analyse… {lignes} lignes")
                elif msg[0] == "erreur":
                    self.barre_prog.pack_forget()
                    messagebox.showerror("Erreur", msg[1])
                    return
                elif msg[0] == "fini":
                    self.barre_prog["value"] = 100
                    self.after(120, lambda: self.barre_prog.pack_forget())
                    self._charge_termine(msg[1])
                    return
        except queue.Empty:
            pass
        self.after(60, self._surveiller_chargement)

    def _charge_termine(self, enregs):
        self.enregistrements = enregs
        self.var_rech.set("")
        self.var_de.set("")
        self.var_a.set("")
        self.categorie = "tout"
        self.niveaux_actifs = set()
        self.classes_actives = set()
        self.url_filtre = None
        self.apps_actives = set()
        self.lbl_fichier.config(text=os.path.basename(self.chemin))
        self.lbl_sous.config(text=f"{len(enregs)} ligne(s) analysée(s)")
        self._ajouter_recent(self.chemin)
        self._maj_sidebar()
        self._rafraichir()

    # -------------------------------------------------- SSH (bastion ADEO)
    def _ouvrir_ssh(self):
        if not parseur.SSH_DISPONIBLE:
            messagebox.showerror(
                "SSH indisponible",
                "Le SSH par mot de passe nécessite PuTTY sur Windows.\n"
                "Installez PuTTY (plink.exe et pscp.exe) puis relancez "
                "l'application.")
            return

        cfg_ssh = self.cfg.get("ssh", {})
        top = self._nouvelle_fenetre("Connexion bastion ADEO", "440x300")
        cadre = ttk.Frame(top, style="TFrame", padding=18)
        cadre.pack(fill=tk.BOTH, expand=True)

        v_caisse = tk.StringVar(value=cfg_ssh.get("caisse", ""))
        v_magasin = tk.StringVar(value=cfg_ssh.get("magasin", ""))
        v_date = tk.StringVar(value=cfg_ssh.get("date", "") or time.strftime("%Y-%m-%d"))
        v_ldap = tk.StringVar(value=cfg_ssh.get("ldap", ""))
        v_mdp = tk.StringVar(value="")

        champs = [
            ("Caisse", v_caisse, False),
            ("Magasin", v_magasin, False),
            ("Date (AAAA-MM-JJ)", v_date, False),
            ("Ldap", v_ldap, False),
            ("Mot de passe", v_mdp, True),
        ]
        entrees = {}
        for i, (lib, var, secret) in enumerate(champs):
            ttk.Label(cadre, text=lib, style="TLabel").grid(
                row=i, column=0, sticky="w", pady=7, padx=(0, 10))
            e = ttk.Entry(cadre, textvariable=var, width=30, font=(self.mono, 11),
                          show="•" if secret else "")
            e.grid(row=i, column=1, sticky="we", pady=7)
            entrees[lib] = e
        cadre.columnconfigure(1, weight=1)

        lbl_etat = ttk.Label(cadre, text=f"Bastion : {parseur.BASTION_HOTE}",
                             style="Doux.TLabel")
        lbl_etat.grid(row=len(champs), column=0, columnspan=2, sticky="w", pady=(12, 4))

        barre_btn = ttk.Frame(cadre, style="TFrame")
        barre_btn.grid(row=len(champs) + 1, column=0, columnspan=2, sticky="e")
        btn_go = ttk.Button(barre_btn, text="🔌  Se connecter et lancer",
                            style="Accent.TButton")
        btn_go.pack(side=tk.RIGHT)
        ttk.Button(barre_btn, text="Annuler", style="Outil.TButton",
                   command=top.destroy).pack(side=tk.RIGHT, padx=(0, 8))

        def lancer():
            caisse = v_caisse.get().strip()
            magasin = v_magasin.get().strip()
            date = v_date.get().strip()
            ldap = v_ldap.get().strip()
            mdp = v_mdp.get()
            if not (ldap and mdp):
                lbl_etat.config(text="Ldap et mot de passe sont obligatoires.")
                return
            self.cfg["ssh"] = {"caisse": caisse, "magasin": magasin,
                               "date": date, "ldap": ldap}
            top.destroy()
            self._console_bastion(ldap, mdp, caisse, magasin, date)

        btn_go.config(command=lancer)
        top.bind("<Return>", lambda e: lancer())
        entrees["Caisse"].focus_set()

    def _console_bastion(self, ldap, mdp, caisse, magasin, date=None):
        """Fenetre console : streame la sortie de la session bastion en direct."""
        top = self._nouvelle_fenetre("Session bastion — sortie en direct", "820x520")
        cadre = ttk.Frame(top, style="TFrame", padding=10)
        cadre.pack(fill=tk.BOTH, expand=True)

        haut = ttk.Frame(cadre, style="TFrame")
        haut.pack(fill=tk.X)
        lbl = ttk.Label(haut, text=f"Connexion {ldap}@{parseur.BASTION_HOTE}…",
                        style="TLabel", font=(self.police, 12, "bold"))
        lbl.pack(side=tk.LEFT)

        zone = ttk.Frame(cadre, style="TFrame")
        zone.pack(fill=tk.BOTH, expand=True, pady=(8, 6))
        txt = tk.Text(zone, bg="#0d1117", fg="#d6deeb", insertbackground="#d6deeb",
                      font=(self.mono, 10), wrap="none", relief="flat", padx=8, pady=8)
        ysb = ttk.Scrollbar(zone, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set, state="disabled")
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._scroller_widget(txt)

        bas = ttk.Frame(cadre, style="TFrame")
        bas.pack(fill=tk.X)
        actif = {"on": True}
        ttk.Button(bas, text="Fermer / Interrompre", style="Outil.TButton",
                   command=lambda: (actif.update(on=False), top.destroy())
                   ).pack(side=tk.RIGHT)

        file_out = queue.Queue()

        def ajouter(texte):
            txt.configure(state="normal")
            txt.insert("end", texte)
            txt.see("end")
            txt.configure(state="disabled")

        def log(t):
            file_out.put(("log", t))

        dest_dir = os.path.join(os.path.expanduser("~"), ".analyseur_cache",
                                f"bastion_{int(time.time())}")

        def tache():
            try:
                # 1) collecte sur le bastion
                file_out.put(("log", "[1/2] Lancement du script de collecte…\n"))
                code, _ = parseur.session_bastion(
                    ldap, mdp, on_log=log, caisse=caisse, magasin=magasin,
                    date=date, doit_continuer=lambda: actif["on"])
                if not actif["on"]:
                    return
                if code != 0:
                    file_out.put(("log", f"\n[AVERTISSEMENT] Le script s'est "
                                  f"terminé en erreur (code {code}). Tentative de "
                                  f"récupération des fichiers présents…\n"))
                # 2) rapatriement du dossier APP_LOG vers le local
                file_out.put(("log", f"\n[2/2] Récupération vers {dest_dir}…\n"))
                fichiers, avert = parseur.recuperer_logs_bastion(
                    ldap, mdp, dest_dir, on_log=log,
                    doit_continuer=lambda: actif["on"])
                file_out.put(("fichiers", (fichiers, avert)))
            except parseur.ErreurSSH as e:
                file_out.put(("err", str(e)))
            except Exception as e:  # noqa
                file_out.put(("err", str(e)))

        threading.Thread(target=tache, daemon=True).start()

        def surveiller():
            try:
                while True:
                    quoi, val = file_out.get_nowait()
                    if quoi == "log":
                        ajouter(val)
                    elif quoi == "fichiers":
                        fichiers, avert = val
                        if avert:
                            ajouter(f"\n[AVERTISSEMENT] {avert}\n")
                        ajouter(f"\n[terminé — {len(fichiers)} fichier(s) "
                                "récupéré(s)]\n")
                        lbl.config(text="Logs récupérés.")
                        actif["on"] = False
                        top.destroy()
                        self._charger_fichiers_bastion(fichiers)
                        return
                    elif quoi == "err":
                        ajouter(f"\n[ERREUR] {val}\n")
                        ajouter("Aucun fichier à lire. Vous pouvez fermer cette "
                                "fenêtre.\n")
                        lbl.config(text="Échec — aucun fichier récupéré.")
                        actif["on"] = False
                        return
            except queue.Empty:
                pass
            if actif["on"]:
                top.after(120, surveiller)

        top.after(120, surveiller)

    def _charger_fichiers_bastion(self, fichiers):
        """Remplit le menu déroulant des fichiers récupérés et ouvre le 1er."""
        self.fichiers_bastion = list(fichiers)
        libelles = []
        for f in self.fichiers_bastion:
            taille = os.path.getsize(f) if os.path.exists(f) else 0
            libelles.append(f"{os.path.basename(f)}  ({taille // 1024} Ko)")
        self.combo_fichiers.configure(values=libelles, state="readonly")
        if libelles:
            self.combo_fichiers.current(0)
            self.ouvrir(self.fichiers_bastion[0])

    def _afficher_info_caisse(self):
        """Cherche et affiche le fichier info_ks.txt dans les fichiers bastion récupérés."""
        fichier_info = None
        for f in getattr(self, "fichiers_bastion", []):
            if os.path.basename(f).lower() == "info_ks.txt":
                fichier_info = f
                break
        
        if not fichier_info or not os.path.exists(fichier_info):
            messagebox.showinfo("Info Caisse", "Fichier info_ks.txt non trouvé.")
            return
        
        # Parser le fichier
        infos = {}
        try:
            with open(fichier_info, "r", encoding="utf-8") as f:
                contenu = f.read()
                for ligne in contenu.split("\n"):
                    ligne = ligne.strip()
                    if "=" in ligne:
                        cle, val = ligne.split("=", 1)
                        cle = cle.strip()
                        val = val.strip()
                        if cle not in infos:
                            infos[cle] = []
                        infos[cle].append(val)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lire info_ks.txt: {e}")
            return
        
        # Créer la fenêtre d'affichage
        top = self._nouvelle_fenetre("📋 Informations Caisse", "600x500")
        cadre = ttk.Frame(top, style="TFrame", padding=16)
        cadre.pack(fill=tk.BOTH, expand=True)
        
        # Titre
        titre = ttk.Label(cadre, text="Informations Caisse", 
                         font=(self.police, 14, "bold"))
        titre.pack(anchor="w", pady=(0, 16))
        
        # Zone de texte scrollable
        frame_text = ttk.Frame(cadre)
        frame_text.pack(fill=tk.BOTH, expand=True)
        
        text_widget = tk.Text(frame_text, wrap=tk.WORD, height=20, width=70,
                             bg=COULEURS["carte"], fg=COULEURS["texte"],
                             font=(self.mono, 10), relief=tk.FLAT, bd=0)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame_text, command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        # Remplir le texte avec formatage
        text_widget.tag_configure("cle", font=(self.mono, 10, "bold"), 
                                 foreground=COULEURS["primaire"])
        text_widget.tag_configure("val", font=(self.mono, 10), 
                                 foreground=COULEURS["texte"])
        text_widget.tag_configure("multi", font=(self.mono, 9), 
                                 foreground=COULEURS["texte_doux"])
        
        for cle, vals in infos.items():
            text_widget.insert(tk.END, f"{cle:15}", "cle")
            text_widget.insert(tk.END, " = ", "val")
            
            if len(vals) == 1:
                # Valeur simple
                text_widget.insert(tk.END, vals[0] + "\n", "val")
            else:
                # Plusieurs valeurs (liste)
                text_widget.insert(tk.END, vals[0] + "\n", "val")
                for val in vals[1:]:
                    text_widget.insert(tk.END, " " * 17, "val")
                    text_widget.insert(tk.END, val + "\n", "multi")
        
        text_widget.configure(state=tk.DISABLED)
        
        # Bouton Copier tout
        def copier_tout():
            contenu = text_widget.get("1.0", tk.END)
            top.clipboard_clear()
            top.clipboard_append(contenu)
            messagebox.showinfo("Copié", "Informations copiées dans le presse-papiers")
        
        btn_frame = ttk.Frame(cadre)
        btn_frame.pack(fill=tk.X, pady=(12, 0))
        btn_copier = ttk.Button(btn_frame, text="📋 Copier tout", 
                               command=copier_tout, style="Outil.TButton")
        btn_copier.pack(side=tk.LEFT, padx=(0, 8))
        
        top.lift()

        idx = self.combo_fichiers.current()
        if 0 <= idx < len(getattr(self, "fichiers_bastion", [])):
            chemin = self.fichiers_bastion[idx]
            if chemin != getattr(self, "chemin", None):
                self.ouvrir(chemin)
        # retire le focus pour pouvoir re-sélectionner le même item ensuite
        self.focus_set()

    # -------------------------------------------------- recents
    def _ajouter_recent(self, chemin):
        self.recents = [chemin] + [r for r in self.recents if r != chemin]
        self.recents = self.recents[:8]
        self._maj_menu_recents()

    def _maj_menu_recents(self):
        self.menu_recents.delete(0, "end")
        existants = [r for r in self.recents if os.path.exists(r)]
        if not existants:
            self.menu_recents.add_command(label="(aucun)", state="disabled")
        for r in existants:
            self.menu_recents.add_command(
                label=os.path.basename(r),
                command=lambda c=r: self.ouvrir(c))

    # -------------------------------------------------- filtres
    def _choisir_categorie(self, cle):
        self.categorie = cle
        self.url_filtre = None
        self._rafraichir()

    def _basculer_niveau(self, niveau):
        self.niveaux_actifs.symmetric_difference_update({niveau})
        self._rafraichir()

    def _basculer_classe(self, classe):
        self.classes_actives.symmetric_difference_update({classe})
        self._rafraichir()

    def _filtrer_url(self, url):
        self.url_filtre = None if self.url_filtre == url else url
        self._rafraichir()

    def _basculer_app(self, app):
        self.apps_actives.symmetric_difference_update({app})
        self._rafraichir()

    def _maj_sidebar(self):
        c = COULEURS
        regs = self.enregistrements
        for cle, (ic, lib, n) in {
                "tout": ("📋", "Tout", len(regs)),
                "erreurs": ("❌", "Erreurs", sum(r["erreur"] for r in regs)),
                "avert": ("⚠️", "Avertissements", sum(r["avert"] for r in regs)),
                "api": ("🌐", "Appels API", sum(r["api"] for r in regs))}.items():
            self.btns_cat[cle].config(text=f"  {ic}  {lib}    ({n})")

        for w in self.cadre_niveaux.winfo_children():
            w.destroy()
        compte_niv = Counter(r["niveau"] for r in regs if r["niveau"])
        ordre = ["FATAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"]
        for niv in sorted(compte_niv, key=lambda x: ordre.index(x) if x in ordre else 99):
            self._case_sidebar(self.cadre_niveaux, f"{niv}  ({compte_niv[niv]})",
                               lambda nv=niv: self._basculer_niveau(nv),
                               {"FATAL": c["rouge"], "ERROR": c["rouge"],
                                "WARN": c["orange"]}.get(niv, c["sidebar_txt"]))

        for w in self.cadre_statuts.winfo_children():
            w.destroy()
        compte_cl = Counter(f"{r['statut'] // 100}xx" for r in regs
                            if r["statut"] is not None)
        for cl in sorted(compte_cl):
            coul = {"4xx": c["orange"], "5xx": c["rouge"]}.get(cl, c["sidebar_txt"])
            self._case_sidebar(self.cadre_statuts, f"{cl}  ({compte_cl[cl]})",
                               lambda x=cl: self._basculer_classe(x), coul)
        if not compte_cl:
            self._label_vide(self.cadre_statuts)

        for w in self.cadre_apps.winfo_children():
            w.destroy()
        self.labels_app = {}
        compte_app = Counter(r["app"] for r in regs if r["app"])
        if not compte_app:
            self._label_vide(self.cadre_apps)
        else:
            for app, n in compte_app.most_common(30):
                court = app if len(app) <= 24 else app[:23] + "…"
                lab = tk.Label(self.cadre_apps, text=f"  {court}  ({n})", bg=c["sidebar"],
                               fg=c["sidebar_txt"], font=(self.police, 11), anchor="w",
                               padx=12, pady=3, cursor="hand2")
                lab.pack(fill=tk.X, padx=8)
                lab.bind("<Button-1>", lambda e, a=app: self._basculer_app(a))
                self.labels_app[app] = lab

        for w in self.cadre_urls.winfo_children():
            w.destroy()
        compte_url = Counter(r["url"] for r in regs if r["url"])
        for url, n in compte_url.most_common(12):
            court = url if len(url) <= 28 else "…" + url[-27:]
            lab = tk.Label(self.cadre_urls, text=f"  {court}  ({n})", bg=c["sidebar"],
                           fg=c["sidebar_txt"], font=(self.police, 10), anchor="w",
                           padx=12, pady=3, cursor="hand2")
            lab.pack(fill=tk.X, padx=8)
            lab.bind("<Button-1>", lambda e, u=url: self._filtrer_url(u))

        self._lier_molette(self.sidebar_contenu)

    def _case_sidebar(self, parent, texte, cmd, coul):
        c = COULEURS
        cb = tk.Checkbutton(parent, text=f" {texte}", bg=c["sidebar"], fg=coul,
                            selectcolor=c["sidebar"], activebackground=c["sidebar"],
                            activeforeground=coul, font=(self.police, 11), anchor="w",
                            padx=10, highlightthickness=0, bd=0, command=cmd)
        cb.pack(fill=tk.X, padx=8)

    def _label_vide(self, parent):
        tk.Label(parent, text="  (aucun)", bg=COULEURS["sidebar"],
                 fg=COULEURS["texte_doux"], font=(self.police, 10, "italic"),
                 anchor="w", padx=12).pack(fill=tk.X, padx=8)

    def _surligner(self):
        c = COULEURS
        for cle, b in self.btns_cat.items():
            actif = (cle == self.categorie)
            b.config(bg=c["sidebar_actif"] if actif else c["sidebar"],
                     fg="white" if actif else c["sidebar_txt"])
        for app, lab in self.labels_app.items():
            actif = app in self.apps_actives
            lab.config(bg=c["sidebar_actif"] if actif else c["sidebar"],
                       fg="white" if actif else c["sidebar_txt"])

    # -------------------------------------------------- rafraichissement
    def _rafraichir_differe(self):
        if getattr(self, "_apres_id", None):
            self.after_cancel(self._apres_id)
        self._apres_id = self.after(180, self._rafraichir)

    def _compiler_regex(self):
        terme = self.var_rech.get()
        if not terme:
            self.lbl_regex.config(text="")
            return None, None
        if self.var_regex.get():
            try:
                flags = 0 if self.var_casse.get() else re.IGNORECASE
                self.lbl_regex.config(text="✓ regex", foreground=COULEURS["vert"])
                return re.compile(terme, flags), True
            except re.error as e:
                self.lbl_regex.config(text=f"✗ {e}", foreground=COULEURS["rouge"])
                return None, "erreur"
        self.lbl_regex.config(text="")
        return (terme if self.var_casse.get() else terme.lower()), False

    def _texte_recherche(self, r):
        morceaux = [r["brut"]]
        for cle in ("request", "response"):
            v = r.get(cle)
            if v:
                morceaux.append(v if isinstance(v, str)
                                else json.dumps(v, ensure_ascii=False))
        return "\n".join(morceaux)

    def _correspond(self, r, motif, est_regex, bornes):
        cat = self.categorie
        if cat == "erreurs" and not r["erreur"]:
            return False
        if cat == "avert" and not r["avert"]:
            return False
        if cat == "api" and not r["api"]:
            return False
        if self.niveaux_actifs and r["niveau"] not in self.niveaux_actifs:
            return False
        if self.classes_actives:
            cl = f"{r['statut'] // 100}xx" if r["statut"] is not None else None
            if cl not in self.classes_actives:
                return False
        if self.url_filtre and r["url"] != self.url_filtre:
            return False
        if self.apps_actives and r["app"] not in self.apps_actives:
            return False
        de, a = bornes
        if de or a:
            if r["dt"] is None:
                return False
            if de and r["dt"] < de:
                return False
            if a and r["dt"] > a:
                return False
        if motif:
            txt = self._texte_recherche(r)
            if est_regex:
                if not motif.search(txt):
                    return False
            else:
                if motif not in (txt if self.var_casse.get() else txt.lower()):
                    return False
        return True

    def _ref_date(self):
        """Date de reference (1er enregistrement horodate) pour les heures seules."""
        for r in self.enregistrements:
            if r["dt"]:
                return r["dt"].date()
        return None

    def _parse_borne(self, texte):
        """Accepte une date+heure complete OU une heure seule (HH:MM[:SS[.fff]])."""
        texte = (texte or "").strip()
        if not texte:
            return None
        dt = parseur.parse_temps(texte)
        if dt:
            return dt
        import datetime as _dt
        m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,](\d+))?$", texte)
        ref = self._ref_date()
        if m and ref:
            frac = (m.group(4) or "0")
            micro = int((frac + "000000")[:6])
            try:
                return _dt.datetime.combine(
                    ref, _dt.time(int(m.group(1)), int(m.group(2)),
                                  int(m.group(3) or 0), micro))
            except ValueError:
                return None
        return None

    def _bornes_temps(self):
        return self._parse_borne(self.var_de.get()), self._parse_borne(self.var_a.get())

    def _remplir_plage(self):
        """Pre-remplit les champs avec la 1ere et la derniere date detectees."""
        dates = [r["dt"] for r in self.enregistrements if r["dt"]]
        if not dates:
            self.lbl_statut.config(text="Aucun horodatage détecté dans ce fichier.")
            return
        fmt = "%Y-%m-%d %H:%M:%S"
        self.var_de.set(min(dates).strftime(fmt))
        self.var_a.set(max(dates).strftime(fmt))

    def _vider_plage(self):
        self.var_de.set("")
        self.var_a.set("")


    def _rafraichir(self):
        self._surligner()
        motif, est_regex = self._compiler_regex()
        if est_regex == "erreur":
            return
        bornes = self._bornes_temps()
        self.vue = [r for r in self.enregistrements
                    if self._correspond(r, motif, est_regex, bornes)]
        if self._tri_col:
            self._appliquer_tri()
        self._remplir_tableau()

    def _remplir_tableau(self):
        self.tab.delete(*self.tab.get_children())
        self._insertion_token += 1
        token = self._insertion_token
        self._inserer_lot(0, token)
        info = f"{len(self.vue)} ligne(s) affichée(s) sur {len(self.enregistrements)}"
        if self.apps_actives:
            info += f"  ·  App : {', '.join(sorted(self.apps_actives))}"
        if self.url_filtre:
            info += f"  ·  URL : {self.url_filtre}"
        self.lbl_statut.config(text=info)

    def _inserer_lot(self, debut, token):
        if token != self._insertion_token:
            return
        fin = min(debut + LOT_INSERTION, len(self.vue))
        for idx in range(debut, fin):
            r = self.vue[idx]
            tags = []
            if r["erreur"]:
                tags.append("err")
            elif r["avert"]:
                tags.append("warn")
            elif r["ignore"]:
                tags.append("ignore")
            if idx % 2 == 0:
                tags.append("pair")
            url_aff = r["url"] if len(r["url"]) <= 60 else "…" + r["url"][-59:]
            msg = r["message"].replace("\n", " ")
            msg = msg if len(msg) <= 120 else msg[:119] + "…"
            duree = f"{r['duree_ms']:.0f} ms" if r["duree_ms"] is not None else ""
            self.tab.insert("", "end", iid=str(r["no"]),
                            values=(r["no"], r["temps"], r["app"], r["niveau"],
                                    r["methode"],
                                    r["statut"] if r["statut"] is not None else "",
                                    duree, url_aff, msg), tags=tags)
        if fin < len(self.vue):
            self.after(1, lambda: self._inserer_lot(fin, token))

    def _trier(self, col):
        if self._tri_col == col:
            self._tri_sens = not self._tri_sens
        else:
            self._tri_col, self._tri_sens = col, False
        self._rafraichir()

    def _appliquer_tri(self):
        col = self._tri_col

        def cle(r):
            if col == "no":
                return r["no"]
            if col == "statut":
                return r["statut"] if r["statut"] is not None else -1
            if col == "duree":
                return r["duree_ms"] if r["duree_ms"] is not None else -1
            if col == "temps":
                return r["dt"].timestamp() if r["dt"] else -1
            return str(r.get(col, "")).lower()
        self.vue.sort(key=cle, reverse=self._tri_sens)

    # -------------------------------------------------- details + coloration
    def _enreg_par_iid(self, iid):
        try:
            no = int(iid)
        except ValueError:
            return None
        return next((r for r in self.enregistrements if r["no"] == no), None)

    def _inserer_json_colore(self, obj):
        t = self.txt_detail
        texte = json.dumps(obj, indent=2, ensure_ascii=False)
        # Tokenisation simple ligne par ligne pour coloration.
        for ligne in texte.splitlines(keepends=True):
            i = 0
            for m in re.finditer(
                    r'"(?:[^"\\]|\\.)*"(\s*:)?|\b(true|false|null)\b|-?\d+\.?\d*',
                    ligne):
                if m.start() > i:
                    t.insert("end", ligne[i:m.start()], "js_ponct")
                frag = m.group(0)
                if frag.endswith(":") or (m.group(1)):
                    cle = frag.rstrip()
                    if cle.endswith(":"):
                        cle = cle[:-1].rstrip()
                    t.insert("end", cle, "js_cle")
                    t.insert("end", frag[len(cle):], "js_ponct")
                elif m.group(2):
                    t.insert("end", frag, "js_bool")
                elif frag.startswith('"'):
                    t.insert("end", frag, "js_txt")
                else:
                    t.insert("end", frag, "js_num")
                i = m.end()
            if i < len(ligne):
                t.insert("end", ligne[i:], "js_ponct")

    def _on_select(self, event=None):
        sel = self.tab.selection()
        if not sel:
            return
        r = self._enreg_par_iid(sel[0])
        if not r:
            return
        self._courant = r
        t = self.txt_detail
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f"Ligne {r['no']}\n", "titre")
        t.insert("end", "─" * 64 + "\n")
        for lib, val in [("Heure", r["temps"]), ("Application", r["app"]),
                         ("Niveau", r["niveau"]), ("Méthode", r["methode"]),
                         ("Statut", r["statut"]), ("URL", r["url"]),
                         ("Temps d'exéc.", r.get("execution_time")),
                         ("Message", r["message"])]:
            if val not in (None, ""):
                t.insert("end", f"{lib} : ", "cle")
                t.insert("end", f"{val}\n")
        for lib, val in [("Requête (request)", r.get("request")),
                         ("Réponse (response)", r.get("response"))]:
            if val in (None, ""):
                continue
            t.insert("end", f"\n{lib}\n", "titre")
            t.insert("end", "─" * 64 + "\n")
            if isinstance(val, (dict, list)):
                self._inserer_json_colore(val)
                t.insert("end", "\n")
            else:
                t.insert("end", f"{val}\n")
        if r["json"]:
            t.insert("end", "\nJSON formaté\n", "titre")
            t.insert("end", "─" * 64 + "\n")
            self._inserer_json_colore(r["json"])
            t.insert("end", "\n")
        t.insert("end", "\nLigne brute\n", "titre")
        t.insert("end", "─" * 64 + "\n")
        t.insert("end", r["brut"])
        t.config(state="disabled")

    # -------------------------------------------------- copier
    def _copier(self, quoi):
        r = getattr(self, "_courant", None)
        if not r:
            self.lbl_statut.config(text="Sélectionnez une ligne d'abord.")
            return
        if quoi == "brut":
            val = r["brut"]
        elif quoi == "json":
            val = json.dumps(r["json"], indent=2, ensure_ascii=False) if r["json"] else ""
        else:
            v = r.get(quoi)
            val = (json.dumps(v, indent=2, ensure_ascii=False)
                   if isinstance(v, (dict, list)) else (v or ""))
        if not val:
            self.lbl_statut.config(text=f"Rien à copier pour « {quoi} ».")
            return
        self.clipboard_clear()
        self.clipboard_append(val)
        self.lbl_statut.config(text=f"✓ {quoi} copié dans le presse-papier.")

    # -------------------------------------------------- export
    def _exporter(self):
        if not self.vue:
            self.lbl_statut.config(text="Rien à exporter.")
            return
        chemin = filedialog.asksaveasfilename(
            title="Exporter le résultat filtré",
            initialdir=getattr(self, "_dernier_dossier", os.path.expanduser("~")),
            defaultextension=".log", initialfile="export_filtre.log",
            filetypes=[("Log/Texte", "*.log *.txt"), ("JSON Lines", "*.jsonl"),
                       ("CSV", "*.csv")])
        if not chemin:
            return
        colonnes = ("no", "temps", "app", "niveau", "methode", "statut",
                    "duree_ms", "url", "message")
        try:
            if chemin.endswith(".jsonl"):
                with open(chemin, "w", encoding="utf-8") as f:
                    for r in self.vue:
                        f.write(json.dumps({k: r[k] for k in colonnes},
                                           ensure_ascii=False) + "\n")
            elif chemin.endswith(".csv"):
                with open(chemin, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(colonnes)
                    for r in self.vue:
                        w.writerow([r[k] for k in colonnes])
            else:
                with open(chemin, "w", encoding="utf-8") as f:
                    for r in self.vue:
                        f.write(r["brut"] + "\n")
        except Exception as e:  # noqa
            messagebox.showerror("Erreur d'export", str(e))
            return
        self.lbl_statut.config(
            text=f"✓ {len(self.vue)} ligne(s) exportée(s) vers {os.path.basename(chemin)}")

    # -------------------------------------------------- ignore.txt
    def _editer_ignore(self):
        top = self._nouvelle_fenetre("Liste d'exclusion — ignore.txt", "560x520")
        tk.Label(top, text="Un motif par ligne. Les lignes correspondantes ne sont "
                 "pas comptées comme erreurs/avertissements.", bg=COULEURS["fond"],
                 fg=COULEURS["texte_doux"], font=(self.police, 11), wraplength=520,
                 justify="left", anchor="w").pack(fill=tk.X, padx=14, pady=(12, 6))
        txt = tk.Text(top, wrap="word", font=(self.mono, 12), relief="flat",
                      bg=COULEURS["carte"], padx=10, pady=10)
        txt.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)
        txt.insert("1.0", parseur.lire_ignore_brut())
        self._scroller_widget(txt)
        txt.focus_set()
        barre = tk.Frame(top, bg=COULEURS["fond"])
        barre.pack(fill=tk.X, padx=14, pady=10)

        def enregistrer():
            parseur.ecrire_ignore_brut(txt.get("1.0", "end-1c"))
            if self.enregistrements and self.chemin:
                # reparse pour appliquer immediatement les nouvelles exclusions
                for r in self.enregistrements:
                    bas = r["brut"].lower()
                    r["ignore"] = parseur.est_ignoree(bas)
                    r["erreur"] = (not r["ignore"]) and (
                        r["niveau"] in ("ERROR", "FATAL")
                        or (r["statut"] is not None and r["statut"] >= 400)
                        or (not r["niveau"] and bool(parseur.RE_MOTS_ERREUR.search(r["brut"]))))
                    r["avert"] = (not r["ignore"]) and r["niveau"] == "WARN"
                self._maj_sidebar()
                self._rafraichir()
            self.lbl_statut.config(text="✓ ignore.txt enregistré et appliqué.")
            top.destroy()

        ttk.Button(barre, text="Enregistrer", style="Accent.TButton",
                   command=enregistrer).pack(side=tk.RIGHT)
        ttk.Button(barre, text="Annuler", style="Outil.TButton",
                   command=top.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    # -------------------------------------------------- statistiques
    def _ouvrir_stats(self):
        if not self.enregistrements:
            self.lbl_statut.config(text="Ouvrez d'abord un fichier.")
            return
        stats = parseur.calculer_stats(self.enregistrements)
        top = self._nouvelle_fenetre("Statistiques", "720x600")
        txt = tk.Text(top, wrap="word", font=(self.mono, 12), relief="flat",
                      bg=COULEURS["carte"], padx=14, pady=12)
        sb = ttk.Scrollbar(top, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill=tk.BOTH, expand=True)
        self._scroller_widget(txt)
        txt.tag_configure("h", font=(self.mono, 13, "bold"),
                          foreground=COULEURS["primaire"])

        def ms(v):
            return f"{v:.0f} ms" if v is not None else "—"

        txt.insert("end", "VUE D'ENSEMBLE\n", "h")
        txt.insert("end", f"  Lignes totales : {stats['total']}\n")
        txt.insert("end", f"  Erreurs        : {stats['erreurs']}\n")
        txt.insert("end", f"  Avertissements : {stats['avert']}\n")
        txt.insert("end", f"  Appels API     : {stats['api']}\n\n")

        txt.insert("end", "TEMPS DE RÉPONSE (global)\n", "h")
        d = stats["duree_globale"]
        txt.insert("end", f"  Mesurés : {d['n']}   moy {ms(d['moy_ms'])}   "
                   f"p95 {ms(d['p95_ms'])}   max {ms(d['max_ms'])}\n\n")

        txt.insert("end", "STATUTS HTTP\n", "h")
        for cl in sorted(stats["classes_statut"]):
            txt.insert("end", f"  {cl} : {stats['classes_statut'][cl]}\n")
        txt.insert("end", "\nNIVEAUX\n", "h")
        for niv, n in sorted(stats["niveaux"].items(), key=lambda x: -x[1]):
            txt.insert("end", f"  {niv:6s} : {n}\n")

        txt.insert("end", "\nPAR APPLICATION (volume · erreurs · moy · p95)\n", "h")
        for a in stats["apps"][:30]:
            txt.insert("end", f"  {a['app'][:28]:28s}  {a['total']:6d}  "
                       f"err {a['erreurs']:4d}  moy {ms(a['moy_ms']):>8s}  "
                       f"p95 {ms(a['p95_ms']):>8s}\n")

        # timeline texte
        tranches, debut, fin = parseur.timeline(self.enregistrements, buckets=40)
        if tranches:
            txt.insert("end", "\nTIMELINE  (volume ▇ · erreurs en rouge)\n", "h")
            txt.insert("end", f"  de {debut}  à  {fin}\n")
            maxi = max((t["total"] for t in tranches), default=1) or 1
            for t in tranches:
                if t["total"] == 0:
                    continue
                barres = int(t["total"] / maxi * 40)
                txt.insert("end", f"  {t['label']}  ")
                txt.insert("end", "▇" * barres)
                txt.insert("end", f"  {t['total']}")
                if t["erreurs"]:
                    txt.insert("end", f"  (err {t['erreurs']})\n", "")
                else:
                    txt.insert("end", "\n")

        barre = tk.Frame(top, bg=COULEURS["fond"])
        barre.pack(fill=tk.X, padx=14, pady=8)
        ttk.Button(barre, text="Exporter le résumé…", style="Outil.TButton",
                   command=lambda: self._exporter_resume(txt.get("1.0", "end-1c"))
                   ).pack(side=tk.RIGHT)
        txt.config(state="disabled")

    def _exporter_resume(self, contenu):
        chemin = filedialog.asksaveasfilename(
            title="Exporter le résumé", defaultextension=".txt",
            initialfile="resume_stats.txt", filetypes=[("Texte", "*.txt")])
        if not chemin:
            return
        try:
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(contenu)
            self.lbl_statut.config(text=f"✓ Résumé exporté ({os.path.basename(chemin)}).")
        except OSError as e:
            messagebox.showerror("Erreur", str(e))

    # -------------------------------------------------- erreurs groupées
    def _ouvrir_groupes(self):
        if not self.enregistrements:
            self.lbl_statut.config(text="Ouvrez d'abord un fichier.")
            return
        groupes = parseur.grouper_erreurs(self.enregistrements, limite=200)
        top = self._nouvelle_fenetre("Erreurs regroupées", "860x560")
        tk.Label(top, text=f"{len(groupes)} type(s) d'erreur distinct(s) — "
                 "double-clic pour filtrer le tableau principal.",
                 bg=COULEURS["fond"], fg=COULEURS["texte_doux"],
                 font=(self.police, 11), anchor="w").pack(fill=tk.X, padx=12, pady=8)
        cols = ("compte", "exemple")
        tv = ttk.Treeview(top, columns=cols, show="headings")
        tv.heading("compte", text="Nb")
        tv.heading("exemple", text="Exemple de message")
        tv.column("compte", width=70, anchor="center", stretch=False)
        tv.column("exemple", width=760, anchor="w")
        sb = ttk.Scrollbar(top, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self._scroller_widget(tv)
        for i, g in enumerate(groupes):
            ex = (g["exemple"] or "").replace("\n", " ")[:160]
            tv.insert("", "end", iid=str(i), values=(g["compte"], ex))

        def ouvrir_groupe(_e=None):
            sel = tv.selection()
            if not sel:
                return
            g = groupes[int(sel[0])]
            self.categorie = "erreurs"
            self.var_regex.set(False)
            self.var_rech.set(g["exemple"][:40] if g["exemple"] else "")
            self._rafraichir()
            top.lift()
        tv.bind("<Double-1>", ouvrir_groupe)

    # -------------------------------------------------- fermeture
    def _quitter(self):
        self._chargement_actif = False
        self.cfg["geometrie"] = self.geometry()
        self.cfg["recents"] = self.recents
        self.cfg["dossier"] = getattr(self, "_dernier_dossier", "")
        sauver_config(self.cfg)
        
        # Nettoyer les processus SSH orphelins
        try:
            import subprocess
            if sys.platform == "win32":
                # Windows: tuer plink/pscp restants
                subprocess.run(["taskkill", "/F", "/IM", "plink.exe"], 
                             capture_output=True, timeout=2)
                subprocess.run(["taskkill", "/F", "/IM", "pscp.exe"], 
                             capture_output=True, timeout=2)
            else:
                # Unix/macOS: tuer ssh restants
                subprocess.run(["pkill", "-f", "ssh|plink|pscp"], 
                             capture_output=True, timeout=2)
        except Exception:
            pass  # Non critique
        
        self.destroy()

if __name__ == "__main__":
    try:
        app = AnalyseurApp()
        
        # Workaround PyInstaller + macOS Tkinter: utiliser update loop au lieu de mainloop
        if getattr(sys, 'frozen', False):
            while True:
                try:
                    app.update()
                except tk.TclError:
                    break
                except KeyboardInterrupt:
                    break
        else:
            app.mainloop()
            
    except Exception as e:
        if _logger:
            _logger.exception(f"Exception: {e}")
        raise
