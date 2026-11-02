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
        # Ricostruzione pulita della tabella per allineare le 20 colonne
        cursor.execute("DROP TABLE IF EXISTS macchine_hvac")

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

        # Inizializzazione dati da Excel se il file esiste
        if os.path.exists(EXCEL_PATH):
            df_excel = pd.read_excel(EXCEL_PATH, sheet_name="Master F-GAS 2026")
            for _, row in df_excel.iterrows():
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

                # Inserimento allineato a 20 parametri esatti
                cursor.execute("""
                    INSERT OR REPLACE INTO macchine_hvac 
                    (id_macchina, nr_unita, marca, modello_matricola, ubicazione_negozio, quadro_elettrico, potenza_kw, n_circuiti, refrigerante, codice_targa, ultima_verifica, scadenza_verifica, macro_area, tonn_co2_eq, carica_kg, f_gas_attivo, data_scadenza_dt, operatore_assegnato, filtro_dimensioni, filtro_quantita)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    id_unic,                    # 1. id_macchina
                    unita_str,                  # 2. nr_unita
                    marca,                      # 3. marca
                    mod_mat,                    # 4. modello_matricola
                    zona,                       # 5. ubicazione_negozio
                    "Quadro Generale",          # 6. quadro_elettrico
                    float(carica_kg * 1.2),     # 7. potenza_kw
                    1,                          # 8. n_circuiti
                    refrigerante,               # 9. refrigerante
                    cod_app,                    # 10. codice_targa
                    "01/01/2026",               # 11. ultima_verifica
                    "01/01/2027",               # 12. scadenza_verifica
                    "MCARTHUR_RM",              # 13. macro_area
                    float(tonn_co2),            # 14. tonn_co2_eq
                    float(carica_kg),           # 15. carica_kg
                    "S",                        # 16. f_gas_attivo
                    "2027-01-01",               # 17. data_scadenza_dt
                    operatore,                  # 18. operatore_assegnato
                    "",                         # 19. filtro_dimensioni
                    1                           # 20. filtro_quantita
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
    for p in doc
