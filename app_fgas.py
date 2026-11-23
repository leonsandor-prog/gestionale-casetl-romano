import io
import os
import re
import sqlite3
import zipfile
from datetime import datetime

from docx import Document
from docx.shared import Inches
import pandas as pd
from PIL import Image
import streamlit as st

# ==============================================================================
# CONFIGURAZIONE PERCORSI E COSTANTI
# ==============================================================================
DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"
FIRMA_PATH = "firma.jpg"
OUTPUT_DIR = "rapportini_generati"

GWP_TABLE = {
    "R-410A": 2088.0,
    "R-407C": 1774.0,
    "R-32": 675.0,
    "R-134a": 1430.0,
    "R-449A": 1397.0,
    "R-404A": 3922.0,
    "R-507A": 3985.0,
    "R-22": 1810.0,
}

MESI_IT = {
    1: "Gennaio",
    2: "Febbraio",
    3: "Marzo",
    4: "Aprile",
    5: "Maggio",
    6: "Giugno",
    7: "Luglio",
    8: "Agosto",
    9: "Settembre",
    10: "Ottobre",
    11: "Novembre",
    12: "Dicembre",
}


# ==============================================================================
# FUNZIONI DI UTILITÀ E CALCOLO
# ==============================================================================
def _safe_float(val, default=0.0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return float(default)
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    if not s:
        return float(default)
    try:
        return float(s)
    except ValueError:
        return float(default)


def get_gwp(gas):
    if not gas:
        return 2088.0
    g = str(gas).strip().upper().replace(" ", "")
    if g in GWP_TABLE:
        return GWP_TABLE[g]
    for k, v in GWP_TABLE.items():
        if k.replace("-", "") == g.replace("-", ""):
            return v
    return 2088.0


def calcola_co2_tonnellate(carica_kg, gas):
    kg = _safe_float(carica_kg, 0.0)
    gwp = get_gwp(gas)
    return round((kg * gwp) / 1000.0, 2)


def sanitize_filename(name):
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "unita"))
    return s.strip("_") or "unita"


def normalizza_data_anno_corrente(val, anno_corrente):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "", None, None

    dt = None
    if isinstance(val, datetime):
        dt = val
    elif hasattr(val, "to_pydatetime"):
        dt = val.to_pydatetime()
    else:
        s = str(val).strip()
        if not s:
            return "", None, None
        for fmt in (
            "%d/%m/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%Y/%m/%d",
            "%d/%m/%y",
        ):
            try:
                dt = datetime.strptime(s[:10], fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return str(val).strip(), None, None

    try:
        dt_corr = dt.replace(year=int(anno_corrente))
    except ValueError:
        dt_corr = dt.replace(year=int(anno_corrente), day=28)

    return dt_corr.strftime("%d/%m/%Y"), dt_corr.month, dt_corr.year


def _trova_colonna(df_cols, candidati):
    cols_map = {str(c).strip().lower(): c for c in df_cols}
    for cand in candidati:
        c_low = cand.strip().lower()
        if c_low in cols_map:
            return cols_map[c_low]
    for c_low, orig in cols_map.items():
        for cand in candidati:
            if cand.strip().lower() in c_low:
                return orig
    return None


# ==============================================================================
# DATABASE SQLITE & SINCRONIZZAZIONE EXCEL
# ==============================================================================
def init_db():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS macchine_hvac (
            id_macchina TEXT PRIMARY KEY,
            nr_unita TEXT,
            marca TEXT,
            modello TEXT,
            matricola TEXT,
            collocazione TEXT,
            codice_targa TEXT,
            refrigerante TEXT,
            carica_kg REAL,
            tonn_co2_eq REAL,
            scadenza_verifica TEXT,
            stato_compilazione TEXT,
            n_circuiti INTEGER,
            carica_circ1 REAL,
            carica_circ2 REAL,
            co2_circ1 REAL,
            co2_circ2 REAL
        )
        """)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM macchine_hvac")
    count = cur.fetchone()[0]

    if count == 0 and os.path.exists(EXCEL_PATH):
        try:
            df_xl = pd.read_excel(EXCEL_PATH)
            col_id = _trova_colonna(
                df_xl.columns, ["id_macchina", "id", "codice", "unita"]
            )
            col_nr = _trova_colonna(
                df_xl.columns, ["nr_unita", "n_unita", "unita", "nr", "num"]
            )
            col_marca = _trova_colonna(df_xl.columns, ["marca", "costruttore"])
            col_mod = _trova_colonna(df_xl.columns, ["modello", "model"])
            col_matr = _trova_colonna(
                df_xl.columns, ["matricola", "seriale", "s/n", "sn"]
            )
            col_coll = _trova_colonna(
                df_xl.columns,
                ["collocazione", "ubicazione", "locale", "store", "punto vendita"],
            )
            col_targa = _trova_colonna(
                df_xl.columns,
                ["codice_targa", "targa", "cod_apparecchiatura", "apparecchiatura"],
            )
            col_gas = _trova_colonna(
                df_xl.columns, ["refrigerante", "gas", "fluido"]
            )
            col_carica = _trova_colonna(
                df_xl.columns, ["carica_kg", "carica", "kg"]
            )
            col_co2 = _trova_colonna(
                df_xl.columns, ["tonn_co2_eq", "co2", "tonn_co2", "t_co2"]
            )
            col_scad = _trova_colonna(
                df_xl.columns,
                [
                    "scadenza_verifica",
                    "data_verifica",
                    "scadenza",
                    "data",
                    "prossima_verifica",
                ],
            )
            col_stato = _trova_colonna(
                df_xl.columns, ["stato_compilazione", "stato", "status"]
            )
            col_ncirc = _trova_colonna(
                df_xl.columns, ["n_circuiti", "circuiti", "num_circuiti"]
            )

            for idx, r in df_xl.iterrows():
                raw_id = r[col_id] if col_id else f"MAC_{idx + 1:03d}"
                id_m = str(raw_id).strip() if pd.notna(raw_id) and str(raw_id).strip() else f"MAC_{idx + 1:03d}"
                nr_u = str(r[col_nr]).strip() if col_nr and pd.notna(r[col_nr]) else str(idx + 1)
                marca = str(r[col_marca]).strip() if col_marca and pd.notna(r[col_marca]) else "N/D"
                mod = str(r[col_mod]).strip() if col_mod and pd.notna(r[col_mod]) else "N/D"
                matr = str(r[col_matr]).strip() if col_matr and pd.notna(r[col_matr]) else "N/D"
                coll = str(r[col_coll]).strip() if col_coll and pd.notna(r[col_coll]) else "Castel Romano"
                targa = str(r[col_targa]).strip() if col_targa and pd.notna(r[col_targa]) else "N/D"
                gas = str(r[col_gas]).strip() if col_gas and pd.notna(r[col_gas]) else "R-410A"
                carica = _safe_float(r[col_carica], 0.0) if col_carica else 0.0
                co2 = (
                    _safe_float(r[col_co2], 0.0)
                    if col_co2 and pd.notna(r[col_co2])
                    else calcola_co2_tonnellate(carica, gas)
                )
                scad = str(r[col_scad]).strip() if col_scad and pd.notna(r[col_scad]) else ""
                stato_raw = str(r[col_stato]).strip() if col_stato and pd.notna(r[col_stato]) else ""
                stato = "Completato" if stato_raw.lower() in ("completato", "ok", "eseguito", "done", "completo") else "Da Lavorare"

                ncirc = int(_safe_float(r[col_ncirc], 1)) if col_ncirc else 1
                ncirc = 2 if ncirc == 2 else 1

                if ncirc == 2:
                    c1 = round(carica / 2.0, 2)
                    c2 = round(carica - c1, 2)
                else:
                    c1 = round(carica, 2)
                    c2 = 0.0

                co2_1 = calcola_co2_tonnellate(c1, gas)
                co2_2 = calcola_co2_tonnellate(c2, gas)

                cur.execute(
                    """
                    INSERT OR REPLACE INTO macchine_hvac (
                        id_macchina, nr_unita, marca, modello, matricola, collocazione,
                        codice_targa, refrigerante, carica_kg, tonn_co2_eq, scadenza_verifica,
                        stato_compilazione, n_circuiti, carica_circ1, carica_circ2, co2_circ1, co2_circ2
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        id_m,
                        nr_u,
                        marca,
                        mod,
                        matr,
                        coll,
                        targa,
                        gas,
                        round(carica, 2),
                        round(co2, 2),
                        scad,
                        stato,
                        ncirc,
                        c1,
                        c2,
                        co2_1,
                        co2_2,
                    ),
                )
            conn.commit()
        except Exception as e:
            st.warning(f"Importazione iniziale da Excel parziale o non riuscita: {e}")

    conn.close()


def carica_macchine():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM macchine_hvac").fetchall()
    conn.close()

    def _sort_key(r):
        s = str(r["nr_unita"] or "")
        m = re.search(r"\d+", s)
        return (0, int(m.group())) if m else (1, s.lower())

    return sorted([dict(r) for r in rows], key=_sort_key)


def salva_su_excel(
    row_dict,
    n_circuiti,
    c1_kg,
    c2_kg,
    co2_c1,
    co2_c2,
    carica_tot,
    co2_tot,
    modello,
    matricola,
    refrigerante,
    codice_targa,
    stato_compilazione,
):
    if not os.path.exists(EXCEL_PATH):
        return False, f"File {EXCEL_PATH} non trovato nella cartella"

    try:
        df = pd.read_excel(EXCEL_PATH)
        id_target = str(row_dict.get("id_macchina", "")).strip()
        nr_target = str(row_dict.get("nr_unita", "")).strip()

        col_id = _trova_colonna(df.columns, ["id_macchina", "id", "codice"])
        col_nr = _trova_colonna(df.columns, ["nr_unita", "n_unita", "unita", "nr"])

        mask = pd.Series([False] * len(df))
        if col_id:
            mask = mask | (df[col_id].astype(str).str.strip() == id_target)
        if not mask.any() and col_nr:
            mask = mask | (df[col_nr].astype(str).str.strip() == nr_target)

        if not mask.any():
            return False, f"Unità {nr_target} non trovata in {EXCEL_PATH}"

        updates = {
            "modello": modello,
            "matricola": matricola,
            "refrigerante": refrigerante,
            "carica_kg": round(float(carica_tot), 2),
            "tonn_co2_eq": round(float(co2_tot), 2),
            "codice_targa": codice_targa,
            "stato_compilazione": stato_compilazione,
            "n_circuiti": int(n_circuiti),
            "carica_circ1": round(float(c1_kg), 2),
            "carica_circ2": round(float(c2_kg),
