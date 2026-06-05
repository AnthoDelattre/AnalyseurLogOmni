@echo off
REM Script d'installation Windows pour Analyseur de fichiers .log
REM Usage: run-windows.bat
REM
REM Ce script:
REM 1. Lance l'executable AnalyseurLog.exe
REM 2. Affiche les instructions en cas de blocage SmartScreen

setlocal enabledelayedexpansion

echo.
echo ==========================================
echo   Installation Analyseur de fichiers .log
echo ==========================================
echo.

REM Chercher l'exe dans le dossier courant
for %%I in (*.exe) do (
    if "%%I"=="AnalyseurLog.exe" (
        set EXE_PATH=%%I
        goto found
    )
)

echo Erreur: AnalyseurLog.exe non trouve dans ce dossier
echo Assure-toi d'avoir telecharge et place le fichier correctement
pause
exit /b 1

:found
echo [OK] Application trouvee: !EXE_PATH!
echo.
echo Lancement de l'application...
echo.

REM Tenter de lancer l'exe
start "" "!EXE_PATH!"

REM Afficher les instructions
echo.
echo Si une fenetre "Windows Defender SmartScreen" apparait:
echo   1. Clique "Infos supplementaires"
echo   2. Clique "Executer quand meme"
echo.
echo L'application s'ouvrira ensuite normalement.
echo.
pause

exit /b 0
