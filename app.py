"""
Gestionale Clienti - HRO Consulting
Applicazione locale (server Flask su 127.0.0.1) per la gestione commerciale:
pipeline clienti, storico attivita', promemoria di richiamo, fatturato per
cliente e bozze email.
"""
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime, date, timedelta
from urllib.parse import quote

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from db import get_connection, init_db, now

APP_NAME = "Gestionale Clienti - HRO Consulting"
PORT = 5731

if getattr(sys, "frozen", False):
    _base = sys._MEIPASS
    app = Flask(__name__, template_folder=os.path.join(_base, "templates"),
                static_folder=os.path.join(_base, "static"))
else:
    app = Flask(__name__)
app.secret_key = "hro-consulting-gestionale-locale"


# ---------------------------------------------------------------------------
# Utilita'
# ---------------------------------------------------------------------------

def parse_it_date(s):
    """Converte una data in formato gg/mm/aaaa (o aaaa-mm-gg) in un oggetto date."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fmt_it_date(d):
    if not d:
        return ""
    return d.strftime("%d/%m/%Y")


def fmt_euro(v):
    if v is None:
        return "€ 0,00"
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


app.jinja_env.filters["euro"] = fmt_euro

STATI = {
    "acquisito": "Cliente acquisito",
    "in_trattativa": "In trattativa",
    "da_contattare": "Da contattare",
}


def classifica_promemoria(clienti_rows):
    oggi = date.today()
    scaduti, oggi_list, prossimi, senza_data = [], [], [], []
    for r in clienti_rows:
        d = parse_it_date(r["prossima_azione_data"])
        if d is None:
            continue
        if d < oggi:
            scaduti.append((d, r))
        elif d == oggi:
            oggi_list.append((d, r))
        elif d <= oggi + timedelta(days=7):
            prossimi.append((d, r))
    scaduti.sort(key=lambda x: x[0])
    oggi_list.sort(key=lambda x: x[0])
    prossimi.sort(key=lambda x: x[0])
    return scaduti, oggi_list, prossimi


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    conn = get_connection()
    clienti = conn.execute(
        "SELECT * FROM clienti WHERE prossima_azione_data IS NOT NULL AND prossima_azione_data != ''"
    ).fetchall()
    scaduti, oggi_list, prossimi = classifica_promemoria(clienti)

    anno_corrente = date.today().year
    fatt_anno = conn.execute(
        "SELECT SUM(importo) tot, COUNT(*) n FROM fatturato WHERE anno = ?", (anno_corrente,)
    ).fetchone()
    fatt_totale = conn.execute("SELECT SUM(importo) tot FROM fatturato").fetchone()["tot"] or 0

    n_acquisiti = conn.execute("SELECT COUNT(*) n FROM clienti WHERE stato='acquisito'").fetchone()["n"]
    n_trattativa = conn.execute("SELECT COUNT(*) n FROM clienti WHERE stato='in_trattativa'").fetchone()["n"]
    n_prospect = conn.execute("SELECT COUNT(*) n FROM prospect").fetchone()["n"]
    conn.close()

    return render_template(
        "dashboard.html",
        app_name=APP_NAME,
        scaduti=scaduti, oggi_list=oggi_list, prossimi=prossimi,
        fatt_anno=fatt_anno["tot"] or 0, fatt_anno_n=fatt_anno["n"] or 0,
        fatt_totale=fatt_totale, anno_corrente=anno_corrente,
        n_acquisiti=n_acquisiti, n_trattativa=n_trattativa, n_prospect=n_prospect,
        fmt_it_date=fmt_it_date,
    )


# ---------------------------------------------------------------------------
# Clienti
# ---------------------------------------------------------------------------

@app.route("/clienti")
def clienti_list():
    stato_filtro = request.args.get("stato", "")
    q = request.args.get("q", "").strip()
    conn = get_connection()
    sql = "SELECT * FROM clienti WHERE 1=1"
    params = []
    if stato_filtro:
        sql += " AND stato = ?"
        params.append(stato_filtro)
    if q:
        sql += " AND (nome_azienda LIKE ? OR referente LIKE ? OR note LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY nome_azienda COLLATE NOCASE"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template(
        "clienti_list.html", app_name=APP_NAME, clienti=rows, stati=STATI,
        stato_filtro=stato_filtro, q=q,
    )


@app.route("/clienti/nuovo", methods=["GET", "POST"])
def cliente_nuovo():
    if request.method == "POST":
        conn = get_connection()
        conn.execute(
            "INSERT INTO clienti (nome_azienda, titolo, referente, email, telefono, regione, "
            "canale, stato, data_primo_contatto, prossima_azione, prossima_azione_data, note, "
            "creato_il, aggiornato_il) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                request.form["nome_azienda"].strip(), request.form.get("titolo", "").strip(),
                request.form.get("referente", "").strip(), request.form.get("email", "").strip(),
                request.form.get("telefono", "").strip(), request.form.get("regione", "").strip(),
                request.form.get("canale", "").strip(), request.form.get("stato", "da_contattare"),
                fmt_it_date(date.today()), request.form.get("prossima_azione", "").strip(),
                request.form.get("prossima_azione_data", "").strip(), request.form.get("note", "").strip(),
                now(), now(),
            ),
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO attivita (cliente_id, data, tipo, descrizione, creato_il) VALUES (?,?,?,?,?)",
            (cid, fmt_it_date(date.today()), "Creazione", "Nuovo contatto inserito manualmente", now()),
        )
        conn.commit()
        conn.close()
        flash("Nuovo contatto creato.", "success")
        return redirect(url_for("cliente_detail", cid=cid))
    return render_template("cliente_form.html", app_name=APP_NAME, cliente=None, stati=STATI, oggi=fmt_it_date(date.today()))


@app.route("/clienti/<int:cid>")
def cliente_detail(cid):
    conn = get_connection()
    cliente = conn.execute("SELECT * FROM clienti WHERE id=?", (cid,)).fetchone()
    if not cliente:
        conn.close()
        flash("Contatto non trovato.", "error")
        return redirect(url_for("clienti_list"))
    attivita = conn.execute(
        "SELECT * FROM attivita WHERE cliente_id=? ORDER BY "
        "CASE WHEN data IS NULL OR data = '' THEN 1 ELSE 0 END, data DESC, id DESC", (cid,)
    ).fetchall()
    fatturato = conn.execute(
        "SELECT * FROM fatturato WHERE cliente_id=? ORDER BY anno DESC, data DESC", (cid,)
    ).fetchall()
    tot_fatturato = sum(f["importo"] for f in fatturato) if fatturato else 0
    conn.close()
    return render_template(
        "cliente_detail.html", app_name=APP_NAME, cliente=cliente, attivita=attivita,
        fatturato=fatturato, tot_fatturato=tot_fatturato, stati=STATI, oggi=fmt_it_date(date.today()),
    )


@app.route("/clienti/<int:cid>/modifica", methods=["POST"])
def cliente_modifica(cid):
    conn = get_connection()
    campi = ["nome_azienda", "titolo", "referente", "email", "telefono", "regione", "canale",
             "stato", "prossima_azione", "prossima_azione_data", "note"]
    valori = [request.form.get(c, "").strip() for c in campi]
    conn.execute(
        f"UPDATE clienti SET {', '.join(c + ' = ?' for c in campi)}, aggiornato_il = ? WHERE id = ?",
        valori + [now(), cid],
    )
    conn.commit()
    conn.close()
    flash("Dati aggiornati.", "success")
    return redirect(url_for("cliente_detail", cid=cid))


@app.route("/clienti/<int:cid>/attivita", methods=["POST"])
def cliente_nuova_attivita(cid):
    conn = get_connection()
    data_att = request.form.get("data", "").strip() or fmt_it_date(date.today())
    tipo = request.form.get("tipo", "Nota").strip()
    descrizione = request.form.get("descrizione", "").strip()
    conn.execute(
        "INSERT INTO attivita (cliente_id, data, tipo, descrizione, creato_il) VALUES (?,?,?,?,?)",
        (cid, data_att, tipo, descrizione, now()),
    )
    prossima_data = request.form.get("prossima_azione_data", "").strip()
    prossima_tipo = request.form.get("prossima_azione", "").strip()
    if prossima_data:
        conn.execute(
            "UPDATE clienti SET prossima_azione = ?, prossima_azione_data = ?, aggiornato_il = ? WHERE id = ?",
            (prossima_tipo or "Richiamo", prossima_data, now(), cid),
        )
    conn.commit()
    conn.close()
    flash("Attivita' registrata.", "success")
    return redirect(url_for("cliente_detail", cid=cid))


@app.route("/clienti/<int:cid>/elimina", methods=["POST"])
def cliente_elimina(cid):
    conn = get_connection()
    conn.execute("DELETE FROM clienti WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    flash("Contatto eliminato.", "success")
    return redirect(url_for("clienti_list"))


@app.route("/clienti/<int:cid>/email")
def cliente_email(cid):
    conn = get_connection()
    cliente = conn.execute("SELECT * FROM clienti WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not cliente:
        flash("Contatto non trovato.", "error")
        return redirect(url_for("clienti_list"))

    nome_ref = cliente["referente"] or cliente["nome_azienda"]
    primo_nome = nome_ref.split()[0] if nome_ref else ""
    oggetto = f"HR&O Consulting - {cliente['nome_azienda']}"
    corpo = (
        f"Buongiorno {primo_nome},\n\n"
        f"[scrivi qui il contenuto del messaggio]\n\n"
        f"Resto a disposizione per qualsiasi chiarimento.\n\n"
        f"Un caro saluto,\nPiero\nHR&O Consulting\nhroconsulting.it"
    )
    mailto = f"mailto:{cliente['email'] or ''}?subject={quote(oggetto)}&body={quote(corpo)}"
    return render_template(
        "cliente_email.html", app_name=APP_NAME, cliente=cliente,
        oggetto=oggetto, corpo=corpo, mailto=mailto,
    )


# ---------------------------------------------------------------------------
# Prospect (lead freddi da promuovere)
# ---------------------------------------------------------------------------

@app.route("/prospect")
def prospect_list():
    regione = request.args.get("regione", "")
    q = request.args.get("q", "").strip()
    conn = get_connection()
    regioni = [r["regione"] for r in conn.execute("SELECT DISTINCT regione FROM prospect ORDER BY regione")]
    sql = "SELECT * FROM prospect WHERE 1=1"
    params = []
    if regione:
        sql += " AND regione = ?"
        params.append(regione)
    if q:
        sql += " AND (nome_azienda LIKE ? OR comune LIKE ? OR settore LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY nome_azienda COLLATE NOCASE LIMIT 300"
    rows = conn.execute(sql, params).fetchall()
    totale = conn.execute("SELECT COUNT(*) n FROM prospect" + (" WHERE regione=?" if regione else ""),
                           (regione,) if regione else ()).fetchone()["n"]
    conn.close()
    return render_template(
        "prospect_list.html", app_name=APP_NAME, prospect=rows, regioni=regioni,
        regione=regione, q=q, totale=totale,
    )


@app.route("/prospect/<int:pid>/promuovi", methods=["POST"])
def prospect_promuovi(pid):
    conn = get_connection()
    p = conn.execute("SELECT * FROM prospect WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        flash("Prospect non trovato.", "error")
        return redirect(url_for("prospect_list"))
    conn.execute(
        "INSERT INTO clienti (nome_azienda, titolo, referente, email, telefono, regione, "
        "canale, stato, note, creato_il, aggiornato_il) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            p["nome_azienda"], p["settore"], "", p["email"], p["telefono"], p["regione"],
            "", "da_contattare", f"Promosso da lista prospect ({p['comune']}, {p['forma_giuridica']})",
            now(), now(),
        ),
    )
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("DELETE FROM prospect WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    flash(f"{p['nome_azienda']} promosso a contatto.", "success")
    return redirect(url_for("cliente_detail", cid=cid))


# ---------------------------------------------------------------------------
# Fatturato
# ---------------------------------------------------------------------------

@app.route("/fatturato")
def fatturato_report():
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.id, c.nome_azienda, c.stato, SUM(f.importo) tot, COUNT(*) n, MAX(f.anno) ultimo_anno
        FROM fatturato f JOIN clienti c ON c.id = f.cliente_id
        GROUP BY c.id ORDER BY tot DESC
    """).fetchall()
    totale_generale = sum(r["tot"] for r in rows) if rows else 0

    per_anno = conn.execute("""
        SELECT anno, SUM(importo) tot FROM fatturato GROUP BY anno ORDER BY anno
    """).fetchall()
    conn.close()
    return render_template(
        "fatturato_report.html", app_name=APP_NAME, righe=rows,
        totale_generale=totale_generale, per_anno=per_anno,
    )


# ---------------------------------------------------------------------------
# Impostazioni (avvio automatico con Windows)
# ---------------------------------------------------------------------------

REG_NOME_VOCE = "GestionaleClientiHRO"
REG_PERCORSO = r"Software\Microsoft\Windows\CurrentVersion\Run"


def exe_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    return None


def avvio_automatico_attivo():
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PERCORSO) as key:
            try:
                winreg.QueryValueEx(key, REG_NOME_VOCE)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return None


def imposta_avvio_automatico(attiva):
    if sys.platform != "win32":
        return False, "L'avvio automatico con Windows e' disponibile solo su Windows."
    path = exe_path()
    if not path:
        return False, "Questa opzione funziona solo nella versione installata (.exe)."
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PERCORSO, 0, winreg.KEY_SET_VALUE)
        if attiva:
            winreg.SetValueEx(key, REG_NOME_VOCE, 0, winreg.REG_SZ, f'"{path}"')
            msg = "Avvio automatico con Windows attivato."
        else:
            try:
                winreg.DeleteValue(key, REG_NOME_VOCE)
            except FileNotFoundError:
                pass
            msg = "Avvio automatico con Windows disattivato."
        winreg.CloseKey(key)
        return True, msg
    except Exception as e:
        return False, f"Errore: {e}"


@app.route("/impostazioni", methods=["GET", "POST"])
def impostazioni():
    if request.method == "POST":
        ok, msg = imposta_avvio_automatico(request.form.get("azione") == "attiva")
        flash(msg, "success" if ok else "error")
        return redirect(url_for("impostazioni"))
    return render_template(
        "impostazioni.html", app_name=APP_NAME,
        stato_avvio=avvio_automatico_attivo(), is_windows=(sys.platform == "win32"),
        is_exe=bool(exe_path()),
    )


# ---------------------------------------------------------------------------
# Avvio applicazione
# ---------------------------------------------------------------------------

def apri_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}/")


def avvia_server_in_background(debug=False):
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=PORT, debug=debug, use_reloader=False),
        daemon=True,
    ).start()


if __name__ == "__main__":
    init_db()
    debug = "--debug" in sys.argv
    senza_tray = "--no-tray" in sys.argv or "--no-browser" in sys.argv

    if senza_tray:
        # Modalita' di sviluppo/test: niente icona nella tray, server in primo piano.
        if "--no-browser" not in sys.argv:
            threading.Timer(1.0, apri_browser).start()
        app.run(host="127.0.0.1", port=PORT, debug=debug, use_reloader=debug)
    else:
        avvia_server_in_background(debug=debug)
        threading.Timer(1.0, apri_browser).start()
        import tray
        avviata = tray.avvia_tray(PORT)
        if not avviata:
            # pystray non disponibile (es. ambiente senza interfaccia grafica):
            # resta comunque in vita come server web.
            print("Icona nella tray non disponibile: l'app resta attiva come server web.")
            print(f"Apri http://127.0.0.1:{PORT}/ nel browser. Premi CTRL+C per uscire.")
            while True:
                time.sleep(3600)
