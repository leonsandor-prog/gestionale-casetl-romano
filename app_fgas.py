import streamlit as st
import sqlite3
import pandas as pd
import docx
import io

# Configurazione pagina per dispositivi mobili / desktop
st.set_page_config(page_title="CBRE - Castel Romano HVAC", layout="centered")

# --- AUTENTICAZIONE E PROFILO RAPIDO ---
st.sidebar.title("Operatore")
codice_inserito = st.sidebar.text_input("Inserisci Codice Operatore (es. 3177 per LUL)", type="password")

is_autorizzato = (codice_inserito == "3177")

if is_autorizzato:
    st.sidebar.success("Profilo LUL Attivo: Modifica F-GAS abilitata")
else:
    st.sidebar.info("Modalità sola lettura (inserisci 3177 per sbloccare F-GAS)")

st.title("Operation Castel Romano 2026")
st.markdown("Gestione rapida impianti HVAC e F-GAS sul campo.")

# --- CONNESSIONE DATABASE ---
def get_db_connection():
    conn = sqlite3.connect('castel_romano.db')
    conn.row_factory = sqlite3.Row
    return conn

conn = get_db_connection()
cursor = conn.cursor()

# Caricamento dati impianti
try:
    df_impianti = pd.read_sql_query("SELECT * FROM impianti", conn)
except Exception as e:
    st.error(f"Errore caricamento database: {e}")
    df_impianti = pd.DataFrame()

conn.close()

if not df_impianti.empty:
    st.subheader("Elenco Unità HVAC")
    
    # Barra di ricerca rapida
    search_query = st.text_input("🔍 Cerca Unità (Nr. Unità, Modello, Targa)", "")
    
    if search_query:
        df_filtered = df_impianti[df_impianti.astype(str).apply(lambda x: x.str.contains(search_query, case=False)).any(axis=1)]
    else:
        df_filtered = df_impianti

    # Iterazione rapida sulle unità con expander dedicati
    for index, row in df_filtered.iterrows():
        unita_label = f"Unità {row.get('nr_unita', 'N/D')} - {row.get('marca', '')} {row.get('modello', '')} [{row.get('codice_targa', 'No Targa')}]"
        
        with st.expander(unita_label):
            st.markdown(f"**Refrigerante:** {row.get('refrigerante', 'N/D')} | **CO2 Eq.:** {row.get('co2_eq', 'N/D')} t")
            st.markdown(f"**Nr. F-GAS:** {row.get('fgas_nr', 'N/D')} | **Scadenza:** {row.get('scadenza', 'N/D')}")
            
            st.divider()
            
            # OPZIONI OPERATIVE DIRETTAMENTE SULL'UNITA'
            tab_op1, tab_op2, tab_op3 = st.tabs(["📋 Gestione & F-GAS", "🔧 Manutenzione", "📄 ODL / Report"])
            
            with tab_op1:
                st.markdown("### Controllo e Intervento F-GAS")
                if is_autorizzato:
                    tipo_intervento = st.selectbox("Tipo Intervento", ["Controllo Fughe", "Carica / Rabbocco", "Recupero", "Manutenzione Straordinaria"], key=f"int_{row['id'] if 'id' in row else index}")
                    note_intervento = st.text_area("Note Operatore", key=f"note_{row['id'] if 'id' in row else index}")
                    if st.button("Registra Intervento F-GAS", key=f"btn_fgas_{index}"):
                        st.success(f"Intervento registrato con successo per l'Unità {row.get('nr_unita', '')}!")
                else:
                    st.warning("🔒 Inserisci il codice operatore autorizzato nella barra laterale per registrare variazioni F-GAS.")
                    
            with tab_op2:
                st.markdown("### Manutenzione Preventiva / Filtri")
                stato_filtri = st.selectbox("Stato Filtri", ["Puliti", "Da Sostituire", "Sostituiti"], key=f"filtri_{index}")
                if st.button("Aggiorna Stato Filtri", key=f"btn_filtri_{index}"):
                    st.success("Stato manutenzione aggiornato.")
                    
            with tab_op3:
                st.markdown("### Documentazione e ODL")
                if st.button("Genera Report Word", key=f"btn_word_{index}"):
                    # Generazione file Word al volo
                    doc = docx.Document()
                    doc.add_heading(f'Rapporto Intervento - Unità {row.get("nr_unita", "")}', level=1)
                    doc.add_paragraph(f"Tecnico: Sandor Antonio León Martinez (Codice: {codice_inserito if is_autorizzato else 'Ospite'})")
                    doc.add_paragraph(f"Marca/Modello: {row.get('marca', '')} {row.get('modello', '')}")
                    doc.add_paragraph(f"Refrigerante: {row.get('refrigerante', '')} | CO2 Eq: {row.get('co2_eq', '')}")
                    
                    buffer = io.BytesIO()
                    doc.save(buffer)
                    buffer.seek(0)
                    
                    st.download_button(
                        label="📥 Scarica Documento Word",
                        data=buffer,
                        file_name=f"Report_Unita_{row.get('nr_unita', 'Dati')}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_{index}"
                    )
else:
    st.warning("Nessun impianto trovato nel database.")
