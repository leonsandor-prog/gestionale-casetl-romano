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
      if mask.any():
        df_xl.loc[mask, col_name] = val

    tutti_fogli[foglio_target] = df_xl

    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
      for nome_foglio, frame in tutti_fogli.items():
        frame.to_excel(writer, sheet_name=nome_foglio, index=False)

    righe_aggiornate = int(mask.sum())
    return True, f"Righe aggiornate: {righe_aggiornate}"
  except Exception as e:
    return False, f"Errore aggiornamento Excel: {e}"


def init_db(force_reload: bool = False):
  conn = sqlite3.connect(DB_PATH, timeout=10.0)
  cursor = conn.cursor()

  cursor.execute("""
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
        """)

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

  cursor.execute("SELECT COUNT(*) FROM macchine_hvac")
  cnt = cursor.fetchone()[0]

  if (cnt == 0 or force_reload) and os.path.exists(EXCEL_PATH):
    xls = pd.ExcelFile(EXCEL_PATH)
    df_excel = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    cursor.execute("DELETE FROM macchine_hvac")

    for idx, row in df_excel.iterrows():
      collocazione = (
          str(row.get("Collocazione", "MCARTHUR_RM")).strip()
          if pd.notna(row.get("Collocazione"))
          else "MCARTHUR_RM"
      )
      nr_unita = str(
          row.get(
              "Descrizione", row.get("Unità / Macchina", row.get("Unità", ""))
          )
          if pd.notna(
              row.get(
                  "Descrizione",
                  row.get("Unità / Macchina", row.get("Unità", "")),
              )
          )
          else ""
      ).strip()
      marca = (
          str(row.get("Marca", "")).strip() if pd.notna(row.get("Marca")) else ""
      )
      modello = (
          str(row.get("Modello", "")).strip()
          if pd.notna(row.get("Modello"))
          else ""
      )
      matricola = str(
          row.get("Matricola", modello)
          if pd.notna(row.get("Matricola"))
          else modello
      ).strip()

      raw_gas = row.get(
          "Tipo HCFC", row.get("Refrigerante", row.get("Tipo Gas", "R-410A"))
      )
      refrigerante = (
          str(raw_gas).strip()
          if pd.notna(raw_gas) and str(raw_gas).strip()
          else "R-410A"
      )

      tonn_co2 = _safe_float(
          row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", 0.0)), 0.0
      )
      carica_col = row.get(
          "Carica Refrigerante (kg)", row.get("Carica (kg)", None)
      )
      gwp_val = get_gwp(refrigerante)

      if carica_col is not None and pd.notna(carica_col):
        carica_kg = _safe_float(carica_col, 0.0)
      else:
        carica_kg = (
            round((tonn_co2 * 1000.0) / gwp_val, 2) if tonn_co2 > 0 else 0.0
        )

      if tonn_co2 == 0.0 and carica_kg > 0:
        tonn_co2 = calcola_co2_tonnellate(carica_kg, refrigerante)

      raw_targa = row.get("Cod. Apparecchiatura", row.get("Codice Targa", ""))
      codice_targa = str(raw_targa).strip() if pd.notna(raw_targa) else ""
      scadenza = estrai_data_verifica_riga_excel(row)

      raw_ncirc = row.get("N° Circuiti", row.get("N_Circuiti", 1))
      n_circ = 2 if int(_safe_float(raw_ncirc, 1)) == 2 else 1

      c1_val = (
          _safe_float(
              row.get("Carica_Circ_1_Kg"),
              carica_kg / 2.0 if n_circ == 2 else carica_kg,
          )
          if pd.notna(row.get("Carica_Circ_1_Kg"))
          else (carica_kg / 2.0 if n_circ == 2 else carica_kg)
      )
      c2_val = (
          _safe_float(
              row.get("Carica_Circ_2_Kg"),
              carica_kg / 2.0 if n_circ == 2 else 0.0,
          )
          if pd.notna(row.get("Carica_Circ_2_Kg"))
          else (carica_kg / 2.0 if n_circ == 2 else 0.0)
      )
      co2_1_val = calcola_co2_tonnellate(c1_val, refrigerante)
      co2_2_val = (
          calcola_co2_tonnellate(c2_val, refrigerante) if n_circ == 2 else 0.0
      )

      stato_xl = (
          str(row.get("Stato Lavorazione", "Da Lavorare")).strip()
          if pd.notna(row.get("Stato Lavorazione"))
          else "Da Lavorare"
      )
      if stato_xl not in ("Da Lavorare", "Completato"):
        stato_xl = "Da Lavorare"

      fgasnum_val = (
          str(row.get("fgasnum", "")).strip()
          if pd.notna(row.get("fgasnum"))
          else ""
      )
      id_unic = (
          f"{fgasnum_val}_{idx}"
          if fgasnum_val
          else f"{idx}_{nr_unita}_{matricola}"
      )

      cursor.execute(
          """
                INSERT INTO macchine_hvac
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
              stato_xl,
              n_circ,
              c1_val,
              c2_val,
              co2_1_val,
              co2_2_val,
          ),
      )

  conn.commit()
  conn.close()
  sincronizza_date_da_excel()


def _inserisci_firma_in_cella(cell, firma_path: str):
  cell.text = ""
  p_firma = cell.paragraphs[0]
  run = p_firma.add_run()
  run.add_picture(firma_path, width=Inches(1.2))


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
    co2_c1_calc,
    co2_c2_calc,
    carica_tot_calc,
    co2_tot_calc,
    oggi,
    target_dir=OUTPUT_DIR,
    data_intervento_custom=None,
    scadenza_custom=None,
):
  os.makedirs(target_dir, exist_ok=True)
  if not os.path.exists(TEMPLATE_FGAS_
