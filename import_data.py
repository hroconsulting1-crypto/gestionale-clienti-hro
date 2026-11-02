"""
Script di importazione dati storici nel gestionale.

Importa:
1. Il foglio "Commerciale HRO 2023/2024/2025/2026" (+ "Commerciale 2023") dal file
   principale -> tabella clienti + attivita (storico).
   - Le aziende nelle prime 40 righe del foglio "Commerciale HRO 2026" sono
     clienti ACQUISITI (confermato da Piero).
   - Tutte le altre aziende presenti nei fogli commerciali (comprese quelle di
     altre regioni) sono IN TRATTATIVA (contattate ma non ancora clienti).
2. I fogli regionali (FRIULI, VENETO, EMILIA ROMAGNA, LIGURIA, LOMBARDIA,
   PIEMONTE, ALTO ADIGE, TRENTINO, VALLE D'AOSTA) -> tabella prospect (lead
   freddi, mai contattati). Non diventano clienti automaticamente: nell'app si
   possono "promuovere" a contatto quando si decide di chiamarli.
3. Il file storico di fatturato (per anno, 2005-2027) -> tabella fatturato,
   collegato per nome azienda ai clienti importati al punto 1. Ogni riga di
   fatturato diventa anche una voce nello storico attivita (cosa e' stato
   fatto, quando, per quanto).

Uso:
    python3 import_data.py <file_commerciale.txt> <file_fatturato.txt>
"""
import csv
import io
import re
import sys
from collections import defaultdict

from db import get_connection, init_db, now

REGIONAL_SHEETS = [
    "FRIULI", "VENETO", "EMILIA ROMAGNA", "LIGURIA", "LOMBARDIA",
    "PIEMONTE", "ALTO ADIGE", "TRENTINO", "VALLE D'AOSTA",
]

COMMERCIAL_SHEETS = [
    "Commerciale HRO 2026", "Commerciale HRO 2025", "Commerciale HRO 2024",
    "Commerciale 2023", "Commerciale HRO 2023",
]

ACQUISITO_SHEET = "Commerciale HRO 2026"
ACQUISITO_MAX_ROW = 40  # riga del foglio Google (1 = intestazione) confermata da Piero

# "Commerciale 2023" e "Commerciale HRO 2023" hanno una struttura di colonne
# completamente diversa (2 righe di intestazione, azienda in colonna 5, stato
# esplicito in colonna 0) rispetto ai fogli HRO 2024/2025/2026.
SHEETS_FORMATO_ALTERNATIVO = {"Commerciale 2023", "Commerciale HRO 2023"}

TIPO_TO_STATO = {
    "da contattare": "da_contattare",
    "contattare": "da_contattare",
    "in trattativa": "in_trattativa",
    "primo contatto": "in_trattativa",
    "nuovo": "in_trattativa",
    "vecchio": "in_trattativa",
    "": "in_trattativa",
}

ENTE_INVALIDI = {
    "totale", "totali", "parziale", "parziali", "recuperati", "recuperare",
    "netto", "ritenuta", "imponibile", "iva", "spesa", "budget", "ricavi",
    "costi", "utile", "ente", "fornitore", "cliente",
}

LEGAL_SUFFIXES = [
    r"\bS\.?P\.?A\.?\b", r"\bS\.?R\.?L\.?\b", r"\bS\.?N\.?C\.?\b", r"\bS\.?A\.?S\.?\b",
    r"\bSOC\.?\s*COOP\.?\b", r"\bSOCIETA\s*COOPERATIVA\b", r"\bIN\s*LIQUIDAZIONE\b",
    r"\bGROUP\b", r"\bGRUPPO\b", r"\bHOLDING\b", r"\bITALIA\b", r"\bITALY\b",
]


def normalize_name(name):
    if not name:
        return ""
    s = name.upper()
    s = s.replace("&", " E ")
    s = re.sub(r"[^\w\s]", " ", s)
    for suf in LEGAL_SUFFIXES:
        s = re.sub(suf, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_italian_currency(s):
    if not s:
        return None
    s = s.strip()
    if not s or s in ("-", "€  -", "€ -"):
        return None
    neg = s.startswith("-") or "-€" in s or s.startswith("-")
    s = s.replace("€", "").replace("EUR", "").strip()
    s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^\d\.\-]", "", s)
    if not s or s == "-":
        return None
    try:
        val = float(s)
        return val
    except ValueError:
        return None


def split_sheets(path):
    """Divide il file di testo esportato in blocchi per nome foglio."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    parts = re.split(r"^## Sheet name:\s*(.+?)\s*$", content, flags=re.MULTILINE)
    # parts[0] = testo prima del primo marcatore (vuoto in genere)
    sheets = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sheets.setdefault(name, body)  # tiene la prima occorrenza se nome duplicato
    return sheets


def parse_csv_block(body):
    reader = csv.reader(io.StringIO(body))
    rows = [r for r in reader if any(c.strip() for c in r)]
    return rows


# ---------------------------------------------------------------------------
# 1 + 2: foglio commerciale principale + fogli regionali
# ---------------------------------------------------------------------------

COMM_HEADER = [
    "Azienda", "Titolo", "contatti", "Contattato", "Tramite", "il", "Riscontro",
    "libro", "mandato_il_1", "catalogo_formativo", "mandato_il_2", "Appuntamento",
    "il_2", "con", "Recall", "il_3", "Proposta", "Preventivo", "Inviato_il",
    "Conversione", "Progetto_condiviso", "Stato_arte", "note", "Regione",
]


def importa_foglio_formato_alternativo(conn, sheet_name, rows):
    """Importa 'Commerciale 2023' / 'Commerciale HRO 2023' (struttura diversa:
    2 righe di intestazione, Tipo/stato in colonna 0, azienda in colonna 5)."""
    nuovi, aggiornati = 0, 0
    data_rows = rows[2:]  # le prime 2 righe sono le doppie intestazioni
    for row in data_rows:
        def g(i):
            return row[i].strip() if len(row) > i and row[i] else ""

        tipo = g(0)
        nome, cognome = g(1), g(2)
        tel, mail = g(3), g(4)
        azienda = g(5)
        posizione = g(7)
        tramite = g(10)
        data_contatto = g(9)
        note = g(13)
        recall_data = g(15)
        tipologia_proposta = g(16)
        stato_arte_col = g(21)

        contatto_persona = f"{nome} {cognome}".strip()
        if not azienda:
            if not contatto_persona:
                continue
            azienda = contatto_persona  # contatto personale senza azienda indicata
            note = (note + " (contatto personale, senza azienda indicata)").strip()

        stato = TIPO_TO_STATO.get(tipo.lower(), "in_trattativa")

        existing = conn.execute(
            "SELECT id, stato FROM clienti WHERE UPPER(nome_azienda) = UPPER(?)",
            (azienda,),
        ).fetchone()

        descr_bits = []
        if tramite:
            descr_bits.append(f"Contattato tramite {tramite}" + (f" il {data_contatto}" if data_contatto else ""))
        if tipologia_proposta:
            descr_bits.append(f"Proposta: {tipologia_proposta}")
        if stato_arte_col:
            descr_bits.append(f"Stato: {stato_arte_col}")
        if note:
            descr_bits.append(note)
        descrizione = ". ".join(descr_bits) if descr_bits else "Importato da foglio commerciale storico"

        if existing:
            cid = existing["id"]
            aggiornati += 1
        else:
            conn.execute(
                "INSERT INTO clienti (nome_azienda, titolo, referente, email, telefono, canale, "
                "stato, data_primo_contatto, prossima_azione, prossima_azione_data, note, "
                "creato_il, aggiornato_il) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    azienda, posizione, contatto_persona, mail or None, tel or None, tramite,
                    stato, data_contatto, "Recall" if recall_data else "", recall_data,
                    note, now(), now(),
                ),
            )
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            nuovi += 1

        conn.execute(
            "INSERT INTO attivita (cliente_id, data, tipo, descrizione, creato_il) "
            "VALUES (?,?,?,?,?)",
            (cid, data_contatto, f"Storico ({sheet_name})", descrizione, now()),
        )
    return nuovi, aggiornati


def importa_foglio_commerciale(conn, sheet_name, rows, acquisiti_fino_a_riga):
    """Importa un foglio 'Commerciale ...'. Ritorna (n_clienti_nuovi, n_clienti_aggiornati)."""
    nuovi, aggiornati = 0, 0
    data_rows = rows[1:]  # riga 0 = intestazione
    for idx, row in enumerate(data_rows, start=2):  # riga 2 = prima azienda
        azienda = (row[0] if len(row) > 0 else "").strip()
        if not azienda:
            continue
        if "\t" in azienda or "\n" in azienda or len(azienda) > 120:
            # riga corrotta (delimitatore sbagliato nel file di origine): saltala
            continue
        titolo = row[1].strip() if len(row) > 1 else ""
        contatto_persona = row[2].strip() if len(row) > 2 else ""
        tramite = row[4].strip() if len(row) > 4 else ""
        data_primo_contatto = row[5].strip() if len(row) > 5 else ""
        stato_arte = row[21].strip() if len(row) > 21 else ""
        note = row[22].strip() if len(row) > 22 else ""
        regione = row[23].strip() if len(row) > 23 else ""
        recall_data = row[15].strip() if len(row) > 15 else ""
        appuntamento_data = row[12].strip() if len(row) > 12 else ""

        if acquisiti_fino_a_riga and idx <= acquisiti_fino_a_riga:
            stato = "acquisito"
        else:
            stato = "in_trattativa"

        prossima_data = recall_data or appuntamento_data or ""

        norm = normalize_name(azienda)
        existing = conn.execute(
            "SELECT id, stato FROM clienti WHERE nome_azienda = ? "
            "OR UPPER(nome_azienda) = UPPER(?)",
            (azienda, azienda),
        ).fetchone()

        descr_bits = []
        if tramite:
            descr_bits.append(f"Contattato tramite {tramite}" + (f" il {data_primo_contatto}" if data_primo_contatto else ""))
        if stato_arte:
            descr_bits.append(f"Stato: {stato_arte}")
        if note:
            descr_bits.append(note)
        descrizione = ". ".join(descr_bits) if descr_bits else "Importato da foglio commerciale storico"

        if existing:
            cid = existing["id"]
            # non retrocedere uno stato acquisito ad in_trattativa per un foglio piu' vecchio
            if stato == "acquisito" or existing["stato"] != "acquisito":
                conn.execute(
                    "UPDATE clienti SET stato = ?, aggiornato_il = ? WHERE id = ?",
                    (stato if stato == "acquisito" else existing["stato"], now(), cid),
                )
            aggiornati += 1
        else:
            conn.execute(
                "INSERT INTO clienti (nome_azienda, titolo, referente, regione, canale, "
                "stato, data_primo_contatto, prossima_azione, prossima_azione_data, note, "
                "creato_il, aggiornato_il) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    azienda, titolo, contatto_persona, regione, tramite, stato,
                    data_primo_contatto, "Recall" if recall_data else "", prossima_data,
                    note, now(), now(),
                ),
            )
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            nuovi += 1

        conn.execute(
            "INSERT INTO attivita (cliente_id, data, tipo, descrizione, creato_il) "
            "VALUES (?,?,?,?,?)",
            (cid, data_primo_contatto, f"Storico ({sheet_name})", descrizione, now()),
        )
    return nuovi, aggiornati


PROSPECT_HEADER_HINTS = ["SETTORE", "DENOMINAZIONE_AZIENDA"]


def importa_foglio_prospect(conn, sheet_name, rows):
    n = 0
    if not rows:
        return 0
    header = [h.strip().upper() for h in rows[0]]
    try:
        idx_settore = header.index("SETTORE")
    except ValueError:
        idx_settore = 0
    try:
        idx_forma = header.index("NATURA_GIURIDICA")
    except ValueError:
        idx_forma = 1
    try:
        idx_nome = header.index("DENOMINAZIONE_AZIENDA")
    except ValueError:
        idx_nome = 2
    try:
        idx_indirizzo = header.index("INDIRIZZO")
    except ValueError:
        idx_indirizzo = 3
    try:
        idx_cap = header.index("CAP")
    except ValueError:
        idx_cap = 4
    try:
        idx_comune = header.index("COMUNE")
    except ValueError:
        idx_comune = 5
    try:
        idx_dip = header.index("N° DIPENDENTI")
    except ValueError:
        idx_dip = 6
    try:
        idx_tel = header.index("TEL")
    except ValueError:
        idx_tel = 7
    try:
        idx_mail = header.index("MAIL")
    except ValueError:
        idx_mail = 8

    for row in rows[1:]:
        def g(i):
            return row[i].strip() if len(row) > i and row[i] else ""

        nome = g(idx_nome)
        if not nome:
            continue
        conn.execute(
            "INSERT INTO prospect (nome_azienda, settore, forma_giuridica, indirizzo, cap, "
            "comune, regione, n_dipendenti, telefono, email, creato_il) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                nome, g(idx_settore), g(idx_forma), g(idx_indirizzo), g(idx_cap),
                g(idx_comune), sheet_name, g(idx_dip), g(idx_tel), g(idx_mail), now(),
            ),
        )
        n += 1
    return n


# ---------------------------------------------------------------------------
# 3: file fatturato storico
# ---------------------------------------------------------------------------

def is_valid_ente_name(name):
    name = name.strip()
    if len(name) < 2:
        return False
    if re.fullmatch(r"[\d.,€\s\-%]+", name):
        return False
    if name.lower() in ENTE_INVALIDI:
        return False
    if name.lower().startswith("obj "):
        return False
    if "previsione" in name.lower():
        return False
    return True


def importa_fatturato(conn, sheets):
    match_cache = {}
    clienti_rows = conn.execute("SELECT id, nome_azienda FROM clienti").fetchall()
    clienti_norm = {normalize_name(r["nome_azienda"]): r["id"] for r in clienti_rows}

    def trova_cliente(ente):
        norm = normalize_name(ente)
        if not norm:
            return None, norm
        if norm in match_cache:
            return match_cache[norm], norm
        if norm in clienti_norm:
            match_cache[norm] = clienti_norm[norm]
            return clienti_norm[norm], norm
        # fallback: contenimento come parola intera, solo per nomi non troppo corti
        # (evita che abbreviazioni di 1-2 lettere "catturino" per errore righe non correlate)
        result = None
        if len(norm) >= 4:
            candidates = set()
            for n, cid in clienti_norm.items():
                if not n or len(n) < 4:
                    continue
                pattern = r"\b" + re.escape(n) + r"\b"
                pattern2 = r"\b" + re.escape(norm) + r"\b"
                if re.search(pattern, norm) or re.search(pattern2, n):
                    candidates.add(cid)
            if len(candidates) == 1:
                result = next(iter(candidates))
        match_cache[norm] = result
        return result, norm

    n_righe = 0
    n_creati = 0
    nuovi_norm_cache = {}
    totale_per_ente = defaultdict(float)

    for sheet_name, body in sheets.items():
        if not re.fullmatch(r"20\d\d", sheet_name):
            continue
        anno = int(sheet_name)
        rows = parse_csv_block(body)
        header = None
        idx_ente = idx_tipologia = idx_totale = idx_fattura = idx_del = idx_pagato = None
        for row in rows:
            low = [c.strip().lower() for c in row]
            if "ente" in low:
                header = low
                idx_ente = low.index("ente")
                idx_tipologia = next((i for i, c in enumerate(low) if "tipologia" in c), None)
                totale_idxs = [i for i, c in enumerate(low) if c == "totale"]
                idx_totale = totale_idxs[0] if totale_idxs else None
                idx_fattura = next((i for i, c in enumerate(low) if "fattura" in c), None)
                idx_del = next((i for i, c in enumerate(low) if c.strip() == "del"), None)
                idx_pagato = next((i for i, c in enumerate(low) if "pagato" in c), None)
                continue
            if header is None or idx_ente is None or idx_totale is None:
                continue

            def g(i):
                return row[i].strip() if i is not None and len(row) > i else ""

            ente = g(idx_ente)
            if not ente or not is_valid_ente_name(ente):
                continue
            importo = parse_italian_currency(g(idx_totale))
            if importo is None:
                continue
            tipologia = g(idx_tipologia)
            fattura = g(idx_fattura)
            data_fattura = g(idx_del)
            pagato = g(idx_pagato)

            cid, norm = trova_cliente(ente)
            if cid is None:
                if norm in nuovi_norm_cache:
                    cid = nuovi_norm_cache[norm]
                else:
                    conn.execute(
                        "INSERT INTO clienti (nome_azienda, stato, note, creato_il, aggiornato_il) "
                        "VALUES (?,?,?,?,?)",
                        (ente, "acquisito", "Creato automaticamente dal file fatturato storico", now(), now()),
                    )
                    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    clienti_norm[norm] = cid
                    nuovi_norm_cache[norm] = cid
                    n_creati += 1

            conn.execute(
                "INSERT INTO fatturato (cliente_id, data, anno, descrizione, importo, "
                "fattura_numero, pagato, creato_il) VALUES (?,?,?,?,?,?,?,?)",
                (cid, data_fattura, anno, tipologia, importo, fattura, pagato, now()),
            )
            conn.execute(
                "INSERT INTO attivita (cliente_id, data, tipo, descrizione, creato_il) "
                "VALUES (?,?,?,?,?)",
                (
                    cid, data_fattura, "Fatturato",
                    f"{tipologia or 'Prestazione'} - € {importo:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    + (f" (fattura {fattura})" if fattura else ""),
                    now(),
                ),
            )
            totale_per_ente[ente] += importo
            n_righe += 1

    return n_righe, n_creati, totale_per_ente


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 import_data.py <file_commerciale.txt> <file_fatturato.txt>")
        sys.exit(1)

    file_commerciale, file_fatturato = sys.argv[1], sys.argv[2]

    init_db()
    conn = get_connection()

    print("Lettura fogli dal file commerciale...")
    sheets = split_sheets(file_commerciale)
    print(f"  Trovati {len(sheets)} fogli")

    totale_nuovi = totale_agg = 0
    for sheet_name in COMMERCIAL_SHEETS:
        if sheet_name not in sheets:
            print(f"  (saltato, non trovato: {sheet_name})")
            continue
        rows = parse_csv_block(sheets[sheet_name])
        if sheet_name in SHEETS_FORMATO_ALTERNATIVO:
            nuovi, agg = importa_foglio_formato_alternativo(conn, sheet_name, rows)
        else:
            acquisiti_fino_a = ACQUISITO_MAX_ROW if sheet_name == ACQUISITO_SHEET else None
            nuovi, agg = importa_foglio_commerciale(conn, sheet_name, rows, acquisiti_fino_a)
        print(f"  {sheet_name}: {nuovi} nuovi, {agg} aggiornati")
        totale_nuovi += nuovi
        totale_agg += agg
    conn.commit()
    print(f"Totale clienti/contatti da fogli commerciali: {totale_nuovi} nuovi, {totale_agg} aggiornati")

    print("Lettura fogli regionali (prospect)...")
    totale_prospect = 0
    for sheet_name in REGIONAL_SHEETS:
        if sheet_name not in sheets:
            print(f"  (saltato, non trovato: {sheet_name})")
            continue
        rows = parse_csv_block(sheets[sheet_name])
        n = importa_foglio_prospect(conn, sheet_name, rows)
        print(f"  {sheet_name}: {n} prospect")
        totale_prospect += n
    conn.commit()
    print(f"Totale prospect importati: {totale_prospect}")

    print("Lettura file fatturato storico...")
    fatt_sheets = split_sheets(file_fatturato)
    n_righe, n_creati, totale_per_ente = importa_fatturato(conn, fatt_sheets)
    conn.commit()
    print(f"Totale righe fatturato importate: {n_righe}")
    print(f"Nuovi clienti creati solo dal fatturato (non presenti nel commerciale): {n_creati}")

    # Chiunque abbia una fattura storica e' per definizione un cliente acquisito,
    # anche se nel foglio commerciale piu' recente non era (ancora) marcato come tale.
    cur = conn.execute(
        "UPDATE clienti SET stato = 'acquisito', aggiornato_il = ? "
        "WHERE stato != 'acquisito' AND id IN (SELECT DISTINCT cliente_id FROM fatturato)",
        (now(),),
    )
    conn.commit()
    print(f"Promossi ad 'acquisito' perche' hanno fatturato storico: {cur.rowcount}")

    conn.close()
    print("Importazione completata.")


if __name__ == "__main__":
    main()
