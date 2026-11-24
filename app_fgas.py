import os
import shutil
import sqlite3
from datetime import datetime
import pandas as pd

DB_PATH = "castel_romano.db"
CANDIDATE_EXCEL_PATHS = [
    "F_GAS_Impianti_Attivi_2026_ (1).xlsx",
    "F_GAS_Impianti_Attivi_2026_.xlsx",
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

# Imposta True se vuoi importare in DB solo le righe con F-Gas? == "S"
SOLO_FGAS_ATTIVI = False


def get_gwp(gas):
    if not gas:
        return 2088.0
    return GWP_MAP.get(str(gas).strip().upper(), 2088.0)


def parse_data(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y")
    if hasattr(val, "to_pydatetime"):
        try:
            return val.to_pydatetime().strftime("%d/%m/%Y")
        except Exception:
            pass
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


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Rimosso vecchio database: {DB_PATH}")

    for folder in OUTPUT_DIRS:
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
            print(f"Rimossa cartella generati: {folder}")

    for fname in os.listdir("."):
        if fname.lower().endswith(".docx") and fname != "Report_FGAS_modello.docx":
            try:
                os.remove(fname)
                print(f"Rimosso file .docx residuo: {fname}")
            except OSError:
                pass

    excel_file = find_excel()
    if not excel_file:
        raise FileNotFoundError(
            "Nessun file Excel trovato tra: " + ", ".join(CANDIDATE_EXCEL_PATHS)
        )

    xls = pd.ExcelFile(excel_file)
    foglio = "Elenco di FGAS" if "Elenco di FGAS" in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=foglio)

    conn = sqlite3.connect(DB_PATH)
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

    inseriti = 0
    for idx, r in df.iterrows():
        fgas_flag = str(r.get("F-Gas?", "S")).strip().upper()
        if SOLO_FGAS_ATTIVI and fgas_flag != "S":
            continue

        fgasnum = str(r.get("fgasnum", "")).strip()
        id_macchina = (
            fgasnum if fgasnum and fgasnum.lower() != "nan" else f"MAC_{idx + 1:03d}"
        )

        collocazione = str(r.get("Collocazione", "MCARTHUR_RM")).strip()
        nr_unita = str(r.get("Descrizione", r.get("Unità / Macchina", ""))).strip()
        marca = str(r.get("Marca", "")).strip()
        modello = str(r.get("Modello", "")).strip()

        matr_raw = r.get("Matricola", "")
        matricola = (
            str(matr_raw).strip()
            if pd.notna(matr_raw) and str(matr_raw).strip()
            else "N/D"
        )

        gas_raw = r.get("Tipo HCFC", r.get("Refrigerante", ""))
        refrigerante = (
            str(gas_raw).strip()
            if pd.notna(gas_raw) and str(gas_raw).strip()
            else "N/D"
        )

        carica_raw = r.get("Carica Refrigerante (kg)", r.get("Carica (kg)", 0.0))
        carica_kg = round(float(carica_raw), 2) if pd.notna(carica_raw) else 0.0

        co2_raw = r.get("Tonn CO2 Eq", r.get("Tonn. CO2 Eq.", None))
        if pd.notna(co2_raw):
            tonn_co2 = round(float(co2_raw), 2)
        elif carica_kg > 0 and refrigerante != "N/D":
            tonn_co2 = round((carica_kg * get_gwp(refrigerante)) / 1000.0, 2)
        else:
            tonn_co2 = 0.0

        targa_raw = r.get("Cod. Apparecchiatura", r.get("Codice Targa", ""))
        codice_targa = str(targa_raw).strip() if pd.notna(targa_raw) else ""

        scadenza = parse_data(r.get("Scadenza verifica", r.get("Scadenza Verifica", "")))

        ncirc_raw = r.get("N° Circuiti", r.get("N_Circuiti", 1))
        try:
            n_circ = (
                2
                if pd.notna(ncirc_raw)
                and str(ncirc_raw).strip() not in ("", "N.D.", "ND")
                and int(float(ncirc_raw)) == 2
                else 1
            )
        except Exception:
            n_circ = 1

        c1 = round(carica_kg / 2.0, 2) if n_circ == 2 else carica_kg
        c2 = round(carica_kg - c1, 2) if n_circ == 2 else 0.0
        co2_1 = (
            round((c1 * get_gwp(refrigerante)) / 1000.0, 2)
            if refrigerante != "N/D"
            else 0.0
        )
        co2_2 = (
            round((c2 * get_gwp(refrigerante)) / 1000.0, 2)
            if (n_circ == 2 and refrigerante != "N/D")
            else 0.0
        )

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
                id_macchina,
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
                fgas_flag if fgas_flag in ("S", "N") else "S",
                "Da Lavorare",
                n_circ,
                c1,
                c2,
                co2_1,
                co2_2,
            ),
        )
        inseriti += 1

    conn.commit()
    conn.close()
    print(f"Database '{DB_PATH}' ricreato da '{excel_file}' (foglio '{foglio}'): {inseriti} impianti inseriti.")


if __name__ == "__main__":
    main()
