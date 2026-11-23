import io
import os
import re
import sqlite3
import zipfile
from datetime import datetime

from docx import Document
from docx.shared import Inches
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Gestionale F-GAS — Castel Romano",
    page_icon="❄️",
    layout="wide",
)

DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"
OUTPUT_DIR = "Report_FGAS_Generati_2026"
FIRMA_PATH = "firma.jpg"

MESI_ITALIANI = {
    1: "01_Gennaio",
    2: "02_Febbraio",
    3: "03_Marzo",
    4: "04_Aprile",
    5: "05_Maggio",
    6: "06_Giugno",
    7: "07_Luglio",
    8: "08_Agosto",
    9: "09_Settembre",
    10: "10_Ottobre",
    11: "11_Novembre",
    12: "12_Dicembre",
}

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


def sanitize_filename(val: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|\s]+', "_", str(val or "").strip())
    return cleaned.strip("_") or "NA"


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


def _safe_float(val, default=0.0) -> float:
    if val is None or pd.isna(val):
        return float(default)
    try:
        s = str(val).strip().replace(",", ".")
        if s in ("", "nan", "NaT", "None"):
            return float(default)
        return float(s)
    except Exception:
        return float(default)


def estrai_data_verifica_riga_excel(row) -> str:
    for col in ["Data ultima verifica", "Scadenza verifica", "Scadenza Verifica"]:
        if col in row.index:
            val = row.get(col)
            if pd.notna(val) and str(val).strip() not in ("", "nan", "NaT", "None"):
                if isinstance(val, (datetime, pd.Timestamp)):
                    return val.strftime("%d/%m/%Y")
                dt_parsed = pd.to_datetime(
                    str(val).strip(), errors="coerce", dayfirst=True
                )
                if pd.notna(dt_parsed):
                    return dt_parsed.strftime("%d/%m/%Y")
                return str(val).strip()
    return ""


def normalizza_data_anno_corrente(data_raw, anno_corrente: int):
    dt = None

    if isinstance(data_raw, (datetime, pd.Timestamp)) and pd.notna(data_raw):
        dt = datetime(data_raw.year, data_raw.month, data_raw.day)
    else:
        s = str(data_raw or "").strip()
        if s and s.lower() not in ("nan", "nat", "none"):
            for fmt in (
                "%d/%m/%Y",
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%d.%m.%Y",
                "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S",
                "%d/%m/%y",
                "%d-%m-%y",
            ):
                try:
                    dt = datetime.strptime(s.split()[0], fmt)
                    break
                except Exception:
                    continue

            if dt is None:
                dt_pd = pd.to_datetime(s, errors="coerce", dayfirst=True)
                if pd.notna(dt_pd):
                    dt = datetime(dt_pd.year, dt_pd.month, dt_pd.day)

    if dt is None:
        return "", None, None

    try:
        dt_corrente = dt.replace(year=anno_corrente)
    except ValueError:
        dt_corrente = dt.replace(year=anno_corrente, day=28)

    mese_num = dt_corrente.month
    cartella_mese = MESI_ITALIANI.get(mese_num, f"{mese_num:02d}_Mese")
    return dt_corrente.strftime("%d/%m/%Y"), mese_num, cartella_mese


def sincronizza_date_da_excel():
    if not os.path.exists(EXCEL_PATH):
        return

    try:
        xls = pd.ExcelFile(EXCEL_PATH)
        df_xl = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

        col_unita = next(
            (
                c
                for c in ["Descrizione", "Unità / Macchina", "Unità", "nr_unita"]
                if c in df_xl.columns
            ),
            None,
        )
        col_matr = next(
            (c for c in ["Matricola", "matricola"] if c in df_xl.columns), None
        )
        col_targa = next(
            (
                c
                for c in ["Cod. Apparecchiatura", "Codice Targa", "codice_targa"]
                if c in df_xl.columns
            ),
            None,
        )

        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()

        for _, r in df_xl.iterrows():
            data_str = estrai_data_verifica_riga_excel(r)
            if not data_str:
                continue

            unita_v = (
                str(r.get(col_unita, "")).strip()
                if col_unita and pd.notna(r.get(col_unita))
                else ""
            )
            matr_v = (
                str(r.get(col_matr, "")).strip()
                if col_matr and pd.notna(r.get(col_matr))
                else ""
            )
            targa_v = (
                str(r.get(col_targa, "")).strip()
                if col_targa and pd.notna(r.get(col_targa))
                else ""
            )

            if unita_v and matr_v:
                cur.execute(
                    (
                        "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE"
                        " TRIM(nr_unita) = ? AND TRIM(matricola) = ?"
                    ),
                    (data_str, unita_v, matr_v),
                )
            elif targa_v and targa_v != "GF":
                cur.execute(
                    (
                        "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE"
                        " TRIM(codice_targa) = ?"
                    ),
                    (data_str, targa_v),
                )
            elif unita_v:
                cur.execute(
                    (
                        "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE"
                        " TRIM(nr_unita) = ?"
                    ),
                    (data_str, unita_v),
                )

        conn.commit()
        conn.close()
    except Exception:
        pass


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
        foglio_target = xls.sheet_names[0]
        tutti_fogli = {
            nome: pd.read_excel(xls, sheet_name=nome) for nome in xls.sheet_names
        }
        df_xl = tutti_fogli[foglio_target]

        col_unita = next(
            (
                c
                for c in ["Descrizione", "Unità / Macchina", "Unità", "nr_unita"]
                if c in df_xl.columns
            ),
            None,
        )
        col_matr = next(
            (c for c in ["Matricola", "matricola"] if c in df_xl.columns), None
        )
        col_targa = next(
            (
                c
                for c in ["Cod. Apparecchiatura", "Codice Targa", "codice_targa"]
                if c in df_xl.columns
            ),
            None,
        )
        col_gas = "Tipo HCFC" if "Tipo HCFC" in df_xl.columns else "Refrigerante"
        col_ncirc = "N° Circuiti" if "N° Circuiti" in df_xl.columns else "N_Circuiti"

        mask = pd.Series([False] * len(df_xl))
        if col_unita and str(row_data.get("nr_unita", "")).strip():
            mask = mask | (
                df_xl[col_unita].astype(str).str.strip()
                == str(row_data["nr_unita"]).strip()
            )
        if col_matr and str(row_data.get("matricola", "")).strip():
            mask = mask | (
                df_xl[col_matr].astype(str).str.strip()
                == str(row_data["matricola"]).strip()
            )
        if (
            col_targa
            and str(row_data.get("codice_targa", "")).strip()
            and str(row_data["codice_targa"]).strip() != "GF"
        ):
            mask = mask | (
                df_xl[col_targa].astype(str).str.strip()
                == str(row_data["codice_targa"]).strip()
            )

        aggiornamenti = {
            col_ncirc: int(n_circ),
            "Carica_Circ_1_Kg": round(float(c1_kg), 2),
            "Carica_Circ_2_Kg": round(float(c2_kg), 2) if int(n_circ) == 2 else 0.0,
            "CO2_Circ_1_T": round(float(co2_c1), 2),
            "CO2_Circ_2_T": round(float(co2_c2), 2) if int(n_circ) == 2 else 0.0,
            "Carica Refrigerante (kg)": round(float(carica_tot), 2),
