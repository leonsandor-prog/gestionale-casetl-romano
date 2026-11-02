import sqlite3
import os
from datetime import datetime
import pandas as pd
import streamlit as st

DB_PATH = "castel_romano.db"
EXCEL_PATH = "F_GAS_Impianti_Attivi_2026_Assegnato.xlsx"

def init_db_mappa():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()

    try:
        # Tabella ODL
        cursor.execute("""
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
                stato TEXT,
                operatore TEXT,
                timestamp_reg TEXT
            )
        """)

        # Creazione tabella se non esiste
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS macchine_hvac (
                id_macchina TEXT PRIMARY KEY,
                f_gas_n TEXT,
                collocazione TEXT,
                nr_unita TEXT,
                descrizione_impianto TEXT,
                codice_targa TEXT,
                tipologia TEXT,
                marca TEXT,
                modello TEXT,
                refrigerante TEXT,
                tonn_co2_eq REAL,
                carica_kg REAL,
                operatore_assegnato TEXT,
                zona_designata TEXT,
                ultima_verifica TEXT,
                scadenza_verifica TEXT,
                data_scadenza_dt TEXT,
                filtro_dimensioni TEXT,
                filtro_quantita INTEGER,
                stato_manutenzione TEXT
            )
        """)

        # Verifica se la tabella esistente ha le nuove colonne. In caso contrario, resetta la tabella per aggiornare la struttura dal nuovo Excel.
        cursor.execute("PRAGMA table_info(macchine_hvac)")
        colonne_db = [col[1] for col in cursor.fetchall()]
        
        if "zona_designata" not in colonne_db or "operatore_assegnato" not in colonne_db:
            cursor.execute("DROP TABLE macchine_hvac")
            cursor.execute("""
                CREATE TABLE macchine_hvac (
                    id_macchina TEXT PRIMARY KEY,
                    f_gas_n TEXT,
                    collocazione TEXT,
                    nr_unita TEXT,
                    descrizione_impianto TEXT,
                    codice_targa TEXT,
                    tipologia TEXT,
                    marca TEXT,
                    modello TEXT,
                    refrigerante TEXT,
                    tonn_co2_eq REAL,
                    carica_kg REAL,
                    operatore_assegnato TEXT,
                    zona_designata TEXT,
                    ultima_verifica TEXT,
                    scadenza_verifica TEXT,
                    data_scadenza_dt TEXT,
                    filtro_dimensioni TEXT,
                    filtro_quantita INTEGER,
                    stato_manutenzione TEXT
                )
            """)

        # Popola/Ripopola se vuota
        cursor.execute("SELECT COUNT(*) FROM macchine_hvac")
        if cursor.fetchone()[0] == 0 and os.path.exists(EXCEL_PATH):
            df_excel = pd.read_excel(EXCEL_PATH, sheet_name="Master F-GAS 2026")
            for _, row in df_excel.iterrows():
                f_gas_num = str(row.get("F-GAS N°", "")).strip()
                collocazione = str(row.get("Collocazione", "MCARTHUR_RM")).strip()
                unita_str = str(row.get("Unità / Macchina", "")).strip()
                desc_imp = str(row.get("Descrizione Impianto", "")).strip()
                cod_app = str(row.get("Cod. Apparecchiatura", "")).strip()
                tipologia = str(row.get("Tipologia", "")).strip()
                marca = str(row.get("Marca", "")).strip()
                modello = str(row.get("Modello", "")).strip()
                refrigerante = str(row.get("Refrigerante", "R-410A")).strip()
                
                tonn_co2 = row.get("Tonn. CO2 Eq.", 0.0)
                if pd.isna(tonn_co2):
                    tonn_co2 = 0.0
                    
                operatore = str(row.get("Operatore Assegnato", "")).strip()
                zona = str(row.get("Zona / Area Designata", "")).strip()

                carica_kg = (tonn_co2 * 1000.0) / 2088.0 if tonn_co2 > 0 else 0.0
                id_unic = f"{f_gas_num}_{unita_str}_{cod_app}"

                cursor.execute("""
                    INSERT OR REPLACE INTO macchine_hvac 
                    (id_macchina, f_gas_n, collocazione, nr_unita, descrizione_impianto, codice_targa, tipologia, marca, modello, refrigerante, tonn_co2_eq, carica_kg, operatore_assegnato, zona_designata, ultima_verifica, scadenza_verifica, data_scadenza_dt, filtro_dimensioni, filtro_quantita, stato_manutenzione)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    id_unic, f_gas_num, collocazione, unita_str, desc_imp, cod_app,
                    tipologia, marca, modello, refrigerante, float(tonn_co2), float(carica_kg),
                    operatore, zona, "01/01/2026", "01/01/2027", "2027-01-01", "", 1, "Regolare"
                ))

        conn.commit()
    finally:
        conn.close()

init_db_mappa()

st.set_page_config(page_title="Gestione F-GAS & Manutenzione Castel Romano", layout="wide")

# Funzione ausiliaria per garantire la presenza delle colonne nel DataFrame
def carica_dataframe_sicuro():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    df = pd.read_sql("SELECT * FROM macchine_hvac", conn)
    conn.close()
    
    colonne_richieste = {
        "operatore_assegnato": "Antonio",
        "zona_designata": "Castel Romano",
        "nr_unita": "N/D",
        "marca": "N/D",
        "modello": "N/D",
        "codice_targa": "N/D",
        "refrigerante": "R-410A",
        "tonn_co2_eq": 0.0,
        "f_gas_n": "N/D",
        "scadenza_verifica": "01/01/2027",
        "data_scadenza_dt": "2027-01-01",
        "filtro_dimensioni": "",
        "filtro_quantita": 1
    }
    
    for col, default_val in colonne_richieste.items():
        if col not in df.columns:
            df[col] = default_val
            
    return df

# --- LOGIN & PROFILAZIONE ---
st.sidebar.title("CBRE GWS - Castel Romano")
st.sidebar.markdown("---")
st.sidebar.subheader("🔐 Accesso Operatore")

profilo_selezionato = st.sidebar.selectbox(
    "Seleziona Profilo:",
    ["Seleziona...", "Antonio (Leon - F-GAS)", "Pino", "Gianluca", "Johann"]
)

autorizzato_fgas = False
operatore_corrente = ""

if profilo_selezionato != "Seleziona...":
    if "Antonio" in profilo_selezionato:
        pin_inserito = st.sidebar.text_input("Inserisci Codice LUL / PIN:", type="password")
        if pin_inserito == "3177":
            autorizzato_fgas = True
            operatore_corrente = "Antonio"
            st.sidebar.success("Accesso Totale F-GAS Autorizzato (Antonio - 3177)")
        elif pin_inserito != "":
            st.sidebar.error("Codice non valido!")
    else:
        operatore_corrente = profilo_selezionato.strip()
        st.sidebar.info(f"Accesso Operativo Standard ({operatore_corrente})")

st.sidebar.markdown("---")

if autorizzato_fgas:
    menu = st.sidebar.selectbox(
        "Seleziona Modulo",
        [
            "Dashboard Operatori (Pallini Stato)",
            "Ricerca & Gestione Impianti",
            "Manutenzione Preventiva & F-GAS (Admin)",
            "ODL Correttiva / A Chiamata",
            "Profilo & F-GAS"
        ]
    )
elif operatore_corrente != "":
    menu = st.sidebar.selectbox(
        "Seleziona Modulo",
        [
            "Dashboard Operatori (Pallini Stato)",
            "Ricerca & Gestione Impianti",
            "Manutenzione Preventiva & Filtri",
            "ODL Correttiva / A Chiamata"
        ]
    )
else:
    menu = "Benvenuto"

oggi = datetime.now()

if menu == "Benvenuto":
    st.title("CBRE Technical Division - Castel Romano")
    st.info("👈 Seleziona il tuo profilo nella barra laterale per accedere al gestionale.")

elif menu == "Dashboard Operatori (Pallini Stato)":
    st.title("Dashboard Operatori - Castel Romano 2026")
    df_impianti = carica_dataframe_sicuro()

    op_filtro = st.radio(
        "Filtra per Operatore:",
        ["Tutti", "Antonio", "Pino", "Gianluca", "Johann"],
        horizontal=True
    )

    if op_filtro != "Tutti":
        df_op = df_impianti[df_impianti["operatore_assegnato"].astype(str).str.lower() == op_filtro.lower()]
    else:
        df_op = df_impianti

    st.subheader(f"Unità HVAC Associate ({len(df_op)} impianti)")

    for idx, row in df_op.iterrows():
        scad_str = str(row.get("data_scadenza_dt", "2027-01-01"))
        try:
            dt_scad = datetime.strptime(scad_str[:10], "%Y-%m-%d")
            delta = (dt_scad - oggi).days
        except:
            delta = 9999

        pallino = "🔴" if delta < 0 else ("🟡" if delta <= 30 else "🟢")

        with st.expander(f"{pallino} Unità {row['nr_unita']} - {row['marca']} ({row['zona_designata']}) [Assegnato a: {row['operatore_assegnato']}]"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.write(f"- **Codice Targa:** `{row['codice_targa']}`")
                st.write(f"- **Modello:** `{row['modello']}`")
            with c2:
                st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
                st.write(f"- **Tonn. CO2 Eq:** `{row['tonn_co2_eq']}`")
            with c3:
                st.write(f"- **F-GAS N°:** `{row['f_gas_n']}`")
                st.write(f"- **Scadenza:** `{row['scadenza_verifica']}`")

elif menu == "Ricerca & Gestione Impianti":
    st.title("Ricerca Impianti & Aggiornamento Filtri in Loco")
    df_impianti = carica_dataframe_sicuro()

    search_query = st.text_input("Cerca per unità, zona, marca o codice targa:", "").strip().lower()
    if search_query:
        unita_filtrate = df_impianti[
            df_impianti["zona_designata"].astype(str).str.lower().str.contains(search_query) |
            df_impianti["nr_unita"].astype(str).str.lower().str.contains(search_query) |
            df_impianti["marca"].astype(str).str.lower().str.contains(search_query) |
            df_impianti["codice_targa"].astype(str).str.lower().str.contains(search_query)
        ]
    else:
        unita_filtrate = df_impianti.copy()

    for idx, row in unita_filtrate.iterrows():
        key_id = str(row["id_macchina"]).replace(" ", "_").replace("/", "_")
        
        with st.expander(f"Unità {row['nr_unita']} - {row['marca']} ({row['zona_designata']})"):
            db_dim = str(row.get("filtro_dimensioni", "") or "")
            db_qta = int(row.get("filtro_quantita", 1) if pd.notna(row.get("filtro_quantita", 1)) else 1)

            with st.form(key=f"form_loco_{key_id}"):
                st.markdown("##### Specifiche Filtri & Manutenzione Ordinaria")
                c_f1, c_f2 = st.columns(2)
                with c_f1:
                    dim_in = st.text_input("Dimensioni Filtri (es. 500x500x48)", value=db_dim, key=f"dim_{key_id}")
                with c_f2:
                    qta_in = st.number_input("Quantità Filtri", min_value=1, max_value=20, value=db_qta, key=f"qta_{key_id}")

                note_op = st.text_input("Note Intervento / Pulizia Batteria & Condensa", "Pulizia filtri e controllo scarico condensa eseguiti regolarmente.", key=f"nt_{key_id}")

                btn_salva = st.form_submit_button("Salva Modifiche nel Database")
                if btn_salva:
                    conn_u = sqlite3.connect(DB_PATH, timeout=10.0)
                    cur_u = conn_u.cursor()
                    cur_u.execute("UPDATE macchine_hvac SET filtro_dimensioni = ?, filtro_quantita = ? WHERE id_macchina = ?", (dim_in, qta_in, row["id_macchina"]))
                    conn_u.commit()
                    conn_u.close()
                    st.success("Specifiche aggiornate con successo nel database locale!")
                    st.rerun()

elif menu in ["Manutenzione Preventiva & Filtri", "Manutenzione Preventiva & F-GAS (Admin)"]:
    st.title("Manutenzione Preventiva & Checklist Operativa")
    df_prev = carica_dataframe_sicuro()[["nr_unita", "marca", "operatore_assegnato", "refrigerante", "tonn_co2_eq", "zona_designata"]]
    st.dataframe(df_prev, use_container_width=True, hide_index=True)

elif menu == "ODL Correttiva / A Chiamata":
    st.title("Gestione ODL Correttivi & Archivio Storico (2+ Anni)")

    tab1, tab2 = st.tabs(["Nuovo ODL / Chiusura", "Archivio Storico (Download 2+ Anni)"])

    with tab1:
        with st.form("form_odl"):
            st.subheader("Registrazione Intervento Straordinario")
            c_odl = st.text_input("Codice ODL", value="C63380570")
            richiedente = st.text_input("Richiedente", value="Security Castel Romano")
            descrizione = st.text_area("Descrizione Lavoro", value="Intervento di manutenzione straordinaria")
            
            c1, c2 = st.columns(2)
            with c1:
                ora_inizio = st.text_input("Ora Inizio", value="19:00")
            with c2:
                ora_fine = st.text_input("Ora Fine", value="19:30")
                
            esito = st.selectbox("Intervento Completato", ["SI", "NO"])
            note_odl = st.text_area("Note Tecniche / Ricambi Utilizzati")

            salva_odl = st.form_submit_button("Registra e Salva ODL nell'Archivio")
            if salva_odl:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                timestamp_attuale = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT INTO odl_chiamata (codice_odl, richiedente, descrizione, ora_inizio, ora_fine, esito, note, stato, operatore, timestamp_reg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (c_odl, richiedente, descrizione, ora_inizio, ora_fine, esito, note_odl, "Completato", operatore_corrente, timestamp_attuale))
                conn.commit()
                conn.close()
                st.success(f"ODL {c_odl} registrato con successo nell'archivio conservativo!")

    with tab2:
        st.subheader("Archivio Storico ODL Eseguiti")
        conn = sqlite3.connect(DB_PATH)
        df_odl = pd.read_sql("SELECT * FROM odl_chiamata ORDER BY id DESC", conn)
        conn.close()

        if not df_odl.empty:
            st.dataframe(df_odl, use_container_width=True)

            excel_filename = f"Archivio_ODL_Castel_Romano_{datetime.now().strftime('%Y%m%d')}.xlsx"
            df_odl.to_excel(excel_filename, index=False)

            with open(excel_filename, "rb") as f_excel:
                st.download_button(
                    label="📥 Scarica Archivio ODL Completo (Excel - Retention 2+ Anni)",
                    data=f_excel,
                    file_name=excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_dl_archivio_odl"
                )
        else:
            st.info("Nessun ODL registrato nell'archivio.")

elif menu == "Profilo & F-GAS":
    st.title("Profilo Tecnico & Certificazione F-GAS")
    st.success("Tecnico Amministratore: Sandor Antonio León Martínez")
    st.write("**Codice LUL:** `3177`")
    st.write("**N. Iscrizione Registro F-GAS:** `PR0148807` (Cat. I)")
