import sqlite3
import os
from datetime import datetime, timedelta
import pandas as pd
from docx import Document
import streamlit as st

DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_Assegnato.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"
OUTPUT_DIR = "Report_FGAS_Generati_2026"

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS macchine_hvac (
            id_macchina TEXT PRIMARY KEY,
            fgas_num TEXT,
            collocazione TEXT,
            nr_unita TEXT,
            descrizione TEXT,
            codice_targa TEXT,
            tipologia TEXT,
            marca TEXT,
            modello TEXT,
            refrigerante TEXT,
            tonn_co2_eq REAL,
            carica_kg REAL,
            operatore_assegnato TEXT,
            zona TEXT,
            ultima_verifica TEXT,
            scadenza_verifica TEXT,
            stato_compilazione TEXT DEFAULT 'Da Lavorare'
        )
    """)

    if os.path.exists(EXCEL_PATH):
        xls = pd.ExcelFile(EXCEL_PATH)
        df_excel = pd.read_excel(xls, sheet_name="Master F-GAS 2026")
        for _, row in df_excel.iterrows():
            fgas_num = str(row.get("F-GAS N°", "")).strip()
            collocazione = str(row.get("Collocazione", "")).strip()
            nr_unita = str(row.get("Unità / Macchina", "")).strip()
            descrizione = str(row.get("Descrizione Impianto", "")).strip()
            codice_targa = str(row.get("Cod. Apparecchiatura", "")).strip()
            tipologia = str(row.get("Tipologia", "")).strip()
            marca = str(row.get("Marca", "")).strip()
            modello = str(row.get("Modello", "")).strip()
            refrigerante = str(row.get("Refrigerante", "R-410A")).strip()
            tonn_co2 = float(row.get("Tonn. CO2 Eq.", 0.0) if pd.notna(row.get("Tonn. CO2 Eq.")) else 0.0)
            operatore = str(row.get("Operatore Assegnato", "")).strip()
            zona = str(row.get("Zona / Area Designata", "")).strip()

            # Calcolo carica kg in base a GWP R-410A (2088) o generico
            carica_kg = (tonn_co2 * 1000.0) / 2088.0 if tonn_co2 > 0 else 0.0
            id_unic = f"{fgas_num}_{nr_unita}_{modello}"

            cursor.execute("""
                INSERT OR IGNORE INTO macchine_hvac 
                (id_macchina, fgas_num, collocazione, nr_unita, descrizione, codice_targa, tipologia, marca, modello, refrigerante, tonn_co2_eq, carica_kg, operatore_assegnato, zona, ultima_verifica, scadenza_verifica, stato_compilazione)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                id_unic, fgas_num, collocazione, nr_unita, descrizione, codice_targa, tipologia, marca, modello, refrigerante, tonn_co2, carica_kg, operatore, zona, "01/01/2026", "01/01/2027", "Da Lavorare"
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

    # Filtro rapido per operatore
    operatori = sorted(df_macchine["operatore_assegnato"].dropna().unique().tolist())
    op_scelto = st.selectbox("Filtra per Operatore Assegnato:", ["Tutti"] + operatori)

    if op_scelto != "Tutti":
        df_view = df_macchine[df_macchine["operatore_assegnato"] == op_scelto]
    else:
        df_view = df_macchine

    search = st.text_input("🔍 Cerca per Unità, Modello, Targa o Zona:", "").strip().lower()
    if search:
        df_view = df_view[
            df_view["nr_unita"].str.lower().str.contains(search) |
            df_view["modello"].str.lower().str.contains(search) |
            df_view["codice_targa"].str.lower().str.contains(search) |
            df_view["zona"].str.lower().str.contains(search)
        ]

    st.markdown(f"**Impianti visualizzati: {len(df_view)} / {len(df_macchine)}**")

    for _, row in df_view.iterrows():
        # Stato con pallini
        stato = row["stato_compilazione"]
        pallino = "🟢" if stato == "Completato" else "🟡"

        with st.expander(f"{pallino} [F-GAS N° {row['fgas_num']}] Unità {row['nr_unita']} - {row['marca']} {row['modello']} ({row['zona']}) - Stato: {stato}"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Dati Impianto & Targa**")
                st.write(f"- **Codice Targa:** `{row['codice_targa']}`")
                st.write(f"- **Tipologia:** `{row['tipologia']}`")
                st.write(f"- **Collocazione:** `{row['collocazione']}`")
            with c2:
                st.markdown("**Parametri F-GAS**")
                st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
                st.write(f"- **Carica:** `{row['carica_kg']:.2f} kg`")
                st.write(f"- **Tonn. CO2 Eq:** `{row['tonn_co2_eq']:.2f} t`")

            st.divider()

            # Form di modifica rapida targa/dati e generazione certificato
            with st.form(key=f"form_unita_{row['id_macchina']}"):
                st.markdown("##### ✏️ Verifica e Modifica Dati (se difformi dal campo)")
                nc1, nc2, nc3 = st.columns(3)
                with nc1:
                    mod_edit = st.text_input("Modello", value=row["modello"], key=f"mod_{row['id_macchina']}")
                    gas_edit = st.selectbox("Refrigerante", ["R-410A", "R-407C", "R-32", "R-134a"], index=0 if row["refrigerante"]=="R-410A" else 1, key=f"gas_{row['id_macchina']}")
                with nc2:
                    carica_edit = st.number_input("Carica (kg)", value=float(row["carica_kg"]), step=0.1, key=f"kg_{row['id_macchina']}")
                    co2_edit = st.number_input("Tonn CO2 Eq", value=float(row["tonn_co2_eq"]), step=0.01, key=f"co2_{row['id_macchina']}")
                with nc3:
                    targa_edit = st.text_input("Codice Targa", value=row["codice_targa"], key=f"targa_{row['id_macchina']}")
                    stato_edit = st.selectbox("Stato Lavorazione", ["Da Lavorare", "Completato"], index=0 if row["stato_compilazione"]=="Da Lavorare" else 1, key=f"st_{row['id_macchina']}")

                btn_aggiorna = st.form_submit_button("💾 Salva Modifiche & Genera Rapportino F-GAS")

                if btn_aggiorna:
                    # Aggiornamento Database
                    conn_up = sqlite3.connect(DB_PATH)
                    cur_up = conn_up.cursor()
                    cur_up.execute("""
                        UPDATE macchine_hvac 
                        SET modello = ?, refrigerante = ?, carica_kg = ?, tonn_co2_eq = ?, codice_targa = ?, stato_compilazione = ?
                        WHERE id_macchina = ?
                    """, (mod_edit, gas_edit, carica_edit, co2_edit, targa_edit, stato_edit, row["id_macchina"]))
                    conn_up.commit()
                    conn_up.close()

                    # Generazione file Word F-GAS
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    if os.path.exists(TEMPLATE_FGAS_PATH):
                        doc = Document(TEMPLATE_FGAS_PATH)
                        mappa = {
                            "{{UNITA}}": str(row["nr_unita"]),
                            "{{MARCA}}": str(row["marca"]),
                            "{{MODELLO}}": mod_edit,
                            "{{MATRICOLA}}": mod_edit,
                            "{{TIPO_GAS}}": gas_edit,
                            "{{CARICA_KG}}": f"{carica_edit:.2f}",
                            "{{CO2_EQ}}": f"{co2_edit:.2f}",
                            "{{COD_APP}}": targa_edit,
                            "{{DATA_INTERVENTO}}": oggi.strftime("%d/%m/%Y"),
                            "{{SCADENZA_VERIFICA}}": (oggi + timedelta(days=365)).strftime("%d/%m/%Y"),
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
                        
                        out_file = os.path.join(OUTPUT_DIR, f"Report_FGAS_{row['marca']}_{mod_edit}_Unita_{row['nr_unita']}.docx")
                        doc.save(out_file)
                        st.success(f"Modifiche salvate e rapportino generato con successo in '{OUTPUT_DIR}'!")
                        st.rerun()

elif menu == "Scan Targhetta (Foto/Camera)":
    st.title("Riconoscimento Impianto da Targhetta in Campo")
    st.markdown("Scatta una foto con lo smartphone o carica l'immagine della targhetta metallica in copertura per identificare l'unità.")

    img_file = st.camera_input("Scatta foto targhetta")
    uploaded_img = st.file_uploader("Oppure carica immagine targhetta", type=["jpg", "jpeg", "png"])

    target_img = img_file if img_file is not None else uploaded_img

    if target_img is not None:
        st.image(target_img, caption="Targhetta acquisita", use_column_width=True)
        st.info("💡 Immagine acquisita correttamente. Inserisci il codice targa o il numero unità visibile nella foto per richiamare subito la scheda nel database:")

        search_code = st.text_input("Inserisci Codice Targa o Unità letta dalla foto:").strip()
        if search_code:
            conn = sqlite3.connect(DB_PATH)
            df_s = pd.read_sql("SELECT * FROM macchine_hvac WHERE codice_targa LIKE ? OR nr_unita LIKE ?", conn, params=(f"%{search_code}%", f"%{search_code}%"))
            conn.close()

            if not df_s.empty:
                st.success(f"Trovate {len(df_s)} unità corrispondenti!")
                for _, match in df_s.iterrows():
                    st.write(f"**Unità {match['nr_unita']}** - Marca: {match['marca']} - Modello: {match['modello']} - Targa: `{match['codice_targa']}`")
            else:
                st.warning("Nessuna unità trovata con questo codice nel database master. Verifica o inserisci i dati manualmente nella sezione Dashboard.")
