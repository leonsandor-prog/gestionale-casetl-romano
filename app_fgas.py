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
cat << 'EOF' >> app_fgas.py
            "carica_circ2": round(float(c2_kg), 2),
            "co2_circ1": round(float(co2_c1), 2),
            "co2_circ2": round(float(co2_c2), 2),
        }

        for field_name, val in updates.items():
            col_found = _trova_colonna(df.columns, [field_name])
            if col_found:
                if df[col_found].dtype == object:
                    df.loc[mask, col_found] = str(val) if isinstance(val, str) else val
                else:
                    df.loc[mask, col_found] = val

        df.to_excel(EXCEL_PATH, index=False)
        return True, f"Aggiornato {EXCEL_PATH}"
    except Exception as e:
        return False, f"Errore scrittura Excel: {e}"


def _sostituisci_placeholder_in_testo(testo, mapping):
    for k, v in mapping.items():
        testo = testo.replace(f"{{{{{k}}}}}", str(v))
        testo = testo.replace(f"{{{k}}}", str(v))
    return testo


def _popola_documento_docx(doc, mapping):
    for p in doc.paragraphs:
        if "{" in p.text:
            nuovo = _sostituisci_placeholder_in_testo(p.text, mapping)
            if nuovo != p.text:
                p.text = nuovo

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if "{" in p.text:
                        nuovo = _sostituisci_placeholder_in_testo(p.text, mapping)
                        if nuovo != p.text:
                            p.text = nuovo


def genera_report_docx(
    row,
    modello,
    matricola,
    refrigerante,
    codice_targa,
    stato_compilazione,
    n_circuiti,
    c1_kg,
    c2_kg,
    co2_c1,
    co2_c2,
    carica_tot,
    co2_tot,
    oggi,
    data_intervento_custom=None,
    scadenza_custom=None,
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    data_int = data_intervento_custom or oggi.strftime("%d/%m/%Y")
    scad_str = scadenza_custom or data_int

    mapping = {
        "ID_MACCHINA": row.get("id_macchina", ""),
        "NR_UNITA": row.get("nr_unita", ""),
        "MARCA": row.get("marca", ""),
        "MODELLO": modello,
        "MATRICOLA": matricola,
        "COLLOCAZIONE": row.get("collocazione", ""),
        "CODICE_TARGA": codice_targa,
        "REFRIGERANTE": refrigerante,
        "N_CIRCUITI": str(n_circuiti),
        "CARICA_CIRC1": f"{float(c1_kg):.2f}",
        "CARICA_CIRC2": f"{float(c2_kg):.2f}",
        "CO2_CIRC1": f"{float(co2_c1):.2f}",
        "CO2_CIRC2": f"{float(co2_c2):.2f}",
        "CARICA_TOTALE": f"{float(carica_tot):.2f}",
        "CO2_TOTALE": f"{float(co2_tot):.2f}",
        "STATO": stato_compilazione,
        "DATA_INTERVENTO": data_int,
        "SCADENZA_VERIFICA": scad_str,
        "GWP": f"{get_gwp(refrigerante):.0f}",
    }

    try:
        if os.path.exists(TEMPLATE_FGAS_PATH):
            doc = Document(TEMPLATE_FGAS_PATH)
            _popola_documento_docx(doc, mapping)
        else:
            doc = Document()
            doc.add_heading("RAPPORTINO DI VERIFICA IMPIANTO F-GAS", level=1)
            doc.add_paragraph(f"Data intervento: {data_int} | Stato: {stato_compilazione}")
            doc.add_paragraph(
                f"Unità: {row.get('nr_unita', '')} — {row.get('marca', '')} {modello} | "
                f"Matricola: {matricola} | Targa: {codice_targa}"
            )
            doc.add_paragraph(f"Collocazione: {row.get('collocazione', '')}")
            doc.add_paragraph(
                f"Refrigerante: {refrigerante} (GWP {get_gwp(refrigerante):.0f}) | "
                f"Circuiti: {n_circuiti}"
            )
            doc.add_paragraph(
                f"Circuito 1: {float(c1_kg):.2f} kg ({float(co2_c1):.2f} t CO2 eq) | "
                f"Circuito 2: {float(c2_kg):.2f} kg ({float(co2_c2):.2f} t CO2 eq)"
            )
            doc.add_paragraph(
                f"Totale Carica: {float(carica_tot):.2f} kg | "
                f"Totale CO2 Eq: {float(co2_tot):.2f} t"
            )

        if os.path.exists(FIRMA_PATH):
            try:
                with Image.open(FIRMA_PATH) as im:
                    im.verify()
                doc.add_paragraph("Firma Tecnico F-GAS:")
                doc.add_picture(FIRMA_PATH, width=Inches(1.8))
            except Exception as e_img:
                doc.add_paragraph(f"Firma Tecnico F-GAS: [Avviso immagine firma: {e_img}]")

        nome_file = (
            f"Rapportino_FGAS_Unita_{sanitize_filename(row.get('nr_unita', 'X'))}_"
            f"{sanitize_filename(row.get('id_macchina', 'ID'))}_{oggi.strftime('%Y%m%d')}.docx"
        )
        out_path = os.path.join(OUTPUT_DIR, nome_file)
        doc.save(out_path)
        return out_path, None
    except Exception as e:
        return None, f"Errore generazione rapportino .docx: {e}"


def genera_zip_mensile_anno_corrente(macchine, oggi):
    anno = oggi.year
    buf = io.BytesIO()
    conteggio = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in macchine:
            data_str, mese, _ = normalizza_data_anno_corrente(
                r.get("scadenza_verifica"), anno
            )
            if not mese:
                mese = oggi.month
                data_str = oggi.strftime("%d/%m/%Y")

            nome_mese = MESI_IT.get(mese, f"Mese_{mese:02d}")
            n_circ = 2 if int(_safe_float(r.get("n_circuiti"), 1)) == 2 else 1
            carica = _safe_float(r.get("carica_kg"), 0.0)
            co2 = _safe_float(r.get("tonn_co2_eq"), calcola_co2_tonnellate(carica, r.get("refrigerante")))
            c1 = _safe_float(r.get("carica_circ1"), carica / 2.0 if n_circ == 2 else carica)
            c2 = _safe_float(r.get("carica_circ2"), carica / 2.0 if n_circ == 2 else 0.0)
            co2_1 = _safe_float(r.get("co2_circ1"), calcola_co2_tonnellate(c1, r.get("refrigerante")))
            co2_2 = _safe_float(r.get("co2_circ2"), calcola_co2_tonnellate(c2, r.get("refrigerante")))

            out_path, err = genera_report_docx(
                r,
                r.get("modello", ""),
                r.get("matricola", ""),
                r.get("refrigerante", "R-410A"),
                r.get("codice_targa", ""),
                r.get("stato_compilazione", "Da Lavorare"),
                n_circ,
                c1,
                c2,
                co2_1,
                co2_2,
                carica,
                co2,
                oggi,
                data_intervento_custom=data_str,
                scadenza_custom=data_str,
            )
            if out_path and os.path.exists(out_path) and not err:
                arcname = f"{anno}_{mese:02d}_{nome_mese}/{os.path.basename(out_path)}"
                zf.write(out_path, arcname=arcname)
                conteggio += 1

    buf.seek(0)
    return buf.getvalue(), conteggio


def render_scheda_unita(row, prefix, oggi, expanded=False):
    key_id = f"{prefix}_{sanitize_filename(row['id_macchina'])}"
    stato = row["stato_compilazione"]
    pallino = "🟢" if stato == "Completato" else "🟡"

    n_circ_db = 2 if int(_safe_float(row.get("n_circuiti"), 1)) == 2 else 1
    carica_db = _safe_float(row.get("carica_kg"), 0.0)
    co2_db = _safe_float(row.get("tonn_co2_eq"), 0.0)
    c1_db = _safe_float(
        row.get("carica_circ1"),
        carica_db / 2.0 if n_circ_db == 2 else carica_db,
    )
    c2_db = _safe_float(
        row.get("carica_circ2"), carica_db / 2.0 if n_circ_db == 2 else 0.0
    )
    data_valida_str, _, _ = normalizza_data_anno_corrente(
        row.get("scadenza_verifica"), oggi.year
    )
    if not data_valida_str:
        data_valida_str = oggi.strftime("%d/%m/%Y")

    with st.expander(
        f"{pallino} Unità {row['nr_unita']} — {row['marca']} {row['modello']} |"
        f" Circuiti: `{n_circ_db}` | Data Verifica: `{data_valida_str}` |"
        f" Targa: `{row['codice_targa']}`",
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
            st.write(f"- **Carica Totale:** `{carica_db:.2f} kg`")
            st.write(f"- **Tonn. CO2 Eq Totale:** `{co2_db:.2f} t`")

        st.divider()

        n_circ_edit = st.selectbox(
            "Numero circuiti impianto (1 = singolo, 2 = doppio circuito)",
            options=[1, 2],
            index=1 if n_circ_db == 2 else 0,
            key=f"ncirc_{key_id}",
        )

        state_key_nc = f"last_ncirc_{key_id}"
        if st.session_state.get(state_key_nc) != n_circ_edit:
            if n_circ_edit == 2:
                if c2_db > 0:
                    val_c1 = round(c1_db, 2)
                    val_c2 = round(c2_db, 2)
                else:
                    meta = round(carica_db / 2.0, 2)
                    val_c1 = meta
                    val_c2 = round(carica_db - meta, 2)
            else:
                val_c1 = round(carica_db, 2)
                val_c2 = 0.0

            st.session_state[f"c1_val_{key_id}"] = val_c1
            st.session_state[f"c2_val_{key_id}"] = val_c2
            st.session_state[f"in_c1_{key_id}"] = float(val_c1)
            st.session_state[f"in_c2_{key_id}"] = float(val_c2)
            st.session_state[state_key_nc] = n_circ_edit

        with st.form(key=f"form_{key_id}"):
            st.markdown("##### ✏️ Verifica e Modifica Dati in Campo")
            nc1, nc2, nc3 = st.columns(3)
            with nc1:
                mod_edit = st.text_input(
                    "Modello", value=str(row["modello"]), key=f"mod_{key_id}"
                )
                matr_edit = st.text_input(
                    "Matricola",
                    value=str(row["matricola"]),
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
                ]
                idx_gas = (
                    gas_lista.index(row["refrigerante"])
                    if row["refrigerante"] in gas_lista
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
                    value=str(row["codice_targa"]),
                    key=f"targa_{key_id}",
                )
            with nc3:
                stato_edit = st.selectbox(
                    "Stato Lavorazione",
                    ["Da Lavorare", "Completato"],
                    index=0 if stato == "Da Lavorare" else 1,
                    key=f"st_{key_id}",
                )
                st.caption(
                    f"GWP applicato ({gas_edit}): **{get_gwp(gas_edit):.0f}**"
                )

            st.markdown(
                "**Carica Refrigerante per Circuito e Calcolo Automatico"
                " Tonn. CO2 Eq**"
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
                    st.info(f"Tonn. CO2 Eq Circuito 1: **{co2_c1_calc:.2f} t**")
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
                    st.info(f"Tonn. CO2 Eq Circuito 2: **{co2_c2_calc:.2f} t**")
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
                st.info(f"Tonn. CO2 Eq Circuito 1: **{co2_c1_calc:.2f} t**")

            carica_tot_calc = round(float(c1_edit) + float(c2_edit), 2)
            co2_tot_calc = round(float(co2_c1_calc) + float(co2_c2_calc), 2)
            st.markdown(
                "**Riepilogo automatico:** Carica Totale ="
                f" **`{carica_tot_calc:.2f} kg`** | Tonn. CO2 Eq Totale ="
                f" **`{co2_tot_calc:.2f} t`**"
            )

            btn_aggiorna = st.form_submit_button(
                "💾 Salva su DB & Excel + Genera Rapportino F-GAS (Firmato)"
            )

            if btn_aggiorna:
                st.session_state[f"c1_val_{key_id}"] = float(c1_edit)
                st.session_state[f"c2_val_{key_id}"] = float(c2_edit)

                conn_up = sqlite3.connect(DB_PATH, timeout=10.0)
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
                    dict(row),
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
                    st.success(
                        f"Salvato su DB e Excel ({msg_xl}) — Rapportino"
                        " generato!"
                    )
                else:
                    st.warning(f"Salvato su DB, ma avviso Excel: {msg_xl}")
                if err_doc:
                    st.error(err_doc)

        ultimo_docx = st.session_state.get(f"last_generated_{key_id}")
        if ultimo_docx and os.path.exists(ultimo_docx):
            with open(ultimo_docx, "rb") as f_docx:
                st.download_button(
                    label="⬇️ Scarica Rapportino .docx generato",
                    data=f_docx.read(),
                    file_name=os.path.basename(ultimo_docx),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    key=f"dl_{key_id}",
                )


def main():
    st.set_page_config(
        page_title="Registro & Rapportini F-GAS",
        page_icon="❄️",
        layout="wide",
    )

    init_db()
    oggi = datetime.now()

    st.title("Registro & Rapportini F-GAS")
    st.caption(
        f"Anno di riferimento: **{oggi.year}** | Database: `{DB_PATH}` | "
        f"Excel: `{EXCEL_PATH}`"
    )

    macchine = carica_macchine()

    if st.button(
        f"📦 Genera Tutti i Rapportini Divisi per Mese (ZIP {oggi.year})",
        key="btn_zip_mensile",
    ):
        with st.spinner("Generazione archivio ZIP mensile in corso..."):
            zip_bytes, n_file = genera_zip_mensile_anno_corrente(macchine, oggi)
            st.session_state["zip_mensile_bytes"] = zip_bytes
            st.session_state["zip_mensile_count"] = n_file

    if st.session_state.get("zip_mensile_bytes"):
        st.download_button(
            label=(
                f"⬇️ Scarica ZIP Rapportini {oggi.year} "
                f"({st.session_state.get('zip_mensile_count', 0)} file)"
            ),
            data=st.session_state["zip_mensile_bytes"],
            file_name=f"Rapportini_FGAS_{oggi.year}_Mensili.zip",
            mime="application/zip",
            key="dl_zip_mensile",
        )

    st.divider()

    tot_unita = len(macchine)
    completate = sum(1 for m in macchine if m.get("stato_compilazione") == "Completato")
    da_lavorare = tot_unita - completate
    carica_tot_flotta = sum(_safe_float(m.get("carica_kg"), 0.0) for m in macchine)
    co2_tot_flotta = sum(_safe_float(m.get("tonn_co2_eq"), 0.0) for m in macchine)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Unità Totali", tot_unita)
    k2.metric("Completate", completate)
    k3.metric("Da Lavorare", da_lavorare)
    k4.metric("CO2 Eq Totale (t)", f"{co2_tot_flotta:.2f} t")
    st.caption(f"Carica totale refrigerante registrata: **{carica_tot_flotta:.2f} kg**")

    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        filtro_testo = st.text_input(
            "🔍 Cerca per Unità, Marca, Modello, Matricola, Targa o Collocazione",
            value="",
        ).strip().lower()
    with f2:
        filtro_stato = st.selectbox(
            "Stato", ["Tutti", "Da Lavorare", "Completato"], index=0
        )
    with f3:
        filtro_gas = st.selectbox(
            "Refrigerante",
            ["Tutti"] + sorted({str(m.get("refrigerante") or "R-410A") for m in macchine}),
            index=0,
        )

    filtrate = []
    for m in macchine:
        if filtro_stato != "Tutti" and m.get("stato_compilazione") != filtro_stato:
            continue
        if filtro_gas != "Tutti" and str(m.get("refrigerante") or "") != filtro_gas:
            continue
        if filtro_testo:
            blob = " ".join(
                str(m.get(k) or "")
                for k in (
                    "id_macchina",
                    "nr_unita",
                    "marca",
                    "modello",
                    "matricola",
                    "collocazione",
                    "codice_targa",
                    "refrigerante",
                )
            ).lower()
            if filtro_testo not in blob:
                continue
        filtrate.append(m)

    st.markdown(f"**Unità visualizzate:** `{len(filtrate)}` su `{tot_unita}`")

    tab_tutte, tab_da_lav, tab_comp = st.tabs(
        [
            f"📋 Tutte ({len(filtrate)})",
            f"🟡 Da Lavorare ({sum(1 for x in filtrate if x.get('stato_compilazione') != 'Completato')})",
            f"🟢 Completate ({sum(1 for x in filtrate if x.get('stato_compilazione') == 'Completato')})",
        ]
    )

    with tab_tutte:
        for idx, r in enumerate(filtrate):
            render_scheda_unita(r, "all", oggi, expanded=(idx == 0 and len(filtrate) == 1))

    with tab_da_lav:
        lista_dl = [x for x in filtrate if x.get("stato_compilazione") != "Completato"]
        for r in lista_dl:
            render_scheda_unita(r, "dl", oggi, expanded=False)

    with tab_comp:
        lista_ok = [x for x in filtrate if x.get("stato_compilazione") == "Completato"]
        for r in lista_ok:
            render_scheda_unita(r, "ok", oggi, expanded=False)


if __name__ == "__main__":
    main()
EOF
