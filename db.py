"""Gestione del database SQLite per il gestionale clienti."""
import sqlite3
import os
import shutil
import sys
from datetime import datetime


def _cartella_dati_utente():
    """Cartella persistente per i dati dell'utente (sopravvive agli aggiornamenti
    dell'app). Su Windows: %APPDATA%\\GestionaleClientiHRO."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    cartella = os.path.join(base, "GestionaleClientiHRO")
    os.makedirs(cartella, exist_ok=True)
    return cartella


def _percorso_risorsa(relativo):
    """Percorso di una risorsa in sola lettura inclusa nel pacchetto: dentro
    l'exe PyInstaller (sys._MEIPASS) oppure nella cartella del progetto in
    fase di sviluppo."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relativo)


DB_PATH = os.path.join(_cartella_dati_utente(), "hroconsulting.db")
DB_INIZIALE = _percorso_risorsa(os.path.join("data", "hroconsulting.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS clienti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_azienda TEXT NOT NULL,
    titolo TEXT,
    referente TEXT,
    email TEXT,
    telefono TEXT,
    regione TEXT,
    canale TEXT,
    stato TEXT NOT NULL DEFAULT 'da_contattare',
    data_primo_contatto TEXT,
    prossima_azione TEXT,
    prossima_azione_data TEXT,
    note TEXT,
    creato_il TEXT NOT NULL,
    aggiornato_il TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attivita (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
    data TEXT,
    tipo TEXT,
    descrizione TEXT,
    creato_il TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fatturato (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clienti(id) ON DELETE CASCADE,
    data TEXT,
    anno INTEGER,
    descrizione TEXT,
    importo REAL NOT NULL DEFAULT 0,
    fattura_numero TEXT,
    pagato TEXT,
    creato_il TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prospect (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_azienda TEXT,
    settore TEXT,
    forma_giuridica TEXT,
    indirizzo TEXT,
    cap TEXT,
    comune TEXT,
    regione TEXT,
    n_dipendenti TEXT,
    telefono TEXT,
    email TEXT,
    creato_il TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clienti_stato ON clienti(stato);
CREATE INDEX IF NOT EXISTS idx_clienti_prossima ON clienti(prossima_azione_data);
CREATE INDEX IF NOT EXISTS idx_attivita_cliente ON attivita(cliente_id);
CREATE INDEX IF NOT EXISTS idx_fatturato_cliente ON fatturato(cliente_id);
CREATE INDEX IF NOT EXISTS idx_prospect_regione ON prospect(regione);
"""


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if not os.path.exists(DB_PATH) and os.path.exists(DB_INIZIALE):
        # Primo avvio: copia il database iniziale (con lo storico importato)
        # nella cartella dati persistente dell'utente.
        shutil.copy(DB_INIZIALE, DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    init_db()
    print(f"Database inizializzato in {DB_PATH}")
