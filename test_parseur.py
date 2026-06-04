#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests unitaires du parseur (stdlib unittest). Lancement : python3 -m unittest -v
ou simplement : python3 test_parseur.py
"""

import json
import unittest
from datetime import datetime

import parseur


class TestParseLigne(unittest.TestCase):
    def test_message_imbrique_priorite(self):
        """app_name/http_code doivent venir de message.* pas du service racine."""
        ligne = json.dumps({
            "service": "omnistore-frlm-pos",
            "level": "INFO",
            "log_timestamp": "2026-06-03 18:32:24.791",
            "message": {
                "app_name": "api-quotation",
                "request": json.dumps({"method": "POST"}),
                "http_code": 200,
                "response": json.dumps({"ok": True}),
                "url": "https://h/api-quotation/v1/quote",
                "execution_time": "123ms",
            },
        })
        r = parseur.parser_ligne(1, ligne)
        self.assertEqual(r["app"], "api-quotation")
        self.assertEqual(r["statut"], 200)
        self.assertEqual(r["niveau"], "INFO")
        self.assertEqual(r["url"], "https://h/api-quotation/v1/quote")
        self.assertEqual(r["duree_ms"], 123.0)
        self.assertIsInstance(r["request"], dict)
        self.assertIsInstance(r["response"], dict)
        self.assertFalse(r["erreur"])

    def test_message_dict_python(self):
        """Dict style Python (quotes simples) doit aussi etre detecte via regex."""
        ligne = "2026-06-03 INFO {'app_name': 'svc-x', 'http_code': 503}"
        r = parseur.parser_ligne(2, ligne)
        self.assertEqual(r["app"], "svc-x")
        self.assertEqual(r["statut"], 503)
        self.assertTrue(r["erreur"])  # 5xx

    def test_niveaux_normalises(self):
        for brut, attendu in [("CRITICAL boom", "FATAL"), ("WARNING x", "WARN"),
                              ("err: nope", "ERROR")]:
            self.assertEqual(parseur.parser_ligne(1, brut)["niveau"], attendu)

    def test_statut_fleche_et_acces(self):
        self.assertEqual(parseur.parser_ligne(1, "handled -> 200 ok")["statut"], 200)
        self.assertEqual(parseur.parser_ligne(1, 'GET /x" 404 12')["statut"], 404)

    def test_url_et_methode(self):
        r = parseur.parser_ligne(1, 'POST https://api/x/y?z=1 done')
        self.assertEqual(r["methode"], "POST")
        self.assertTrue(r["url"].startswith("https://api/x/y"))

    def test_erreur_par_mot_cle(self):
        self.assertTrue(parseur.parser_ligne(1, "NullPointerException traceback")["erreur"])

    def test_duree_unites(self):
        self.assertEqual(parseur.parse_duree_ms("1.5s"), 1500.0)
        self.assertEqual(parseur.parse_duree_ms("250ms"), 250.0)
        self.assertEqual(parseur.parse_duree_ms(42), 42.0)
        self.assertIsNone(parseur.parse_duree_ms(None))

    def test_parse_temps(self):
        self.assertEqual(parseur.parse_temps("2026-06-03 18:32:24.791"),
                         datetime(2026, 6, 3, 18, 32, 24, 791000))
        self.assertEqual(parseur.parse_temps("2026-06-03T18:32:24"),
                         datetime(2026, 6, 3, 18, 32, 24))
        self.assertIsNone(parseur.parse_temps("pas une date"))


class TestAnalytique(unittest.TestCase):
    def _jeu(self):
        lignes = [
            json.dumps({"level": "INFO", "log_timestamp": "2026-06-03 10:00:00",
                        "message": {"app_name": "a", "http_code": 200,
                                    "execution_time": "100ms"}}),
            json.dumps({"level": "ERROR", "log_timestamp": "2026-06-03 10:01:00",
                        "message": {"app_name": "a", "http_code": 500,
                                    "execution_time": "300ms"}}),
            json.dumps({"level": "INFO", "log_timestamp": "2026-06-03 10:02:00",
                        "message": {"app_name": "b", "http_code": 404}}),
        ]
        return [parseur.parser_ligne(i, l) for i, l in enumerate(lignes, 1)]

    def test_stats(self):
        s = parseur.calculer_stats(self._jeu())
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["erreurs"], 2)  # 500 + 404
        self.assertEqual(s["classes_statut"], {"2xx": 1, "4xx": 1, "5xx": 1})
        app_a = next(a for a in s["apps"] if a["app"] == "a")
        self.assertEqual(app_a["total"], 2)
        self.assertEqual(app_a["moy_ms"], 200.0)

    def test_grouper_erreurs(self):
        regs = self._jeu()
        groupes = parseur.grouper_erreurs(regs)
        self.assertTrue(len(groupes) >= 1)
        self.assertTrue(all("compte" in g for g in groupes))

    def test_timeline(self):
        tranches, debut, fin = parseur.timeline(self._jeu(), buckets=10)
        self.assertTrue(tranches)
        self.assertEqual(debut, datetime(2026, 6, 3, 10, 0, 0))
        self.assertEqual(sum(t["total"] for t in tranches), 3)

    def test_signature_erreur(self):
        s1 = parseur.signature_erreur("user 123 not found at 0xAB")
        s2 = parseur.signature_erreur("user 999 not found at 0xCD")
        self.assertEqual(s1, s2)


class TestSSH(unittest.TestCase):
    def test_interpreter_permission(self):
        msg = parseur._interpreter_erreur_ssh("scp: Permission denied (password).", 1)
        self.assertIn("Authentification refusée", msg)

    def test_interpreter_hote(self):
        msg = parseur._interpreter_erreur_ssh(
            "ssh: Could not resolve hostname srv: nodename nor servname provided", 255)
        self.assertIn("Hôte introuvable", msg)

    def test_interpreter_fichier(self):
        msg = parseur._interpreter_erreur_ssh("scp: /var/log/x.log: No such file", 1)
        self.assertIn("introuvable", msg.lower())

    def test_telecharger_sans_champs(self):
        with self.assertRaises(parseur.ErreurSSH):
            parseur.telecharger_scp("", "", "", "/tmp/x", "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
