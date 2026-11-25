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
import streamlit as st

st.set_page_config(page_title="CBRE GWS - F-GAS Castel Romano", layout="wide")

DB_PATH = "castel_romano.db"
BACKUP_DIR = "Backup_FGAS"
CANDIDATE_EXCEL_PATHS = [
    "F_GAS_Impianti_Attivi_2026_ (3).xlsx",
    "F_GAS_Impianti_Attivi_2026_ (2).xlsx",
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
    custom_path = st.session_state.get("active_excel_path")
    if custom_path and os.path.exists(custom_path):
        return custom_path
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
        with pd.ExcelFile(excel_file, engine="openpyxl") as xls:
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


def _scrivi_foglio_excel_sicuro(excel_file: str, foglio: str, df_xl: pd.DataFrame):
    """
    Scrive il foglio aggiornato mantenendo gli altri fogli del workbook e salvando
    su disco in modo affidabile.
    """
    abs_target = os.path.abspath(excel_file)
    os.makedirs(os.path.dirname(abs_target) or ".", exist_ok=True)
    tmp_path = f"{abs_target}.tmp_{os.getpid()}.xlsx"

    with pd.ExcelFile(abs_target, engine="openpyxl") as xls:
        all_sheets = {
            name: pd.read_excel(xls, sheet_name=name) for name in xls.sheet_names
        }

    all_sheets[foglio] = df_xl

    with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
        for sheet_name, sheet_df in all_sheets.items():
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)

    os.replace(tmp_path, abs_target)


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
    desc_val: str | None = None,
    fgas_attivo_val: str | None = None,
    data_verifica_str: str | None = None,
):
    excel_file = resolve_excel_path()
    if not os.path.exists(excel_file):
        return False, f"File Excel non trovato: {excel_file}"

    try:
        with pd.ExcelFile(excel_file, engine="openpyxl") as xls:
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

        if desc_val is not None:
            col_desc = (
                "Descrizione"
                if "Descrizione" in df_xl.columns
                else ("Unità" if "Unità" in df_xl.columns else "Descrizione")
            )
            aggiornamenti[col_desc] = desc_val

        if fgas_attivo_val is not None:
            aggiornamenti["F-Gas?"] = str(fgas_attivo_val).strip().upper()

        if data_verifica_str:
            if "Data ultima verifica" in df_xl.columns:
                aggiornamenti["Data ultima verifica"] = data_verifica_str

        for col_name, val in aggiornamenti.items():
            if col_name not in df_xl.columns:
                df_xl[col_name] = None
            df_xl[col_name] = df_xl[col_name].astype(object)
            df_xl.loc[mask, col_name] = val

        _scrivi_foglio_excel_sicuro(excel_file, foglio, df_xl)

        n_righe = int(mask.sum())
        return (
            True,
            f"Excel ({foglio}) aggiornato ({n_righe} riga/e) su chiave={fgas_target} [{os.path.abspath(excel_file)}].",
        )
    except PermissionError:
        return (
            False,
            f"File Excel bloccato o aperto altrove: {os.path.abspath(excel_file)}",
        )
    except Exception as e:
        return False, f"Errore aggiornamento Excel: {e}"


def salva_su_db(
    fgas_id: str,
    desc_val: str,
    mod_val: str,
    matr_val: str,
    gas_val: str,
    targa_val: str,
    stato_val: str,
    fgas_attivo_val: str,
    n_circ: int,
    c1_kg: float,
    c2_kg: float,
    co2_c1: float,
    co2_c2: float,
    carica_tot: float,
    co2_tot: float,
    data_verifica_str: str,
):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE macchine_hvac
            SET nr_unita = ?,
                modello = ?,
                matricola = ?,
                refrigerante = ?,
                codice_targa = ?,
                stato_compilazione = ?,
                f_gas_attivo = ?,
                n_circuiti = ?,
                carica_circ1 = ?,
                carica_circ2 = ?,
                co2_circ1 = ?,
                co2_circ2 = ?,
                carica_kg = ?,
                tonn_co2_eq = ?,
                scadenza_verifica = ?
            WHERE id_macchina = ?
            """,
            (
                desc_val,
                mod_val,
                matr_val,
                gas_val,
                targa_val,
                stato_val,
                str(fgas_attivo_val).strip().upper(),
                int(n_circ),
                round(float(c1_kg), 2),
                round(float(c2_kg), 2) if int(n_circ) == 2 else 0.0,
                round(float(co2_c1), 2),
                round(float(co2_c2), 2) if int(n_circ) == 2 else 0.0,
                round(float(carica_tot), 2),
                round(float(co2_tot), 2),
                data_verifica_str,
                _normalizza_chiave(fgas_id),
            ),
        )
        updated = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return updated


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

    with pd.ExcelFile(excel_file, engine="openpyxl") as xls:
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
            if pd.notna(row.get("Carica_Circ_2_Kg"))
            else (carica_kg / 2 if n_circ == 2 else 0.0)
        )
        co2_1_val = calcola_co2_tonnellate(c1_val, refrigerante)
        co2_2_val = (
            calcola_co2_tonnellate(c2_val, refrigerante)
            if n_circ == 2
            else 0.0
        )

        cur.execute(
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
        inseriti += 1

    return inseriti


def _crea_backup_db() -> str | None:
    if not os.path.exists(DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"castel_romano_backup_{ts}.db")
    shutil.copy2(DB_PATH, dest)
    return dest


def reset_database_da_excel() -> tuple[bool, str]:
    """
    Crea un backup del DB attuale e poi ricrea la tabella macchine_hvac su castel_romano.db
    partendo dall'Excel con chiave primaria univoca su fgasnum.
    """
    excel_file = resolve_excel_path()
    if not os.path.exists(excel_file):
        return False, "Nessun file Excel trovato per il reset."

    backup_path = _crea_backup_db()

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        inseriti = _popola_tabella_da_excel(cur, excel_file, ricrea_tabella=True)
        conn.commit()
    finally:
        conn.close()

    msg_bkp = f" (backup salvato in '{backup_path}')" if backup_path else ""
    return (
        True,
        f"DB resettato da '{excel_file}': {inseriti} record univoci.{msg_bkp}",
    )


def init_db():
    excel_file = resolve_excel_path()
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        cur = conn.cursor()
        _popola_tabella_da_excel(cur, excel_file, ricrea_tabella=False)
        conn.commit()
    finally:
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
    data_str = (
        data_intervento_custom
        if data_intervento_custom
        else oggi.strftime("%d/%m/%Y")
    )
    scadenza_str = (
        scadenza_custom
        if scadenza_custom
        else str(row.get("scadenza_verifica", ""))
    )

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

    fgas_key = sanitize_filename(row.get("id_macchina", ""))
    nome_file = (
        f"Report_FGAS_{fgas_key}_{sanitize_filename(row.get('marca', ''))}_{sanitize_filename(mod_edit)}"
        f"_Unita_{sanitize_filename(row.get('nr_unita', ''))}.docx"
    )
    out_file = os.path.join(target_dir, nome_file)
    doc.save(out_file)
    return out_file, None


def genera_zip_mensile_anno_corrente(
    anno_corrente: int, solo_fgas_attivi: bool = True
):
    """
    Genera l'archivio ZIP diviso per mese basandosi sui record univoci su fgasnum.
    """
    if not os.path.exists(TEMPLATE_FGAS_PATH):
        return None, 0, "Template Word non trovato."

    sincronizza_date_da_excel()
    df_unici = leggi_macchine_db()
    if df_unici.empty:
        return None, 0, "Nessun record presente nel database."

    base_batch_dir = os.path.join(OUTPUT_DIR, f"Batch_Mensile_{anno_corrente}")
    os.makedirs(base_batch_dir, exist_ok=True)

    zip_buffer = io.BytesIO()
    oggi_now = datetime.now()
    tot_generati = 0
    fgas_visti = set()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, r_db in df_unici.iterrows():
            fgas_id = _normalizza_chiave(r_db.get("id_macchina", ""))
            if not fgas_id or fgas_id in fgas_visti:
                continue
            fgas_visti.add(fgas_id)

            fgas_flag = str(r_db.get("f_gas_attivo", "S")).strip().upper()
            if solo_fgas_attivi and fgas_flag == "N":
                continue

            desc_unita = str(r_db.get("nr_unita", "")).strip()
            if any(
                k in desc_unita.upper()
                for k in ["DISMESS", "NON INDIVIDUATA", "DOPP."]
            ):
                continue

            data_corr_str, _, cartella_mese = normalizza_data_anno_corrente(
                r_db.get("scadenza_verifica"), anno_corrente
            )
            if not data_corr_str or not cartella_mese:
                continue

            n_circ = (
                2
                if pd.notna(r_db.get("n_circuiti"))
                and int(r_db.get("n_circuiti")) == 2
                else 1
            )
            gas = str(r_db.get("refrigerante") or "R-410A").strip()
            carica_db = float(r_db.get("carica_kg") or 0.0)
            c1 = float(
                r_db.get("carica_circ1")
                if pd.notna(r_db.get("carica_circ1"))
                else (carica_db / 2.0 if n_circ == 2 else carica_db)
            )
            c2 = float(
                r_db.get("carica_circ2")
                if pd.notna(r_db.get("carica_circ2"))
                else (carica_db / 2.0 if n_circ == 2 else 0.0)
            )

            co2_1 = calcola_co2_tonnellate(c1, gas)
            co2_2 = (
                calcola_co2_tonnellate(c2, gas) if n_circ == 2 else 0.0
            )
            co2_tot = round(co2_1 + co2_2, 2)

            row_payload = {
                "id_macchina": fgas_id,
                "nr_unita": desc_unita,
                "marca": str(r_db.get("marca") or "").strip(),
                "scadenza_verifica": data_corr_str,
            }

            mese_dir = os.path.join(base_batch_dir, cartella_mese)
            out_file, _ = genera_report_docx(
                row=row_payload,
                mod_edit=str(r_db.get("modello") or "").strip(),
                matr_edit=str(r_db.get("matricola") or "").strip(),
                gas_edit=gas,
                targa_edit=str(r_db.get("codice_targa") or "").strip(),
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
                zf.write(
                    out_file,
                    arcname=os.path.join(cartella_mese, os.path.basename(out_file)),
                )
                tot_generati += 1

    zip_buffer.seek(0)
    return zip_buffer.getvalue(), tot_generati, None


def render_scheda_unita(row, prefix, oggi, expanded=False):
    fgas_id = _normalizza_chiave(row.get("id_macchina", ""))
    key_id = f"{prefix}_{sanitize_filename(fgas_id)}"
    stato = row.get("stato_compilazione", "Da Lavorare")
    pallino = "🟢" if stato == "Completato" else "🟡"
    fgas_attivo_db = (
        str(row.get("f_gas_attivo", "S")).strip().upper()
        if str(row.get("f_gas_attivo", "S")).strip().upper() in ("S", "N")
        else "S"
    )

    n_circ_db = (
        2
        if pd.notna(row.get("n_circuiti")) and int(row.get("n_circuiti")) == 2
        else 1
    )
    carica_db = float(row.get("carica_kg") or 0.0)
    c1_db = float(
        row.get("carica_circ1")
        or (carica_db / 2 if n_circ_db == 2 else carica_db)
    )
    c2_db = float(
        row.get("carica_circ2") or (carica_db / 2 if n_circ_db == 2 else 0.0)
    )
    data_valida_str, _, _ = normalizza_data_anno_corrente(
        row.get("scadenza_verifica"), oggi.year
    )
    if not data_valida_str:
        data_valida_str = oggi.strftime("%d/%m/%Y")

    with st.expander(
        f"{pallino} [FGAS `{fgas_id}`] Unità {row.get('nr_unita', '')} — {row.get('marca', '')} {row.get('modello', '')} | Circuiti: `{n_circ_db}` | Data Verifica: `{data_valida_str}` | Targa: `{row.get('codice_targa', '')}`",
        expanded=expanded,
    ):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Dati Impianto & Identificativi**")
            st.write(f"- **N° FGAS (`id_macchina`):** `{fgas_id}`")
            st.write(f"- **Collocazione:** `{row.get('collocazione', '')}`")
            st.write(f"- **Descrizione / Unità:** `{row.get('nr_unita', '')}`")
            st.write(f"- **Matricola:** `{row.get('matricola', '')}`")
            st.write(f"- **Cod. Apparecchiatura:** `{row.get('codice_targa', '')}`")
            st.write(f"- **Data Verifica (Anno Corrente):** `{data_valida_str}`")
            st.write(f"- **N° Circuiti registrati:** `{n_circ_db}`")
        with c2:
            st.markdown("**Parametri F-GAS**")
            st.write(f"- **F-Gas?:** `{fgas_attivo_db}`")
            st.write(f"- **Refrigerante:** `{row.get('refrigerante', '')}`")
            st.write(f"- **Carica Totale:** `{carica_db:.2f} kg`")
            st.write(
                f"- **Tonn. CO2 Eq Totale:** `{float(row.get('tonn_co2_eq') or 0.0):.2f} t`"
            )

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
                    st.session_state[f"c2_val_{key_id}"] = round(
                        carica_db - meta, 2
                    )
            else:
                st.session_state[f"c1_val_{key_id}"] = round(carica_db, 2)
                st.session_state[f"c2_val_{key_id}"] = 0.0
            st.session_state[state_key_nc] = n_circ_edit

        with st.form(key=f"form_{key_id}"):
            st.markdown("##### ✏️ Verifica e Modifica Dati in Campo")
            desc_edit = st.text_input(
                "Descrizione / Unità (es. rimuovi '- DISMESS / - DISMESSO' se attiva)",
                value=str(row.get("nr_unita", "")),
                key=f"desc_{key_id}",
            )

            nc1, nc2, nc3 = st.columns(3)
            with nc1:
                mod_edit = st.text_input(
                    "Modello",
                    value=str(row.get("modello", "")),
                    key=f"mod_{key_id}",
                )
                matr_edit = st.text_input(
                    "Matricola",
                    value=str(row.get("matricola", "")),
                    key=f"matr_{key_id}",
                )
            with nc2:
                gas_lista = [
                    "R-410A",
                    "R-407C",
                    "R-32",
                    "R-134a",
                    "R-449A",
                    "R-404A",
                    "R-507A",
                    "R-22",
                ]
                idx_gas = (
                    gas_lista.index(row.get("refrigerante"))
                    if row.get("refrigerante") in gas_lista
                    else 0
                )
                gas_edit = st.selectbox(
                    "Refrigerante",
                    gas_lista,
                    index=idx_gas,
                    key=f"gas_{key_id}",
                )
                targa_edit = st.text_input(
                    "Codice Apparecchiatura (Targa)",
                    value=str(row.get("codice_targa", "")),
                    key=f"targa_{key_id}",
                )
            with nc3:
                stato_edit = st.selectbox(
                    "Stato Lavorazione",
                    ["Da Lavorare", "Completato"],
                    index=0 if stato == "Da Lavorare" else 1,
                    key=f"st_{key_id}",
                )
                fgas_attivo_edit = st.selectbox(
                    "Flag F-Gas? (S / N)",
                    ["S", "N"],
                    index=0 if fgas_attivo_db == "S" else 1,
                    key=f"fgasflag_{key_id}",
                )
                st.caption(
                    f"GWP applicato ({gas_edit}): **{get_gwp(gas_edit):.0f}**"
                )

            st.markdown(
                "**Carica Refrigerante per Circuito e Calcolo Automatico Tonn. CO2 Eq**"
            )
            if n_circ_edit == 2:
                cc1, cc2 = st.columns(2)
                with cc1:
                    c1_edit = st.number_input(
                        "Carica Circuito 1 (kg)",
                        min_value=0.0,
                        step=0.1,
                        format="%.2f",
                        value=float(
                            st.session_state.get(f"c1_val_{key_id}", c1_db)
                        ),
                        key=f"in_c1_{key_id}",
                    )
                    co2_c1_calc = calcola_co2_tonnellate(c1_edit, gas_edit)
                    st.info(
                        f"Tonn. CO2 Eq Circuito 1 (calcolate): **{co2_c1_calc:.2f} t**"
                    )
                with cc2:
                    c2_edit = st.number_input(
                        "Carica Circuito 2 (kg)",
                        min_value=0.0,
                        step=0.1,
                        format="%.2f",
                        value=float(
                            st.session_state.get(f"c2_val_{key_id}", c2_db)
                        ),
                        key=f"in_c2_{key_id}",
                    )
                    co2_c2_calc = calcola_co2_tonnellate(c2_edit, gas_edit)
                    st.info(
                        f"Tonn. CO2 Eq Circuito 2 (calcolate): **{co2_c2_calc:.2f} t**"
                    )
            else:
                c1_edit = st.number_input(
                    "Carica Circuito 1 (kg)",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                    value=float(
                        st.session_state.get(f"c1_val_{key_id}", carica_db)
                    ),
                    key=f"in_c1_{key_id}",
                )
                c2_edit = 0.0
                co2_c1_calc = calcola_co2_tonnellate(c1_edit, gas_edit)
                co2_c2_calc = 0.0
                st.info(
                    f"Tonn. CO2 Eq Circuito 1 (calcolate): **{co2_c1_calc:.2f} t**"
                )

            carica_tot_calc = round(float(c1_edit) + float(c2_edit), 2)
            co2_tot_calc = round(float(co2_c1_calc) + float(co2_c2_calc), 2)
            st.markdown(
                f"**Riepilogo automatico:** Carica Totale = **`{carica_tot_calc:.2f} kg`** | Tonn. CO2 Eq Totale = **`{co2_tot_calc:.2f} t`**"
            )

            btn_aggiorna = st.form_submit_button(
                "💾 Salva su DB & Excel + Genera Rapportino F-GAS (Firmato)"
            )

            if btn_aggiorna:
                c1_pulito = round(float(c1_edit), 2)
                c2_pulito = (
                    round(float(c2_edit), 2) if int(n_circ_edit) == 2 else 0.0
                )
                co2_1_pulito = calcola_co2_tonnellate(c1_pulito, gas_edit)
                co2_2_pulito = (
                    calcola_co2_tonnellate(c2_pulito, gas_edit)
                    if int(n_circ_edit) == 2
                    else 0.0
                )
                tot_kg_pulito = round(c1_pulito + c2_pulito, 2)
                tot_co2_pulito = round(co2_1_pulito + co2_2_pulito, 2)

                st.session_state[f"c1_val_{key_id}"] = c1_pulito
                st.session_state[f"c2_val_{key_id}"] = c2_pulito

                db_rows = salva_su_db(
                    fgas_id=fgas_id,
                    desc_val=desc_edit.strip(),
                    mod_val=mod_edit.strip(),
                    matr_val=matr_edit.strip(),
                    gas_val=gas_edit,
                    targa_val=targa_edit.strip(),
                    stato_val=stato_edit,
                    fgas_attivo_val=fgas_attivo_edit,
                    n_circ=int(n_circ_edit),
                    c1_kg=c1_pulito,
                    c2_kg=c2_pulito,
                    co2_c1=co2_1_pulito,
                    co2_c2=co2_2_pulito,
                    carica_tot=tot_kg_pulito,
                    co2_tot=tot_co2_pulito,
                    data_verifica_str=data_valida_str,
                )

                ok_xl, msg_xl = salva_su_excel(
                    row_data={"id_macchina": fgas_id},
                    n_circ=int(n_circ_edit),
                    c1_kg=c1_pulito,
                    c2_kg=c2_pulito,
                    co2_c1=co2_1_pulito,
                    co2_c2=co2_2_pulito,
                    carica_tot=tot_kg_pulito,
                    co2_tot=tot_co2_pulito,
                    mod_val=mod_edit.strip(),
                    matr_val=matr_edit.strip(),
                    gas_val=gas_edit,
                    targa_val=targa_edit.strip(),
                    stato_val=stato_edit,
                    desc_val=desc_edit.strip(),
                    fgas_attivo_val=fgas_attivo_edit,
                    data_verifica_str=data_valida_str,
                )

                row_per_docx = dict(row)
                row_per_docx["id_macchina"] = fgas_id
                row_per_docx["nr_unita"] = desc_edit.strip()
                out_docx, err_docx = genera_report_docx(
                    row=row_per_docx,
                    mod_edit=mod_edit.strip(),
                    matr_edit=matr_edit.strip(),
                    gas_edit=gas_edit,
                    targa_edit=targa_edit.strip(),
                    stato_edit=stato_edit,
                    n_circ_edit=int(n_circ_edit),
                    c1_edit=c1_pulito,
                    c2_edit=c2_pulito,
                    co2_c1_calc=co2_1_pulito,
                    co2_c2_calc=co2_2_pulito,
                    carica_tot_calc=tot_kg_pulito,
                    co2_tot_calc=tot_co2_pulito,
                    oggi=oggi,
                    data_intervento_custom=data_valida_str,
                    scadenza_custom=data_valida_str,
                )

                st.session_state["last_save_feedback"] = {
                    "db_rows": db_rows,
                    "ok_xl": ok_xl,
                    "msg_xl": msg_xl,
                    "out_docx": out_docx,
                    "err_docx": err_docx,
                }
                st.rerun()


def main():
    st.title("CBRE GWS — Registro F-GAS Castel Romano")

    excel_attivo = resolve_excel_path()
    with st.sidebar:
        st.markdown("### Gestione File Excel & DB")
        st.caption(f"File Excel attivo: `{os.path.abspath(excel_attivo)}`")

        uploaded_xl = st.file_uploader(
            "Carica/Sostituisci file Excel (.xlsx)",
            type=["xlsx"],
            key="uploader_excel_fgas",
        )
        if uploaded_xl is not None:
            dest_xl = (
                excel_attivo
                if os.path.exists(excel_attivo)
                else "F_GAS_Impianti_Attivi_2026_ (3).xlsx"
            )
            with open(dest_xl, "wb") as f:
                f.write(uploaded_xl.getbuffer())
            st.session_state["active_excel_path"] = dest_xl
            st.success(f"File salvato su `{dest_xl}`")

        if st.button("🔄 Reset DB da Excel (con backup)"):
            ok_r, msg_r = reset_database_da_excel()
            if ok_r:
                st.success(msg_r)
                st.rerun()
            else:
                st.error(msg_r)

        if os.path.exists(excel_attivo):
            with open(excel_attivo, "rb") as f_xl:
                xl_bytes = f_xl.read()
            st.download_button(
                label="⬇️ Scarica Excel Aggiornato (.xlsx)",
                data=xl_bytes,
                file_name=os.path.basename(excel_attivo),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_excel_aggiornato",
            )

    init_db()

    feedback = st.session_state.pop("last_save_feedback", None)
    if feedback:
        msg_docx = (
            f"Rapportino DOCX pronto: `{feedback['out_docx']}`"
            if feedback.get("out_docx")
            else f"Errore DOCX: {feedback.get('err_docx')}"
        )
        st.success(
            f"DB aggiornato ({feedback.get('db_rows', 0)} record). {feedback.get('msg_xl', '')} | {msg_docx}"
        )
        if not feedback.get("ok_xl"):
            st.warning(feedback.get("msg_xl", ""))

    df_macchine = leggi_macchine_db()
    if df_macchine.empty:
        st.warning("Nessun impianto trovato nel database.")
        return

    oggi = datetime.now()
    tot_impianti = len(df_macchine)
    completati = int(
        (df_macchine["stato_compilazione"] == "Completato").sum()
    )

    filtro_stato = st.radio(
        "Filtro stato lavorazione",
        options=["Tutti", "Da Lavorare", "Completato"],
        horizontal=True,
    )
    ricerca = st.text_input(
        "Cerca per N° FGAS, Unità, Modello, Matricola o Targa",
        value="",
    ).strip().lower()

    df_view = df_macchine.copy()
    if filtro_stato != "Tutti":
        df_view = df_view[df_view["stato_compilazione"] == filtro_stato]
    if ricerca:
        mask_txt = (
            df_view.apply(
                lambda r: ricerca
                in " ".join(
                    str(r.get(c, ""))
                    for c in [
                        "id_macchina",
                        "nr_unita",
                        "marca",
                        "modello",
                        "matricola",
                        "codice_targa",
                    ]
                ).lower(),
                axis=1,
            )
        )
        df_view = df_view[mask_txt]

    st.caption(
        f"Impianti visualizzati: {len(df_view)} / {tot_impianti} — Completati: {completati}"
    )

    for idx, (_, row) in enumerate(df_view.iterrows()):
        render_scheda_unita(
            row=row,
            prefix=f"v{idx}",
            oggi=oggi,
            expanded=False,
        )


if __name__ == "__main__":
    main()
