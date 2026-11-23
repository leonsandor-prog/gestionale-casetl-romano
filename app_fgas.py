def render_scheda_unita(row, prefix, oggi, expanded=False):
    key_id = f"{prefix}_{sanitize_filename(row['id_macchina'])}"
    stato = row["stato_compilazione"]
    pallino = "🟢" if stato == "Completato" else "🟡"

    n_circ_db = 2 if int(_safe_float(row.get("n_circuiti"), 1)) == 2 else 1
    carica_db = _safe_float(row.get("carica_kg"), 0.0)
    co2_db = _safe_float(row.get("tonn_co2_eq"), 0.0)
    c1_db = _safe_float(
        row.get("carica_circ1"),
        carica_db / 2.0 if n_circ_db == 2 else carica_db,
    )
    c2_db = _safe_float(
        row.get("carica_circ2"), carica_db / 2.0 if n_circ_db == 2 else 0.0
    )
    data_valida_str, _, _ = normalizza_data_anno_corrente(
        row.get("scadenza_verifica"), oggi.year
    )
    if not data_valida_str:
        data_valida_str = oggi.strftime("%d/%m/%Y")

    with st.expander(
        f"{pallino} Unità {row['nr_unita']} — {row['marca']} {row['modello']} |"
        f" Circuiti: `{n_circ_db}` | Data Verifica: `{data_valida_str}` |"
        f" Targa: `{row['codice_targa']}`",
        expanded=expanded,
    ):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Dati Impianto & Identificativi**")
            st.write(f"- **Collocazione:** `{row['collocazione']}`")
            st.write(f"- **Matricola:** `{row['matricola']}`")
            st.write(f"- **Cod. Apparecchiatura:** `{row['codice_targa']}`")
            st.write(f"- **Data Verifica (Anno Corrente):** `{data_valida_str}`")
            st.write(f"- **N° Circuiti registrati:** `{n_circ_db}`")
        with c2:
            st.markdown("**Parametri F-GAS**")
            st.write(f"- **Refrigerante:** `{row['refrigerante']}`")
            st.write(f"- **Carica Totale:** `{carica_db:.2f} kg`")
            st.write(f"- **Tonn. CO2 Eq Totale:** `{co2_db:.2f} t`")

        st.divider()

        n_circ_edit = st.selectbox(
            "Numero circuiti impianto (1 = singolo, 2 = doppio circuito)",
            options=[1, 2],
            index=1 if n_circ_db == 2 else 0,
            key=f"ncirc_{key_id}",
        )

        state_key_nc = f"last_ncirc_{key_id}"
        if st.session_state.get(state_key_nc) != n_circ_edit:
            if n_circ_edit == 2:
                if c2_db > 0:
                    st.session_state[f"c1_val_{key_id}"] = round(c1_db, 2)
                    st.session_state[f"c2_val_{key_id}"] = round(c2_db, 2)
                else:
                    meta = round(carica_db / 2.0, 2)
                    st.session_state[f"c1_val_{key_id}"] = meta
                    st.session_state[f"c2_val_{key_id}"] = round(
                        carica_db - meta, 2
                    )
            else:
                st.session_state[f"c1_val_{key_id}"] = round(carica_db, 2)
                st.session_state[f"c2_val_{key_id}"] = 0.0
            st.session_state[state_key_nc] = n_circ_edit

        with st.form(key=f"form_{key_id}"):
            st.markdown("##### ✏️ Verifica e Modifica Dati in Campo")
            nc1, nc2, nc3 = st.columns(3)
            with nc1:
                mod_edit = st.text_input(
                    "Modello", value=str(row["modello"]), key=f"mod_{key_id}"
                )
                matr_edit = st.text_input(
                    "Matricola",
                    value=str(row["matricola"]),
                    key=f"matr_{key_id}",
                )
            with nc2:
                gas_lista = [
                    "R-410A",
                    "R-407C",
                    "R-32",
                    "R-134a",
                    "R-449A",
                    "R-404A",
                    "R-507A",
                ]
                idx_gas = (
                    gas_lista.index(row["refrigerante"])
                    if row["refrigerante"] in gas_lista
                    else 0
                )
                gas_edit = st.selectbox(
                    "Refrigerante",
                    gas_lista,
                    index=idx_gas,
                    key=f"gas_{key_id}",
                )
                targa_edit = st.text_input(
                    "Codice Apparecchiatura (Targa)",
                    value=str(row["codice_targa"]),
                    key=f"targa_{key_id}",
                )
            with nc3:
                stato_edit = st.selectbox(
                    "Stato Lavorazione",
                    ["Da Lavorare", "Completato"],
                    index=0 if stato == "Da Lavorare" else 1,
                    key=f"st_{key_id}",
                )
                st.caption(
                    f"GWP applicato ({gas_edit}): **{get_gwp(gas_edit):.0f}**"
                )

            st.markdown(
                "**Carica Refrigerante per Circuito e Calcolo Automatico"
                " Tonn. CO2 Eq**"
            )
            if n_circ_edit == 2:
                cc1, cc2 = st.columns(2)
                with cc1:
                    c1_edit = st.number_input(
                        "Carica Circuito 1 (kg)",
                        min_value=0.0,
                        step=0.1,
                        format="%.2f",
                        value=float(
                            st.session_state.get(f"c1_val_{key_id}", c1_db)
                        ),
                        key=f"in_c1_{key_id}",
                    )
                    co2_c1_calc = calcola_co2_tonnellate(c1_edit, gas_edit)
                    st.info(f"Tonn. CO2 Eq Circuito 1: **{co2_c1_calc:.2f} t**")
                with cc2:
                    c2_edit = st.number_input(
                        "Carica Circuito 2 (kg)",
                        min_value=0.0,
                        step=0.1,
                        format="%.2f",
                        value=float(
                            st.session_state.get(f"c2_val_{key_id}", c2_db)
                        ),
                        key=f"in_c2_{key_id}",
                    )
                    co2_c2_calc = calcola_co2_tonnellate(c2_edit, gas_edit)
                    st.info(f"Tonn. CO2 Eq Circuito 2: **{co2_c2_calc:.2f} t**")
            else:
                c1_edit = st.number_input(
                    "Carica Circuito 1 (kg)",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f",
                    value=float(
                        st.session_state.get(f"c1_val_{key_id}", carica_db)
                    ),
                    key=f"in_c1_{key_id}",
                )
                c2_edit = 0.0
                co2_c1_calc = calcola_co2_tonnellate(c1_edit, gas_edit)
                co2_c2_calc = 0.0
                st.info(f"Tonn. CO2 Eq Circuito 1: **{co2_c1_calc:.2f} t**")

            carica_tot_calc = round(float(c1_edit) + float(c2_edit), 2)
            co2_tot_calc = round(float(co2_c1_calc) + float(co2_c2_calc), 2)
            st.markdown(
                "**Riepilogo automatico:** Carica Totale ="
                f" **`{carica_tot_calc:.2f} kg`** | Tonn. CO2 Eq Totale ="
                f" **`{co2_tot_calc:.2f} t`**"
            )

            btn_aggiorna = st.form_submit_button(
                "💾 Salva su DB & Excel + Genera Rapportino F-GAS (Firmato)"
            )

            if btn_aggiorna:
                st.session_state[f"c1_val_{key_id}"] = float(c1_edit)
                st.session_state[f"c2_val_{key_id}"] = float(c2_edit)

                conn_up = sqlite3.connect(DB_PATH, timeout=10.0)
                cur_up = conn_up.cursor()
                cur_up.execute(
                    """
                    UPDATE macchine_hvac
                    SET modello = ?, matricola = ?, refrigerante = ?, carica_kg = ?, tonn_co2_eq = ?, codice_targa = ?, stato_compilazione = ?,
                        n_circuiti = ?, carica_circ1 = ?, carica_circ2 = ?, co2_circ1 = ?, co2_circ2 = ?
                    WHERE id_macchina = ?
                    """,
                    (
                        mod_edit,
                        matr_edit,
                        gas_edit,
                        carica_tot_calc,
                        co2_tot_calc,
                        targa_edit,
                        stato_edit,
                        int(n_circ_edit),
                        float(c1_edit),
                        float(c2_edit),
                        float(co2_c1_calc),
                        float(co2_c2_calc),
                        row["id_macchina"],
                    ),
                )
                conn_up.commit()
                conn_up.close()

                ok_xl, msg_xl = salva_su_excel(
                    dict(row),
                    int(n_circ_edit),
                    c1_edit,
                    c2_edit,
                    co2_c1_calc,
                    co2_c2_calc,
                    carica_tot_calc,
                    co2_tot_calc,
                    mod_edit,
                    matr_edit,
                    gas_edit,
                    targa_edit,
                    stato_edit,
                )

                out_file, err_doc = genera_report_docx(
                    row,
                    mod_edit,
                    matr_edit,
                    gas_edit,
                    targa_edit,
                    stato_edit,
                    int(n_circ_edit),
                    c1_edit,
                    c2_edit,
                    co2_c1_calc,
                    co2_c2_calc,
                    carica_tot_calc,
                    co2_tot_calc,
                    oggi,
                    data_intervento_custom=data_valida_str,
                    scadenza_custom=data_valida_str,
                )
                if out_file:
                    st.session_state[f"last_generated_{key_id}"] = out_file

                if ok_xl:
                    st.success(
                        f"Salvato su DB e Excel ({msg_xl}) — Rapportino"
                        " generato!"
                    )
                else:
                    st.warning(f"Salvato su DB, ma avviso Excel: {msg_xl}")
                if err_doc:
                    st.error(err_doc)

        ultimo_docx = st.session_state.get(f"last_generated_{key_id}")
        if ultimo_docx and os.path.exists(ultimo_docx):
            with open(ultimo_docx, "rb") as f_docx:
                st.download_button(
                    label="⬇️ Scarica Rapportino .docx generato",
                    data=f_docx.read(),
                    file_name=os.path.basename(ultimo_docx),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    key=f"dl_{key_id}",
                )
