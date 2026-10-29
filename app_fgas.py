import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta
from docx import Document

DB_PATH = "castel_romano.db"
EXCEL_PATH = "Registro_Master_Unificato_Completo_Castel_Romano.xlsx"
TEMPLATE_FGAS_PATH = "Report_FGAS_modello.docx"

def init_db_mappa():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS odl_chiamata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codice_odl TEXT,
                richiedente TEXT,
                descrizione TEXT,
                data_limite TEXT,
                ora_inizio TEXT,
                ora_fine TEXT,
                esito TEXT,
                note TEXT,
                stato TEXT
            )
        ''')

        cursor.execute('DROP TABLE IF EXISTS macchine_hvac')
        cursor.execute('''
            CREATE TABLE macchine_hvac (
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
                carica_kg REAL
            )
        ''')
        
        if os.path.exists(EXCEL_PATH):
            df_excel = pd.read_excel(EXCEL_PATH, sheet_name='Impianti HVAC & Planimetria')
            for _, row in df_excel.iterrows():
                nr_u = str(row.get("Nr. Unità", "")).strip()
                marca = str(row.get("Marca", "")).strip()
                mod_mat = str(row.get("Modello / Matricola", "")).strip()
                negozio = str(row.get("Ubicazione / Negozio", "")).strip()
                quadro = str(row.get("Quadro / Interruttore (Planimetria)", "")).strip()
                
                macro = str(row.get("Macro-Area / Piazza", "Piazza di Augusto / Traiano")).strip()
                if not macro or macro == "nan":
                    macro = "Piazza di Augusto / Traiano"

                id_unic = f"{nr_u}_{negozio}_{quadro}"
                
                tonn_co2 = row.get("Tonnellate CO2 Eq. (tCO2e)", 0.0)
                if pd.isna(tonn_co2):
                    tonn_co2 = 0.0
                
                carica_kg = (tonn_co2 * 1000.0) / 2088.0 if tonn_co2 > 0 else 0.0
                
                cursor.execute('''
                    INSERT OR REPLACE INTO macchine_hvac 
                    (id_macchina, nr_unita, marca, modello_matricola, ubicazione_negozio, quadro_elettrico, potenza_kw, n_circuiti, refrigerante, codice_targa, ultima_verifica, scadenza_verifica, macro_area, tonn_co2_eq, carica_kg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    id_unic,
                    nr_u,
                    marca,
                    mod_mat,
                    negozio,
                    quadro,
                    float(row.get("Potenza (kW)", 0.0) or 0.0),
                    int(row.get("N. Circuiti", 1) or 1),
                    str(row.get("Refrigerante", "")),
                    str(row.get("Codice Impianto / Targa", "")),
                    str(row.get("Ultima Verifica RCEE", "")),
                    str(row.get("Scadenza Verifica", "")),
                    macro,
                    float(tonn_co2),
                    float(carica_kg)
                ))
                    
        conn.commit()
    finally:
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

st.set_page_config(page_title="Gestione F-GAS & Manutenzione Castel Romano", layout="wide")
st.sidebar.title("CBRE GWS - Castel Romano")
st.sidebar.markdown("**Tecnico:** Sandor Antonio Leon Martinez")
st.sidebar.markdown("**Certificazione F-GAS:** PR0148807 (Cat. I)")

menu = st.sidebar.selectbox(
    "Seleziona Modulo",
    [
        "Ricerca & Planimetria Impianti",
        "Manutenzione Preventiva & F-GAS",
        "ODL Correttiva / A Chiamata",
        "Profilo & F-GAS"
    ]
)

if menu == "Ricerca & Planimetria Impianti":
    st.title("Gestione Impianti HVAC - Castel Romano (211 Unita)")
    
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_impianti = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    # Selettore chiaro per la modalita di visualizzazione e filtraggio
    modo_vista = st.radio("Seleziona modalita di navigazione:", ["Navigazione per Piazza / Zona (con pallini stato)", "Filtro per Quadro Elettrico", "Ricerca Rapida Testo"], horizontal=True)

    unita_filtrate = pd.DataFrame()

    if modo_vista == "Navigazione per Piazza / Zona (con pallini stato)":
        piazze_disponibili = sorted(df_impianti["macro_area"].dropna().unique())
        piazza_scelta = st.selectbox("Seleziona Piazza / Zona del Centro:", piazze_disponibili)
        unita_filtrate = df_impianti[df_impianti["macro_area"] == piazza_scelta]
        st.info(f"Trovate **{len(unita_filtrate)} unita HVAC** in `{piazza_scelta}`")
        
    elif modo_vista == "Filtro per Quadro Elettrico":
        quadri = sorted(df_impianti["quadro_elettrico"].dropna().unique())
        quadro_scelto = st.selectbox("Seleziona Quadro / Interruttore (Planimetria)", quadri)
        unita_filtrate = df_impianti[df_impianti["quadro_elettrico"] == quadro_scelto]
        st.info(f"Trovate **{len(unita_filtrate)} unita HVAC** collegate al quadro `{quadro_scelto}`")
        
    else:
        search_query = st.text_input("Ricerca rapida per Nome Negozio, Numero Unita o Marca (es. Levi's, 130, Trane):", "").strip().lower()
        if search_query:
            unita_filtrate = df_impianti[
                df_impianti['ubicazione_negozio'].astype(str).str.lower().str.contains(search_query) |
                df_impianti['nr_unita'].astype(str).str.lower().str.contains(search_query) |
                df_impianti['marca'].astype(str).str.lower().str.contains(search_query) |
                df_impianti['modello_matricola'].astype(str).str.lower().str.contains(search_query)
            ]
            st.subheader(f"Risultati della ricerca per '{search_query}': ({len(unita_filtrate)} macchine trovate)")
        else:
            unita_filtrate = df_impianti.copy()

    st.markdown("---")

    for idx, row in unita_filtrate.iterrows():
        matricola_str = str(row['modello_matricola']).strip()
        key_id = str(row['id_macchina']).replace(" ", "_").replace("/", "_")
        
        # Pallino colorato in base allo stato o verifica
        stato_pallino = "🟢" if str(row['scadenza_verifica']) != "" else "🟡"
        
        with st.expander(f"{stato_pallino} Unita {row['nr_unita']} - {row['marca']} ({row['ubicazione_negozio']}) - [{row['macro_area']}]"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**Dati Tecnici**")
                st.write(f"- Modello / Matricola: `{matricola_str}`")
                st.write(f"- Potenza: `{row['potenza_kw']} kW`")
                st.write(f"- N. Circuiti: `{row['n_circuiti']}`")
            with c2:
                st.markdown("**Refrigerante & Targa**")
                st.write(f"- Gas: `{row['refrigerante']}`")
                st.write(f"- Cod. Targa: `{row['codice_targa']}`")
                st.write(f"- Quadro: `{row['quadro_elettrico']}`")
            with c3:
                st.markdown("**Verifiche**")
                st.write(f"- Ultima RCEE: `{row['ultima_verifica']}`")
                st.write(f"- Scadenza: `{row['scadenza_verifica']}`")
            
            st.markdown("---")
            tab_fgas, tab_filtri = st.tabs(["1. Compila Modello F-GAS (CBRE)", "2. Rapportino Manutenzione Filtri"])
            
            with tab_fgas:
                with st.form(key=f"form_fgas_{key_id}"):
                    st.markdown("##### Controllo Periodico F-GAS e Generazione Report Ufficiale")
                    esito_circ1 = st.selectbox("Esito Circuito 1", ["Assenza Perdite", "Rilevata Perdita"], key=f"es1_{key_id}")
                    note_fgas = st.text_input("Note Tecniche / Causa ed Azioni", "Controllo periodico eseguito con esito regolare.", key=f"note_f_{key_id}")
                    
                    btn_fgas = st.form_submit_button("Genera Report Word F-GAS Ufficiale")
                    if btn_fgas:
                        dt_oggi = datetime.now()
                        if os.path.exists(TEMPLATE_FGAS_PATH):
                            doc = Document(TEMPLATE_FGAS_PATH)
                            mappa_dati = {
                                "{{UNITA}}": str(row['nr_unita']),
                                "{{MARCA}}": str(row['marca']),
                                "{{MODELLO}}": str(row['modello_matricola']),
                                "{{MATRICOLA}}": matricola_str,
                                "{{TIPO_GAS}}": str(row['refrigerante']),
                                "{{CARICA_KG}}": f"{row['carica_kg']:.2f} kg",
                                "{{CO2_EQ}}": f"{row['tonn_co2_eq']} tCO2e",
                                "{{COD_APP}}": str(row['codice_targa']),
                                "{{DATA_INTERVENTO}}": dt_oggi.strftime("%d/%m/%Y"),
                                "{{ESITO_CIRC1}}": esito_circ1.upper(),
                                "{{NOTE_FGAS}}": note_fgas
                            }
                            sostituisci_testo_docx(doc, mappa_dati)
                            filename_fgas = f"Report_FGAS_{row['marca']}_{matricola_str.replace('/', '_')}.docx"
                            doc.save(filename_fgas)
                            st.session_state[f'dl_fgas_{key_id}'] = filename_fgas
                            st.success("Report F-GAS generato con successo!")
                            st.rerun()
                        else:
                            st.error(f"File modello '{TEMPLATE_FGAS_PATH}' non trovato nella directory.")

                if st.session_state.get(f'dl_fgas_{key_id}'):
                    f_path = st.session_state[f'dl_fgas_{key_id}']
                    if os.path.exists(f_path):
                        with open(f_path, "rb") as f_in:
                            st.download_button(label="Scarica Documento Word F-GAS", data=f_in, file_name=f_path, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_btn_f_{key_id}")

            with tab_filtri:
                with st.form(key=f"form_filt_{key_id}"):
                    st.markdown("##### Rapportino Intervento Filtri & Pulizia")
                    azione_f = st.selectbox("Azione Eseguita", ["Pulizia / Spolveratura Filtri", "Lavaggio Filtri & Sanificazione Vasca", "Sostituzione Filtri Nuovi"], key=f"az_{key_id}")
                    stato_f = st.selectbox("Stato Post-Intervento", ["Pulito / Ottimale", "Buono", "Da Sostituire"], key=f"st_{key_id}")
                    note_f = st.text_input("Note Tecniche", "Eseguita pulizia filtri e controllo flusso d'aria.", key=f"nt_{key_id}")
                    
                    btn_filt = st.form_submit_button("Genera Rapportino Filtri Word")
                    if btn_filt:
                        doc_f = Document()
                        doc_f.add_heading('RAPPORTINO MANUTENZIONE FILTRI & INTERVENTO ORDINARIO', level=1)
                        doc_f.add_paragraph(f"Sito: McArthurGlen Designer Outlet Castel Romano - Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\nUnita / Negozio: {row['nr_unita']} ({row['ubicazione_negozio']})")
                        doc_f.add_paragraph(f"DETTAGLI APPARECCHIATURA:\nMarca/Modello: {row['marca']} {row['modello_matricola']} | Quadro: {row['quadro_elettrico']}")
                        doc_f.add_paragraph(f"INTERVENTO:\nAzione: {azione_f} | Stato: {stato_f.upper()}\nNote: {note_f}")
                        doc_f.add_paragraph(f"TECNICO ESECUTORE:\nCBRE GWS Technical Division - ANTONIO MARTINEZ (Cert. PR-0148807)")
                        
                        filename_filt = f"Rapportino_Filtri_Unita_{row['nr_unita']}.docx"
                        doc_f.save(filename_filt)
                        st.session_state[f'dl_filt_{key_id}'] = filename_filt
                        st.success("Rapportino filtri generato con successo!")
                        st.rerun()

                if st.session_state.get(f'dl_filt_{key_id}'):
                    f_path_filt = st.session_state[f'dl_filt_{key_id}']
                    if os.path.exists(f_path_filt):
                        with open(f_path_filt, "rb") as f_in_f:
                            st.download_button(label="Scarica Rapportino Word Filtri", data=f_in_f, file_name=f_path_filt, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"dl_btn_filt_{key_id}")

elif menu == "Manutenzione Preventiva & F-GAS":
    st.title("Checklist Preventiva e Scadenze F-GAS")
    st.markdown("Panoramica completa di tutte le 211 unita HVAC, scadenze di verifica e tonnellate di CO2 equivalente.")
    
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_prev = pd.read_sql("SELECT nr_unita, marca, modello_matricola, ubicazione_negozio, quadro_elettrico, potenza_kw, refrigerante, codice_targa, ultima_verifica, scadenza_verifica, macro_area, tonn_co2_eq, carica_kg FROM macchine_hvac", conn)
    conn.close()
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filtro_piazza = st.selectbox("Filtra per Piazza / Zona", ["Tutte le piazze"] + sorted(df_prev['macro_area'].dropna().unique().tolist()))
    with col_f2:
        filtro_marca = st.selectbox("Filtra per Marca", ["Tutte le marche"] + sorted(df_prev['marca'].dropna().unique().tolist()))
        
    df_filtered = df_prev.copy()
    if filtro_piazza != "Tutte le piazze":
        df_filtered = df_filtered[df_filtered['macro_area'] == filtro_piazza]
    if filtro_marca != "Tutte le marche":
        df_filtered = df_filtered[df_filtered['marca'] == filtro_marca]
        
    st.markdown(f"**Impianti visualizzati:** {len(df_filtered)}")
    st.dataframe(df_filtered, use_container_width=True, hide_index=True)
    
    excel_scadenze = "Scadenze_HVAC_Castel_Romano.xlsx"
    df_filtered.to_excel(excel_scadenze, index=False)
    with open(excel_scadenze, "rb") as f_scad:
        st.download_button(
            label="Scarica Tabella Scadenze in formato Excel",
            data=f_scad,
            file_name=excel_scadenze,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_scad_hvac"
        )

elif menu == "ODL Correttiva / A Chiamata":
    st.title("Gestione ODL Correttivi / Extra a Chiamata")
    st.markdown("Inserimento e verifica degli interventi straordinari (es. ODL C63380570 per la fontana o richieste Security).")

    tab1, tab2 = st.tabs(["Nuovo ODL / Inoltro", "Archivio ODL a Chiamata"])

    with tab1:
        with st.form("form_odl_chiamata"):
            st.subheader("Registrazione / Chiusura ODL Straordinario")
            c_odl = st.text_input("Codice ODL", value="C63380570")
            richiedente = st.text_input("Richiedente", value="Security Castel Romano")
            descrizione = st.text_area("Descrizione Lavoro", value="Intervento di regolazione e manutenzione straordinaria impianti")
            data_limite = st.text_input("Data e Ora Riferimento", value=datetime.now().strftime("%d/%m/%Y %H:%M"))
            
            st.markdown("---")
            ora_inizio = st.text_input("Ora Inizio", value="19:00")
            ora_fine = st.text_input("Ora Fine", value="19:30")
            esito = st.selectbox("Intervento Completato", ["SI", "NO"])
            note_odl = st.text_area("Note dell'Intervento / Ricambi Utilizzati")
            
            salva_odl = st.form_submit_button("Registra e Chiudi ODL")
            if salva_odl:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO odl_chiamata (codice_odl, richiedente, descrizione, data_limite, ora_inizio, ora_fine, esito, note, stato)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (c_odl, richiedente, descrizione, data_limite, ora_inizio, ora_fine, esito, note_odl, "Completato"))
                conn.commit()
                conn.close()
                st.success(f"ODL {c_odl} registrato e archiviato con successo!")

    with tab2:
        st.subheader("Storico ODL Registrati")
        conn = sqlite3.connect(DB_PATH)
        df_odl = pd.read_sql("SELECT * FROM odl_chiamata", conn)
        conn.close()
        
        if not df_odl.empty:
            st.dataframe(df_odl, use_container_width=True)
            
            excel_filename = "Archivio_ODL_Castel_Romano.xlsx"
            df_odl.to_excel(excel_filename, index=False)
            
            with open(excel_filename, "rb") as f_excel:
                st.download_button(
                    label="Scarica Archivio ODL in formato Excel",
                    data=f_excel,
                    file_name=excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_dl_archivio_odl"
                )
        else:
            st.info("Nessun ODL a chiamata registrato nel database locale.")

elif menu == "Profilo & F-GAS":
    st.title("Certificazione e Profilo Tecnico")
    st.markdown("Dettagli ufficiali dell'abilitazione registrata per operare sugli impianti del centro.")
    
    st.success("Tecnico: Sandor Antonio Leon Martinez")
    st.write("**Codice Fiscale:** LNMSDR79801Z504U")
    st.write("**Ente Certificatore:** IMQ S.p.A. (Accredia)")
    st.write("**N. Iscrizione Registro F-GAS:** PR0148807")
    st.write("**N. Certificato:** 2067P-1912001 (Scadenza: 03/12/2029)")
    st.write("**Categoria:** Categoria I (Senza limiti di carica frigorifera)")
