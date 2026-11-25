import io
import os
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime

from docx import Document
from docx.shared import Inches
import pandas as pd
from PIL import Image
import streamlit as st

st.set_page_config(page_title="CBRE GWS - F-GAS Castel Romano", layout="wide")

DB_PATH = "castel_romano.db"
BACKUP_DIR = "Backup_FGAS"
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


def _normalizza_chiave(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return s.strip()


def get_id_macchina(row, fallback_idx: int = 0) -> str:
    """Restituisce sempre una chiave univoca basata su fgasnum."""
    raw_fgasnum = row.get("fgasnum", "")
    val = _normalizza_chiave(raw_fgasnum)
    if val:
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
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        df = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    finally:
        conn.close()

    if df.empty:
        return df

    df["id_macchina"] = df["id_macchina"].apply(_normalizza_chiave)
    return df.drop_duplicates(subset=["id_macchina"], keep="first").reset_index(
        drop=True
    )


def sincronizza_date_da_excel():
    """
    Sincronizza le date dall'Excel verso il DB SQLite usando la chiave normalizzata
    senza sovrascrivere eventuali date già impostate sul DB se l'Excel non ha data.
    """
    excel_file = resolve_excel_path()
    if not os.path.exists(excel_file) or not os.path.exists(DB_PATH):
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
        try:
            cur = conn.cursor()
            for idx, r in df_xl.iterrows():
                data_str = estrai_data_verifica_riga_excel(r)
                if not data_str:
                    continue
                fgas_id = get_id_macchina(r, idx)
                cur.execute(
                    """
                    UPDATE macchine_hvac
                    SET scadenza_verifica = ?
                    WHERE id_macchina = ?
                      AND (scadenza_verifica IS NULL OR TRIM(scadenza_verifica) = '')
                    """,
                    (data_str, fgas_id),
                )
            conn.commit()
        finally:
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

        fgas_target = _normalizza_chiave(row_data.get("id_macchina", ""))
        if not fgas_target:
            return False, "Chiave id_macchina mancante per l'aggiornamento Excel."

        chiavi_xl = pd.Series(
            [_normalizza_chiave(get_id_macchina(r, idx)) for idx, r in df_xl.iterrows()],
            index=df_xl.index,
            dtype=str,
        )
        mask = chiavi_xl == fgas_target

        if not mask.any():
            return (
                False,
                f"Nessuna riga trovata su Excel per chiave '{fgas_target}'.",
            )

        col_gas = (
            "Tipo HCFC" if "Tipo HCFC" in df_xl.columns else "Refrigerante"
        )
        col_ncirc = (
            "N° Circuiti" if "N° Circuiti" in df_xl.columns else "N_Circuiti"
        )

        aggiornamenti = {
            col_ncirc: int(n_circ),
            "Carica_Circ_1_Kg": round(float(c1_kg), 2),
            "Carica_Circ_2_Kg": round(float(c2_kg), 2) if int(n_circ) == 2 else 0.0,
            "CO2_Circ_1_T": round(float(co2_c1), 2),
            "CO2_Circ_2_T": round(float(co2_c2), 2) if int(n_circ) == 2 else 0.0,
            "Carica Refrigerante (kg)": round(float(carica_tot), 2),
            "Tonn CO2 Eq": round(float(co2_tot), 2),
            "Modello": mod_val,
            "Matricola": matr_val,
            col_gas: gas_val,
            "Cod. Apparecchiatura": targa_val,
            "Stato Lavorazione": stato_val,
        }

        for col_name, val in aggiornamenti.items():
            if col_name not in df_xl.columns:
                df_xl[col_name] = None
            df_xl.loc[mask, col_name] = val

        with pd.ExcelWriter(
            excel_file, engine="openpyxl", mode="a", if_sheet_exists="replace"
        ) as writer:
            df_xl.to_excel(writer, sheet_name=foglio, index=False)

        n_righe = int(mask.sum())
        return (
            True,
            f"Excel ({foglio}) aggiornato ({n_righe} riga/e) su chiave={fgas_target}.",
        )
    except PermissionError:
        return False, "File Excel bloccato o aperto in un altro programma."
    except Exception as e:
        return False, f"Errore aggiornamento Excel: {e}"


def _popola_tabella_da_excel(cur, excel_file: str, ricrea_tabella: bool = False) -> int:
    if ricrea_tabella:
        cur.execute("DROP TABLE IF EXISTS macchine_hvac")

    cur.execute(
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

    cur.execute("PRAGMA table_info(macchine_hvac)")
    colonne_esistenti = {info[1] for info in cur.fetchall()}
    nuove_colonne = {
        "f_gas_attivo": "TEXT DEFAULT 'S'",
        "n_circuiti": "INTEGER DEFAULT 1",
        "carica_circ1": "REAL DEFAULT 0.0",
        "carica_circ2": "REAL DEFAULT 0.0",
        "co2_circ1": "REAL DEFAULT 0.0",
        "co2_circ2": "REAL DEFAULT 0.0",
    }
    for col_name, col_def in nuove_colonne.items():
        if col_name not in colonne_esistenti:
            cur.execute(
                f"ALTER TABLE macchine_hvac ADD COLUMN {col_name} {col_def}"
            )

    if not os.path.exists(excel_file):
        return 0

    xls = pd.ExcelFile(excel_file)
    foglio = (
        "Elenco di FGAS"
        if "Elenco di FGAS" in xls.sheet_names
        else xls.sheet_names[0]
    )
    df_excel = pd.read_excel(xls, sheet_name=foglio)

    inseriti = 0
    for idx, row in df_excel.iterrows():
        id_unic = get_id_macchina(row, idx)
        collocazione = str(row.get("Collocazione", "MCARTHUR_RM")).strip()
        nr_unita = str(
            row.get(
                "Descrizione",
                row.get("Unità / Macchina", row.get("Unità", "")),
            )
        ).strip()
        marca = str(row.get("Marca", "")).strip()
        modello = str(row.get("Modello", "")).strip()

        matr_raw = row.get("Matricola", "")
        matricola = (
            str(matr_raw).strip()
            if pd.notna(matr_raw) and str(matr_raw).strip()
            else "N/D"
        )

        gas_raw = row.get(
            "Tipo HCFC", row.get("Refrigerante", row.get("Tipo Gas", "R-410A"))
        )
        refrigerante = (
            str(gas_raw).strip()
            if pd.notna(gas_raw) and str(gas_raw).strip()
            else "R-410A"
        )

        co2_raw = row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", None))
        carica_col = row.get(
            "Carica Refrigerante (kg)", row.get("Carica (kg)", None)
        )

        if pd.notna(carica_col):
            carica_kg = round(float(carica_col), 2)
        elif pd.notna(co2_raw):
            carica_kg = calcola_carica_da_co2(float(co2_raw), refrigerante)
        else:
            carica_kg = 0.0

        if pd.notna(co2_raw):
            tonn_co2 = round(float(co2_raw), 2)
        elif carica_kg > 0:
            tonn_co2 = calcola_co2_tonnellate(carica_kg, refrigerante)
        else:
            tonn_co2 = 0.0

        codice_targa = str(
            row.get("Cod. Apparecchiatura", row.get("Codice Targa", ""))
        ).strip()
        scadenza = estrai_data_verifica_riga_excel(row)

        fgas_raw = row.get("F-Gas?", "S")
        f_gas_attivo = (
            str(fgas_raw).strip().upper()
            if pd.notna(fgas_raw) and str(fgas_raw).strip().upper() in ("S", "N")
            else "S"
        )

        raw_ncirc = row.get("N° Circuiti", row.get("N_Circuiti", 1))
        try:
            n_circ = (
                2
                if pd.notna(raw_ncirc)
                and str(raw_ncirc).strip() not in ("", "N.D.", "ND")
                and int(float(str(raw_ncirc).strip())) == 2
                else 1
            )
        except Exception:
            n_circ = 1

        c1_val = float(
            row.get(
                "Carica_Circ_1_Kg",
                carica_kg / 2 if n_circ == 2 else carica_kg,
            )
            if pd.notna(row.get("Carica_Circ_1_Kg"))
            else (carica_kg / 2 if n_circ == 2 else carica_kg)
        )
        c2_val = float(
            row.get(
                "Carica_Circ_2_Kg",
                carica_kg / 2 if n_circ == 2 else 0.0,
            )
            if pd.notna(row.get("
