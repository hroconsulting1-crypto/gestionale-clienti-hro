@echo off
REM Compila il gestionale in un unico file gestionale-clienti.exe (Windows).
REM Richiede Python 3 installato (https://www.python.org/downloads/ - durante
REM l'installazione spunta "Add python.exe to PATH").

echo ============================================
echo  Creazione di gestionale-clienti.exe
echo ============================================

python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato. Installalo da python.org e riprova.
    pause
    exit /b 1
)

echo Installazione delle dipendenze necessarie...
pip install -r requirements.txt

echo Compilazione in corso (puo' richiedere qualche minuto)...
pyinstaller gestionale.spec --noconfirm

if exist dist\gestionale-clienti.exe (
    echo.
    echo Fatto! Trovi il programma in: dist\gestionale-clienti.exe
    echo Puoi copiarlo dove preferisci e lanciarlo con un doppio click.
) else (
    echo.
    echo Qualcosa e' andato storto durante la compilazione. Controlla i messaggi sopra.
)

pause
