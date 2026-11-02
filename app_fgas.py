import streamlit as st
import sqlite3
import pandas as pd
import docx
import io

# 1. CONFIGURAZIONE PAGINA (Mobile-first)
st.set_page_config(
    page_title="CBRE - Castel Romano HVAC", 
    page_icon="🔧", 
    layout="centered"
)

# 2. GESTIONE DATABASE SQLITE
DB_NAME = 'castel_romano.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Crea la tabella e inserisce i dati iniziali di prova se vuota."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Creazione tabella impianti
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS impianti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nr_unita TEXT,
            marca TEXT,
            modello TEXT,
            codice_targa TEXT,
            refrigerante TEXT,
            co2_eq TEXT,
            fgas_nr TEXT,
            scadenza TEXT
        )
    ''')
    
    # Inserimento dati predefiniti se la tabella è vuota
    cursor.execute("SELECT COUNT(*) FROM impianti")
    if cursor.fetchone()[0] == 0:
        unita_default = [
            ("85", "Clivet", "Rooftop RTD", "CTR-85-A", "R410A", "11.55", "FG-2023-001", "15/12/2026"),
            ("86", "Daikin", "VRV-S RXYSQ", "DK-86-B", "R32", "4.20", "FG-2023-002", "20/10/2026")
        ]
        cursor.executemany('''
            INSERT INTO impianti (nr_unita, marca, modello, codice_targa, refrigerante, co2_eq, fgas_nr, scadenza)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', unita_default)
        conn.commit()
    conn.close()

# Esecuzione dell'inizializzazione del DB all'avvio
init_db()

# 3. AUTENTICAZIONE E CONTROL PANEL IN SIDEBAR
st.sidebar.title("Operatore")
codice_inserito = st.sidebar.text_input("Inserisci Codice LUL (es. 3177)", type="password")

is_autorizzato = (codice_inserito == "3177")

if is_autorizzato:
    st.sidebar.success("Profilo LUL Attivo: Scrittura ed F-GAS abilitati")
else:
    st.sidebar.info("Modalità Sola Lettura. Inserisci 3177 per abilitare la gestione F-GAS.")

# 4. INTESTAZIONE DASHBOARD
st.title("Operation Castel Romano 2026")
st.markdown("Interfaccia monomano per manutenzione rapida impianti HVAC ed F-GAS.")

# 5. CARICAMENTO DATI
conn = get_db_connection()
try:
    df_impianti = pd.read_sql_query("SELECT * FROM impianti", conn)
except Exception as e:
    st.error(f"Errore durante il caricamento del database: {e}")
    df_impianti = pd.DataFrame()
finally:
    conn.close()

# 6. INTERFACCIA PRINCIPALE
if not df_impianti.empty:
    st.subheader("Elenco Unità HVAC")
    
    # Ricerca rapida per il campo
    search_query = st.text_input("🔍 Cerca per Nr. Unità, Marca, Modello o Targa", "")
    
    if search_query:
        df_filtered = df_impianti[
            df_impianti.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)
        ]
    else:
        df_filtered = df_impianti

    # Visualizzazione macchine tramite Expander
    for index, row in df_filtered.iterrows():
        unit_id = row['id']
        nr_unita = row.get('nr_unita', 'N/D')
        marca = row.get('marca', '')
        modello = row.get('modello', '')
        targa = row.get('codice_targa', 'No Targa')
        
        expander_title = f"Unità {nr_unita} — {marca} {modello} [{targa}]"
        
        with st.expander(expander_title):
            # Header informativo sintetico
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Refrigerante:** {row.get('refrigerante', 'N/D')}")
                st.markdown(f"**CO2 Eq.:** {row.get('co2_eq', 'N/D')} t")
            with col_b:
                st.markdown(f"**Nr. F-GAS:** {row.get('fgas_nr', 'N/D')}")
                st.markdown(f"**Scadenza:** {row.get('scadenza', 'N/D')}")
            
            st.divider()
            
            # Schede operative integrate direttamente nell'expander
            tab1, tab2, tab3 = st.tabs(["📋 F-GAS", "🔧 Manutenzione", "📄 ODL & Report"])
            
            # TAB 1: GESTIONE F-GAS
            with tab1:
                st.markdown("#### Intervento F-GAS")
                if is_autorizzato:
                    tipo_int = st.selectbox(
                        "Tipo Intervento", 
                        ["Controllo Fughe", "Carica / Rabbocco", "Recupero Refrigerante", "Manutenzione Straordinaria"],
                        key=f"fgas_tipo_{unit_id}"
                    )
                    note_int = st.text_area("Note e Variazioni", key=f"fgas_note_{unit_id}")
                    if st.button("Registra Registro F-GAS", key=f"btn_fgas_{unit_id}"):
                        st.success(f"Intervento '{tipo_int}' registrato per l'Unità {nr_unita}!")
                else:
                    st.warning("🔒 Richiesto codice operatore LUL (3177) per compilare o modificare la scheda F-GAS.")

            # TAB 2: MANUTENZIONE PREVENTIVA
            with tab2:
                st.markdown("#### Controllo Filtri e Componenti")
                stato_filtri = st.selectbox(
                    "Stato Filtri", 
                    ["OK - Puliti", "Da Sostituire", "Sostituiti"],
                    key=f"filtri_stato_{unit_id}"
                )
                if st.button("Aggiorna Manutenzione", key=f"btn_maint_{unit_id}"):
                    st.success(f"Stato filtri ({stato_filtri}) aggiornato per l'Unità {nr_unita}.")

            # TAB 3: GENERAZIONE DOCUMENTAZIONE / ODL
            with tab3:
                st.markdown("#### Reportistico")
                if st.button("Genera Rapporto Word (.docx)", key=f"btn_doc_{unit_id}"):
                    doc = docx.Document()
                    doc.add_heading(f'Rapporto di Intervento - Unità {nr_unita}', level=1)
                    
                    tecnico = "Sandor Antonio León Martinez" if is_autorizzato else "Operatore Sola Lettura"
                    doc.add_paragraph(f"Tecnico Assegnato: {tecnico}")
                    doc.add_paragraph(f"Impianto: {marca} {modello} (Targa: {targa})")
                    doc.add_paragraph(f"Refrigerante: {row.get('refrigerante', '')} | CO2 Eq: {row.get('co2_eq', '')} t")
                    doc.add_paragraph(f"Registro F-GAS Nr: {row.get('fgas_nr', '')}")
                    
                    buffer = io.BytesIO()
                    doc.save(buffer)
                    buffer.seek(0)
                    
                    st.download_button(
                        label="📥 Scarica File Word",
                        data=buffer,
                        file_name=f"Report_Unita_{nr_unita}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"download_{unit_id}"
                    )
else:
    st.warning("Nessuna unità HVAC trovata nel database.")
