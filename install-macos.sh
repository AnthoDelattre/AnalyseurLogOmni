#!/bin/bash
# Script d'installation macOS pour Analyseur de fichiers .log
# Usage: bash install-macos.sh

set -e

echo "🔧 Installation Analyseur de fichiers .log"
echo "=========================================="

# Detecter où le script est lancé
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BUNDLE="$SCRIPT_DIR/AnalyseurLog.app"

if [ ! -d "$APP_BUNDLE" ]; then
    echo "❌ Erreur: AnalyseurLog.app non trouvé dans $SCRIPT_DIR"
    echo "Assure-toi que ce script est au même niveau que AnalyseurLog.app"
    exit 1
fi

echo "📦 Application trouvée: $APP_BUNDLE"

# Retirer l'attribut de quarantaine
echo "🔓 Retrait de la quarantaine macOS..."
xattr -rd com.apple.quarantine "$APP_BUNDLE" 2>/dev/null || true

# Re-signer
echo "✍️  Signature ad-hoc..."
codesign -s - "$APP_BUNDLE" --deep --force 2>/dev/null || true

# Copier dans /Applications
echo "📁 Copie dans /Applications..."
cp -r "$APP_BUNDLE" /Applications/AnalyseurLog.app

# Retirer la quarantaine sur la version installée
xattr -rd com.apple.quarantine /Applications/AnalyseurLog.app 2>/dev/null || true

# Re-signer la version installée
codesign -s - /Applications/AnalyseurLog.app --deep --force 2>/dev/null || true

echo ""
echo "✅ Installation terminée!"
echo "🚀 Lancement de l'application..."
open /Applications/AnalyseurLog.app

exit 0
