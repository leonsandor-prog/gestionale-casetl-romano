import sqlite3
import os
from datetime import datetime, timedelta
import pandas as pd
from docx import Document
import streamlit as st

DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_Assegnato.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"

def init_db_mappa():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()

    try:
        # Tabella ODL Straordinari / A chiamata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS odl_chiamata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codice_odl TEXT,
                richiedente TEXT,
                descrizione TEXT,
                data_registro TEXT,
                ora_inizio TEXT,
                ora_fine TEXT,
                esito TEXT,
                note TEXT,
                stato TEXT,
                operatore_esecutore TEXT
            )
        """)

        # Tabella HVAC con specifica filtri e gestione della retention
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS macchine_hvac (
                id_macchina TEXT PRIMARY KEY,
                nr_unita TEXT,
                marca TEXT,
                modello_matricola TEXT,
                ubicazione_negozio TEXT,
                quadro_elettrico TEXT,
                potenza_kw REAL,
                n_circuiti INTEGER,
                refrigerante TEXT,
                codice_targa TEXT,
                ultima_verifica TEXT,
                scadenza_verifica TEXT,
                macro_area TEXT,
                tonn_co2_eq REAL,
                carica_kg REAL,
                f_gas_attivo TEXT,
                data_scadenza_dt TEXT,
                operatore_assegnato TEXT,
                filtro_dimensioni TEXT,
                filtro_quantita INTEGER
            )
        """)

        # Inizializzazione dati da Excel solo se il DB è vuoto
        cursor.execute("SELECT COUNT(*) FROM macchine_hvac")
        if cursor.fetchone()[0] == 0 and os.path.exists(EXCEL_PATH):
            df_excel = pd.read_excel(EXCEL_PATH, sheet_name="Master F-GAS 2026")
            for _, row in df_excel.iterrows():
                descrizione = str(row.get("Descrizione Impianto", "")).strip()
                marca = str(row.get("Marca", "")).strip()
                mod_mat = str(row.get("Modello", "")).strip()
                cod_app = str(row.get("Cod. Apparecchiatura", "")).strip()
                refrigerante = str(row.get("Refrigerante", "R410A")).strip()
                tonn_co2 = row.get("Tonn. CO2 Eq.", 0.0)
                if pd.isna(tonn_co2):
                    tonn_co2 = 0.0
                operatore = str(row.get("Operatore Assegnato", "")).strip()
                zona = str(row.get("Zona / Area Designata", "")).strip()
                unita_str = str(row.get("Unità / Macchina", "")).strip()

                carica_kg = (tonn_co2 * 1000.0) / 2088.0 if tonn_co2 > 0 else 0.0
                id_unic = f"{unita_str}_{mod_mat}_{cod_app}"

                cursor.execute("""
                    INSERT OR REPLACE INTO macchine_hvac 
                    (id_macchina, nr_unita, marca, modello_matricola, ubicazione_negozio, quadro_elettrico, potenza_kw, n_circuiti, refrigerante, codice_targa, ultima_verifica, scadenza_verifica, macro_area, tonn_co2_eq, carica_kg, f_gas_attivo, data_scadenza_dt, operatore_assegnato, filtro_dimensioni, filtro_quantita)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    id_unic, unita_str, marca, mod_mat, zona, "Quadro Generale", 
                    float(carica_kg * 1.2), 1, refrigerante, cod_app, 
                    "01/01/2026", "01/01/2027", "MCARTHUR_RM", float(tonn_co2), 
                    float(carica_kg), "S", "2027-01-01", operatore, "", 1
                ))

        conn.commit()
    finally:
        conn.close()

def aggiorna_scadenza_db(id_macchina, nuova_data_str, nuova_scad_str):
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE macchine_hvac 
        SET ultima_verifica = ?, scadenza_verifica = ?, data_scadenza_dt = ?
        WHERE id_macchina = ?
    """, (
        nuova_data_str, 
        nuova_scad_str, 
        datetime.strptime(nuova_scad_str, "%d/%m/%Y").strftime("%Y-%m-%d"), 
        id_macchina
    ))
    conn.commit()
    conn.close()

def sostituisci_testo_docx(doc, mappa_sostituzioni):
    for p in doc.paragraphs:
        for chiave, valore in mappa_sostituzioni.items():
            if chiave in p.text:
                p.text = p.text.replace(chiave, str(valore))

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for chiave, valore in mappa_sostituzioni.items():
                        if chiave in p.text:
                            p.text = p.text.replace(chiave, str(valore))

init_db_mappa()

st.set_page_config(page_title="CBRE GWS - Castel Romano HVAC", layout="wide")

# --- LOGIN E PROFILAZIONE UTENTE ---
st.sidebar.title("CBRE GWS - Castel Romano")
st.sidebar.markdown("### 🔐 Autenticazione")

utente_login = st.sidebar.selectbox(
    "Seleziona Tecnico / Operatore:",
    ["Seleziona...", "Antonio (Lead / F-GAS)", "Pino", "Gianluca", "Johann"]
)

if "autorizzato_fgas" not in st.session_state:
    st.session_state["autorizzato_fgas"] = False
if "operatore_corrente" not in st.session_state:
    st.session_state["operatore_corrente"] = ""

if utente_login != "Seleziona...":
    if "Antonio" in utente_login:
        codice_id = st.sidebar.text_input("Inserisci Codice LUL (PIN):", type="password")
        if codice_id == "3177":
            st.session_state["autorizzato_fgas"] = True
            st.session_state["operatore_corrente"] = "Antonio"
            st.sidebar.success("✅ Accesso Admin F-GAS Abilitato")
            st.sidebar.markdown("**Certificazione:** PR0148807 (Cat. I)")
        elif codice_id != "":
            st.sidebar.error("❌ Codice LUL Errato")
            st.session_state["autorizzato_fgas"] = False
    else:
        st.session_state["autorizzato_fgas"] = False
        st.session_state["operatore_corrente"] = utente_login
        st.sidebar.info(f"ℹ️ Accesso Operativo: {utente_login}")

# MENU DINAMICO IN BASE AI PERMESSI
opzioni_menu = ["Dashboard Operatori", "Ricerca & Planimetria Impianti", "ODL Correttiva / Extra"]
if st.session_state["autorizzato_fgas"]:
    opzioni_menu.insert(1, "Registro F-GAS & Scadenze (Riservato)")
    opzioni_menu.append("Profilo & Abilitazioni F-GAS")

menu = st.sidebar.selectbox("Seleziona Modulo Operativo", opzioni_menu)
oggi = datetime.now()

# ---------------------------------------------------------
# 1. DASHBOARD OPERATORI
# ---------------------------------------------------------
if menu == "Dashboard Operatori":
    st.title("Dashboard Manutenzione & Stato Impianti")
    st.markdown("Panoramica operativa delle macchine HVAC per zona e operatore di riferimento.")

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_impianti = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    op_scelto = st.radio(
        "Filtra Impianti per Operatore:",
        ["🟢 Pino", "🟡 Gianluca", "🔵 Johann", "🟣 Antonio", "Tutti"],
        horizontal=True
    )
    
    mapping_nomi = {"🟢 Pino": "Pino", "🟡 Gianluca": "Gianluca", "🔵 Johann": "Johann", "🟣 Antonio": "Antonio"}
    
    if op_scelto != "Tutti":
        nome_sel = mapping_nomi[op_scelto]
        df_op = df_impianti[df_impianti["operatore_assegnato"].str.lower() == nome_sel.lower()]
    else:
        df_op = df_impianti.copy()

    st.subheader(f"Unità Mappate ({len(df_op)} macchine)")

    for idx, row in df_op.iterrows():
        key_id = str(row["id_macchina"]).replace(" ", "_").replace("/", "_")
        scad_str = str(row["data_scadenza_dt"])
        try:
            dt_scad = datetime.strptime(scad_str[:10], "%Y-%m-%d")
            delta = (dt_scad - oggi).days
        except:
            delta = 9999

        pallino = "🔴" if delta < 0 else ("🟡" if delta <= 30 else "🟢")

        with st.expander(f"{pallino} Unità {row['nr_unita']} - {row['marca']} ({row['ubicazione_negozio']})"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**Dati Impianto**")
                st.write(f"- **Modello/Matricola:** `{row['modello_matricola']}`")
                st.write(f"- **Targa:** `{row['codice_targa']}`")
            with c2:
                st.markdown("**Refrigerante**")
                st.write(f"- **Tipo Gas:** `{row['refrigerante']}`")
                st.write(f"- **Carica:** `{row['carica_kg']:.2f} kg` ({row['tonn_co2_eq']} tCO2e)")
            with c3:
                st.markdown("**Stato Controllo**")
                st.write(f"- **Ultima Verifica:** `{row['ultima_verifica']}`")
                st.write(f"- **Scadenza:** `{row['scadenza_verifica']}`")

# ---------------------------------------------------------
# 2. RICERCA & PLANIMETRIA (CHECKLIST MANUTENZIONE & FILTRI)
# ---------------------------------------------------------
elif menu == "Ricerca & Planimetria Impianti":
    st.title("Gestione Impianti HVAC & Checklist Operative")

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_impianti = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    search_query = st.text_input("Cerca per unità, negozio, marca o targa:", "").strip().lower()
    if search_query:
        unita_filtrate = df_impianti[
            df_impianti["ubicazione_negozio"].astype(str).str.lower().str.contains(search_query) |
            df_impianti["nr_unita"].astype(str).str.lower().str.contains(search_query) |
            df_impianti["marca"].astype(str).str.lower().str.contains(search_query) |
            df_impianti["codice_targa"].astype(str).str.lower().str.contains(search_query)
        ]
    else:
        unita_filtrate = df_impianti.copy()

    for idx, row in unita_filtrate.iterrows():
        key_id = str(row["id_macchina"]).replace(" ", "_").replace("/", "_")
        scad_str = str(row["data_scadenza_dt"])
        try:
            dt_scad = datetime.strptime(scad_str[:10], "%Y-%m-%d")
            delta = (dt_scad - oggi).days
        except:
            delta = 9999

        pallino = "🔴" if delta < 0 else ("🟡" if delta <= 30 else "🟢")

        with st.expander(f"{pallino} Unità {row['nr_unita']} - {row['marca']} (Targa: {row['codice_targa']})"):
            tab_manutenzione, tab_fgas_admin = st.tabs(["📋 Checklist & Filtri (Operativo)", "🔒 Controllo F-GAS (Riservato)"])

            with tab_manutenzione:
                db_dim_filtro = str(row.get("filtro_dimensioni", "") or "")
                db_qta_filtro = int(row.get("filtro_quantita", 1) if pd.notna(row.get("filtro_quantita", 1)) else 1)

                with st.form(key=f"form_manut_{key_id}"):
                    st.markdown("##### Checklist Manutenzione Ordinaria & Specifiche Filtri")
                    
                    c_f1, c_f2 = st.columns(2)
                    with c_f1:
                        dim_in = st.text_input("Dimensioni Filtri (es. 500x500x48 mm)", value=db_dim_filtro, key=f"dim_{key_id}")
                    with c_f2:
                        qta_in = st.number_input("Quantità Filtri", min_value=1, max_value=20, value=db_qta_filtro, key=f"qta_{key_id}")

                    st.markdown("**Controlli Operativi Eseguiti:**")
                    chk_visivo = st.checkbox("Controllo visivo generale e fissaggi", value=True, key=f"chk1_{key_id}")
                    chk_filtri = st.checkbox("Pulizia / Sostituzione filtri aria", value=True, key=f"chk2_{key_id}")
                    chk_batterie = st.checkbox("Pulizia batteria di condensazione / espansione", value=True, key=f"chk3_{key_id}")
                    chk_comandi = st.checkbox("Verifica principali organi di controllo e comando", value=True, key=f"chk4_{key_id}")
                    chk_condensa = st.checkbox("Verifica e pulizia scarico condensa", value=True, key=f"chk5_{key_id}")

                    note_manut = st.text_input("Note Intervento", "Manutenzione ordinaria e controllo eseguiti regolarmente.", key=f"nt_man_{key_id}")

                    btn_salva = st.form_submit_button("Salva Aggiornamenti & Genera Rapportino Word")
                    if btn_salva:
                        # Update SQLite per preservare dimensioni e quantità filtri
                        conn_u = sqlite3.connect(DB_PATH, timeout=10.0)
                        cur_u = conn_u.cursor()
                        cur_u.execute("UPDATE macchine_hvac SET filtro_dimensioni = ?, filtro_quantita = ? WHERE id_macchina = ?", (dim_in, qta_in, row["id_macchina"]))
                        conn_u.commit()
                        conn_u.close()

                        # Documento Word
                        doc_f = Document()
                        doc_f.add_heading("RAPPORTINO MANUTENZIONE ORDINARIA & FILTRI", level=1)
                        doc_f.add_paragraph(f"Sito: McArthurGlen Designer Outlet Castel Romano\nData: {datetime.now().strftime('%d/%m/%Y %H:%M')}\nImpianto: {row['nr_unita']}")
                        doc_f.add_paragraph(f"Dettagli: Marca/Modello: {row['marca']} {row['modello_matricola']} | Targa: {row['codice_targa']}")
                        doc_f.add_paragraph(f"Specifiche Filtri: {dim_in} | Quantità: {qta_in} pz")
                        doc_f.add_paragraph(f"Esito Controlli:\n- Controllo Visivo: {'OK' if chk_visivo else 'NO'}\n- Pulizia Filtri: {'OK' if chk_filtri else 'NO'}\n- Batteria Condensazione: {'OK' if chk_batterie else 'NO'}\n- Organi Comando: {'OK' if chk_comandi else 'NO'}\n- Scarico Condensa: {'OK' if chk_condensa else 'NO'}")
                        doc_f.add_paragraph(f"Note Tecniche: {note_manut}")
                        doc_f.add_paragraph(f"Tecnico Esecutore: {st.session_state.get('operatore_corrente', 'CBRE Technician')}")

                        filename_filt = f"Rapportino_Ordinario_{str(row['nr_unita']).replace(' ', '_')}.docx"
                        doc_f.save(filename_filt)
                        st.session_state[f"dl_filt_{key_id}"] = filename_filt
                        st.success("Dati e specifiche filtri aggiornati nel database con successo!")
                        st.rerun()

                if st.session_state.get(f"dl_filt_{key_id}"):
                    f_path_filt = st.session_state[f"dl_filt_{key_id}"]
                    if os.path.exists(f_path_filt):
                        with open(f_path_filt, "rb") as f_in_f:
                            st.download_button(
                                label="📥 Scarica Rapportino Manutenzione Word",
                                data=f_in_f,
                                file_name=f_path_filt,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"dl_btn_m_{key_id}",
                            )

            with tab_fgas_admin:
                if not st.session_state["autorizzato_fgas"]:
                    st.warning("⚠️ Accesso Riservato. Moduli F-GAS modificabili solo da Antonio (ID 3177).")
                else:
                    with st.form(key=f"form_fgas_{key_id}"):
                        st.markdown("##### Controllo Periodico F-GAS e Rinnovo Registro Ufficiale")
                        data_int = st.text_input("Data Intervento", value=oggi.strftime("%d/%m/%Y"), key=f"dt_fgas_{key_id}")
                        nuova_scad = st.text_input("Nuova Scadenza (1 Anno)", value=(oggi + timedelta(days=365)).strftime("%d/%m/%Y"), key=f"scad_fgas_{key_id}")
                        esito_fgas = st.selectbox("Esito Controllo Perdite", ["Assenza Perdite", "Rilevata Perdita"], key=f"es_fgas_{key_id}")
                        note_fgas = st.text_input("Note Certificato", "Verifica uscite e tenuta gas eseguita con esito regolare.", key=f"nt_fgas_{key_id}")

                        btn_fgas = st.form_submit_button("Emetti Certificato F-GAS e Aggiorna Registro")
                        if btn_fgas:
                            if os.path.exists(TEMPLATE_FGAS_PATH):
                                doc = Document(TEMPLATE_FGAS_PATH)
                                me_data = {
                                    "{{UNITA}}": str(row["nr_unita"]),
                                    "{{MARCA}}": str(row["marca"]),
                                    "{{MODELLO}}": str(row["modello_matricola"]),
                                    "{{MATRICOLA}}": str(row["modello_matricola"]),
                                    "{{TIPO_GAS}}": str(row["refrigerante"]),
                                    "{{CARICA_KG}}": f"{row['carica_kg']:.2f} kg",
                                    "{{CO2_EQ}}": f"{row['tonn_co2_eq']} tCO2e",
                                    "{{COD_APP}}": str(row["codice_targa"]),
                                    "{{DATA_INTERVENTO}}": data_int,
                                    "{{SCADENZA_VERIFICA}}": nuova_scad,
                                    "{{ESITO_CIRC1}}": esito_fgas.upper(),
                                    "{{NOTE_FGAS}}": note_fgas,
                                }
                                sostituisci_testo_docx(doc, me_data)
                                filename_fgas = f"Report_FGAS_{row['marca']}_{key_id}.docx"
                                doc.save(filename_fgas)

                                aggiorna_scadenza_db(row["id_macchina"], data_int, nuova_scad)
                                st.session_state[f"dl_fgas_{key_id}"] = filename_fgas
                                st.success("Certificato F-GAS emesso e registro aggiornato!")
                                st.rerun()
                            else:
                                st.error(f"Modello '{TEMPLATE_FGAS_PATH}' non reperito nel sistema.")

                    if st.session_state.get(f"dl_fgas_{key_id}"):
                        f_path = st.session_state[f"dl_fgas_{key_id}"]
                        if os.path.exists(f_path):
                            with open(f_path, "rb") as f_in:
                                st.download_button(
                                    label="📥 Scarica Certificato F-GAS (.docx)",
                                    data=f_in,
                                    file_name=f_path,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"dl_btn_fgas_{key_id}",
                                )

# ---------------------------------------------------------
# 3. REGISTRO F-GAS (SOLO ADMIN ANTONIO)
# ---------------------------------------------------------
elif menu == "Registro F-GAS & Scadenze (Riservato)":
    st.title("Registro Ufficiale Apparecchiature F-GAS 2026")
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_prev = pd.read_sql("SELECT nr_unita, marca, modello_matricola, refrigerante, codice_targa, ultima_verifica, scadenza_verifica, tonn_co2_eq, carica_kg, operatore_assegnato FROM macchine_hvac", conn)
    conn.close()

    st.dataframe(df_prev, use_container_width=True, hide_index=True)

    excel_scadenze = f"Registro_Master_FGAS_CastelRomano_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df_prev.to_excel(excel_scadenze, index=False)
    with open(excel_scadenze, "rb") as f_scad:
        st.download_button(
            label="📊 Scarica Registro Master F-GAS in Excel",
            data=f_scad,
            file_name=excel_scadenze,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_scad_fgas_admin",
        )

# ---------------------------------------------------------
# 4. ODL CORRETTIVA & ARCHIVIO RETENTION 2+ ANNI
# ---------------------------------------------------------
elif menu == "ODL Correttiva / Extra":
    st.title("Gestione ODL Correttivi & Archivio (Retention 2+ Anni)")

    tab1, tab2 = st.tabs(["Chiusura Nuovo ODL", "📂 Archivio ODL Eseguiti (Download Excel)"])

    with tab1:
        with st.form("form_odl_chiamata"):
            st.subheader("Registrazione / Chiusura Intervento Straordinario")
            c_odl = st.text_input("Codice ODL", value="C63380570")
            richiedente = st.text_input("Richiedente", value="Security Castel Romano")
            descrizione = st.text_area("Descrizione Intervento", value="Manutenzione straordinaria su chiamata")
            
            c1, c2 = st.columns(2)
            with c1:
                ora_inizio = st.text_input("Ora Inizio", value="19:00")
            with c2:
                ora_fine = st.text_input("Ora Fine", value="19:30")
                
            esito = st.selectbox("Intervento Riconosciuto / Completato", ["SI", "NO"])
            note_odl = st.text_area("Note Tecniche / Ricambi Impiegati")

            salva_odl = st.form_submit_button("Registra e Archivia ODL")
            if salva_odl:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                dt_reg = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                esecutore = st.session_state.get("operatore_corrente", "Operatore CBRE")
                cursor.execute("""
                    INSERT INTO odl_chiamata (codice_odl, richiedente, descrizione, data_registro, ora_inizio, ora_fine, esito, note, stato, operatore_esecutore)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (c_odl, richiedente, descrizione, dt_reg, ora_inizio, ora_fine, esito, note_odl, "Completato", esecutore))
                conn.commit()
                conn.close()
                st.success(f"ODL {c_odl} inserito con successo nell'archivio storico!")

    with tab2:
        st.subheader("Archivio Storico ODL Eseguiti (Storage Legal Compliance > 2 Anni)")
        conn = sqlite3.connect(DB_PATH)
        df_odl = pd.read_sql("SELECT * FROM odl_chiamata ORDER BY id DESC", conn)
        conn.close()

        if not df_odl.empty:
            st.dataframe(df_odl, use_container_width=True)

            excel_filename = f"Archivio_ODL_Castel_Romano_2Anni_{datetime.now().strftime('%Y%m%d')}.xlsx"
            df_odl.to_excel(excel_filename, index=False)

            with open(excel_filename, "rb") as f_excel:
                st.download_button(
                    label="📊 Scarica Storico Completo ODL (Excel)",
                    data=f_excel,
                    file_name=excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_dl_archivio_odl_full"
                )
        else:
            st.info("Nessun ODL straordinario attualmente registrato nell'archivio locale.")

# ---------------------------------------------------------
# 5. PROFILO ANTONIO (SOLO ADMIN)
# ---------------------------------------------------------
elif menu == "Profilo & Abilitazioni F-GAS":
    st.title("Profilo Tecnico Amministratore")
    st.success("Tecnico Responsabile: Sandor Antonio Leon Martinez")
    st.write("**Codice Fiscale:** LNMSDR79801Z504U")
    st.write("**Organismo di Certificazione:** IMQ S.p.A. (Accredia)")
    st.write("**Numero Iscrizione Registro F-GAS:** PR0148807")
    st.write("**Certificato N.:** 2067P-1912001 (Scadenza: 03/12/2029)")
    st.write("**Categoria:** Categoria I (Senza limiti di carica frigorifera)")
