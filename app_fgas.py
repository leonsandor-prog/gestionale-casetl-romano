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

DB_PATH = "castel_romano.db"
CANDIDATE_EXCEL_PATHS = [
    "F_GAS_Impianti_Attivi_2026_ (1).xlsx",
    "F_GAS_Impianti_Attivi_2026_.xlsx",
    "F-GAS Impianti attivi 2026.xlsx",
]
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
    "R-22": 1810.0,
}


def resolve_excel_path() -> str:
    for path in CANDIDATE_EXCEL_PATHS:
        if os.path.exists(path):
            return path
    return CANDIDATE_EXCEL_PATHS[0]


def get_id_macchina(row, fallback_idx: int = 0) -> str:
    """Restituisce sempre una chiave univoca basata su fgasnum."""
    raw_fgasnum = row.get("fgasnum", "")
    if pd.notna(raw_fgasnum):
        val = str(raw_fgasnum).strip()
        if val and val.lower() not in ("nan", "nat", "none"):
            if val.endswith(".0"):
                val = val[:-2]
            return val
    return f"FGAS_{fallback_idx + 1:04d}"


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


def calcola_carica_da_co2(tonn_co2: float, refrigerante: str) -> float:
    gwp = get_gwp(refrigerante)
    if gwp <= 0:
        return 0.0
    return round((float(tonn_co2 or 0.0) * 1000.0) / gwp, 2)


def parse_data_sicura(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        if pd.isna(val):
            return None
        return datetime(val.year, val.month, val.day)

    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none", "n/d", "n.d."):
        return None

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
            return datetime(dt.year, dt.month, dt.day)
        except ValueError:
            continue

    dt_pd = pd.to_datetime(s, errors="coerce")
    if pd.notna(dt_pd):
        return datetime(dt_pd.year, dt_pd.month, dt_pd.day)
    return None


def estrai_data_verifica_riga_excel(row) -> str:
    """
    Legge la data da 'Data ultima verifica' (o 'Scadenza verifica' se la prima è vuota)
    e la restituisce come stringa 'GG/MM/AAAA'.
    """
    for col in [
        "Data ultima verifica",
        "Scadenza verifica",
        "Scadenza Verifica",
    ]:
        if col in row.index:
            dt = parse_data_sicura(row.get(col))
            if dt is not None:
                return dt.strftime("%d/%m/%Y")
    return ""


def normalizza_data_anno_corrente(data_raw, anno_corrente: int):
    """
    Mantiene invariati giorno e mese dalla data verifica e imposta l'anno con anno_corrente.
    Restituisce (stringa_dd_mm_yyyy, numero_mese_int, cartella_mese_str).
    """
    dt = parse_data_sicura(data_raw)
    if dt is None:
        return "", None, None

    try:
        dt_corrente = dt.replace(year=anno_corrente)
    except ValueError:
        dt_corrente = dt.replace(year=anno_corrente, day=28)

    mese_num = dt_corrente.month
    cartella_mese = MESI_ITALIANI.get(mese_num, f"{mese_num:02d}_Mese")
    return dt_corrente.strftime("%d/%m/%Y"), mese_num, cartella_mese


def leggi_macchine_db() -> pd.DataFrame:
    """Legge le macchine dal DB garantendo sempre unicità su id_macchina (fgasnum)."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        df = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    finally:
        conn.close()

    if df.empty:
        return df

    df["id_macchina"] = (
        df["id_macchina"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    return df.drop_duplicates(subset=["id_macchina"], keep="first").reset_index(
        drop=True
    )


def sincronizza_date_da_excel():
    """
    Sincronizza le date dall'Excel verso il DB SQLite usando fgasnum come chiave primaria.
    """
    excel_file = resolve_excel_path()
    if not os.path.exists(excel_file):
        return

    try:
        xls = pd.ExcelFile(excel_file)
        foglio = (
            "Elenco di FGAS"
            if "Elenco di FGAS" in xls.sheet_names
            else xls.sheet_names[0]
        )
        df_xl = pd.read_excel(xls, sheet_name=foglio)

        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()

        for idx, r in df_xl.iterrows():
            data_str = estrai_data_verifica_riga_excel(r)
            if not data_str:
                continue
            fgas_id = get_id_macchina(r, idx)
            cur.execute(
                "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE id_macchina = ?",
                (data_str, fgas_id),
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
    excel_file = resolve_excel_path()
    if not os.path.exists(excel_file):
        return False, "File Excel non trovato."

    try:
        xls = pd.ExcelFile(excel_file)
        foglio = (
            "Elenco di FGAS"
            if "Elenco di FGAS" in xls.sheet_names
            else xls.sheet_names[0]
        )
        df_xl = pd.read_excel(xls, sheet_name=foglio)

        fgas_target = (
            str(row_data.get("id_macchina", ""))
            .strip()
            .replace(".0", "")
            if str(row_data.get("id_macchina", "")).strip().endswith(".0")
            else str(row_data.get("id_macchina", "")).strip()
        )

        col_gas = (
            "Tipo HCFC" if "Tipo HCFC" in df_xl.columns else "Refrigerante"
        )
        col_ncirc = (
            "N° Circuiti" if "N° Circuiti" in df_xl.columns else "N_Circuiti"
        )

        if "fgasnum" in df_xl.columns and fgas_target:
            serie_fgas = (
                df_xl["
