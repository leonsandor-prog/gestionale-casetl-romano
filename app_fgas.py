import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta
from docx import Document

DB_PATH = "castel_romano.db"
EXCEL_PATH = "dati con unita.xlsx"

def init_db_mappa():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS macchine_hvac (
                id_macchina TEXT PRIMARY KEY,
                collocazione TEXT,
                prov TEXT,
                unita TEXT,
                cod_apparecchiatura TEXT,
                marca TEXT,
                modello TEXT,
                matricola TEXT,
                tipo_refrigerante TEXT,
                tonn_co2_eq REAL,
                carica_kg REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS manutenzione_impianti (
                matricola TEXT PRIMARY KEY,
                macro_area TEXT,
                tipo_filtro TEXT DEFAULT 'G4 Cella',
                quantita_filtri INTEGER DEFAULT 2,
                misure_filtri TEXT DEFAULT '592x592x48 mm',
                stato_pulizia TEXT DEFAULT 'Buono',
                data_ultima_manutenzione TEXT,
                data_prossima_scadenza TEXT,
                stato_scadenza TEXT DEFAULT 'REGOLARE'
            )
        ''')
        
        cursor.execute('SELECT COUNT(*) FROM macchine_hvac')
        count = cursor.fetchone()[0]
        
        if count == 0 and os.path.exists(EXCEL_PATH):
            df_excel = pd.read_excel(EXCEL_PATH)
            valid_rows = [r for _, r in df_excel.iterrows() if str(r.get("Matricola", "")).strip() and str(r.get("Matricola", "")) != "nan"]
            
            dt_oggi = datetime.now()
            for i, row in enumerate(valid_rows):
                matr = str(row.get("Matricola", "")).strip()
                unita_val = str(row.get("unita ", "")).strip()
                num_unita_str = unita_val.split('/')[0].split(' ')[0].strip()
                
                macro = "📍 Piazza Centrale"
                if num_unita_str.isdigit():
                    n = int(num_unita_str)
                    if n >= 100 and n <= 135:
                        macro = "🏛️ Piazza del Colosseo"
                    elif n >= 110 and n <= 129:
                        macro = "🦕 Piazza del Foro Romano"
                    elif n >= 60 and n <= 90:
                        macro = "🏛️ Piazza di Augusto / Traiano"
                    elif n >= 140 and n <= 184:
                        macro = "🏺 Piazza di Caracalla / G. Cesare"
                    elif n < 40:
                        macro = "⚡ Locali Tecnici & Coperture (Unità 31...)"
                
                cursor.execute('''
                    INSERT OR REPLACE INTO macchine_hvac 
                    (id_macchina, collocazione, prov, unita, cod_apparecchiatura, marca, modello, matricola, tipo_refrigerante, tonn_co2_eq, carica_kg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    matr,
                    str(row.get("COLLOCAZIONE", "")),
                    str(row.get("Prov", "")),
                    unita_val,
                    str(row.get("Cod. Apparecchiatura", "")),
                    str(row.get("Marca", "")),
                    str(row.get("Modello", "")),
                    matr,
                    str(row.get("Tipo HCFC", "")),
                    float(row.get("Tonn CO2 Eq", 0.0) or 0.0),
                    float(row.get("Carica Refrigerante (kg)", 0.0) or 0.0)
                ))
                
                days_offset = (i % 30) + 1
                dt_scad_val = dt_oggi + timedelta(days=days_offset)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO manutenzione_impianti 
                    (matricola, macro_area, tipo_filtro, quantita_filtri, misure_filtri, stato_pulizia, data_ultima_manutenzione, data_prossima_scadenza, stato_scadenza)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'REGOLARE')
                ''', (matr, macro, 'G4 Cella', 2, '592x592x48 mm', 'Buono', dt_oggi.strftime("%Y-%m-%d"), dt_scad_val.strftime("%Y-%m-%d")))
                    
        conn.commit()
    finally:
        conn.close()

init_db_mappa()

st.set_page_config(page_title="Planimetria Visiva & F-GAS Castel Romano", layout="wide")
st.title("🗺️ Planimetria Visiva Interattiva — Castel Romano")

conn = sqlite3.connect(DB_PATH, timeout=10.0)
df_full = pd.read_sql_query("SELECT M.*, F.macro_area, F.tipo_filtro, F.quantita_filtri, F.misure_filtri, F.stato_pulizia, F.data_ultima_manutenzione, F.data_prossima_scadenza, F.stato_scadenza FROM macchine_hvac M JOIN manutenzione_impianti F ON M.matricola = F.matricola", conn)
conn.close()

# Verifica dinamica dello stato in base alla data odierna
data_oggi_str = datetime.now().strftime("%Y-%m-%d")
df_full.loc[df_full['data_prossima_scadenza'] < data_oggi_str, 'stato_scadenza'] = 'SCADUTO'
df_full.loc[df_full['data_prossima_scadenza'] >= data_oggi_str, 'stato_scadenza'] = 'REGOLARE'

# --- MAPPA VISIVA A BLOCCHI ---
st.markdown("### 🧭 Mappa Visiva delle Piazze e Coperture")
st.markdown("Clicca su una zona per accedere direttamente alle unità e ai negozi corrispondenti.")

macro_aree_disponibili = sorted(df_full['macro_area'].unique())

cols_grid = st.columns(2)
for idx, zona in enumerate(macro_aree_disponibili):
    df_zona_check = df_full[df_full['macro_area'] == zona]
    num_impianti = len(df_zona_check)
    
    ha_scadenze = "SCADUTO" in df_zona_check['stato_scadenza'].values
    ha_filtri_pendenti = "Da Sostituire" in df_zona_check['stato_pulizia'].values
    
    if ha_scadenze:
        icona_stato = "🔴 [Scadenze F-GAS Attive]"
    elif ha_filtri_pendenti:
        icona_stato = "🟠 [Attenzione: Filtri da Sostituire]"
    else:
        icona_stato = "🟢 [Regolare]"
    
    with cols_grid[idx % 2]:
        with st.container(border=True):
            st.markdown(f"#### {zona}")
            st.write(f"Impianti censiti in quest'area: **{num_impianti}**")
            st.write(f"Stato area: {icona_stato}")
            
            if st.button(f"🔍 Apri Planimetria Zona", key=f"btn_map_{idx}", use_container_width=True):
                st.session_state['zona_selezionata'] = zona

st.markdown("---")

if 'zona_selezionata' not in st.session_state:
    st.session_state['zona_selezionata'] = macro_aree_disponibili[0] if len(macro_aree_disponibili) > 0 else ""

st.markdown(f"### 🏢 Unità e Negozi in: `{st.session_state['zona_selezionata']}`")

df_corrente = df_full[df_full['macro_area'] == st.session_state['zona_selezionata']]
df_corrente['unita_base'] = df_corrente['unita'].astype(str).apply(lambda x: x.split('/')[0].split(' ')[0].strip())
unita_nella_zona = sorted(df_corrente['unita_base'].unique(), key=lambda x: int(x) if x.isdigit() else 0)

if not unita_nella_zona:
    st.info("Nessuna unità trovata in questa area.")
else:
    st.markdown("**Seleziona l'Unità / Negozio rapido:**")
    cols_unita = st.columns(min(len(unita_nella_zona), 6))
    
    if 'unita_selezionata' not in st.session_state:
        st.session_state['unita_selezionata'] = unita_nella_zona[0]

    for i, u_val in enumerate(unita_nella_zona):
        df_u_chk = df_corrente[df_corrente['unita_base'] == u_val]
        ha_scad_u = "SCADUTO" in df_u_chk['stato_scadenza'].values
        ha_filt_u = "Da Sostituire" in df_u_chk['stato_pulizia'].values
        
        if ha_scad_u:
            prefix = "🔴"
        elif ha_filt_u:
            prefix = "🟠"
        else:
            prefix = "🟢"
        
        with cols_unita[i % len(cols_unita)]:
            if st.button(f"{prefix} Un. {u_val}", key=f"unita_btn_{u_val}", use_container_width=True):
                st.session_state['unita_selezionata'] = u_val

    unita_scelta_dettaglio = st.selectbox(
        "Oppure seleziona dal menu a tendina:", 
        unita_nella_zona, 
        index=unita_nella_zona.index(st.session_state['unita_selezionata']) if st.session_state['unita_selezionata'] in unita_nella_zona else 0
    )
    
    df_unita_finale = df_corrente[df_corrente['unita_base'] == unita_scelta_dettaglio]
    
    st.markdown(f"#### Impianti associati all'Unità `{unita_scelta_dettaglio}`")
    
    for _, row in df_unita_finale.iterrows():
        matricola_str = str(row['matricola']).strip()
        is_scaduto = row['stato_scadenza'] == "SCADUTO"
        is_da_sostituire = row['stato_pulizia'] == "Da Sostituire"
        
        if is_scaduto:
            stato_icona = "🔴 [SCADUTA / CONTROLLO F-GAS]"
        elif is_da_sostituire:
            stato_icona = "🟠 [ATTENZIONE: FILTRI DA SOSTITUIRE]"
        else:
            stato_icona = "🟢 [REGOLARE]"
        
        with st.expander(f"{stato_icona} Unità {row['unita']} — {row['marca']} {row['modello']} (Matr: {matricola_str})", expanded=is_scaduto or is_da_sostituire):
            
            if is_scaduto:
                st.warning(f"⚠️ **Impianto Scaduto**: Scadenza registrata: `{row['data_prossima_scadenza']}`.")
            elif is_da_sostituire:
                st.info(f"🟠 **Segnalazione Aperta**: I filtri risultano da sostituire (In attesa di materiale/ricambi). Scadenza F-GAS valida fino al `{row['data_prossima_scadenza']}`.")
            else:
                st.success(f"🟢 **Impianto Regolare**: Scadenza valida fino al `{row['data_prossima_scadenza']}`.")
            
            # Pulsante rapido per ripristinare a verde quando i filtri vengono cambiati
            if st.button(f"🟢 Conferma Cambio Filtri e Ripristina a Verde", key=f"btn_reset_{matricola_str}", type="primary", use_container_width=True):
                conn_r = sqlite3.connect(DB_PATH, timeout=10.0)
                cursor_r = conn_r.cursor()
                dt_oggi = datetime.now()
                dt_scad_nuova = dt_oggi + timedelta(days=30)
                
                cursor_r.execute('''
                    UPDATE manutenzione_impianti 
                    SET data_ultima_manutenzione = ?,
                        data_prossima_scadenza = ?,
                        stato_pulizia = 'Pulito / Ottimale',
                        stato_scadenza = 'REGOLARE'
                    WHERE matricola = ?
                ''', (
                    dt_oggi.strftime("%Y-%m-%d"), 
                    dt_scad_nuova.strftime("%Y-%m-%d"), 
                    matricola_str
                ))
                conn_r.commit()
                conn_r.close()
                st.success("Filtri sostituiti e impianto riportato a VERDE con successo!")
                st.rerun()

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**📋 Dati Tecnici**")
                st.write(f"• Cod. Apparecchiatura: `{row['cod_apparecchiatura']}`")
                st.write(f"• Gas: `{row['tipo_refrigerante']}` ({row['carica_kg']} kg)")
                st.write(f"• CO2 eq: `{row['tonn_co2_eq']} t`")
            with c2:
                st.markdown("**🔧 Filtri & Pulizia**")
                st.write(f"• Tipo: `{row['tipo_filtro']}`")
                st.write(f"• Q.tà: `{row['quantita_filtri']} pz`")
                st.write(f"• Misure: `{row['misure_filtri']}`")
                st.write(f"• Stato: `{row['stato_pulizia']}`")
            with c3:
                st.markdown("**📅 Manutenzione**")
                st.write(f"• Ultimo: `{row['data_ultima_manutenzione']}`")
                st.write(f"• Scadenza: `{row['data_prossima_scadenza']}`")
                
            st.markdown("---")
            
            form_key = f"form_map_{matricola_str}"
            with st.form(key=form_key):
                st.markdown("##### 📝 Esecuzione Controlli e Registrazione Intervento Completo")
                
                rc1, rc2 = st.columns(2)
                with rc1:
                    fatto_perdite = st.checkbox("🔍 Controllo Periodico Perdite Gas Eseguito", value=True, key=f"fatto_perdite_{matricola_str}")
                    esito_perdite = st.selectbox("Esito Controllo Perdite (WIGAN ELD-H)", ["Assenza Perdite", "Rilevata Perdita"], key=f"esito_{matricola_str}")
                with rc2:
                    fatto_filtri = st.checkbox("🧹 Pulizia / Sostituzione Filtri Eseguita", value=False, key=f"fatto_filtri_{matricola_str}")
                    nuovo_stato = st.selectbox("Stato Filtri Post-Intervento", ["Da Sostituire", "Pulito / Ottimale", "Buono"], key=f"stato_{matricola_str}")
                
                note_intervento = st.text_input("Note Tecniche / Azioni eseguite", "Controllo eseguito, registrato stato filtri.", key=f"note_{matricola_str}")
                
                btn_salva = st.form_submit_button("✅ Salvataggio Intervento e Genera Report Word")
                
                if btn_salva:
                    conn_update = sqlite3.connect(DB_PATH, timeout=10.0)
                    cursor_up = conn_update.cursor()
                    
                    dt_oggi = datetime.now()
                    dt_scadenza_nuova = dt_oggi + timedelta(days=30)
                    
                    cursor_up.execute('''
                        UPDATE manutenzione_impianti 
                        SET data_ultima_manutenzione = ?,
                            data_prossima_scadenza = ?,
                            stato_pulizia = ?,
                            stato_scadenza = 'REGOLARE'
                        WHERE matricola = ?
                    ''', (
                        dt_oggi.strftime("%Y-%m-%d"), 
                        dt_scadenza_nuova.strftime("%Y-%m-%d"), 
                        nuovo_stato, 
                        matricola_str
                    ))
                    conn_update.commit()
                    conn_update.close()
                    
                    doc = Document()
                    doc.add_heading('12-00.646.GWS-IT - REPORT DI MANUTENZIONE APPARECCHIATURE F-GAS', level=1)
                    doc.add_paragraph('Reg. 517/14 UE e DPR 146/2018')
                    
                    p_info = doc.add_paragraph()
                    p_info.add_run(f"N° Report: {row['cod_apparecchiatura']}/2026\n").bold = True
                    p_info.add_run(f"Data Intervento: {dt_oggi.strftime('%d/%m/%Y')}\n")
                    
                    doc.add_heading('ESTREMI CLIENTE & INSTALLAZIONE', level=2)
                    p_cli = doc.add_paragraph()
                    p_cli.add_run("Ragione Sociale: ").bold = True
                    p_cli.add_run("BMG CASTELROMANO SRL\n")
                    p_cli.add_run("Indirizzo: ").bold = True
                    p_cli.add_run("VIA DEL PONTE DI PISCINA CUPA 64 (Unità: " + str(row['unita']) + ")\n")
                    p_cli.add_run("Codice Fiscale: ").bold = True
                    p_cli.add_run("13096010156\n")
                    
                    doc.add_heading('ESTREMI APPARECCHIATURA', level=2)
                    p_mac = doc.add_paragraph()
                    p_mac.add_run("Marca: ").bold = True
                    p_mac.add_run(str(row['marca']) + "   ")
                    p_mac.add_run("Modello: ").bold = True
                    p_mac.add_run(str(row['modello']) + "   ")
                    p_mac.add_run("Matricola / N° Serie: ").bold = True
                    p_mac.add_run(matricola_str + "\n")
                    p_mac.add_run("Codice Apparecchiatura: ").bold = True
                    p_mac.add_run(str(row['cod_apparecchiatura']) + "\n")
                    p_mac.add_run("Gas Refrigerante: ").bold = True
                    p_mac.add_run(str(row['tipo_refrigerante']) + " - Carica: " + str(row['carica_kg']) + " Kg - Tonn CO2 Eq: " + str(row['tonn_co2_eq']) + "\n")
                    
                    doc.add_heading('ESTREMI MANUTENTORE & TECNICO', level=2)
                    p_tec = doc.add_paragraph()
                    p_tec.add_run("Società Manutentrice: ").bold = True
                    p_tec.add_run("CBRE TECHNICAL DIVISION (Certificato Azienda N°: 303310)\n")
                    p_tec.add_run("Nome Tecnico: ").bold = True
                    p_tec.add_run("ANTONIO MARTINEZ (Certificato Tecnico N°: PR-0148807)\n")
                    
                    doc.add_heading('CONTROLLO PERDITE & ESITO', level=2)
                    p_cont = doc.add_paragraph()
                    p_cont.add_run("Controllo Periodico: ").bold = True
                    p_cont.add_run("ESEGUITO (" + ("Spuntato" if fatto_perdite else "Non eseguito") + ")\n")
                    p_cont.add_run("Pulizia Filtri: ").bold = True
                    p_cont.add_run(f"STATO IMPOSTATO: {nuovo_stato.upper()}\n")
                    p_cont.add_run("Metodo Cercafughe: ").bold = True
                    p_cont.add_run("Diretto (WIGAN ELD-H - Matricola: 21020370BA)\n")
                    p_cont.add_run("Esito Circuito 1: ").bold = True
                    p_cont.add_run(f"{esito_perdite.upper()}\n")
                    p_cont.add_run("Note Operative: ").bold = True
                    p_cont.add_run(note_intervento + "\n")
                    
                    safe_matr = matricola_str.replace('/', '_')
                    filename = f"Report_FGAS_{row['marca']}_{safe_matr}.docx"
                    doc.save(filename)
                    
                    st.session_state[f'file_pronto_{matricola_str}'] = filename
                    st.success(f"Intervento registrato! Stato filtri aggiornato a: {nuovo_stato}.")
                    st.rerun()

            if st.session_state.get(f'file_pronto_{matricola_str}'):
                file_da_scaricare = st.session_state[f'file_pronto_{matricola_str}']
                if os.path.exists(file_da_scaricare):
                    with open(file_da_scaricare, "rb") as file_in:
                        st.download_button(
                            label=f"📥 Scarica Modulo Ufficiale Word ({file_da_scaricare})",
                            data=file_in,
                            file_name=file_da_scaricare,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"dl_{matricola_str}"
                        )