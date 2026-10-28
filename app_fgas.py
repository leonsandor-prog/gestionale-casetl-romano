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
        # Tabella ODL a Chiamata / Correttivi
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

        # Tabella Impianti aggiornata per 211 macchine HVAC
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
                macro_area TEXT
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
                
                # Lettura diretta della Macro-Area / Piazza dal file Excel unificato
                macro = str(row.get("Macro-Area / Piazza", "Piazza di Augusto / Traiano")).strip()
                if not macro or macro == "nan":
                    macro = "Piazza di Augusto / Traiano"

                id_unic = f"{nr_u}_{negozio}_{quadro}"
                
                cursor.execute('''
                    INSERT OR REPLACE INTO macchine_hvac 
                    (id_macchina, nr_unita, marca, modello_matricola, ubicazione_negozio, quadro_elettrico, potenza_kw, n_circuiti, refrigerante, codice_targa, ultima_verifica, scadenza_verifica, macro_area)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    macro
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
st.sidebar.title("🔧 CBRE GWS - Castel Romano")
st.sidebar.markdown("**Tecnico:** Sandor Antonio Leon Martinez")
st.sidebar.markdown("**Certificazione F-GAS:** PR0148807 (Cat. I)")

menu = st.sidebar.selectbox(
    "Seleziona Modulo",
    [
        "🔍 Ricerca & Planimetria Impianti",
        "📋 Manutenzione Preventiva & F-GAS",
        "⚡ ODL Correttiva / A Chiamata",
        "📜 Profilo & F-GAS"
    ]
)

# --- MODULO 1: RICERCA & PLANIMETRIA ---
if menu == "🔍 Ricerca & Planimetria Impianti":
    st.title("🗺️ Gestione Impianti HVAC — Castel Romano (211 Unità)")
    
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df_impianti = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()

    search_query = st.text_input("🔍 Ricerca rapida per Nome Negozio, Numero Unità o Marca (es. Levi's, 130, Trane):", "").strip().lower()

    st.markdown("---")
    
    if search_query:
        unita_filtrate = df_impianti[
            df_impianti['ubicazione_negozio'].astype(str).str.lower().str.contains(search_query) |
            df_impianti['nr_unita'].astype(str).str.lower().str.contains(search_query) |
            df_impianti['marca'].astype(str).str.lower().str.contains(search_query) |
            df_impianti['modello_matricola'].astype(str).str.lower().str.contains(search_query)
        ]
        st.subheader(f"🔎 Risultati della ricerca per '{search_query}': ({len(unita_filtrate)} macchine trovate)")
    else:
        tab_piazze, tab_quadri = st.tabs(["🏛️ Navigazione per Piazze / Mappa Centro", "⚡ Filtro per Quadro Elettrico"])
        
        with tab_piazze:
            piazze_disponibili = sorted(df_impianti["macro_area"].dropna().unique())
            piazza_scelta = st.selectbox("📍 Seleziona Piazza / Zona del Centro:", piazze_disponibili)
            unita_filtrate = df_impianti[df_impianti["macro_area"] == piazza_scelta]
            st.info(f"Trovate **{len(unita_filtrate)} unità HVAC** in `{piazza_scelta}`")
            
        with tab_quadri:
            quadri = sorted(df_impianti["quadro_elettrico"].dropna().unique())
            quadro_scelto = st.selectbox("📍 Seleziona Quadro / Interruttore (Planimetria)", quadri)
            unita_filtrate = df_impianti[df_impianti["quadro_elettrico"] == quadro_scelto]
            st.info(f"Trovate **{len(unita_filtrate)} unità HVAC** collegate al quadro `{quadro_scelto}`")

    for idx, row in unita_filtrate.iterrows():
        matricola_str = str(row['modello_matricola']).strip()
        key_id = str(row['id_macchina']).replace(" ", "_").replace("/", "_")
        
        with st.expander(f"⚙️ Unità {row['nr_unita']} — {row['marca']} ({row['ubicazione_negozio']}) — [{row['macro_area']}]"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**📋 Dati Tecnici**")
                st.write(f"• Modello / Matricola: `{matricola_str}`")
                st.write(f"• Potenza: `{row['potenza_kw']} kW`")
                st.write(f"• N. Circuiti: `{row['n_circuiti']}`")
            with c2:
                st.markdown("**🔧 Refrigerante & Targa**")
                st.write(f"• Gas: `{row['refrigerante']}`")
                st.write(f"• Cod. Targa: `{row['codice_targa']}`")
                st.write(f"• Quadro: `{row['quadro_elettrico']}`")
            with c3:
                st.markdown("**📅 Verifiche**")
                st.write(f"• Ultima RCEE: `{row['ultima_verifica']}`")
                st.write(f"• Scadenza: `{row['scadenza_verifica']}`")
            
            st.markdown("---")
            tab_fgas, tab_filtri = st.tabs(["❄️ 1. Compila Modello F-GAS (CBRE)", "🧹 2. Rapportino Manutenzione Filtri"])
            
            with tab_fgas:
                with st.form(key=f"form_fgas_{key_id}"):
                    st.markdown("##### 📝 Controllo Periodico F-GAS e Generazione Report Ufficiale")
                    esito_circ1 = st.selectbox("Esito Circuito 1", ["Assenza Perdite", "Rilevata Perdita"], key=f"es1_{key_id}")
                    note_fgas = st.text_input("Note Tecniche / Causa ed Azioni", "Controllo periodico eseguito con esito regolare.", key=f"note_f_{key_id}")
                    
                    btn_fgas = st.form_submit_button("✅ Genera Report Word F-GAS Ufficiale")
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
                                "{{CARICA_KG}}": f"{row['potenza_kw']} kW",
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
                            st.error(
