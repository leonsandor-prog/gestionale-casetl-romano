import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="Gestionale Manutenzione - Castel Romano",
    page_icon="🔧",
    layout="wide"
)

# --- CONNESSIONE DATABASE & SINCRONIZZAZIONE MASTER ---
def init_db():
    conn = sqlite3.connect("castel_romano.db")
    cursor = conn.cursor()
    
    # 1. Tabella ODL a Chiamata / Correttivi
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
    
    # 2. Sincronizzazione automatica tabella impianti da Excel (se presente)
    try:
        df_excel = pd.read_excel("Registro_Master_Definitivo_Castel_Romano.xlsx", sheet_name="Impianti HVAC & Planimetria")
        df_excel.to_sql("impianti", conn, if_exists="replace", index=False)
    except Exception as e:
        pass # Se il file excel non è ancora caricato, usa il db esistente se presente

    conn.commit()
    conn.close()

init_db()

# --- BARRA LATERALE: NAVIGAZIONE & PROFILO ---
st.sidebar.title("🔧 CBRE GWS - Castel Romano")
st.sidebar.markdown("**Tecnico:** Sandor Antonio Leon Martinez")
st.sidebar.markdown("**Certificazione F-GAS:** PR0148807 (Cat. I)")

menu = st.sidebar.selectbox(
    "Seleziona Modulo",
    [
        "🗺️ Mappa & Censimento Impianti",
        "📋 Manutenzione Preventiva",
        "⚡ ODL Correttiva / A Chiamata",
        "📜 Profilo & F-GAS"
    ]
)

# --- MODULO 1: MAPPA INTERATTIVA & IMPIANTI HVAC ---
if menu == "🗺️ Mappa & Censimento Impianti":
    st.title("🗺️ Mappa Interattiva e Censimento Impianti HVAC")
    st.markdown("Seleziona il quadro elettrico di riferimento dalla planimetria per visualizzare le unità associate.")

    try:
        conn = sqlite3.connect("castel_romano.db")
        df_impianti = pd.read_sql("SELECT * FROM impianti", conn)
        conn.close()

        quadri = sorted(df_impianti["Quadro / Interruttore (Planimetria)"].dropna().unique())
        quadro_scelto = st.selectbox("📍 Seleziona Quadro / Zona Elettrica", quadri)

        unita_filtrate = df_impianti[df_impianti["Quadro / Interruttore (Planimetria)"] == quadro_scelto]
        st.info(f"Trovate **{len(unita_filtrate)} unità** collegate alla zona {quadro_scelto}")

        for idx, row in unita_filtrate.iterrows():
            with st.expander(f"⚙️ Unità {row['Nr. Unità']} — {row['Marca']} ({row['Ubicazione / Negozio']})"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Modello / Matricola:** {row['Modello / Matricola']}")
                    st.write(f"**Potenza:** {row['Potenza (kW)']} kW")
                with c2:
                    st.write(f"**Refrigerante:** {row['Refrigerante']}")
                    st.write(f"**Scadenza RCEE:** {row['Scadenza Verifica']}")
                
                if st.button(f"📝 Esegui Check Unità {row['Nr. Unità']}", key=f"unita_{row['Nr. Unità']}"):
                    st.success(f"Scheda aperta per Unità {row['Nr. Unità']} ({row['Ubicazione / Negozio']}). Pronto per il controllo F-GAS / Filtri.")

    except Exception as e:
        st.warning("⚠️ Carica il file Excel 'Registro_Master_Definitivo_Castel_Romano.xlsx' nel repository GitHub per popolare la mappa.")

# --- MODULO 2: MANUTENZIONE PREVENTIVA ---
elif menu == "📋 Manutenzione Preventiva":
    st.title("📋 Manutenzione Preventiva & Programmata")
    st.markdown("Gestione ciclica delle checklist per filtri, quadri elettrici, cabine e controlli F-GAS.")

    with st.form("form_preventiva"):
        unita_sel = st.text_input("Codice o Numero Unità Impianto")
        tipo_intervento = st.selectbox("Tipo Attività", ["Controllo Perdite F-GAS", "Sostituzione Celle Filtranti", "Termografia Quadro Elettrico"])
        note_prev = st.text_area("Note e Riscontro Tecnico")
        firma_tech = st.text_input("Firma Digitale Tecnico (Nome e Cognome)", value="Sandor Antonio Leon Martinez")
        
        submitted = st.form_submit_button("Salva e Genera Rapporto Preventivo")
        if submitted:
            st.success(f"Intervento preventivo registrato con successo per l'unità {unita_sel}!")

# --- MODULO 3: ODL CORRETTIVA / A CHIAMATA ---
elif menu == "⚡ ODL Correttiva / A Chiamata":
    st.title("⚡ Gestione ODL Correttivi / Extra a Chiamata")
    st.markdown("Inserimento e verifica degli interventi straordinari (es. richieste Security o guasti puntuali).")

    tab1, tab2 = st.tabs(["➕ Nuovo ODL / Inoltro", "📂 Archivio ODL a Chiamata"])

    with tab1:
        with st.form("form_odl_chiamata"):
            st.subheader("Registrazione / Verifica ODL (es. C63380570)")
            c_odl = st.text_input("Codice ODL", value="C63380570")
            richiedente = st.text_input("Richiedente", value="Security Castel Romano")
            descrizione = st.text_area("Descrizione Lavoro", value="Cambio orario accensione e spegnimento fontana per ora legale")
            data_limite = st.text_input("Data e Ora Limite", value="26 ottobre 2026 19:44")
            
            st.markdown("---")
            st.subheader("Compilazione sul Campo")
            ora_inizio = st.text_input("Ora Inizio", value="19:00")
            ora_fine = st.text_input("Ora Fine", value="19:30")
            esito = st.selectbox("Intervento Completato", ["SI", "NO"])
            note_odl = st.text_area("Note dell'Intervento / Ricambi")
            
            salva_odl = st.form_submit_button("Registra e Firma ODL")
            if salva_odl:
                conn = sqlite3.connect("castel_romano.db")
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO odl_chiamata (codice_odl, richiedente, descrizione, data_limite, ora_inizio, ora_fine, esito, note, stato)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (c_odl, richiedente, descrizione, data_limite, ora_inizio, ora_fine, esito, note_odl, "Completato"))
                conn.commit()
                conn.close()
                st.success(f"ODL {c_odl} registrato, firmato e chiuso con successo!")

    with tab2:
            conn = sqlite3.connect("castel_romano.db")
            df_odl = pd.read_sql("SELECT * FROM odl_chiamata", conn)
            conn.close()
            if not df_odl.empty:
                st.dataframe(df_odl)
            else:
                st.info("Nessun ODL a chiamata registrato nel database locale.")

# --- MODULO 4: PROFILO & F-GAS ---
elif menu == "📜 Profilo & F-GAS":
    st.title("📜 Certificazione e Profilo Tecnico")
    st.markdown("Dettagli ufficiali dell'abilitazione registrata per operare sugli impianti.")
    
    st.success("✅ **Tecnico:** Sandor Antonio Leon Martinez")
    st.write("**Codice Fiscale:** LNMSDR79801Z504U")
    st.write("**Ente Certificatore:** IMQ S.p.A. (Accredia)")
    st.write("**N. Iscrizione Registro F-GAS:** PR0148807")
    st.write("**N. Certificato:** 2067P-1912001 (Scadenza: 03/12/2029)")
    st.write("**Categoria:** Categoria I (Senza limiti di carica frigorifera)")
