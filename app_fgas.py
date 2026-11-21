import sqlite3
import os
import re
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
    co2_c1_calc,
    co2_c2_calc,
    carica_tot_calc,
    co2_tot_calc,
    oggi,
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(TEMPLATE_FGAS_PATH):
        return None, "Template Word non trovato."

    doc = Document(TEMPLATE_FGAS_PATH)
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
        "{{DATA_INTERVENTO}}": oggi.strftime("%d/%m/%Y"),
        "{{SCADENZA_VERIFICA}}": str(row["scadenza_verifica"]),
        "{{ESITO_CIRC1}}": "ASSENZA PERDITE",
    }

    for p in doc.paragraphs:
        for k, v in mappa.items():
            if k in p.text:
                p.text = p.text.replace(k, str(v))

    for t in doc.tables:
        for r in t.rows:
            for c in r.cells:
                for p in c.paragraphs:
                    for k, v in mappa.items():
                        if k in p.text:
                            p.text = p.text.replace(k, str(v))

    if os.path.exists(FIRMA_PATH):
        for table in doc.tables:
            for row_t in table.rows:
                for cell in row_t.cells:
                    if "Firma" in cell.text:
                        cell.text = ""
                        p_firma = cell.paragraphs[0]
                        run = p_firma.add_run()
                        run.add_picture(FIRMA_PATH, width=Inches(1.2))

    nome_file = (
        f"Report_FGAS_{sanitize_filename(row['marca'])}_{sanitize_filename(mod_edit)}"
        f"_Unita_{sanitize_filename(row['nr_unita'])}.docx"
    )
    out_file = os.path.join(OUTPUT_DIR, nome_file)
    doc.save(out_file)
    return out_file, None


def render_scheda_unita(row, prefix, oggi, expanded=False):
    key_id = f"{prefix}_{sanitize_filename(row['id_macchina'])}"
    stato = row["stato_compilazione"]
    pallino = "🟢" if stato == "Completato" else "🟡"

    n_circ_db = 2 if pd.notna(row.get("n_circuiti")) and int(row.get("n_circuiti")) == 2 else 1
    carica_db = float(row.get("carica_kg") or 0.0)
    c1_db = float(row.get("carica_circ1") or (carica_db / 2 if n_circ_db == 2 else carica_db))
    c2_db = float(row.get("carica_circ2") or (carica_db / 2 if n_circ_db == 2 else 0.0))

    with st.expander(
        f"{pallino} Unità {row['nr_unita']} — {row['marca']} {row['modello']} | Circuiti: `{n_circ_db}` | Targa: `{row['codice_targa']}` | Matr: `{row['matricola']}`",
        expanded=expanded,
    ):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Dati Impianto & Identificativi**")
            st.write(f"- **Collocazione:** `{row['collocazione']}`")
            st.write(f"- **Matricola:** `{row['matricola']}`")
            st.write(f"- **Cod. Apparecchiatura:** `{row['codice_targa']}`")
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

st.sidebar.title("CBRE GWS - Castel Romano")
st.sidebar.markdown("### 🗂️ Registro F-GAS 2026")
menu = st.sidebar.radio("Sezione:", ["Dashboard & Impianti", "Scan Targhetta (Foto/Camera)"])

oggi = datetime.now()

if menu == "Dashboard & Impianti":
    st.title("Gestione Registro & Rapportini F-GAS")

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

            raw_ocr = pytesseract.image_to_string(image).strip()
            if raw_ocr:
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
