import sqlite3
import os
from datetime import datetime, timedelta
import pandas as pd
from docx import Document
from docx.shared import Inches
import streamlit as st

DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"
OUTPUT_DIR = "Report_FGAS_Generati_2026"
FIRMA_PATH = "firma.jpg"

def init_db():
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
            stato_compilazione TEXT DEFAULT 'Da Lavorare'
        )
    """)

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
            tonn_co2 = float(row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", 0.0)) if pd.notna(row.get("Tonn CO2 Eq", row.get("Tonn. CO2 Eq.", 0.0))) else 0.0)
            carica_col = row.get("Carica Refrigerante (kg)", row.get("Carica (kg)", 0.0))
            carica_kg = float(carica_col) if pd.notna(carica_col) and carica_col != 0.0 else ((tonn_co2 * 1000.0) / 2088.0 if tonn_co2 > 0 else 0.0)
            codice_targa = str(row.get("Cod. Apparecchiatura", row.get("Codice Targa", ""))).strip()
            scadenza = str(row.get("Scadenza Verifica", "14/04/2027")).strip()

            id_unic = f"{nr_unita}_{modello}_{matricola}"

            cursor.execute("""
                INSERT OR IGNORE INTO macchine_hvac 
                (id_macchina, collocazione, nr_unita, marca, modello, matricola, refrigerante, tonn_co2_eq, carica_kg, codice_targa, scadenza_verifica, stato_compilazione)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                id_unic, collocazione, nr_unita, marca, modello, matricola, refrigerante, tonn_co2, carica_kg, codice_targa, scadenza, "Da Lavorare"
            ))

    conn.commit()
    conn.close()

init_db()

st.set_page_config(page_title="CBRE GWS - F-GAS Castel Romano", layout="wide")

st.sidebar.title("CBRE GWS - Castel Romano")
st.sidebar.markdown("### 🗂️ Registro F-GAS 2026")
menu = st.sidebar.radio("Sezione:", ["Dashboard & Impianti", "Scan Targhetta (Foto/Camera)"])

oggi = datetime.now()

if menu == "Dashboard & Impianti":
    st.title("Gestione Registro & Rapportini F-GAS (Firmati)")

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_macchine = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    search = st.text_input("🔍 Cerca per Unità, Modello, Targa o Marca:", "").strip().lower()
    if search:
        df_view = df_macchine[
            df_macchine["nr_unita"].str.lower().str.contains(search) |
            df_macchine["modello"].str.lower().str.contains(search) |
            df_macchine["codice_targa"].str.lower().str.contains(search) |
            df_macchine["marca"].str.lower().str.contains(search)
        ]
    else:
        df_view = df_macchine

    st.markdown(f"**Impianti visualizzati: {len(df_view)} / {len(df_macchine)}**")

    for _, row in df_view.iterrows():
        key_id = str(row["id_macchina"]).replace(" ", "_").replace("/", "_")
        stato = row["stato_compilazione"]
        pallino = "🟢" if stato == "Completato" else "🟡"

        with st.expander(f"{pallino} Unità {row['nr_unita']} - {row['marca']} {row['modello']} (Targa: `{row['codice_targa']}`) - Stato: {stato}"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Dati Impianto & Targa**")
                st.write(f"- **Collocazione:** `{row['collocazione']}`")
                st.write(f"- **Matricola:** `{row['matricola']}`")
            with c2:
                st.markdown("**Parametri F-GAS**")
                st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
                st.write(f"- **Carica:** `{row['carica_kg']:.2f} kg`")
                st.write(f"- **Tonn. CO2 Eq:** `{row['tonn_co2_eq']:.2f} t`")

            st.divider()

            with st.form(key=f"form_unita_{key_id}"):
                st.markdown("##### ✏️ Verifica e Modifica Dati (se difformi dal campo)")
                nc1, nc2, nc3 = st.columns(3)
                with nc1:
                    mod_edit = st.text_input("Modello", value=row["modello"], key=f"mod_{key_id}")
                    gas_edit = st.selectbox("Refrigerante", ["R-410A", "R-407C", "R-32", "R-134a"], index=0 if "410" in row["refrigerante"] else 1, key=f"gas_{key_id}")
                with nc2:
                    carica_edit = st.number_input("Carica (kg)", value=float(row["carica_kg"]), step=0.1, key=f"kg_{key_id}")
                    co2_edit = st.number_input("Tonn CO2 Eq", value=float(row["tonn_co2_eq"]), step=0.01, key=f"co2_{key_id}")
                with nc3:
                    targa_edit = st.text_input("Codice Targa", value=row["codice_targa"], key=f"targa_{key_id}")
                    stato_edit = st.selectbox("Stato Lavorazione", ["Da Lavorare", "Completato"], index=0 if row["stato_compilazione"]=="Da Lavorare" else 1, key=f"st_{key_id}")

                btn_aggiorna = st.form_submit_button("💾 Salva & Genera Rapportino F-GAS (Firmato)")

                if btn_aggiorna:
                    conn_up = sqlite3.connect(DB_PATH)
                    cur_up = conn_up.cursor()
                    cur_up.execute("""
                        UPDATE macchine_hvac 
                        SET modello = ?, refrigerante = ?, carica_kg = ?, tonn_co2_eq = ?, codice_targa = ?, stato_compilazione = ?
                        WHERE id_macchina = ?
                    """, (mod_edit, gas_edit, carica_edit, co2_edit, targa_edit, stato_edit, row["id_macchina"]))
                    conn_up.commit()
                    conn_up.close()

                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    if os.path.exists(TEMPLATE_FGAS_PATH):
                        doc = Document(TEMPLATE_FGAS_PATH)
                        mappa = {
                            "{{UNITA}}": str(row["nr_unita"]),
                            "{{MARCA}}": str(row["marca"]),
                            "{{MODELLO}}": mod_edit,
                            "{{MATRICOLA}}": str(row["matricola"]),
                            "{{TIPO_GAS}}": gas_edit,
                            "{{CARICA_KG}}": f"{carica_edit:.2f}",
                            "{{CO2_EQ}}": f"{co2_edit:.2f}",
                            "{{COD_APP}}": targa_edit,
                            "{{DATA_INTERVENTO}}": oggi.strftime("%d/%m/%Y"),
                            "{{SCADENZA_VERIFICA}}": str(row["scadenza_verifica"]),
                            "{{ESITO_CIRC1}}": "ASSENZA PERDITE"
                        }
                        
                        # Sostituzione testo
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

                        # Inserimento automatico dell'immagine della firma 'firma.jpg' nelle celle con "Firma"
                        if os.path.exists(FIRMA_PATH):
                            for table in doc.tables:
                                for row_t in table.rows:
                                    for cell in row_t.cells:
                                        if "Firma" in cell.text:
                                            # Rimuoviamo il testo "Firma" o aggiungiamo l'immagine sotto/al posto del testo
                                            cell.text = "" # Pulisce la cella o mantiene lo spazio
                                            p_firma = cell.paragraphs[0]
                                            run = p_firma.add_run()
                                            run.add_picture(FIRMA_PATH, width=Inches(1.2))

                        out_file = os.path.join(OUTPUT_DIR, f"Report_FGAS_{row['marca']}_{mod_edit}_Unita_{row['nr_unita']}.docx")
                        doc.save(out_file)
                        st.session_state[f"last_generated_{key_id}"] = out_file
                        st.success("Modifiche salvate e rapportino firmato generato con successo!")
                        st.rerun()

            # Pulsante di download diretto
            last_file = st.session_state.get(f"last_generated_{key_id}")
            if not last_file:
                possible_path = os.path.join(OUTPUT_DIR, f"Report_FGAS_{row['marca']}_{row['modello']}_Unita_{row['nr_unita']}.docx")
                if os.path.exists(possible_path):
                    last_file = possible_path

            if last_file and os.path.exists(last_file):
                with open(last_file, "rb") as f_dl:
                    st.download_button(
                        label=f"📥 Scarica Rapportino F-GAS Firmato ({os.path.basename(last_file)})",
                        data=f_dl,
                        file_name=os.path.basename(last_file),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"btn_dl_{key_id}"
                    )

elif menu == "Scan Targhetta (Foto/Camera)":
    st.title("Riconoscimento Impianto da Targhetta in Campo")
    st.markdown("Scatta una foto con lo smartphone o carica l'immagine della targhetta metallica in copertura per identificare l'unità.")

    img_file = st.camera_input("Scatta foto targhetta")
    uploaded_img = st.file_uploader("Oppure carica immagine targhetta", type=["jpg", "jpeg", "png"])

    target_img = img_file if img_file is not None else uploaded_img

    if target_img is not None:
        st.image(target_img, caption="Targhetta acquisita", use_column_width=True)
        search_code = st.text_input("Inserisci Codice Targa o Unità letta dalla foto:").strip()
        if search_code:
            conn = sqlite3.connect(DB_PATH)
            df_s = pd.read_sql("SELECT * FROM macchine_hvac WHERE codice_targa LIKE ? OR nr_unita LIKE ?", conn, params=(f"%{search_code}%", f"%{search_code}%"))
            conn.close()

            if not df_s.empty:
                st.success(f"Trovate {len(df_s)} unità corrispondenti!")
                for _, match in df_s.iterrows():
                    st.write(f"**Unità {match['nr_unita']}** - Marca: {match['marca']} - Modello: {match['modello']} - Targa: `{match['codice_targa']}` - Stato: `{match['stato_compilazione']}`")
            else:
                st.warning("Nessuna unità trovata con questo codice nel database master.")
            
