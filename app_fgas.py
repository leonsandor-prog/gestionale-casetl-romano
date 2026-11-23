import sqlite3
import os
import re
import io
import zipfile
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


def estrai_data_verifica_riga_excel(row) -> str:
    """
    Legge la data da 'Data ultima verifica' (o 'Scadenza verifica' se la prima è vuota)
    e la restituisce come stringa 'GG/MM/AAAA'.
    """
    for col in ["Data ultima verifica", "Scadenza verifica", "Scadenza Verifica"]:
        if col in row.index:
            val = row.get(col)
            if pd.notna(val) and str(val).strip() not in ("", "nan", "NaT", "None"):
                if isinstance(val, (datetime, pd.Timestamp)):
                    return val.strftime("%d/%m/%Y")
                dt_parsed = pd.to_datetime(str(val).strip(), errors="coerce", dayfirst=False)
                if pd.notna(dt_parsed):
                    return dt_parsed.strftime("%d/%m/%Y")
                return str(val).strip()
    return ""


def normalizza_data_anno_corrente(data_raw, anno_corrente: int):
    """
    Mantiene invariati giorno e mese dalla data verifica e imposta l'anno con anno_corrente.
    Restituisce (stringa_dd_mm_yyyy, numero_mese_int, cartella_mese_str).
    """
    dt = None

    if isinstance(data_raw, (datetime, pd.Timestamp)) and pd.notna(data_raw):
        dt = datetime(data_raw.year, data_raw.month, data_raw.day)
    else:
        s = str(data_raw or "").strip()
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
            dt_pd = pd.to_datetime(s, errors="coerce")
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
    """
    Legge le date reali ('Data ultima verifica' / 'Scadenza verifica') dall'Excel
    e aggiorna scadenza_verifica nel DB SQLite per ogni unità.
    """
    if not os.path.exists(EXCEL_PATH):
        return

    try:
        xls = pd.ExcelFile(EXCEL_PATH)
        df_xl = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

        col_unita = next(
            (c for c in ["Descrizione", "Unità / Macchina", "Unità", "nr_unita"] if c in df_xl.columns),
            None,
        )
        col_matr = next((c for c in ["Matricola", "matricola"] if c in df_xl.columns), None)
        col_targa = next(
            (c for c in ["Cod. Apparecchiatura", "Codice Targa", "codice_targa"] if c in df_xl.columns),
            None,
        )

        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()

        for _, r in df_xl.iterrows():
            data_str = estrai_data_verifica_riga_excel(r)
            if not data_str:
                continue

            unita_v = str(r.get(col_unita, "")).strip() if col_unita and pd.notna(r.get(col_unita)) else ""
            matr_v = str(r.get(col_matr, "")).strip() if col_matr and pd.notna(r.get(col_matr)) else ""
            targa_v = str(r.get(col_targa, "")).strip() if col_targa and pd.notna(r.get(col_targa)) else ""

            if unita_v and matr_v:
                cur.execute(
                    "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE TRIM(nr_unita) = ? AND TRIM(matricola) = ?",
                    (data_str, unita_v, matr_v),
                )
            elif targa_v and targa_v != "GF":
                cur.execute(
                    "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE TRIM(codice_targa) = ?",
                    (data_str, targa_v),
                )
            elif unita_v:
                cur.execute(
                    "UPDATE macchine_hvac SET scadenza_verifica = ? WHERE TRIM(nr_unita) = ?",
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
        foglio = xls.sheet_names[0]
        df_xl = pd.read_excel(xls, sheet_name=foglio)

        col_unita = next(
            (c for c in ["Descrizione", "Unità / Macchina", "Unità", "nr_unita"] if c in df_xl.columns),
            None,
        )
        col_matr = next((c for c in ["Matricola", "matricola"] if c in df_xl.columns), None)
        col_targa = next(
            (c for c in ["Cod. Apparecchiatura", "Codice Targa", "codice_targa"] if c in df_xl.columns),
            None,
        )
        col_gas = "Tipo HCFC" if "Tipo HCFC" in df_xl.columns else "Refrigerante"
        col_ncirc = "N° Circuiti" if "N° Circuiti" in df_xl.columns else "N_Circuiti"

        mask = pd.Series([False] * len(df_xl))
        if col_unita and str(row_data["nr_unita"]).strip():
            mask = mask | (df_xl[col_unita].astype(str).str.strip() == str(row_data["nr_unita"]).strip())
        if col_matr and str(row_data["matricola"]).strip():
            mask = mask | (df_xl[col_matr].astype(str).str.strip() == str(row_data["matricola"]).strip())
        if col_targa and str(row_data["codice_targa"]).strip() and str(row_data["codice_targa"]).strip() != "GF":
            mask = mask | (df_xl[col_targa].astype(str).str.strip() == str(row_data["codice_targa"]).strip())

        aggiornamenti = {
            col_ncirc: int(n_circ),
            "Carica_Circ_1_Kg": round(float(c1_kg), 2),
            "Carica_Circ_2_Kg": round(float(c2_kg), 2) if n_circ == 2 else 0.0,
            "CO2_Circ_1_T": round(float(co2_c1), 2),
            "CO2_Circ_2_T": round(float(co2_c2), 2) if n_circ == 2 else 0.0,
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
            nr_unita = str(row.get("Descrizione", row.get("Unità / Macchina", row.get("Unità", "")))).strip()
            marca = str(row.get("Marca", "")).strip()
            modello = str(row.get("Modello", "")).strip()
            matricola = str(row.get("Matricola", modello) if pd.notna(row.get("Matricola")) else modello).strip()
            refrigerante = str(
                row.get("Tipo HCFC", row.get("Refrigerante", row.get("Tipo Gas", "R-410A")))
                if pd.notna(row.get("Tipo HCFC", row.get("Refrigerante", "R-410A")))
                else "R-410A"
            ).strip()
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
            scadenza = estrai_data_verifica_riga_excel(row)

            raw_ncirc = row.get("N° Circuiti", row.get("N_Circuiti", 1))
            try:
                n_circ = 2 if pd.notna(raw_ncirc) and int(float(str(raw_ncirc).strip())) == 2 else 1
            except Exception:
                n_circ = 1

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

            fgasnum_val = str(row.get("fgasnum", "")).strip()
            id_unic = f"{fgasnum_val}_{nr_unita}_{matricola}" if fgasnum_val else f"{nr_unita}_{modello}_{matricola}"

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
    if not os.path.exists(TEMPLATE_FGAS_PATH):
        return None, "Template Word non trovato."

    doc = Document(TEMPLATE_FGAS_PATH)
    data_str = data_intervento_custom if data_intervento_custom else oggi.strftime("%d/%m/%Y")
    scadenza_str = scadenza_custom if scadenza_custom else str(row["scadenza_verifica"])

    mappa = {
        "{{UNITA}}": str(row["nr_unita"]),
        "{{MARCA}}": str(row["marca"]),
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
        "{{SCADENZA_VERIFICA}}": scadenza_str,
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
        f"Report_FGAS_{sanitize_filename(row['marca'])}_{sanitize_filename(mod_edit)}"
        f"_Unita_{sanitize_filename(row['nr_unita'])}.docx"
    )
    out_file = os.path.join(target_dir, nome_file)
    doc.save(out_file)
    return out_file, None


def genera_zip_mensile_anno_corrente(anno_corrente: int):
    """
    Legge direttamente il foglio Excel aggiornato ('Elenco di FGAS'), mantiene
    invariati giorno e mese di 'Data ultima verifica' / 'Scadenza verifica'
    sostituendo solo l'anno con anno_corrente, genera i rapportini per le unità
    F-Gas attive ('F-Gas?' == 'S') divisi per mese e crea uno ZIP scaricabile.
    """
    if not os.path.exists(TEMPLATE_FGAS_PATH):
        return None, 0, "Template Word non trovato."

    if not os.path.exists(EXCEL_PATH):
        return None, 0, "File Excel non trovato."

    sincronizza_date_da_excel()

    xls = pd.ExcelFile(EXCEL_PATH)
    df_xl = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_db = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    base_batch_dir = os.path.join(OUTPUT_DIR, f"Batch_Mensile_{anno_corrente}")
    os.makedirs(base_batch_dir, exist_ok=True)

    zip_buffer = io.BytesIO()
    oggi_now = datetime.now()
    tot_generati = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, r_xl in df_xl.iterrows():
            fgas_flag = str(r_xl.get("F-Gas?", "S")).strip().upper()
            if fgas_flag == "N":
                continue

            desc_unita = str(r_xl.get("Descrizione", r_xl.get("Unità / Macchina", ""))).strip()
            if any(k in desc_unita.upper() for k in ["DISMESS", "NON INDIVIDUATA", "DOPP."]):
                continue

            data_orig = estrai_data_verifica_riga_excel(r_xl)
            data_corr_str, _, cartella_mese = normalizza_data_anno_corrente(data_orig, anno_corrente)
            if not data_corr_str or not cartella_mese:
                continue

            matr_xl = str(r_xl.get("Matricola", "") if pd.notna(r_xl.get("Matricola")) else "").strip()
            targa_xl = str(r_xl.get("Cod. Apparecchiatura", "") if pd.notna(r_xl.get("Cod. Apparecchiatura")) else "").strip()

            # Recupera eventuali dati aggiornati nel DB (es. circuiti, cariche modificate in campo)
            match_db = pd.DataFrame()
            if not df_db.empty:
                if desc_unita and matr_xl:
                    match_db = df_db[
                        (df_db["nr_unita"].astype(str).str.strip() == desc_unita)
                        & (df_db["matricola"].astype(str).str.strip() == matr_xl)
                    ]
                if match_db.empty and targa_xl and targa_xl != "GF":
                    match_db = df_db[df_db["codice_targa"].astype(str).str.strip() == targa_xl]

            gas = str(
                r_xl.get("Tipo HCFC", r_xl.get("Refrigerante", "R-410A"))
                if pd.notna(r_xl.get("Tipo HCFC", r_xl.get("Refrigerante", "R-410A")))
                else "R-410A"
            ).strip()

            carica_xl = float(r_xl.get("Carica Refrigerante (kg)") or 0.0) if pd.notna(r_xl.get("Carica Refrigerante (kg)")) else 0.0
            raw_nc = r_xl.get("N° Circuiti", r_xl.get("N_Circuiti", 1))
            try:
                n_circ = 2 if pd.notna(raw_nc) and int(float(str(raw_nc).strip())) == 2 else 1
            except Exception:
                n_circ = 1

            c1 = float(r_xl.get("Carica_Circ_1_Kg")) if pd.notna(r_xl.get("Carica_Circ_1_Kg")) else (carica_xl / 2.0 if n_circ == 2 else carica_xl)
            c2 = float(r_xl.get("Carica_Circ_2_Kg")) if pd.notna(r_xl.get("Carica_Circ_2_Kg")) else (carica_xl / 2.0 if n_circ == 2 else 0.0)

            if not match_db.empty:
                db_r = match_db.iloc[0]
                n_circ = 2 if pd.notna(db_r.get("n_circuiti")) and int(db_r.get("n_circuiti")) == 2 else n_circ
                if float(db_r.get("carica_circ1") or 0.0) > 0:
                    c1 = float(db_r.get("carica_circ1"))
                    c2 = float(db_r.get("carica_circ2") or 0.0)
                if pd.notna(db_r.get("refrigerante")) and str(db_r.get("refrigerante")).strip():
                    gas = str(db_r.get("refrigerante")).strip()

            co2_1 = calcola_co2_tonnellate(c1, gas)
            co2_2 = calcola_co2_tonnellate(c2, gas) if n_circ == 2 else 0.0
            co2_tot = round(co2_1 + co2_2, 2)

            row_payload = {
                "nr_unita": desc_unita,
                "marca": str(r_xl.get("Marca", "") if pd.notna(r_xl.get("Marca")) else "").strip(),
                "scadenza_verifica": data_corr_str,
            }
            mod_val = str(r_xl.get("Modello", "") if pd.notna(r_xl.get("Modello")) else "").strip()

            mese_dir = os.path.join(base_batch_dir, cartella_mese)
            out_file, _ = genera_report_docx(
                row=row_payload,
                mod_edit=mod_val,
                matr_edit=matr_xl,
                gas_edit=gas,
                targa_edit=targa_xl,
                stato_edit="Completato",
                n_circ_edit=n_circ,
                c1_edit=c1,
                c2_edit=c2,
                co2_c1_calc=co2_1,
                co2_c2_calc=co2_2,
                carica_tot_calc=round(c1 + c2, 2),
                co2_tot_calc=co2_tot,
                oggi=oggi_now,
                target_dir=mese_dir,
                data_intervento_custom=data_corr_str,
                scadenza_custom=data_corr_str,
            )

            if out_file and os.path.exists(out_file):
                fgas_id = str(r_xl.get("fgasnum", "")).strip()
                arc_name = (
                    f"{fgas_id}_{os.path.basename(out_file)}"
                    if fgas_id
                    else os.path.basename(out_file)
                )
                zf.write(out_file, arcname=os.path.join(cartella_mese, arc_name))
                tot_generati += 1

    zip_buffer.seek(0)
    return zip_buffer.getvalue(), tot_generati, None


def render_scheda_unita(row, prefix, oggi, expanded=False):
    key_id = f"{prefix}_{sanitize_filename(row['id_macchina'])}"
    stato = row["stato_compilazione"]
    pallino = "🟢" if stato == "Completato" else "🟡"

    n_circ_db = 2 if pd.notna(row.get("n_circuiti")) and int(row.get("n_circuiti")) == 2 else 1
    carica_db = float(row.get("carica_kg") or 0.0)
    c1_db = float(row.get("carica_circ1") or (carica_db / 2 if n_circ_db == 2 else carica_db))
    c2_db = float(row.get("carica_circ2") or (carica_db / 2 if n_circ_db == 2 else 0.0))
    data_valida_str, _, _ = normalizza_data_anno_corrente(row.get("scadenza_verifica"), oggi.year)
    if not data_valida_str:
        data_valida_str = oggi.strftime("%d/%m/%Y")

    with st.expander(
        f"{pallino} Unità {row['nr_unita']} — {row['marca']} {row['modello']} | Circuiti: `{n_circ_db}` | Data Verifica: `{data_valida_str}` | Targa: `{row['codice_targa']}`",
        expanded=expanded,
    ):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Dati Impianto & Identificativi**")
            st.write(f"- **Collocazione:** `{row['collocazione']}`")
            st.write(f"- **Matricola:** `{row['matricola']}`")
            st.write(f"- **Cod. Apparecchiatura:** `{row['codice_targa']}`")
            st.write(f"- **Data Verifica (Anno Corrente):** `{data_valida_str}`")
            st.write(f"- **N° Circuiti registrati:** `{n_circ_db}`")
        with c2:
            st.markdown("**Parametri F-GAS**")
            st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
            st.write(f"- **Carica Totale:** `{row['carica_kg']:.2f} kg`")
            st.write(f"- **Tonn. CO2 Eq Totale:** `{row['tonn_co2_eq']:.2f} t`")

        st.divider()

        n_circ_edit = st.selectbox(
            "Numero circuiti impianto (default 1 — imposta 2 se doppio circuito)",
            options=[1, 2],
            index=1 if n_circ_db == 2 else 0,
            key=f"ncirc_{key_id}",
        )

        state_key_nc = f"last_ncirc_{key_id}"
        if st.session_state.get(state_key_nc) != n_circ_edit:
            if n_circ_edit == 2:
                if c2_db > 0:
                    st.session_state[f"c1_val_{key_id}"] = round(c1_db, 2)
                    st.session_state[f"c2_val_{key_id}"] = round(c2_db, 2)
                else:
                    meta = round(carica_db / 2.0, 2)
                    st.session_state[f"c1_val_{key_id}"] = meta
                    st.session_state[f"c2_val_{key_id}"] = round(carica_db - meta, 2)
            else:
                st.session_state[f"c1_val_{key_id}"] = round(carica_db, 2)
                st.session_state[f"c2_val_{key_id}"] = 0.0
            st.session_state[state_key_nc] = n_circ_edit

        with st.form(key=f"form_{key_id}"):
            st.markdown("##### ✏️ Verifica e Modifica Dati in Campo")
            nc1, nc2, nc3 = st.columns(3)
            with nc1:
                mod_edit = st.text_input("Modello", value=str(row["modello"]), key=f"mod_{key_id}")
                matr_edit = st.text_input("Matricola", value=str(row["matricola"]), key=f"matr_{key_id}")
            with nc2:
                gas_lista = ["R-410A", "R-407C", "R-32", "R-134a", "R-449A"]
                idx_gas = gas_lista.index(row["refrigerante"]) if row["refrigerante"] in gas_lista else 0
                gas_edit = st.selectbox("Refrigerante", gas_lista, index=idx_gas, key=f"gas_{key_id}")
                targa_edit = st.text_input("Codice Apparecchiatura (Targa)", value=str(row["codice_targa"]), key=f"targa_{key_id}")
            with nc3:
                stato_edit = st.selectbox(
                    "Stato Lavorazione",
                    ["Da Lavorare", "Completato"],
                    index=0 if stato == "Da Lavorare" else 1,
                    key=f"st_{key_id}",
                )
                st.caption(f"GWP applicato ({gas_edit}): **{get_gwp(gas_edit):.0f}**")

            st.markdown("**Carica Refrigerante per Circuito e Calcolo Automatico Tonn. CO2 Eq**")
            if n_circ_edit == 2:
                cc1, cc2 = st.columns(2)
                with cc1:
                    c1_edit = st.number_input(
                        "Carica Circuito 1 (kg)",
                        min_value=0.0,
                        step=0.1,
                        format="%.2f",
                        value=float(st.session_state.get(f"c1_val_{key_id}", c1_db)),
                        key=f"in_c1_{key_id}",
                    )
                    co2_c1_calc = calcola_co2_tonnellate(c1_edit, gas_edit)
                    st.info(f"Tonn. CO2 Eq Circuito 1 (calcolate): **{co2_c1_calc:.2f} t**")
                with cc2:
                    c2_edit = st.number_input(
                        "Carica Circuito 2 (kg)",
                        min_value=0.0,
                        step=0.1,
                        format="%.2f",
                        value=float(st.session_state.get(f"c2_val_{key_id}", c2_db)),
                        key=f"in_c2_{key_id}",
                    )
                    co2_c2_calc = calcola_co2_tonnellate(c2_edit, gas_edit)
                    st.info(f"Tonn. CO2 Eq Circuito 2 (calcolate): **{co2_c2_calc:.2f} t**")
            else:
                c1_edit = st.number_input(
                    "Carica Circuito 1 (kg)",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                    value=float(st.session_state.get(f"c1_val_{key_id}", carica_db)),
                    key=f"in_c1_{key_id}",
                )
                c2_edit = 0.0
                co2_c1_calc = calcola_co2_tonnellate(c1_edit, gas_edit)
                co2_c2_calc = 0.0
                st.info(f"Tonn. CO2 Eq Circuito 1 (calcolate): **{co2_c1_calc:.2f} t**")

            carica_tot_calc = round(float(c1_edit) + float(c2_edit), 2)
            co2_tot_calc = round(float(co2_c1_calc) + float(co2_c2_calc), 2)
            st.markdown(
                f"**Riepilogo automatico:** Carica Totale = **`{carica_tot_calc:.2f} kg`** | Tonn. CO2 Eq Totale = **`{co2_tot_calc:.2f} t`**"
            )

            btn_aggiorna = st.form_submit_button("💾 Salva su DB & Excel + Genera Rapportino F-GAS (Firmato)")

            if btn_aggiorna:
                st.session_state[f"c1_val_{key_id}"] = float(c1_edit)
                st.session_state[f"c2_val_{key_id}"] = float(c2_edit)

                conn_up = sqlite3.connect(DB_PATH)
                cur_up = conn_up.cursor()
                cur_up.execute(
                    """
                    UPDATE macchine_hvac
                    SET modello = ?, matricola = ?, refrigerante = ?, carica_kg = ?, tonn_co2_eq = ?, codice_targa = ?, stato_compilazione = ?,
                        n_circuiti = ?, carica_circ1 = ?, carica_circ2 = ?, co2_circ1 = ?, co2_circ2 = ?
                    WHERE id_macchina = ?
                    """,
                    (
                        mod_edit,
                        matr_edit,
                        gas_edit,
                        carica_tot_calc,
                        co2_tot_calc,
                        targa_edit,
                        stato_edit,
                        int(n_circ_edit),
                        float(c1_edit),
                        float(c2_edit),
                        float(co2_c1_calc),
                        float(co2_c2_calc),
                        row["id_macchina"],
                    ),
                )
                conn_up.commit()
                conn_up.close()

                ok_xl, msg_xl = salva_su_excel(
                    row,
                    int(n_circ_edit),
                    c1_edit,
                    c2_edit,
                    co2_c1_calc,
                    co2_c2_calc,
                    carica_tot_calc,
                    co2_tot_calc,
                    mod_edit,
                    matr_edit,
                    gas_edit,
                    targa_edit,
                    stato_edit,
                )

                out_file, err_doc = genera_report_docx(
                    row,
                    mod_edit,
                    matr_edit,
                    gas_edit,
                    targa_edit,
                    stato_edit,
                    int(n_circ_edit),
                    c1_edit,
                    c2_edit,
                    co2_c1_calc,
                    co2_c2_calc,
                    carica_tot_calc,
                    co2_tot_calc,
                    oggi,
                    data_intervento_custom=data_valida_str,
                    scadenza_custom=data_valida_str,
                )
                if out_file:
                    st.session_state[f"last_generated_{key_id}"] = out_file

                if ok_xl:
                    st.success(f"Salvato su DB e Excel ({msg_xl}) — Rapportino generato!")
                else:
                    st.warning(f"Salvato su DB, ma avviso Excel: {msg_xl}")
                if err_doc:
                    st.error(err_doc)
                st.rerun()

        last_file = st.session_state.get(f"last_generated_{key_id}")
        if not last_file:
            possible_path = os.path.join(
                OUTPUT_DIR,
                f"Report_FGAS_{sanitize_filename(row['marca'])}_{sanitize_filename(row['modello'])}"
                f"_Unita_{sanitize_filename(row['nr_unita'])}.docx",
            )
            if os.path.exists(possible_path):
                last_file = possible_path

        if last_file and os.path.exists(last_file):
            with open(last_file, "rb") as f_dl:
                st.download_button(
                    label=f"📥 Scarica Rapportino F-GAS Firmato ({os.path.basename(last_file)})",
                    data=f_dl,
                    file_name=os.path.basename(last_file),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"btn_dl_{key_id}",
                )


init_db()

st.set_page_config(page_title="CBRE GWS - F-GAS Castel Romano", layout="wide")

oggi = datetime.now()
anno_corrente = oggi.year

st.sidebar.title("CBRE GWS - Castel Romano")
st.sidebar.markdown("### 🗂️ Registro F-GAS 2026")
menu = st.sidebar.radio("Sezione:", ["Dashboard & Impianti", "Scan Targhetta (Foto/Camera)"])

st.sidebar.divider()
st.sidebar.markdown("### 📦 Esportazione Massiva")
if st.sidebar.button("📦 Genera Tutti i Rapportini per Mese (Anno Corrente)"):
    with st.spinner("Lettura date verifica Excel e generazione rapportini per mese..."):
        zip_bytes, count_doc, err_zip = genera_zip_mensile_anno_corrente(anno_corrente)
        if err_zip:
            st.sidebar.error(err_zip)
        else:
            st.session_state["zip_mensile_data"] = zip_bytes
            st.session_state["zip_mensile_count"] = count_doc

if "zip_mensile_data" in st.session_state and st.session_state["zip_mensile_data"]:
    st.sidebar.success(f"Pronti {st.session_state['zip_mensile_count']} rapportini divisi per mese!")
    st.sidebar.download_button(
        label=f"⬇️ Scarica ZIP Rapportini {anno_corrente} per Mese",
        data=st.session_state["zip_mensile_data"],
        file_name=f"Rapportini_FGAS_{anno_corrente}_Divisi_Per_Mese.zip",
        mime="application/zip",
        key="dl_zip_sidebar",
    )

if menu == "Dashboard & Impianti":
    st.title("Gestione Registro & Rapportini F-GAS")

    col_exp1, col_exp2 = st.columns([1, 1])
    with col_exp1:
        if st.button("📦 Genera Tutti i Rapportini Divisi per Mese (ZIP Anno Corrente)", key="btn_zip_main"):
            with st.spinner("Lettura date verifica Excel e creazione pacchetto mensile..."):
                zip_bytes, count_doc, err_zip = genera_zip_mensile_anno_corrente(anno_corrente)
                if err_zip:
                    st.error(err_zip)
                else:
                    st.session_state["zip_mensile_data"] = zip_bytes
                    st.session_state["zip_mensile_count"] = count_doc
    with col_exp2:
        if "zip_mensile_data" in st.session_state and st.session_state["zip_mensile_data"]:
            st.download_button(
                label=f"⬇️ Scarica ZIP ({st.session_state['zip_mensile_count']} rapportini - {anno_corrente})",
                data=st.session_state["zip_mensile_data"],
                file_name=f"Rapportini_FGAS_{anno_corrente}_Divisi_Per_Mese.zip",
                mime="application/zip",
                key="dl_zip_main",
            )

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_macchine = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    search = st.text_input("🔍 Cerca per Unità, Matricola, Codice Apparecchiatura (Targa), Modello o Marca:", "").strip().lower()
    if search:
        df_view = df_macchine[
            df_macchine["nr_unita"].astype(str).str.lower().str.contains(search)
            | df_macchine["matricola"].astype(str).str.lower().str.contains(search)
            | df_macchine["codice_targa"].astype(str).str.lower().str.contains(search)
            | df_macchine["modello"].astype(str).str.lower().str.contains(search)
            | df_macchine["marca"].astype(str).str.lower().str.contains(search)
        ]
    else:
        df_view = df_macchine

    completati = len(df_macchine[df_macchine["stato_compilazione"] == "Completato"])
    st.markdown(f"**Impianti visualizzati: {len(df_view)} / {len(df_macchine)}** — *Completati: {completati}*")

    for _, row in df_view.iterrows():
        render_scheda_unita(row, prefix="dash", oggi=oggi, expanded=False)

elif menu == "Scan Targhetta (Foto/Camera)":
    st.title("Riconoscimento Impianto da Targhetta in Campo")
    st.markdown("Inquadra la targhetta metallica della macchina: il sistema leggerà automaticamente il codice o ti permetterà di cercarlo al volo.")

    img_file = st.camera_input("Scatta foto targhetta")
    uploaded_img = st.file_uploader("Oppure carica foto dalla galleria", type=["jpg", "jpeg", "png"])

    target_img = img_file if img_file is not None else uploaded_img
    testo_rilevato = ""

    if target_img is not None:
        image = Image.open(target_img)
        st.image(image, caption="Targhetta acquisita", use_container_width=True)

        try:
            import pytesseract

            raw_ocr = pytesseract.image_to_string(image, config="--psm 6").strip()
            if raw_ocr:
                candidati = []
                for token in raw_ocr.split():
                    pulito = re.sub(r"^[^A-Za-z0-9*]+|[^A-Za-z0-9*]+$", "", token)
                    if len(pulito) >= 5 and any(c.isalpha() for c in pulito) and any(c.isdigit() for c in pulito):
                        if pulito not in candidati:
                            candidati.append(pulito)

                if candidati:
                    testo_rilevato = max(candidati, key=len)
                    scelto_ocr = st.selectbox(
                        "Codici rilevati dalla targhetta (seleziona per cercare):",
                        options=candidati,
                        index=candidati.index(testo_rilevato),
                    )
                    if scelto_ocr:
                        testo_rilevato = scelto_ocr
                else:
                    parole = [p.strip() for p in raw_ocr.split() if len(p.strip()) >= 3]
                    if parole:
                        testo_rilevato = parole[0]
        except Exception:
            pass

    search_code = st.text_input(
        "Cerca per Matricola, Codice Apparecchiatura (Targa), Numero Unità o Modello:",
        value=testo_rilevato,
    ).strip()

    if search_code:
        conn = sqlite3.connect(DB_PATH)
        query_ricerca = """
            SELECT * FROM macchine_hvac
            WHERE LOWER(codice_targa) LIKE ?
               OR LOWER(nr_unita) LIKE ?
               OR LOWER(matricola) LIKE ?
               OR LOWER(modello) LIKE ?
        """
        param = f"%{search_code.lower()}%"
        df_s = pd.read_sql(query_ricerca, conn, params=(param, param, param, param))
        conn.close()

        if not df_s.empty:
            st.success(f"Trovate {len(df_s)} unità corrispondenti!")
            is_single = len(df_s) == 1
            for _, row in df_s.iterrows():
                render_scheda_unita(row, prefix="scan", oggi=oggi, expanded=is_single)
        else:
            st.warning("Nessuna unità trovata nel database con questo identificativo.")
