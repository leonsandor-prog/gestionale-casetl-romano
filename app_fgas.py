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
        cod_app_str = str(row['cod_apparecchiatura']).strip()
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
                st.info(f"🟠 **Segnalazione Aperta**: I filtri risultano da sostituire. Scadenza F-GAS fino al `{row['data_prossima_scadenza']}`.")
            else:
                st.success(f"🟢 **Impianto Regolare**: Scadenza valida fino al `{row['data_prossima_scadenza']}`.")
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**📋 Dati Tecnici**")
                st.write(f"• Cod. Apparecchiatura: `{cod_app_str}`")
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
                st.write(f"• Scadenza F-GAS: `{row['data_prossima_scadenza']}`")
                
            st.markdown("---")
            
            tab_fgas, tab_filtri = st.tabs(["❄️ 1. Report Ufficiale F-GAS (CBRE / DPR 146)", "🧹 2. Rapportino Manutenzione Filtri"])
            
            # ==========================================
            # TAB 1: REPORT UFFICIALE F-GAS CBRE
            # ==========================================
            with tab_fgas:
                with st.form(key=f"form_fgas_{matricola_str}"):
                    st.markdown("##### 📝 Controllo Periodico F-GAS (Modello 12-00.646.GWS-IT)")
                    
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        tipo_funzione = st.radio("Funzione Prevalente", ["Condizionamento", "Pompa di Calore", "Refrigerazione", "Antincendio"], index=0, key=f"func_{matricola_str}")
                        num_circuiti = st.number_input("N° Circuiti Impianto", min_value=1, max_value=4, value=1, key=f"circ_num_{matricola_str}")
                    with col_f2:
                        ermetico = st.radio("Ermeticamente Sigillato?", ["NO", "SI"], index=0, key=f"erm_{matricola_str}")
                        metodo_cerca = st.radio("Metodo Cercafughe", ["Diretto", "Indiretto"], index=0, key=f"metodo_{matricola_str}")
                    
                    st.markdown("**Esito Controllo Perdite per Circuito:**")
                    esito_circ1 = st.selectbox("Circuito 1", ["Assenza Perdite", "Rilevata Perdita"], key=f"es1_{matricola_str}")
                    esito_circ2 = "N/A"
                    esito_circ3 = "N/A"
                    esito_circ4 = "N/A"
                    if num_circuiti >= 2:
                        esito_circ2 = st.selectbox("Circuito 2", ["Assenza Perdite", "Rilevata Perdita"], key=f"es2_{matricola_str}")
                    if num_circuiti >= 3:
                        esito_circ3 = st.selectbox("Circuito 3", ["Assenza Perdite", "Rilevata Perdita"], key=f"es3_{matricola_str}")
                    if num_circuiti >= 4:
                        esito_circ4 = st.selectbox("Circuito 4", ["Assenza Perdite", "Rilevata Perdita"], key=f"es4_{matricola_str}")
                        
                    note_fgas = st.text_input("Note / Causa ed Azioni se Rilevata Perdita", "Controllo periodico eseguito con esito regolare.", key=f"note_fgas_{matricola_str}")
                    
                    btn_fgas_submit = st.form_submit_button("✅ Salvataggio Intervento & Genera Word F-GAS Ufficiale")
                    
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
                        
                        # GENERAZIONE WORD RIGIDO CBRE
                        doc = Document()
                        
                        # Margini stretti come il modello ufficiale
                        for s in doc.sections:
                            s.top_margin = Inches(0.4)
                            s.bottom_margin = Inches(0.4)
                            s.left_margin = Inches(0.5)
                            s.right_margin = Inches(0.5)

                        # Tabella Intestazione Principale
                        t_top = doc.add_table(rows=2, cols=3)
                        t_top.alignment = WD_TABLE_ALIGNMENT.CENTER
                        
                        cell_logo = t_top.cell(0, 0)
                        cell_logo.text = "CBRE"
                        p_logo = cell_logo.paragraphs[0]
                        p_logo.runs[0].font.name = 'Arial'
                        p_logo.runs[0].font.size = Pt(22)
                        p_logo.runs[0].font.bold = True
                        p_logo.runs[0].font.color.rgb = RGBColor(0, 67, 45) # CBRE Green
                        
                        cell_tit = t_top.cell(0, 1)
                        cell_tit.text = "12-00.646.GWS-IT - REPORT DI MANUTENZIONE APPARECCHIATURE F-GAS\nReg. 517/14 UE e DPR 146/2018\n(validità 30 gg. in attesa del Rapporto inviato dal portale F-GAS)"
                        p_tit = cell_tit.paragraphs[0]
                        p_tit.runs[0].font.name = 'Arial'
                        p_tit.runs[0].font.size = Pt(8.5)
                        p_tit.runs[0].font.bold = True
                        
                        cell_num = t_top.cell(0, 2)
                        cell_num.text = f"N° Report:\n{cod_app_str}/2026\nAnno: 2026"
                        p_num = cell_num.paragraphs[0]
                        p_num.runs[0].font.name = 'Arial'
                        p_num.runs[0].font.size = Pt(8.5)
                        p_num.runs[0].font.bold = True

                        doc.add_paragraph().paragraph_format.space_after = Pt(4)

                        # DATI OPERATORE
                        doc.add_paragraph("ESTREMI OPERATORE").paragraph_format.space_after = Pt(2)
                        t_op = doc.add_table(rows=2, cols=2)
                        t_op.style = 'Table Grid'
                        
                        r0 = t_op.rows[0]
                        r0.cells[0].text = "Ragione Sociale: BMG CASTELROMANO SRL"
                        r0.cells[1].text = "Indirizzo: VIA DEL PONTE DI PISCINA CUPA 64"
                        
                        r1 = t_op.rows[1]
                        r1.cells[0].text = "Codice Fiscale: 13096010156"
                        r1.cells[1].text = "Mail di riferimento: Letizia.Bianchetti@mcarthurglen.com"

                        doc.add_paragraph().paragraph_format.space_after = Pt(4)

                        # DATI APPARECCHIATURA
                        doc.add_paragraph("ESTREMI APPARECCHIATURA").paragraph_format.space_after = Pt(2)
                        t_app = doc.add_table(rows=6, cols=5)
                        t_app.style = 'Table Grid'
                        
                        # Row 0: Funzione
                        c_func = t_app.cell(0, 0)
                        c_func.merge(t_app.cell(0, 4))
                        c_func.text = f"[{'X' if tipo_funzione=='Condizionamento' else ' '}] Condizionamento   [{'X' if tipo_funzione=='Pompa di Calore' else ' '}] Pompa di Calore   [{'X' if tipo_funzione=='Refrigerazione' else ' '}] Refrigerazione   [{'X' if tipo_funzione=='Antincendio' else ' '}] Antincendio"
                        
                        # Row 1: Marca, Modello, Matr, Anno
                        t_app.cell(1, 0).text = f"Marca: {row['marca']}"
                        t_app.cell(1, 1).text = f"Modello: {row['modello']}"
                        t_app.cell(1, 2).merge(t_app.cell(1, 3)).text = f"Matricola: {matricola_str}"
                        t_app.cell(1, 4).text = "Anno Installazione: -"

                        # Row 2: Gas & Sigillo
                        t_app.cell(2, 0).merge(t_app.cell(2, 1)).text = f"Gas Refrigerante (tipo): {row['tipo_refrigerante']}"
                        t_app.cell(2, 2).merge(t_app.cell(2, 4)).text = f"Ermeticamente Sigillato: [{'X' if ermetico=='SI' else ' '}] SI   [{'X' if ermetico=='NO' else ' '}] NO"

                        # Row 3: Tabella Cariche Gas
                        t_app.cell(3, 0).text = "Carica Gas / Circuiti"
                        t_app.cell(3, 1).text = "Circ. 1"
                        t_app.cell(3, 2).text = "Circ. 2"
                        t_app.cell(3, 3).text = "Circ. 3"
                        t_app.cell(3, 4).text = "Circ. 4"

                        # Row 4: Kg e CO2
                        t_app.cell(4, 0).text = f"Quantità: {row['carica_kg']} Kg"
                        t_app.cell(4, 1).text = f"{row['carica_kg']} Kg"
                        t_app.cell(4, 2).text = "-"
                        t_app.cell(4, 3).text = "-"
                        t_app.cell(4, 4).text = "-"

                        # Row 5: Luogo e Codice Apparecchiatura
                        t_app.cell(5, 0).merge(t_app.cell(5, 1)).text = f"Luogo: Castel Romano — VIA DEL PONTE DI PISCINA CUPA 64 (Unità: {row['unita']})"
                        t_app.cell(5, 2).merge(t_app.cell(5, 3)).text = f"Codice Apparecchiatura: {cod_app_str}"
                        t_app.cell(5, 4).text = f"N° Circuiti: {num_circuiti}"

                        doc.add_paragraph().paragraph_format.space_after = Pt(4)

                        # DATI MANUTENTORE
                        doc.add_paragraph("ESTREMI MANUTENTORE").paragraph_format.space_after = Pt(2)
                        t_man = doc.add_table(rows=2, cols=2)
                        t_man.style = 'Table Grid'
                        
                        t_man.rows[0].cells[0].text = "Ragione Sociale: CBRE TECHNICAL DIVISION\nIndirizzo: Via G Verrotti 216 Montesilvano PE\nCertificato Azienda N°: 303310"
                        t_man.rows[0].cells[1].text = "Nome Tecnico: ANTONIO MARTINEZ\nCertificato Tecnico N°: PR-0148807\nN° tel / E-mail: 3499743841"

                        doc.add_paragraph().paragraph_format.space_after = Pt(4)

                        # CONTROLLO PERDITE
                        doc.add_paragraph("CONTROLLO PERDITE").paragraph_format.space_after = Pt(2)
                        t_perd = doc.add_table(rows=4, cols=4)
                        t_perd.style = 'Table Grid'
                        
                        t_perd.cell(0, 0).merge(t_perd.cell(0, 3)).text = "[X] Controllo Periodico      [ ] Controllo a seguito di riparazione"
                        t_perd.cell(1, 0).merge(t_perd.cell(1, 1)).text = f"Metodo: [{'X' if metodo_cerca=='Diretto' else ' '}] Diretto   [{'X' if metodo_cerca=='Indiretto' else ' '}] Indiretto"
                        t_perd.cell(1, 2).text = "Cercafughe: WIGAN ELD-H (Matr: 21020370BA)"
                        t_perd.cell(1, 3).text = "Sensibilità: 14 g/anno"

                        t_perd.cell(2, 0).text = f"Circuito 1:\n[{'X' if esito_circ1=='Assenza Perdite' else ' '}] Assenza Perdite\n[{'X' if esito_circ1=='Rilevata Perdita' else ' '}] Rilevata"
                        t_perd.cell(2, 1).text = f"Circuito 2:\n[{'X' if esito_circ2=='Assenza Perdite' else ' '}] Assenza Perdite\n[{'X' if esito_circ2=='Rilevata Perdita' else ' '}] Rilevata" if num_circuiti>=2 else "Circuito 2: N/A"
                        t_perd.cell(2, 2).text = f"Circuito 3:\n[{'X' if esito_circ3=='Assenza Perdite' else ' '}] Assenza Perdite\n[{'X' if esito_circ3=='Rilevata Perdita' else ' '}] Rilevata" if num_circuiti>=3 else "Circuito 3: N/A"
                        t_perd.cell(2, 3).text = f"Circuito 4:\n[{'X' if esito_circ4=='Assenza Perdite' else ' '}] Assenza Perdite\n[{'X' if esito_circ4=='Rilevata Perdita' else ' '}] Rilevata" if num_circuiti>=4 else "Circuito 4: N/A"

                        t_perd.cell(3, 0).merge(t_perd.cell(3, 3)).text = f"Note Tecniche / Causa ed Azioni: {note_fgas}\nNome Tecnico: ANTONIO MARTINEZ — Data: {dt_oggi.strftime('%d/%m/%Y')} — Società: CBRE TECHNICAL DIVISION"

                        # Formattazione Font per tutte le tabelle
                        for table in doc.tables:
                            for r_idx, r in enumerate(table.rows):
                                for cell in r.cells:
                                    set_cell_margins(cell, top=60, bottom=60, left=100, right=100)
                                    for p in cell.paragraphs:
                                        p.paragraph_format.space_before = Pt(1)
                                        p.paragraph_format.space_after = Pt(1)
                                        for run in p.runs:
                                            run.font.name = 'Arial'
                                            run.font.size = Pt(8)

                        safe_matr = matricola_str.replace('/', '_')
                        filename_fgas = f"Report_FGAS_{row['marca']}_{safe_matr}.docx"
                        doc.save(filename_fgas)
                        
                        st.session_state[f'dl_fgas_{matricola_str}'] = filename_fgas
                        st.success("Report Ufficiale F-GAS CBRE generato con successo!")
                        st.rerun()

                if st.session_state.get(f'dl_fgas_{matricola_str}'):
                    f_fgas = st.session_state[f'dl_fgas_{matricola_str}']
                    if os.path.exists(f_fgas):
                        with open(f_fgas, "rb") as file_in:
                            st.download_button(
                                label=f"📥 Scarica Modulo Ufficiale Word CBRE ({f_fgas})",
                                data=file_in,
                                file_name=f_fgas,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"btn_dl_fgas_{matricola_str}"
                            )

            # ==========================================
            # TAB 2: RAPPORTINO MANUTENZIONE FILTRI
            # ==========================================
            with tab_filtri:
                with st.form(key=f"form_filtri_{matricola_str}"):
                    st.markdown("##### 🧹 Rapportino Manutenzione Filtri / Ventilo-Convettori")
                    
                    tipo_azione_filtri = st.selectbox("Azione Eseguita", ["Pulizia / Spolveratura Filtri", "Sostituzione Filtri Nuovi", "Segnalato Filtro Da Ordinare"], key=f"azione_f_{matricola_str}")
                    nuovo_stato_filtri = st.selectbox("Stato Filtri Post-Intervento", ["Pulito / Ottimale", "Buono", "Da Sostituire"], key=f"stato_f_{matricola_str}")
                    note_filtri = st.text_input("Note Intervento Filtri", "Pulizia filtri eseguita, ripristinato il corretto flusso d'aria.", key=f"note_f_{matricola_str}")
                    
                    btn_filtri_submit = st.form_submit_button("✅ Salva Stato Filtri & Genera Rapportino Manutenzione")
                    
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
                        doc_f.add_heading('RAPPORTINO MANUTENZIONE ORDINARIA & FILTRI', level=1)
                        doc_f.add_paragraph(f"Data Intervento: {dt_oggi.strftime('%d/%m/%Y %H:%M')}")
                        doc_f.add_paragraph(f"Sito: McArthurGlen Designer Outlet Castel Romano")
                        doc_f.add_paragraph(f"Unità / Negozio: {row['unita']} (Collocazione: {row['collocazione']})")
                        doc_f.add_paragraph("--------------------------------------------------------------------------------")
                        
                        doc_f.add_heading('DATI APPARECCHIATURA', level=2)
                        pf1 = doc_f.add_paragraph()
                        pf1.add_run("Codice Apparecchiatura: ").bold = True
                        pf1.add_run(f"{cod_app_str}\n")
                        pf1.add_run("Marca / Modello: ").bold = True
                        pf1.add_run(f"{row['marca']} {row['modello']}\n")
                        pf1.add_run("Matricola: ").bold = True
                        pf1.add_run(f"{matricola_str}\n")
                        
                        doc_f.add_heading('DETTAGLI INTERVENTO FILTRI', level=2)
                        pf2 = doc_f.add_paragraph()
                        pf2.add_run("Azione Eseguita: ").bold = True
                        pf2.add_run(f"{tipo_azione_filtri}\n")
                        pf2.add_run("Tipologia Filtri: ").bold = True
                        pf2.add_run(f"{row['tipo_filtro']} — Q.tà: {row['quantita_filtri']} pz — Misura: {row['misure_filtri']}\n")
                        pf2.add_run("Stato finale filtri: ").bold = True
                        pf2.add_run(f"{nuovo_stato_filtri.upper()}\n")
                        pf2.add_run("Note Tecniche Operative: ").bold = True
                        pf2.add_run(f"{note_filtri}\n")
                        
                        doc_f.add_heading('TECNICO MANUTENTORE', level=2)
                        pf3 = doc_f.add_paragraph()
                        pf3.add_run("Esecutore: ").bold = True
                        pf3.add_run("ANTONIO MARTINEZ — CBRE GWS Technical Division\n")
                        
                        safe_matr = matricola_str.replace('/', '_')
                        filename_filtri = f"Rapportino_Filtri_{row['unita_base']}_{safe_matr}.docx"
                        doc_f.save(filename_filtri)
                        
                        st.session_state[f'dl_filtri_{matricola_str}'] = filename_filtri
                        st.success("Rapportino Filtri generato con successo!")
                        st.rerun()

                if st.session_state.get(f'dl_filtri_{matricola_str}'):
                    f_filt = st.session_state[f'dl_filtri_{matricola_str}']
                    if os.path.exists(f_filt):
                        with open(f_filt, "rb") as file_in:
                            st.download_button(
                                label=f"📥 Scarica Rapportino Pulizia Filtri ({f_filt})",
                                data=file_in,
                                file_name=f_filt,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"btn_dl_filt_{matricola_str}"
                            )
