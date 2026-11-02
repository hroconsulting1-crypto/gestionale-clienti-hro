"""
Icona nella barra di sistema (tray) + controllo periodico dei promemoria con
notifiche desktop. Pensato per Windows (pystray + Pillow); se questi pacchetti
non sono disponibili (es. durante lo sviluppo su Linux) l'app continua a
funzionare comunque solo via browser, senza icona né notifiche.
"""
import threading
import time
import webbrowser
from datetime import date

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_DISPONIBILE = True
except ImportError:
    TRAY_DISPONIBILE = False

from db import get_connection

INTERVALLO_CONTROLLO_SECONDI = 30 * 60  # ogni 30 minuti


def _crea_icona():
    img = Image.new("RGB", (64, 64), "#1f3a5f")
    d = ImageDraw.Draw(img)
    d.ellipse((14, 10, 50, 46), fill="#ffffff")
    d.rectangle((20, 46, 44, 54), fill="#2e7d4f")
    return img


def _promemoria_di_oggi(conn):
    oggi_str_variants = [date.today().strftime("%d/%m/%Y")]
    rows = conn.execute(
        "SELECT nome_azienda, prossima_azione_data FROM clienti "
        "WHERE prossima_azione_data IS NOT NULL AND prossima_azione_data != ''"
    ).fetchall()
    from app import parse_it_date  # import locale per evitare ciclo in fase di modulo
    oggi = date.today()
    scaduti_e_oggi = []
    for r in rows:
        d = parse_it_date(r["prossima_azione_data"])
        if d and d <= oggi:
            scaduti_e_oggi.append(r["nome_azienda"])
    return scaduti_e_oggi


def _loop_promemoria(icon, porta):
    notificati_oggi = set()
    giorno_corrente = date.today()
    while True:
        try:
            oggi = date.today()
            if oggi != giorno_corrente:
                notificati_oggi.clear()
                giorno_corrente = oggi
            conn = get_connection()
            aziende = _promemoria_di_oggi(conn)
            conn.close()
            nuove = [a for a in aziende if a not in notificati_oggi]
            if nuove:
                notificati_oggi.update(nuove)
                if len(nuove) == 1:
                    msg = f"Ricorda di contattare: {nuove[0]}"
                else:
                    msg = f"Hai {len(nuove)} contatti da richiamare: " + ", ".join(nuove[:5])
                    if len(nuove) > 5:
                        msg += "..."
                icon.notify(msg, "Gestionale clienti - promemoria")
        except Exception:
            pass
        time.sleep(INTERVALLO_CONTROLLO_SECONDI)


def avvia_tray(porta):
    """Avvia l'icona nella system tray e il controllo periodico dei promemoria.
    Blocca il thread corrente: va chiamata dal thread principale."""
    if not TRAY_DISPONIBILE:
        return False

    def apri(icon=None, item=None):
        webbrowser.open(f"http://127.0.0.1:{porta}/")

    def esci(icon=None, item=None):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Apri gestionale", apri, default=True),
        pystray.MenuItem("Esci", esci),
    )
    icon = pystray.Icon("gestionale_clienti", _crea_icona(), "Gestionale Clienti HR&O", menu)

    threading.Thread(target=_loop_promemoria, args=(icon, porta), daemon=True).start()
    icon.run()
    return True
