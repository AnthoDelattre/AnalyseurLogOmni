# Guide de distribution - Analyseur de fichiers .log

## Pour les utilisateurs finaux

### macOS
1. Télécharge **`AnalyseurLog-macos.zip`** depuis [GitHub Releases](https://github.com/AnthoDelattre/AnalyseurLogOmni/releases)
2. Dézipe l'archive (ou double-clic)
3. Lance le script : `bash install-macos.sh`
4. **C'est tout !** L'app s'ouvre dans `/Applications/`

### Windows
1. Télécharge **`AnalyseurLog-windows.exe`** depuis [GitHub Releases](https://github.com/AnthoDelattre/AnalyseurLogOmni/releases)
2. Double-clic sur l'exécutable
3. Si SmartScreen bloque : clic « Infos supplémentaires » → « Exécuter quand même »
4. **C'est tout !** L'app se lance

### Linux
1. Télécharge **`AnalyseurLog-linux`** depuis [GitHub Releases](https://github.com/AnthoDelattre/AnalyseurLogOmni/releases)
2. Lance : `./AnalyseurLog-linux`

---

## Pour les développeurs / mainteneurs

### Processus de release

1. **Faire les changements** sur la branche `main`
2. **Committer** : `git commit -m "message"`
3. **Tagger** : `git tag v1.x` (ex: `v1.5`)
4. **Pousser** : `git push && git push origin v1.x`

La CI (GitHub Actions) :
- ✅ Lance les tests
- ✅ Build Windows/macOS/Linux
- ✅ Télécharge PuTTY pour Windows
- ✅ Signe ad-hoc sur macOS
- ✅ Zippe correctement le `.app` macOS
- ✅ Crée les artefacts

### Tests avant release

```bash
# Tests unitaires
python3 -m unittest test_parseur -v

# Build local macOS
.venv_build/bin/pyinstaller --noconfirm --clean AnalyseurLog.spec
open dist/AnalyseurLog.app

# Simuler l'installation
bash install-macos.sh  # depuis le dossier dist/
```

### Architecture

- **parseur.py** : core (parsing, analytics, SSH)
- **analyseur.py** : UI Tkinter
- **test_parseur.py** : 19 tests unitaires
- **AnalyseurLog.spec** : config PyInstaller (multi-OS)
- **.github/workflows/build.yml** : CI/CD

### Points sensibles

#### macOS
- ✅ Signature ad-hoc pour éviter Gatekeeper
- ✅ Update loop au lieu de mainloop() (PyInstaller workaround)
- ✅ Ditto pour zipper correctement la structure `.app`

#### Windows
- ✅ plink.exe/pscp.exe embarqués (téléchargés par CI)
- ✅ Backend subprocess avec lecteur de réponses (stdin)
- ✅ Pas de pty (Windows spécifique)

#### SSH Bastion (macOS/Linux)
- ✅ Backend pty (Unix natif)
- ✅ Double quoting pour 2 shells (bastion + hôte interne)
- ✅ Max 3 tentatives de mot de passe (bastion + sshclient + rebond)

#### SSH Bastion (Windows)
- ✅ Backend plink avec stdin (pas de pty)
- ✅ Détection des prompts "Password:" et "(y/n)"
- ✅ Injection automatique des réponses

### Fichiers de distribution

Les artefacts GitHub Actions produisent :
- `AnalyseurLog-macos` → ZIP contenant le `.app` signé
- `AnalyseurLog-windows` → EXE standalone avec plink/pscp embarqués
- `AnalyseurLog-linux` → Binaire autonome

---

## Checklist de release

- [ ] Tous les tests passent (`python3 -m unittest test_parseur`)
- [ ] README.md à jour
- [ ] Version bumped dans `git tag`
- [ ] `git push` + `git push origin tag`
- [ ] Attendre CI (~5 min)
- [ ] Vérifier les artefacts sur Actions
- [ ] Créer une GitHub Release avec notes

---

## Limitations connues

### macOS
- App non signée par un certificat Apple (pas de 99€/an dépensés)
- Gatekeeper bloque au 1er lancement → script `install-macos.sh` ou manuel workaround

### Windows
- SmartScreen affiche avertissement (non signé)
- SSH requiert PuTTY (embarqué, donc pas d'installation supplémentaire)

### Tous OS
- Performance : parsing asynchrone, mais gros fichiers (>100MB) peuvent être lents
- Pas de signature de code officielle (distribution interne uniquement)

---

## Support

- Repository : https://github.com/AnthoDelattre/AnalyseurLogOmni
- Issues : Crée une GitHub issue
- Contact : anthony.delattre@leroymerlin.fr (interne)
