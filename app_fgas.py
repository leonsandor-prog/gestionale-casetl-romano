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
]
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"
OUTPUT_DIR = "Report_FGAS_Generati_2026"
FIRMA_PATH = "firma.jpg"
PIN_RISERVATO_FGAS = "3177"

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


def resolve_excel_path() -> str:
    for path in CANDIDATE_EXCEL_PATHS:
        if os.path.exists(path):
            return path
    return CANDIDATE_EXCEL_PATHS[0]


EXCEL_PATH = resolve_excel_path()


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


def parse_data_sicura(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val
    if hasattr(val, "to_pydatetime"):
        try:
            return val.to_pydatetime()
        except Exception:
            return None

    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none", "n/d", "n.d."):
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            continue
    return None


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
        foglio = xls.sheet_names[0]
        df_xl = pd.read_excel(xls, sheet_name=foglio)

        col_unita = next(
            (
                c
                for c in [
                    "Unità / Macchina",
                    "Unità",
                    "Descrizione",
                    "nr_unita",
                ]
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
                for c in [
                    "Cod. Apparecchiatura",
                    "Codice Targa",
                    "codice_targa",
                ]
                if c in df_xl.columns
            ),
            None,
        )

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
        if col_targa and str(row_data.get("codice_targa", "")).strip():
            mask = mask | (
                df_xl[col_targa].astype(str).str.strip()
                == str(row_data["codice_targa"]).strip()
            )

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

        with pd.ExcelWriter(
            excel_file, engine="openpyxl", mode="a", if_sheet_exists="replace"
        ) as writer:
            df_xl.to_excel(writer, sheet_name=foglio, index=False)

        return True, "Excel aggiornato correttamente."
    except Exception as e:
        return False, f"Errore aggiornamento Excel: {e}"


def init_db():
    excel_file = resolve_excel_path()
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

    cursor.execute("PRAGMA table_info(macchine_hvac)")
    colonne_esistenti = {info[1] for info in cursor.fetchall()}
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
            cursor.execute(
                f"ALTER TABLE macchine_hvac ADD COLUMN {col_name} {col_def}"
            )

    if os.path.exists(excel_file):
        xls = pd.ExcelFile(excel_file)
        df_excel = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

        for idx, row in df_excel.iterrows():
            collocazione = str(row.get("Collocazione", "MCARTHUR_RM")).strip()
            nr_unita = str(
                row.get(
                    "Unità / Macchina",
                    row.get("Unità", row.get("Descrizione", "")),
                )
            ).strip()
            marca = str(row.get("Marca", "")).strip()
            modello = str(row.get("Modello", "")).strip()
            matricola_raw = row.get("Matricola", modello)
            matricola = (
                str(matricola_raw).strip()
                if pd.notna(matricola_raw) and str(matricola_raw).strip()
                else modello
            )

            gas_raw = row.get(
                "Tipo HCFC", row.get("Refrigerante", row.get("Tipo Gas", "R-410A"))
            )
            refrigerante = (
                str(gas_raw).strip()
                if pd.notna(gas_raw) and str(gas_raw).strip()
                else "R-410A"
            )

            co2_raw = row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", 0.0))
            tonn_co2 = float(co2_raw) if pd.notna(co2_raw) else 0.0

            carica_col = row.get(
                "Carica Refrigerante (kg)", row.get("Carica (kg)", 0.0)
            )
            gwp_val = get_gwp(refrigerante)
            carica_kg = (
                float(carica_col)
                if pd.notna(carica_col) and float(carica_col) != 0.0
                else ((tonn_co2 * 1000.0) / gwp_val if tonn_co2 > 0 else 0.0)
            )
            if tonn_co2 == 0.0 and carica_kg > 0:
                tonn_co2 = calcola_co2_tonnellate(carica_kg, refrigerante)

            codice_targa = str(
                row.get("Cod. Apparecchiatura", row.get("Codice Targa", ""))
            ).strip()

            scad_raw = row.get(
                "Scadenza verifica", row.get("Scadenza Verifica", "")
            )
            dt_scad = parse_data_sicura(scad_raw)
            scadenza = (
                dt_scad.strftime("%d/%m/%Y")
                if dt_scad
                else (str(scad_raw).strip() if pd.notna(scad_raw) else "")
            )

            fgas_raw = row.get("F-Gas?", "S")
            f_gas_attivo = (
                str(fgas_raw).strip().upper()
                if pd.notna(fgas_raw) and str(fgas_raw).strip()
                else "S"
            )

            raw_ncirc = row.get("N° Circuiti", row.get("N_Circuiti", 1))
            try:
                n_circ = (
                    2
                    if pd.notna(raw_ncirc)
                    and str(raw_ncirc).strip() not in ("", "N.D.", "ND")
                    and int(float(raw_ncirc)) == 2
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
                if pd.notna(row.get("Carica_Circ_2_Kg"))
                else (carica_kg / 2 if n_circ == 2 else 0.0)
            )
            co2_1_val = calcola_co2_tonnellate(c1_val, refrigerante)
            co2_2_val = (
                calcola_co2_tonnellate(c2_val, refrigerante)
                if n_circ == 2
                else 0.0
            )

            fgasnum_raw = row.get("fgasnum", "")
            if pd.notna(fgasnum_raw) and str(fgasnum_raw).strip():
                id_unic = str(fgasnum_raw).strip()
            else:
                id_unic = f"{nr_unita}_{modello}_{matricola}_{idx}"

            cursor.execute(
                """
                INSERT OR IGNORE INTO macchine_hvac
                (id_macchina, collocazione, nr_unita, marca, modello, matricola, refrigerante, tonn_co2_eq, carica_kg, codice_targa, scadenza_verifica, f_gas_attivo, stato_compilazione, n_circuiti, carica_circ1, carica_circ2, co2_circ1, co2_circ2)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    f_gas_attivo,
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
    data_intervento_custom=None,
    scadenza_custom=None,
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(TEMPLATE_FGAS_PATH):
        return None, "Template Word non trovato."

    doc = Document(TEMPLATE_FGAS_PATH)
    data_str = data_intervento_custom or oggi.strftime("%d/%m/%Y")
    scad_str = scadenza_custom or str(row.get("scadenza_verifica") or data_str)

    mappa = {
        "{{UNITA}}": str(row.get("nr_unita", "")),
        "{{MARCA}}": str(row.get("marca", "")),
        "{{MODELLO}}": mod_edit,
        "{{MATRICOLA}}": matr_edit,
        "{{TIPO_GAS}}": gas_edit,
        "{{CARICA_KG}}": f"{carica_tot_calc:.2f}",
        "{{CARICA_KG 1}}": f"{c1_edit:.2f}",
        "{{CARICA_KG 2}}": f"{c2_edit:.2f}" if n_circ_edit == 2 else "",
        "{{CO2_EQ}}": f"{co2_tot_calc:.2f}",
        "{{CO2_EQ 1}}": f"{co2_c1_calc:.2f}",
        "{{CO2_EQ 2}}": f"{co2_c2_calc:.2f}" if n_circ_edit == 2 else "",
        "{{CIRQUITTI}}": str(n_circ_edit),
        "{{ CIRQUITTI}}": str(n_circ_edit),
        "{{COD_APP}}": targa_edit,
        "{{DATA_INTERVENTO}}": data_str,
        "{{SCADENZA_VERIFICA}}": scad_str,
        "{{ESITO_CIRC1}}": "ASSENZA PERDITE",
    }

    for p in doc.paragraphs:
        for k, v in mappa.items():
            if k in p.text:
                p.text = p.text.replace(k, str(v))

    firma_inserita = False
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells:
                if "{{FIRMA}}" in c.text:
                    for p in c.paragraphs:
                        if "{{FIRMA}}" in p.text:
                            p.text = p.text.replace("{{FIRMA}}", "")
                    if os.path.exists(FIRMA_PATH):
                        _inserisci_firma_in_cella(c, FIRMA_PATH)
                        firma_inserita = True
                    continue

                for p in c.paragraphs:
                    for k, v in mappa.items():
                        if k in p.text:
                            p.text = p.text.replace(k, str(v))

    if not firma_inserita and os.path.exists(FIRMA_PATH):
        for t in doc.tables:
            for r in t.rows:
                for c in r.cells:
                    if c.text.strip().lower().startswith("firma"):
                        _inserisci_firma_in_cella(c, FIRMA_PATH)
                        firma_inserita = True
                        break
                if firma_inserita:
                    break
            if firma_inserita:
                break

    nome_file = (
        f"Report_FGAS_{sanitize_filename(row.get('marca', ''))}_{sanitize_filename(mod_edit)}"
        f"_Unita_{sanitize_filename(row.get('nr_unita', ''))}_{sanitize_filename(row.get('id_macchina', ''))}.docx"
    )
    out_file = os.path.join(OUTPUT_DIR, nome_file)
    doc.save(out_file)
    return out_file, None


def genera_zip
