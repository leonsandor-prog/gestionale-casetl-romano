import sqlite3
import os
from datetime import datetime
import pandas as pd
from docx import Document
from docx.shared import Inches
from PIL import Image
import streamlit as st

DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"
OUTPUT_DIR = "Report_FGAS_Generati_2026"
FIRMA_PATH = "firma.jpg"

GWP_MAP = {
    "R-410A": 2088.0,
    "R-407C": 1774.0,
    "R-32": 675.0,
    "R-134A": 1430.0,
    "R-134a": 1430.0,
    "R-449A": 1397.0,
    "R-404A": 3922.0,
    "R-507A": 3985.0,
}


def get_gwp(refrigerante: str) -> float:
    if not refrigerante:
        return 2088.0
    key = str(refrigerante).strip().upper()
    if key in GWP_MAP:
        return GWP_MAP[key]
    for k, v in GWP_MAP.items():
        if k.upper() == key:
            return v
    return 2088.0


def calcola_co2_tonnellate(carica_kg: float, refrigerante: str) -> float:
    gwp = get_gwp(refrigerante)
    return round((float(carica_kg or 0.0) * gwp) / 1000.0, 2)


def salva_su_excel(
    row_data: dict,
    n_circ: int,
    c1_kg: float,
    c2_kg: float,
    co2_c1: float,
    co2_c2: float,
    carica_tot: float,
    co2_tot: float,
    mod_val: str,
    matr_val: str,
    gas_val: str,
    targa_val: str,
    stato_val: str,
):
    if not os.path.exists(EXCEL_PATH):
        return False, "File Excel non trovato."

    try:
        xls = pd.ExcelFile(EXCEL_PATH)
        foglio = xls.sheet_names[0]
        df_xl = pd.read_excel(xls, sheet_name=foglio)

        col_unita = next(
            (c for c in ["Unità / Macchina", "Unità", "Descrizione", "nr_unita"] if c in df_xl.columns),
            None,
        )
        col_matr = next((c for c in ["Matricola", "matricola"] if c in df_xl.columns), None)
        col_targa = next(
            (c for c in ["Cod. Apparecchiatura", "Codice Targa", "codice_targa"] if c in df_xl.columns),
            None,
        )

        mask = pd.Series([False] * len(df_xl))
        if col_unita and str(row_data["nr_unita"]).strip():
            mask = mask | (df_xl[col_unita].astype(str).str.strip() == str(row_data["nr_unita"]).strip())
        if col_matr and str(row_data["matricola"]).strip():
            mask = mask | (df_xl[col_matr].astype(str).str.strip() == str(row_data["matricola"]).strip())
        if col_targa and str(row_data["codice_targa"]).strip():
            mask = mask | (df_xl[col_targa].astype(str).str.strip() == str(row_data["codice_targa"]).strip())

        aggiornamenti = {
            "N_Circuiti": int(n_circ),
            "Carica_Circ_1_Kg": round(float(c1_kg), 2),
            "Carica_Circ_2_Kg": round(float(c2_kg), 2) if n_circ == 2 else 0.0,
            "CO2_Circ_1_T": round(float(co2_c1), 2),
            "CO2_Circ_2_T": round(float(co2_c2), 2) if n_circ == 2 else 0.0,
            "Carica Refrigerante (kg)": round(float(carica_tot), 2),
            "Tonn CO2 Eq": round(float(co2_tot), 2),
            "Modello": mod_val,
            "Matricola": matr_val,
            "Refrigerante": gas_val,
            "Cod. Apparecchiatura": targa_val,
            "Stato Lavorazione": stato_val,
        }

        for col_name, val in aggiornamenti.items():
            if col_name not in df_xl.columns:
                df_xl[col_name] = None
            if mask.any():
                df_xl.loc[mask, col_name] = val

        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            df_xl.to_excel(writer, sheet_name=foglio, index=False)

        return True, "Excel aggiornato correttamente."
    except Exception as e:
        return False, f"Errore aggiornamento Excel: {e}"


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS macchine_hvac (
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
            stato_compilazione TEXT DEFAULT 'Da Lavorare',
            n_circuiti INTEGER DEFAULT 1,
            carica_circ1 REAL DEFAULT 0.0,
            carica_circ2 REAL DEFAULT 0.0,
            co2_circ1 REAL DEFAULT 0.0,
            co2_circ2 REAL DEFAULT 0.0
        )
        """
    )

    cursor.execute("PRAGMA table_info(macchine_hvac)")
    colonne_esistenti = {info[1] for info in cursor.fetchall()}
    nuove_colonne = {
        "n_circuiti": "INTEGER DEFAULT 1",
        "carica_circ1": "REAL DEFAULT 0.0",
        "carica_circ2": "REAL DEFAULT 0.0",
        "co2_circ1": "REAL DEFAULT 0.0",
        "co2_circ2": "REAL DEFAULT 0.0",
    }
    for col_name, col_def in nuove_colonne.items():
        if col_name not in colonne_esistenti:
            cursor.execute(f"ALTER TABLE macchine_hvac ADD COLUMN {col_name} {col_def}")

    if os.path.exists(EXCEL_PATH):
        xls = pd.ExcelFile(EXCEL_PATH)
        df_excel = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

        for _, row in df_excel.iterrows():
            collocazione = str(row.get("Collocazione", "MCARTHUR_RM")).strip()
            nr_unita = str(row.get("Unità / Macchina", row.get("Unità", row.get("Descrizione", "")))).strip()
            marca = str(row.get("Marca", "")).strip()
            modello = str(row.get("Modello", "")).strip()
            matricola = str(row.get("Matricola", modello)).strip()
            refrigerante = str(row.get("Refrigerante", row.get("Tipo Gas", "R-410A"))).strip()
            tonn_co2 = float(
                row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", 0.0))
                if pd.notna(row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", 0.0)))
                else 0.0
            )
            carica_col = row.get("Carica Refrigerante (kg)", row.get("Carica (kg)", 0.0))
            gwp_val = get_gwp(refrigerante)
            carica_kg = (
                float(carica_col)
                if pd.notna(carica_col) and float(carica_col) != 0.0
                else ((tonn_co2 * 1000.0) / gwp_val if tonn_co2 > 0 else 0.0)
            )
            if tonn_co2 == 0.0 and carica_kg > 0:
                tonn_co2 = calcola_co2_tonnellate(carica_kg, refrigerante)

            codice_targa = str(row.get("Cod. Apparecchiatura", row.get("Codice Targa", ""))).strip()
            scadenza = str(row.get("Scadenza Verifica", "14/04/2027")).strip()

            raw_ncirc = row.get("N_Circuiti", 1)
            n_circ = 2 if pd.notna(raw_ncirc) and int(float(raw_ncirc)) == 2 else 1

            c1_val = float(
                row.get("Carica_Circ_1_Kg", carica_kg / 2 if n_circ == 2 else carica_kg)
                if pd.notna(row.get("Carica_Circ_1_Kg"))
                else (carica_kg / 2 if n_circ == 2 else carica_kg)
            )
            c2_val = float(
                row.get("Carica_Circ_2_Kg", carica_kg / 2 if n_circ == 2 else 0.0)
                if pd.notna(row.get("Carica_Circ_2_Kg"))
                else (carica_kg / 2 if n_circ == 2 else 0.0)
            )
            co2_1_val = calcola_co2_tonnellate(c1_val, refrigerante)
            co2_2_val = calcola_co2_tonnellate(c2_val, refrigerante) if n_circ == 2 else 0.0

            id_unic = f"{nr_unita}_{modello}_{matricola}"

            cursor.execute(
                """
                INSERT OR IGNORE INTO macchine_hvac
                (id_macchina, collocazione, nr_unita, marca, modello, matricola, refrigerante, tonn_co2_eq, carica_kg, codice_targa, scadenza_verifica, stato_compilazione, n_circuiti, carica_circ1, carica_circ2, co2_circ1, co2_circ2)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id_unic,
                    collocazione,
                    nr_unita,
                    marca,
                    modello,
                    matricola,
                    refrigerante,
                    tonn_co2,
                    carica_kg,
                    codice_targa,
                    scadenza,
                    "Da Lavorare",
                    n_circ,
                    c1_val,
                    c2_val,
                    co2_1_val,
                    co2_2_val,
                ),
            )

    conn.commit()
    conn.close()


def genera_report_docx(
    row,
    mod_edit,
    matr_edit,
    gas_edit,
    targa_edit,
    stato_edit,
    n_circ_edit,
    c1_edit,
    c2_edit,
    co2_c1
