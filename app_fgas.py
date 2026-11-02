def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Creazione tabella impianti se non esiste
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
    
    # Inserisce un paio di unità di prova se la tabella è vuota
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
