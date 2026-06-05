#!/bin/bash
# Script d'installation macOS pour Analyseur de fichiers .log
# Usage: bash install-macos.sh
# 
# Ce script :
# 1. Détecte si l'archive est zippée ou le dossier .app est déjà présent
# 2. Dézipe si nécessaire
# 3. Retire la quarantaine Gatekeeper
# 4. Signe l'application
# 5. Copie dans /Applications
# 6. Lance l'app

set -e

echo "🔧 Installation Analyseur de fichiers .log"
echo "=========================================="
echo ""

# Détecter l'archive .zip ou le .app
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZIP_FILE=$(find "$SCRIPT_DIR" -maxdepth 1 -name "AnalyseurLog-macos.zip" -o -name "AnalyseurLog*.zip" 2>/dev/null | head -1)
APP_BUNDLE="$SCRIPT_DIR/AnalyseurLog.app"

# Si archive ZIP, la déziper
if [ -n "$ZIP_FILE" ]; then
    echo "📦 Archive détectée: $(basename "$ZIP_FILE")"
    echo "📂 Décompression..."
    unzip -q "$ZIP_FILE" -d "$SCRIPT_DIR"
    echo "✓ Décompression terminée"
fi

# Vérifier que l'app existe
if [ ! -d "$APP_BUNDLE" ]; then
    echo "❌ Erreur: AnalyseurLog.app non trouvé"
    echo "Assure-toi que :"
    echo "  - Le .zip est dans le même dossier que ce script, OU"
    echo "  - Le dossier AnalyseurLog.app est présent"
    exit 1
fi

echo ""
echo "📍 Application: $APP_BUNDLE"

# Retirer l'attribut de quarantaine
echo "🔓 Retrait de la quarantaine Gatekeeper..."
xattr -rd com.apple.quarantine "$APP_BUNDLE" 2>/dev/null || true

# Re-signer ad-hoc
echo "✍️  Signature de l'application..."
codesign -s - "$APP_BUNDLE" --deep --force 2>/dev/null || {
    echo "⚠️  Signature échouée (non critique)"
}

# Copier dans /Applications
echo "📁 Copie dans /Applications..."
if [ -e /Applications/AnalyseurLog.app ]; then
    echo "   (remplacement de la version existante)"
    rm -rf /Applications/AnalyseurLog.app
fi
cp -r "$APP_BUNDLE" /Applications/

# Signer la version installée
xattr -rd com.apple.quarantine /Applications/AnalyseurLog.app 2>/dev/null || true
codesign -s - /Applications/AnalyseurLog.app --deep --force 2>/dev/null || true

echo ""
echo "✅ Installation terminée!"
echo ""
echo "📍 Localisation: /Applications/AnalyseurLog.app"
echo "🚀 Lancement..."
sleep 1
open /Applications/AnalyseurLog.app

exit 0
