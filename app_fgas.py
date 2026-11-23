def genera_report_docx(
    row,
    mod_edit,
    matr_edit,
    gas_edit,
    targa_edit,
    stato_edit,
    n_circ_edit,
    c1_edit,
    c2_edit,
    co2_c1_calc,
    co2_c2_calc,
    carica_tot_calc,
    co2_tot_calc,
    oggi,
    target_dir=OUTPUT_DIR,
    data_intervento_custom=None,
    scadenza_custom=None,
):
  os.makedirs(target_dir, exist_ok=True)
  if not os.path.exists(TEMPLATE_FGAS_PATH):
    return None, "Template Word non trovato."

  doc = Document(TEMPLATE_FGAS_PATH)
  data_str = (
      data_intervento_custom
      if data_intervento_custom
      else oggi.strftime("%d/%m/%Y")
  )
  scadenza_str = (
      scadenza_custom if scadenza_custom else str(row.get("scadenza_verifica", ""))
  )

  mappa = {
      "{{UNITA}}": str(row.get("nr_unita", "")),
      "{{MARCA}}": str(row.get("marca", "")),
      "{{MODELLO}}": mod_edit,
      "{{MATRICOLA}}": matr_edit,
      "{{TIPO_GAS}}": gas_edit,
      "{{CARICA_KG}}": f"{carica_tot_calc:.2f}",
      "{{CARICA_KG 1}}": f"{c1_edit:.2f}",
      "{{CARICA_KG 2}}": f"{c2_edit:.2f}" if int(n_circ_edit) == 2 else "",
      "{{CO2_EQ}}": f"{co2_tot_calc:.2f}",
      "{{CO2_EQ 1}}": f"{co2_c1_calc:.2f}",
      "{{CO2_EQ 2}}": f"{co2_c2_calc:.2f}" if int(n_circ_edit) == 2 else "",
      "{{CIRQUITTI}}": str(n_circ_edit),
      "{{ CIRQUITTI}}": str(n_circ_edit),
      "{{COD_APP}}": targa_edit,
      "{{DATA_INTERVENTO}}": data_str,
      "{{SCADENZA_VERIFICA}}": scadenza_str,
      "{{ESITO_CIRC1}}": "ASSENZA PERDITE",
  }

  for p in doc.paragraphs:
    for k, v in mappa.items():
      if k in p.text:
        p.text = p.text.replace(k, str(v))

  firma_inserita = False
  for t in doc.tables:
    for r in t.rows:
      for c in r.cells:
        if "{{FIRMA}}" in c.text:
          for p in c.paragraphs:
            if "{{FIRMA}}" in p.text:
              p.text = p.text.replace("{{FIRMA}}", "")
          if os.path.exists(FIRMA_PATH):
            _inserisci_firma_in_cella(c, FIRMA_PATH)
            firma_inserita = True
          continue

        for p in c.paragraphs:
          for k, v in mappa.items():
            if k in p.text:
              p.text = p.text.replace(k, str(v))

  if not firma_inserita and os.path.exists(FIRMA_PATH):
    for t in doc.tables:
      for r in t.rows:
        for c in r.cells:
          if c.text.strip().lower().startswith("firma"):
            _inserisci_firma_in_cella(c, FIRMA_PATH)
            firma_inserita = True
            break
        if firma_inserita:
          break
      if firma_inserita:
        break

  nome_file = (
      f"Report_FGAS_{sanitize_filename(row.get('marca', ''))}_{sanitize_filename(mod_edit)}"
      f"_Unita_{sanitize_filename(row.get('nr_unita', ''))}.docx"
  )
  out_file = os.path.join(target_dir, nome_file)
  doc.save(out_file)
  return out_file, None
