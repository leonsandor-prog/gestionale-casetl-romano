import os
import shutil
import sqlite3
from datetime import datetime
import pandas as pd
import streamlit as st

DB_PATH = "castel_romano.db"
CANDIDATE_EXCEL_PATHS = [
    "F_GAS_Impianti_Attivi_2026_ (1).xlsx",
    "F_GAS_Impianti_Attivi_2026_.xlsx",
    "F-GAS Impianti attivi 2026.xlsx",
]
OUTPUT_DIRS = ["Report_FGAS_Generati_2026", "rapportini_generati"]

GWP_MAP = {
    "R-410A": 2088.0,
    "R-407C": 1774.0,
    "R-32": 675.0,
    "R-134A": 1430.0,
    "R-134a": 1430.0,
    "R-449A": 1397.0,
    "R-404A": 3922.0,
    "R-507A": 3985.0,
    "R-22": 1810.0,
}


def get_gwp(gas):
    if not gas:
        return 2088.0
    return GWP_MAP.get(str(gas).strip().upper(), 2088.0)


def parse_data(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none", "n/d", "n.d."):
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s


def find_excel():
    for path in CANDIDATE_EXCEL_PATHS:
        if os.path.exists(path):
            return path
    return None


def pulisci_tutto():
    log = []
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        log.append(f"Rimosso {DB_PATH}")

    for folder in OUTPUT_DIRS:
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
            log.append(f"Rimossa cartella {folder}")

    for fname in os.listdir("."):
        if fname.lower().endswith(".docx") and fname != "Report_FGAS_modello.docx":
            try:
                os.remove(fname)
                log.append(f"Rimosso {fname}")
            except OSError:
                pass

    return log


def ricrea_db_pulito(excel_path: str) -> int:
    xls = pd.ExcelFile(excel_path)
    foglio = "Elenco di FGAS" if "Elenco di FGAS" in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=foglio)

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE macchine_hvac (
            id_macchina TEXT PRIMARY KEY,
            collocazione TEXT,
            nr_unita TEXT,
            marca TEXT,
            modello TEXT,
            matricola TEXT,
            refrigerante TEXT,
            tonn_co2_eq REAL,
            carica_kg REAL,
            codice_targa TEXT,
            scadenza_verifica TEXT,
            f_gas_attivo TEXT DEFAULT 'S',
            stato_compilazione TEXT DEFAULT 'Da Lavorare',
            n_circuiti INTEGER DEFAULT 1,
            carica_circ1 REAL DEFAULT 0.0,
            carica_circ2 REAL DEFAULT 0.0,
            co2_circ1 REAL DEFAULT 0.0,
            co2_circ2 REAL DEFAULT 0.0
        )
        """
    )

    count = 0
    for idx, r in df.iterrows():
        fgasnum = str(r.get("fgasnum", "")).strip()
        id_macchina = fgasnum if fgasnum and fgasnum.lower() != "nan" else f"MAC_{idx + 1:03d}"

        collocazione = str(r.get("Collocazione", "MCARTHUR_RM")).strip()
        nr_unita = str(r.get("Descrizione", r.get("Unità / Macchina", ""))).strip()
        marca = str(r.get("Marca", "")).strip()
        modello = str(r.get("Modello", "")).strip()

        matr_raw = r.get("Matricola", "")
        matricola = str(matr_raw).strip() if pd.notna(matr_raw) and str(matr_raw).strip() else "N/D"

        gas_raw = r.get("Tipo HCFC", r.get("Refrigerante", ""))
        refrigerante = str(gas_raw).strip() if pd.notna(gas_raw) and str(gas_raw).strip() else "N/D"

        carica_raw = r.get("Carica Refrigerante (kg)", r.get("Carica (kg)", None))
        co2_raw = r.get("Tonn CO2 Eq", r.get("Tonn. CO2 Eq.", None))

        if pd.notna(carica_raw):
            carica_kg = round(float(carica_raw), 2)
        elif pd.notna(co2_raw) and refrigerante != "N/D":
            carica_kg = round((float(co2_raw) * 1000.0) / get_gwp(refrigerante), 2)
        else:
            carica_kg = 0.0

        if pd.notna(co2_raw):
            tonn_co2 = round(float(co2_raw), 2)
        elif carica_kg > 0 and refrigerante != "N/D":
            tonn_co2 = round((carica_kg * get_gwp(refrigerante)) / 1000.0, 2)
        else:
            tonn_co2 = 0.0

        targa_raw = r.get("Cod. Apparecchiatura", r.get("Codice Targa", ""))
        codice_targa = str(targa_raw).strip() if pd.notna(targa_raw) else ""
        scadenza = parse_data(r.get("Scadenza verifica", r.get("Scadenza Verifica", "")))
        fgas_flag = str(r.get("F-Gas?", "S")).strip().upper()

        cur.execute(
            """
            INSERT INTO macchine_hvac (
                id_macchina, collocazione, nr_unita, marca, modello, matricola,
                refrigerante, tonn_co2_eq, carica_kg, codice_targa, scadenza_verifica,
                f_gas_attivo, stato_compilazione, n_circuiti, carica_circ1, carica_circ2,
                co2_circ1, co2_circ2
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id_macchina, collocazione, nr_unita, marca, modello, matricola,
                refrigerante, tonn_co2, carica_kg, codice_targa, scadenza,
                fgas_flag if fgas_flag in ("S", "N") else "S", "Da Lavorare",
                1, carica_kg, 0.0, tonn_co2, 0.0,
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


st.set_page_config(page_title="Pulizia Temporanea F-GAS", layout="centered")
st.title("🧹 Pulizia Temporanea & Reset DB")

excel_found = find_excel()
st.write(f"File Excel rilevato: `{excel_found or 'NESSUNO'}`")

if st.button("🗑️ Elimina Tutto (DB + Report generati) e Ricrea DB Pulito"):
    logs = pulisci_tutto()
    for item in logs:
        st.write(f"- {item}")

    if excel_found:
        n = ricrea_db_pulito(excel_found)
        st.success(f"Fatto! Database ricreato con {n} record univoci. Ora puoi rimettere il tuo app_fgas.py funzionante.")
    else:
        st.warning("Pulizia completata, ma non ho trovato un file Excel nella cartella.")
