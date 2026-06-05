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

## Installation

### macOS

#### Option 1 : Script automatique (recommandé)
```bash
# Dézippe l'archive si ce n'est pas fait
unzip AnalyseurLog-macos.zip

# Lance le script d'installation
bash install-macos.sh
```

Le script :
- Retire l'attribut de quarantaine Gatekeeper
- Signe l'application
- Place l'app dans `/Applications/`
- Lance l'application

#### Option 2 : Manuel (si le script ne fonctionne pas)
```bash
# Dézippe
unzip AnalyseurLog-macos.zip

# Retire la quarantaine
xattr -rd com.apple.quarantine AnalyseurLog.app

# Signe
codesign -s - AnalyseurLog.app --deep --force

# Copie dans Applications
cp -r AnalyseurLog.app /Applications/

# Lance
open /Applications/AnalyseurLog.app
```

### Windows

Télécharge `AnalyseurLog-windows.exe` et double-clic pour lancer.

**Note :** Au premier lancement, SmartScreen peut afficher un avertissement → clique « Exécuter quand même ».

**Dépendance optionnelle (SSH bastion) :**
Si tu veux utiliser la fonctionnalité SSH pour récupérer des logs du bastion ADEO, installe [PuTTY](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html). L'exécutable Windows a PuTTY déjà embarqué.

### Linux

```bash
chmod +x AnalyseurLog-linux
./AnalyseurLog-linux
```

## Utilisation

### Ouverture d'un fichier .log
1. Clique sur **📁** (ouvrir un fichier)
2. Sélectionne un `.log` local ou un fichier texte

### Récupération de logs distants (bastion ADEO)
1. Clique sur **🔐 SSH**
2. Remplis : Caisse, Magasin, Date (optionnel), LDAP, Mot de passe
3. L'app télécharge automatiquement les logs depuis `APP_LOG`
4. Sélectionne dans le menu **📁**

### Filtres
- **Catégorie** : tout, erreurs, avertissements, info
- **Niveaux** : FATAL, ERROR, WARN, INFO, DEBUG, TRACE
- **Statut HTTP** : 2xx, 3xx, 4xx, 5xx
- **Applications** : multi-sélection
- **Plage horaire** : HH:MM - HH:MM
- **Recherche** : texte libre ou regex

### Export
- **📊 Stats** : résumé des volumes et temps de réponse
- **🚫 Groupes** : erreurs regroupées par similarité
- **💾 Exporter** : CSV ou JSON

## Dépannage

### « Application potentiellement malveillante » (macOS)
→ Utilise le script `install-macos.sh` (voir Installation → macOS → Option 1)

### SSH bloqué (Windows)
→ Assure-toi d'avoir installé PuTTY. L'app contient déjà plink.exe/pscp.exe.

### Performance lente sur gros fichiers
→ L'app charge le fichier de manière asynchrone. Laisse-le finir le parsing avant de filtrer.

## Source

- **Repository** : https://github.com/AnthoDelattre/AnalyseurLogOmni
- **License** : MIT (interne Leroy Merlin)

---

Questions ? Crée une issue sur le repo GitHub.
