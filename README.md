# Gestionale Clienti - HR&O Consulting

Applicazione locale per la gestione dei clienti: pipeline commerciale, storico
attivita', promemoria di richiamo, fatturato per cliente e bozze email.

## Come funziona

E' un programma che gira sul tuo PC (nessun dato va su internet): apre un
server locale e lo mostra nel tuo browser. All'avvio appare un'icona nella
system tray (vicino all'orologio di Windows) da cui puoi riaprire l'app o
uscire. Ogni 30 minuti controlla se ci sono clienti da richiamare e, se si',
mostra una notifica di Windows.

I tuoi dati vengono salvati in:
`%APPDATA%\GestionaleClientiHRO\hroconsulting.db`

Questo file non viene mai sovrascritto dagli aggiornamenti dell'app: anche
installando una versione piu' recente, la tua cronologia resta intatta.

## Dati iniziali

Il programma arriva gia' precaricato con lo storico importato dai tuoi file
("Commerciale in azione" e lo storico fatturato): clienti acquisiti, contatti
in trattativa, il database di lead per regione e il fatturato storico per
cliente collegato dove possibile.

## Struttura del progetto

- `app.py` - applicazione Flask (pagine, logica)
- `db.py` - gestione del database SQLite
- `import_data.py` - script di importazione dati (usato una volta, gia' eseguito)
- `tray.py` - icona nella system tray e notifiche
- `templates/`, `static/` - interfaccia
- `data/hroconsulting.db` - database iniziale precaricato (bundlato nell'exe)
- `gestionale.spec` - istruzioni di compilazione per PyInstaller
- `build.bat` - compila l'exe in locale (alternativa a GitHub Actions)
- `.github/workflows/build-windows.yml` - compila l'exe automaticamente su GitHub

## Sviluppo / test (Linux o Windows con Python)

```
pip install -r requirements.txt
python3 app.py --no-browser   # per lo sviluppo: niente tray, niente auto-apertura browser
```
