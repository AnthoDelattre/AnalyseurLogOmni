# Analyseur de fichiers .log

Application Tkinter pour analyser, filtrer et regrouper les erreurs dans les fichiers `.log`.

**Fonctionnalités :**
- Parsing robuste de JSON imbriqué
- Filtres (catégorie, niveau, statut HTTP, plages horaires)
- Recherche texte/regex avancée
- Regroupement automatique des erreurs
- Export CSV/JSON/JSONL
- **Récupération de logs distants via bastion SSH ADEO** (macOS/Linux et Windows avec PuTTY)
- Persistance (géométrie, fichiers récents, configuration)

## Installation et lancement

### 🍎 macOS

#### Méthode 1 : Script automatique (recommandé)
```bash
bash install-macos.sh
```

Le script :
- ✅ Dézipe l'archive si nécessaire
- ✅ Retire l'attribut de quarantaine Gatekeeper
- ✅ Signe l'application
- ✅ Place l'app dans `/Applications/`
- ✅ Lance l'application

**C'est tout !** L'app se lancera immédiatement.

#### Méthode 2 : Manuel (si le script ne fonctionne pas)
```bash
# Déziper l'archive
unzip AnalyseurLog-macos.zip

# Retirer la quarantaine
xattr -rd com.apple.quarantine AnalyseurLog.app

# Signer
codesign -s - AnalyseurLog.app --deep --force

# Copier dans Applications
cp -r AnalyseurLog.app /Applications/

# Lancer
open /Applications/AnalyseurLog.app
```

#### Dépannage macOS
- **« Application potentiellement malveillante »** → Utilise la Méthode 1 (script)
- **Icône verrouillée** → Essaie à nouveau le script ou la Méthode 2

### 🪟 Windows

#### Méthode simple
1. **Télécharge** `AnalyseurLog.exe`
2. **Double-clic** sur le fichier
3. Si une fenêtre « Windows Defender SmartScreen » apparaît :
   - Clique **« Infos supplémentaires »**
   - Clique **« Exécuter quand même »**
4. L'application se lance

**C'est tout !** L'app s'ouvrira une fois SmartScreen acceptée.

#### Avec script (optionnel)
```cmd
run-windows.bat
```

#### Dépannage Windows
- **SmartScreen bloque l'app** → Clic sur « Infos supplémentaires » puis « Exécuter quand même »
- **SSH bastion ne fonctionne pas** → PuTTY est déjà embarqué dans l'exécutable (aucune action requise)

### 🐧 Linux

```bash
chmod +x AnalyseurLog-linux
./AnalyseurLog-linux
```

---

## Utilisation

### Ouverture d'un fichier .log
1. Clique sur **📁** (ouvrir un fichier)
2. Sélectionne un `.log` local

### Récupération de logs distants (bastion ADEO)
1. Clique sur **🔐 SSH**
2. Remplis les champs :
   - **Caisse** : numéro de caisse
   - **Magasin** : numéro de magasin
   - **Date** : AAAA-MM-JJ (optionnel, défaut = aujourd'hui)
   - **LDAP** : identifiant LDAP (ex: `10100168`)
   - **Mot de passe** : ton mot de passe bastion
3. L'app télécharge automatiquement les logs
4. Sélectionne dans le menu **📁**

### Filtres
- **Catégorie** : tout, erreurs, avertissements, info
- **Niveaux** : FATAL, ERROR, WARN, INFO, DEBUG, TRACE
- **Statut HTTP** : 2xx, 3xx, 4xx, 5xx
- **Applications** : multi-sélection
- **Plage horaire** : HH:MM - HH:MM
- **Recherche** : texte libre ou regex

### Statistiques et Export
- **📊 Tableau** : visualisation des logs filtrés
- **💾 Exporter** : télécharge en CSV, JSON ou JSONL

---

## Configuration

L'app mémorise :
- Géométrie de la fenêtre
- Dernier dossier utilisé
- Fichiers récents
- Configuration SSH (sauf mot de passe)

Ces données sont sauvegardées dans `~/.analyseur_config.json`.

---

## Support et issues

- **Repository** : https://github.com/AnthoDelattre/AnalyseurLogOmni
- **Problèmes ?** Crée une issue sur GitHub

---

## Licence

Interne Leroy Merlin

