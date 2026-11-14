import sqlite3
import os
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
    st.title("Gestione Registro & Rapportini F-GAS")

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_macchine = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    search = st.text_input("🔍 Cerca per Unità, Matricola, Codice Apparecchiatura (Targa), Modello o Marca:", "").strip().lower()
    if search:
        df_view = df_macchine[
            df_macchine["nr_unita"].astype(str).str.lower().str.contains(search) |
            df_macchine["matricola"].astype(str).str.lower().str.contains(search) |
            df_macchine["codice_targa"].astype(str).str.lower().str.contains(search) |
            df_macchine["modello"].astype(str).str.lower().str.contains(search) |
            df_macchine["marca"].astype(str).str.lower().str.contains(search)
        ]
    else:
        df_view = df_macchine

    completati = len(df_macchine[df_macchine["stato_compilazione"] == "Completato"])
    st.markdown(f"**Impianti visualizzati: {len(df_view)} / {len(df_macchine)}** — *Completati: {completati}*")

    for _, row in df_view.iterrows():
        key_id = str(row["id_macchina"]).replace(" ", "_").replace("/", "_")
        stato = row["stato_compilazione"]
        pallino = "🟢" if stato == "Completato" else "🟡"

        with st.expander(f"{pallino} Unità {row['nr_unita']} - {row['marca']} {row['modello']} | Targa: `{row['codice_targa']}` | Matr: `{row['matricola']}`"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Dati Impianto & Identificativi**")
                st.write(f"- **Collocazione:** `{row['collocazione']}`")
                st.write(f"- **Matricola:** `{row['matricola']}`")
                st.write(f"- **Cod. Apparecchiatura:** `{row['codice_targa']}`")
            with c2:
                st.markdown("**Parametri F-GAS**")
                st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
                st.write(f"- **Carica:** `{row['carica_kg']:.2f} kg`")
                st.write(f"- **Tonn. CO2 Eq:** `{row['tonn_co2_eq']:.2f} t`")

            st.divider()

            with st.form(key=f"form_unita_{key_id}"):
                st.markdown("##### ✏️ Verifica e Modifica Dati in Campo")
                nc1, nc2, nc3 = st.columns(3)
                with nc1:
                    mod_edit = st.text_input("Modello", value=row["modello"], key=f"mod_{key_id}")
                    matr_edit = st.text_input("Matricola", value=row["matricola"], key=f"matr_{key_id}")
                with nc2:
                    gas_lista = ["R-410A", "R-407C", "R-32", "R-134a"]
                    idx_gas = gas_lista.index(row["refrigerante"]) if row["refrigerante"] in gas_lista else 0
                    gas_edit = st.selectbox("Refrigerante", gas_lista, index=idx_gas, key=f"gas_{key_id}")
                    carica_edit = st.number_input("Carica (kg)", value=float(row["carica_kg"]), step=0.1, key=f"kg_{key_id}")
                with nc3:
                    co2_edit = st.number_input("Tonn CO2 Eq", value=float(row["tonn_co2_eq"]), step=0.01, key=f"co2_{key_id}")
                    targa_edit = st.text_input("Codice Apparecchiatura (Targa)", value=row["codice_targa"], key=f"targa_{key_id}")
                
                stato_edit = st.selectbox("Stato Lavorazione", ["Da Lavorare", "Completato"], index=0 if row["stato_compilazione"] == "Da Lavorare" else 1, key=f"st_{key_id}")

                btn_aggiorna = st.form_submit_button("💾 Salva & Genera Rapportino F-GAS (Firmato)")

                if btn_aggiorna:
                    conn_up = sqlite3.connect(DB_PATH)
                    cur_up = conn_up.cursor()
                    cur_up.execute("""
                        UPDATE macchine_hvac 
                        SET modello = ?, matricola = ?, refrigerante = ?, carica_kg = ?, tonn_co2_eq = ?, codice_targa = ?, stato_compilazione = ?
                        WHERE id_macchina = ?
                    """, (mod_edit, matr_edit, gas_edit, carica_edit, co2_edit, targa_edit, stato_edit, row["id_macchina"]))
                    conn_up.commit()
                    conn_up.close()

                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    if os.path.exists(TEMPLATE_FGAS_PATH):
                        doc = Document(TEMPLATE_FGAS_PATH)
                        mappa = {
                            "{{UNITA}}": str(row["nr_unita"]),
                            "{{MARCA}}": str(row["marca"]),
                            "{{MODELLO}}": mod_edit,
                            "{{MATRICOLA}}": matr_edit,
                            "{{TIPO_GAS}}": gas_edit,
                            "{{CARICA_KG}}": f"{carica_edit:.2f}",
                            "{{CO2_EQ}}": f"{co2_edit:.2f}",
                            "{{COD_APP}}": targa_edit,
                            "{{DATA_INTERVENTO}}": oggi.strftime("%d/%m/%Y"),
                            "{{SCADENZA_VERIFICA}}": str(row["scadenza_verifica"]),
                            "{{ESITO_CIRC1}}": "ASSENZA PERDITE"
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

                        out_file = os.path.join(OUTPUT_DIR, f"Report_FGAS_{row['marca']}_{mod_edit}_Unita_{row['nr_unita']}.docx")
                        doc.save(out_file)
                        st.session_state[f"last_generated_{key_id}"] = out_file
                        st.success("Modifiche salvate e rapportino firmato generato!")
                        st.rerun()

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
        value=testo_rilevato
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
            
            # Mostra direttamente i risultati con gli expander di modifica e generazione rapportino
            for _, row in df_s.iterrows():
                key_id = str(row["id_macchina"]).replace(" ", "_").replace("/", "_")
                stato = row["stato_compilazione"]
                pallino = "🟢" if stato == "Completato" else "🟡"
                is_single = (len(df_s) == 1)

                with st.expander(f"{pallino} Unità {row['nr_unita']} — {row['marca']} {row['modello']} | Targa: `{row['codice_targa']}` | Matr: `{row['matricola']}`", expanded=is_single):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Dati Impianto & Identificativi**")
                        st.write(f"- **Collocazione:** `{row['collocazione']}`")
                        st.write(f"- **Matricola:** `{row['matricola']}`")
                        st.write(f"- **Cod. Apparecchiatura:** `{row['codice_targa']}`")
                    with c2:
                        st.markdown("**Parametri F-GAS**")
                        st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
                        st.write(f"- **Carica:** `{row['carica_kg']:.2f} kg`")
                        st.write(f"- **Tonn. CO2 Eq:** `{row['tonn_co2_eq']:.2f} t`")

                    st.divider()

                    with st.form(key=f"form_scan_{key_id}"):
                        st.markdown("##### ✏️ Verifica e Modifica Dati in Campo")
                        nc1, nc2, nc3 = st.columns(3)
                        with nc1:
                            mod_edit = st.text_input("Modello", value=row["modello"], key=f"mod_s_{key_id}")
                            matr_edit = st.text_input("Matricola", value=row["matricola"], key=f"matr_s_{key_id}")
                        with nc2:
                            gas_lista = ["R-410A", "R-407C", "R-32", "R-134a"]
                            idx_gas = gas_lista.index(row["refrigerante"]) if row["refrigerante"] in gas_lista else 0
                            gas_edit = st.selectbox("Refrigerante", gas_lista, index=idx_gas, key=f"gas_s_{key_id}")
                            carica_edit = st.number_input("Carica (kg)", value=float(row["carica_kg"]), step=0.1, key=f"kg_s_{key_id}")
                        with nc3:
                            co2_edit = st.number_input("Tonn CO2 Eq", value=float(row["tonn_co2_eq"]), step=0.01, key=f"co2_s_{key_id}")
                            targa_edit = st.text_input("Codice Apparecchiatura (Targa)", value=row["codice_targa"], key=f"targa_s_{key_id}")
                        
                        stato_edit = st.selectbox("Stato Lavorazione", ["Da Lavorare", "Completato"], index=0 if row["stato_compilazione"] == "Da Lavorare" else 1, key=f"st_s_{key_id}")

                        btn_aggiorna_scan = st.form_submit_button("💾 Salva & Genera Rapportino F-GAS (Firmato)")

                        if btn_aggiorna_scan:
                            conn_up = sqlite3.connect(DB_PATH)
                            cur_up = conn_up.cursor()
                            cur_up.execute("""
                                UPDATE macchine_hvac 
                                SET modello = ?, matricola = ?, refrigerante = ?, carica_kg = ?, tonn_co2_eq = ?, codice_targa = ?, stato_compilazione = ?
                                WHERE id_macchina = ?
                            """, (mod_edit, matr_edit, gas_edit, carica_edit, co2_edit, targa_edit, stato_edit, row["id_macchina"]))
                            conn_up.commit()
                            conn_up.close()

                            os.makedirs(OUTPUT_DIR, exist_ok=True)
                            if os.path.exists(TEMPLATE_FGAS_PATH):
                                doc = Document(TEMPLATE_FGAS_PATH)
                                mappa = {
                                    "{{UNITA}}": str(row["nr_unita"]),
                                    "{{MARCA}}": str(row["marca"]),
                                    "{{MODELLO}}": mod_edit,
                                    "{{MATRICOLA}}": matr_edit,
                                    "{{TIPO_GAS}}": gas_edit,
                                    "{{CARICA_KG}}": f"{carica_edit:.2f}",
                                    "{{CO2_EQ}}": f"{co2_edit:.2f}",
                                    "{{COD_APP}}": targa_edit,
                                    "{{DATA_INTERVENTO}}": oggi.strftime("%d/%m/%Y"),
                                    "{{SCADENZA_VERIFICA}}": str(row["scadenza_verifica"]),
                                    "{{ESITO_CIRC1}}": "ASSENZA PERDITE"
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

                                out_file = os.path.join(OUTPUT_DIR, f"Report_FGAS_{row['marca']}_{mod_edit}_Unita_{row['nr_unita']}.docx")
                                doc.save(out_file)
                                st.session_state[f"last_generated_scan_{key_id}"] = out_file
                                st.success("Modifiche salvate e rapportino firmato generato!")
                                st.rerun()

                    last_file_scan = st.session_state.get(f"last_generated_scan_{key_id}")
                    if not last_file_scan:
                        possible_path = os.path.join(OUTPUT_DIR, f"Report_FGAS_{row['marca']}_{row['modello']}_Unita_{row['nr_unita']}.docx")
                        if os.path.exists(possible_path):
                            last_file_scan = possible_path

                    if last_file_scan and os.path.exists(last_file_scan):
                        with open(last_file_scan, "rb") as f_dl_s:
                            st.download_button(
                                label=f"📥 Scarica Rapportino F-GAS Firmato ({os.path.basename(last_file_scan)})",
                                data=f_dl_s,
                                file_name=os.path.basename(last_file_scan),
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"btn_dl_scan_{key_id}"
                            )
        else:
            st.warning("Nessuna unità trovata nel database con questo identificativo.")
