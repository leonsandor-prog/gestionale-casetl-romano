import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

DB_PATH = "castel_romano.db"
EXCEL_PATH = "dati con unita.xlsx"

def set_cell_background(cell, fill_hex):
    tcPr = cell._element.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

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

st.set_page_config(page_title="Gestione F-GAS & Manutenzione Castel Romano", layout="wide")
st.title("🗺️ Planimetria Visiva & Gestione Report — Castel Romano")

conn = sqlite3.connect(DB_PATH, timeout=10.0)
df_full = pd.read_sql_query("SELECT M.*, F.macro_area, F.tipo_filtro, F.quantita_filtri, F.misure_filtri, F.stato_pulizia, F.data_ultima_manutenzione, F.data_prossima_scadenza, F.stato_scadenza FROM macchine_hvac M JOIN manutenzione_impianti F ON M.matricola = F.matricola", conn)
conn.close()

data_oggi_str = datetime.now().strftime("%Y-%m-%d")
df_full.loc[df_full['data_prossima_scadenza'] < data_oggi_str, 'stato_scadenza'] = 'SCADUTO'
df_full.loc[df_full['data_prossima_scadenza'] >= data_oggi_str, 'stato_scadenza'] = 'REGOLARE'

st.markdown("### 🧭 Mappa Visiva delle Piazze e Coperture")

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
            st.write(f"Impianti censiti: **{num_impianti}**")
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
        
        prefix = "🔴" if ha_scad_u else ("🟠" if ha_filt_u else "🟢")
        
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
        cod_app_str = str(row['cod_apparecchiatura']).strip()
        is_scaduto = row['stato_scadenza'] == "SCADUTO"
        is_da_sostituire = row['stato_pulizia'] == "Da Sostituire"
        
        stato_icona = "🔴 [SCADUTA F-GAS]" if is_scaduto else ("🟠 [FILTRI DA SOSTITUIRE]" if is_da_sostituire else "🟢 [REGOLARE]")
        
        with st.expander(f"{stato_icona} Unità {row['unita']} — {row['marca']} {row['modello']} (Matr: {matricola_str})", expanded=is_scaduto or is_da_sostituire):
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**📋 Dati Tecnici**")
                st.write(f"• Cod. Apparecchiatura: `{cod_app_str}`")
                st.write(f"• Gas: `{row['tipo_refrigerante']}` ({row['carica_kg']} kg)")
            with c2:
                st.markdown("**🔧 Filtri & Pulizia**")
                st.write(f"• Tipo: `{row['tipo_filtro']}` ({row['quantita_filtri']} pz)")
                st.write(f"• Misure: `{row['misure_filtri']}`")
                st.write(f"• Stato: `{row['stato_pulizia']}`")
            with c3:
                st.markdown("**📅 Scadenze**")
                st.write(f"• Ultimo: `{row['data_ultima_manutenzione']}`")
                st.write(f"• F-GAS: `{row['data_prossima_scadenza']}`")
                
            st.markdown("---")
            
            tab_fgas, tab_filtri = st.tabs(["❄️ 1. Report Ufficiale F-GAS (CBRE)", "🧹 2. Rapportino Manutenzione Filtri"])
            
            # --- TAB 1: REPORT UFFICIALE F-GAS ---
            with tab_fgas:
                with st.form(key=f"form_fgas_{matricola_str}"):
                    st.markdown("##### 📝 Controllo Periodico F-GAS (Modello 12-00.646.GWS-IT)")
                    
                    tipo_funzione = st.radio("Funzione Prevalente", ["Condizionamento", "Pompa di Calore", "Refrigerazione", "Antincendio"], index=0, key=f"func_{matricola_str}")
                    num_circuiti = st.number_input("N° Circuiti Impianto", min_value=1, max_value=4, value=1, key=f"circ_num_{matricola_str}")
                    ermetico = st.radio("Ermeticamente Sigillato?", ["NO", "SI"], index=0, key=f"erm_{matricola_str}")
                    metodo_cerca = st.radio("Metodo Cercafughe", ["Diretto", "Indiretto"], index=0, key=f"metodo_{matricola_str}")
                    
                    esito_circ1 = st.selectbox("Esito Circuito 1", ["Assenza Perdite", "Rilevata Perdita"], key=f"es1_{matricola_str}")
                    note_fgas = st.text_input("Note Tecniche F-GAS", "Controllo periodico eseguito con esito regolare.", key=f"note_fgas_{matricola_str}")
                    
                    btn_fgas_submit = st.form_submit_button("✅ Salva & Genera Word F-GAS Ufficiale")
                    
                    if btn_fgas_submit:
                        conn_up = sqlite3.connect(DB_PATH, timeout=10.0)
                        cursor_up = conn_up.cursor()
                        dt_oggi = datetime.now()
                        dt_scad_nuova = dt_oggi + timedelta(days=30)
                        
                        cursor_up.execute('''
                            UPDATE manutenzione_impianti 
                            SET data_ultima_manutenzione = ?,
                                data_prossima_scadenza = ?,
                                stato_scadenza = 'REGOLARE'
                            WHERE matricola = ?
                        ''', (dt_oggi.strftime("%Y-%m-%d"), dt_scad_nuova.strftime("%Y-%m-%d"), matricola_str))
                        conn_up.commit()
                        conn_up.close()
                        
                        # Generazione Modello Word Ufficiale CBRE F-GAS
                        doc = Document()
                        for s in doc.sections:
                            s.top_margin = Inches(0.4)
                            s.bottom_margin = Inches(0.4)
                            s.left_margin = Inches(0.5)
                            s.right_margin = Inches(0.5)

                        t_top = doc.add_table(rows=1, cols=3)
                        t_top.alignment = WD_TABLE_ALIGNMENT.CENTER
                        t_top.cell(0, 0).text = "CBRE"
                        t_top.cell(0, 1).text = "12-00.646.GWS-IT - REPORT DI MANUTENZIONE APPARECCHIATURE F-GAS\nReg. 517/14 UE e DPR 146/2018 (Validità 30 gg)"
                        t_top.cell(0, 2).text = f"N° Report:\n{cod_app_str}/2026\nData: {dt_oggi.strftime('%d/%m/%Y')}"

                        doc.add_paragraph().paragraph_format.space_after = Pt(4)
                        doc.add_paragraph(f"1. ESTREMI OPERATORE:\nRagione Sociale: BMG CASTELROMANO SRL — Indirizzo: VIA DEL PONTE DI PISCINA CUPA 64 (Unità: {row['unita']})\nMail: Letizia.Bianchetti@mcarthurglen.com")
                        doc.add_paragraph(f"2. ESTREMI APPARECCHIATURA:\nMarca: {row['marca']} | Modello: {row['modello']} | Matricola: {matricola_str}\nGas: {row['tipo_refrigerante']} - Carica: {row['carica_kg']} Kg - CO2 eq: {row['tonn_co2_eq']} t")
                        doc.add_paragraph(f"3. ESTREMI MANUTENTORE:\nCBRE TECHNICAL DIVISION (Cert. Azienda N°: 303310)\nTecnico: ANTONIO MARTINEZ (Cert. Tecnico N°: PR-0148807)")
                        doc.add_paragraph(f"4. CONTROLLO PERDITE:\nControllo Periodico Eseguito — Metodo: {metodo_cerca} — Cercafughe: WIGAN ELD-H (Matr: 21020370BA, Sensibilità: 14 g/anno)\nEsito Circuito 1: {esito_circ1.upper()} — Note: {note_fgas}")

                        safe_matr = matricola_str.replace('/', '_')
                        filename_fgas = f"Report_FGAS_{row['marca']}_{safe_matr}.docx"
                        doc.save(filename_fgas)
                        st.session_state[f'dl_fgas_{matricola_str}'] = filename_fgas
                        st.success("Report Ufficiale F-GAS generato con successo!")
                        st.rerun()

                if st.session_state.get(f'dl_fgas_{matricola_str}'):
                    f_fgas = st.session_state[f'dl_fgas_{matricola_str}']
                    if os.path.exists(f_fgas):
                        with open(f_fgas, "rb") as file_in:
                            st.download_button(label=f"📥 Scarica Word Ufficiale F-GAS ({f_fgas})", data=file_in, file_name=f_fgas, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

            # --- TAB 2: RAPPORTINO FILTRI ---
            with tab_filtri:
                with st.form(key=f"form_filtri_{matricola_str}"):
                    st.markdown("##### 🧹 Rapportino Intervento Filtri & Manutenzione Ordinaria")
                    
                    tipo_azione_filtri = st.selectbox(
                        "Tipo di Intervento Eseguito", 
                        ["Pulizia / Spolveratura Filtri", "Lavaggio Filtri & Sanificazione Vasca", "Sostituzione Filtri Nuovi", "Segnalato Filtro Da Ordinare"], 
                        key=f"azione_f_{matricola_str}"
                    )
                    nuovo_stato_filtri = st.selectbox(
                        "Stato Filtri Post-Intervento", 
                        ["Pulito / Ottimale", "Buono", "Da Sostituire"], 
                        key=f"stato_f_{matricola_str}"
                    )
                    note_filtri = st.text_input(
                        "Note Tecniche Operative", 
                        "Eseguita pulizia filtri, controllato il corretto scarico condensa e ripristinato il flusso d'aria.", 
                        key=f"note_f_{matricola_str}"
                    )
                    
                    btn_filtri_submit = st.form_submit_button("✅ Salva Stato & Genera Rapportino Word")
                    
                    if btn_filtri_submit:
                        conn_up = sqlite3.connect(DB_PATH, timeout=10.0)
                        cursor_up = conn_up.cursor()
                        dt_oggi = datetime.now()
                        
                        cursor_up.execute('''
                            UPDATE manutenzione_impianti 
                            SET stato_pulizia = ?
                            WHERE matricola = ?
                        ''', (nuovo_stato_filtri, matricola_str))
                        conn_up.commit()
                        conn_up.close()
                        
                        doc_f = Document()
                        for s in doc_f.sections:
                            s.top_margin = Inches(0.5)
                            s.bottom_margin = Inches(0.5)
                            s.left_margin = Inches(0.6)
                            s.right_margin = Inches(0.6)
                        
                        t_head = doc_f.add_table(rows=1, cols=2)
                        t_head.alignment = WD_TABLE_ALIGNMENT.CENTER
                        t_head.cell(0, 0).text = "CBRE"
                        t_head.cell(0, 1).text = "RAPPORTINO MANUTENZIONE FILTRI\n& INTERVENTO ORDINARIO"
                        
                        doc_f.add_paragraph().paragraph_format.space_after = Pt(6)
                        doc_f.add_paragraph(f"Sito: McArthurGlen Designer Outlet Castel Romano — Data: {dt_oggi.strftime('%d/%m/%Y %H:%M')}\nUnità / Negozio: {row['unita']} — Collocazione: {row['collocazione']}")
                        doc_f.add_paragraph(f"ESTREMI APPARECCHIATURA:\nCodice: {cod_app_str} | Marca/Modello: {row['marca']} {row['modello']} | Matricola: {matricola_str}")
                        doc_f.add_paragraph(f"DETTAGLI INTERVENTO:\nAzione: {tipo_azione_filtri} | Stato Post-Intervento: {nuovo_stato_filtri.upper()}\nTipologia Filtri: {row['tipo_filtro']} ({row['quantita_filtri']} pz, {row['misure_filtri']})\nNote: {note_filtri}")
                        doc_f.add_paragraph(f"TECNICO ESECUTORE:\nCBRE GWS Technical Division — ANTONIO MARTINEZ (Cert. PR-0148807)")

                        safe_matr = matricola_str.replace('/', '_')
                        filename_filtri = f"Rapportino_Filtri_{row['unita_base']}_{safe_matr}.docx"
                        doc_f.save(filename_filtri)
                        
                        st.session_state[f'dl_filtri_{matricola_str}'] = filename_filtri
                        st.success("Rapportino Filtri Word generato con successo!")
                        st.rerun()

                if st.session_state.get(f'dl_filtri_{matricola_str}'):
                    f_filt = st.session_state[f'dl_filtri_{matricola_str}']
                    if os.path.exists(f_filt):
                        with open(f_filt, "rb") as file_in:
                            st.download_button(
                                label=f"📥 Scarica Rapportino Word Filtri ({f_filt})",
                                data=file_in,
                                file_name=f_filt,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"btn_dl_filt_{matricola_str}"
                            )
