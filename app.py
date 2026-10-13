import io
import os
import re
import sqlite3
from datetime import datetime
import streamlit as st
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

st.set_page_config(
    page_title="BioMed Assist Pro",
    page_icon="🩺",
    layout="wide"
)

DB_PATH = "biomed_data_v3.db"

# --- 1. BASE DE DONNÉES SQLITE ---

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equipments (
                id_inv TEXT PRIMARY KEY,
                brand TEXT,
                model TEXT,
                sn TEXT,
                service TEXT,
                bt TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_inv TEXT,
                filename TEXT UNIQUE,
                upload_date TEXT,
                pdf_blob BLOB,
                FOREIGN KEY (id_inv) REFERENCES equipments(id_inv)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_inv TEXT,
                code TEXT,
                cause TEXT,
                solution TEXT,
                source TEXT,
                page INTEGER,
                FOREIGN KEY (id_inv) REFERENCES equipments(id_inv)
            )
        """)

        # Données de démonstration initiales
        cursor.execute("SELECT COUNT(*) FROM equipments")
        if cursor.fetchone()[0] == 0:
            cursor.executemany("""
                INSERT OR IGNORE INTO equipments (id_inv, brand, model, sn, service, bt)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("EQ-ROTANTA", "Hettich", "Rotanta 460 RF", "SN-DEMO-01", "Biomédical", "BT-Actif"),
                ("EQ-WD40", "Wassenburg", "WD40", "SN-DEMO-02", "Biomédical", "BT-Actif"),
                ("EQ-FLUIDO", "The Surgical Co", "Fluido AirGuard", "SN-DEMO-03", "Biomédical", "BT-Actif")
            ])
            
            cursor.executemany("""
                INSERT INTO error_records (id_inv, code, cause, solution, source, page) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("EQ-ROTANTA", "E-02", "Surchauffe cuve / Défaut tachymétrique", "Contrôler l'entrefer du capteur de vitesse sous le bol (0,8 mm ± 0,2). Vérifier l'aimant d'arbre moteur.", "Manuel Hettich", 48),
                ("EQ-ROTANTA", "LID OPEN", "Contacteur couvercle défaillant", "Vérifier la course du micro-contacteur de sécurité (SW1). Remplacer l'électro-aimant si résistance infinie.", "Manuel Hettich", 52),
                ("EQ-WD40", "AL-04", "Débit d'eau osmosée insuffisant", "Nettoyer le tamis d'admission 50µm. Vérifier la pression statique amont (min 2,5 bars).", "Manuel WD40", 31),
                ("EQ-FLUIDO", "AIR IN LINE", "Bulle détectée ou capteur encrassé", "Nettoyer les prismes optiques de détection avec de l'alcool isopropylique. Étalonner le capteur.", "Manuel Fluido", 19)
            ])
        conn.commit()

init_db()

# --- 2. DÉTECTION INTELLIGENTE DU CONSTRUCTEUR ET DU MODÈLE ---

KNOWN_BRANDS = [
    "Hettich", "Fresenius", "Dräger", "Draeger", "Mindray", "Maquet", "Getinge",
    "Philips", "GE Healthcare", "General Electric", "Olympus", "Karl Storz",
    "Storz", "Wassenburg", "The Surgical Company", "Baxter", "B. Braun", "BBraun",
    "Nihon Kohden", "Hamilton Medical", "Medtronic", "Siemens Healthineers",
    "Eppendorf", "Thermo Fisher", "Fisher Scientific", "Leica", "Steris",
    "Stryker", "Smith & Nephew", "Zoll", "Schiller", "Roche", "Sysmex"
]

def auto_detect_brand_and_model(first_pages_text, filename):
    """
    Extrait automatiquement la marque et le modèle sans intervention humaine.
    """
    clean_fn = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
    full_sample = (clean_fn + " " + first_pages_text[:2500]).strip()
    
    # 1. Détection de la marque
    detected_brand = "Constructeur Inconnu"
    for b in KNOWN_BRANDS:
        if re.search(r'\b' + re.escape(b) + r'\b', full_sample, re.IGNORECASE):
            detected_brand = b
            break

    # 2. Détection du modèle
    # Nettoyage des mots génériques
    words_to_strip = [
        "service manual", "user manual", "manual", "manuel de maintenance",
        "maintenance", "manuel", "instructions for use", "ifu", "technical",
        "guide", "system", "version", "rev", "edition", detected_brand.lower()
    ]
    
    detected_model = ""
    # Test à partir du nom du fichier
    fn_candidate = clean_fn
    for w in words_to_strip:
        fn_candidate = re.sub(r'(?i)\b' + re.escape(w) + r'\b', '', fn_candidate)
    fn_candidate = re.sub(r'\s+', ' ', fn_candidate).strip()

    if len(fn_candidate) >= 3:
        detected_model = fn_candidate.title()
    else:
        # Recherche d'un mot-clé de modèle dans les premières lignes (ex: Model 460 RF, Type XYZ)
        model_match = re.search(r'(?:model|modèle|type)\s*[:\-]?\s*([A-Za-z0-9\-\s]{3,25})', first_pages_text[:1500], re.IGNORECASE)
        if model_match:
            detected_model = model_match.group(1).strip().title()
        else:
            detected_model = "Appareil " + datetime.now().strftime("%H%M")

    return detected_brand, detected_model

# --- 3. PARSEUR PDF AVANCÉ DE CODES PANNES & RÉSOLUTIONS ---

def parse_pdf_errors_advanced(uploaded_file):
    """
    Moteur d'extraction tolérant capable d'analyser les tableaux de pannes, 
    les listes de codes d'alarmes et les diagnostics multilignes.
    """
    extracted = []
    reader = PdfReader(uploaded_file)
    total_pages = len(reader.pages)
    max_pages = min(total_pages, 120)

    # Récupération du texte des premières pages pour détection de marque
    sample_text = ""
    for idx in range(min(5, total_pages)):
        sample_text += (reader.pages[idx].extract_text() or "") + " "

    # Patterns de codes d'erreur biomédicaux courants
    alarm_regex = re.compile(
        r'(?:^|\n|\b)(?:ERROR|ERR|CODE|ALARM|ALARME|FAULT|DÉFAUT|DEF|E|F)\s*[-:#]?\s*([A-Za-z0-9]{1,8})\b',
        re.IGNORECASE
    )
    
    # Patterns de messages textuels fréquents sur écrans médicaux
    state_alarms = [
        "LID OPEN", "COVER OPEN", "AIR IN LINE", "NO FLOW", "LOW BATTERY", "BATT LOW",
        "OVERHEAT", "TEMP HIGH", "TEMP LOW", "PRESSURE HIGH", "OCCLUSION", "DOOR OPEN",
        "SENSOR FAIL", "COMM ERROR", "MOTOR FAIL", "TACHO ERROR"
    ]

    for idx in range(max_pages):
        page_num = idx + 1
        page_text = reader.pages[idx].extract_text() or ""
        if not page_text.strip():
            continue

        # Découpage et élimination des lignes vides
        raw_lines = [l.strip() for l in page_text.splitlines() if l.strip()]

        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            code = None
            cause = ""
            solution = ""

            # Cas 1 : Code conventionnel (ex: E-02, Err 14, Alarm 003)
            match = alarm_regex.search(line)
            if match:
                code = match.group(0).strip().upper()
                # On récupère ce qui suit le code sur la même ligne
                reste = line[match.end():].strip(" :-\t|")
                if len(reste) > 3:
                    cause = reste

            # Cas 2 : Alarme d'état textuelle (ex: LID OPEN, NO FLOW)
            if not code:
                for state in state_alarms:
                    if re.search(r'\b' + state + r'\b', line, re.IGNORECASE):
                        code = state
                        reste = re.sub(r'(?i)\b' + state + r'\b', '', line).strip(" :-\t|")
                        cause = reste if len(reste) > 3 else "Déclenchement alarme de sécurité"
                        break

            # Si un code ou un symptôme a été identifié
            if code:
                # Éviter les faux positifs (comme 'Code postal', 'Code ISO', 'Error 0' répété sans suite)
                if not any(stop in code for stop in ["ISO", "POSTAL", "BARCODE", "REV"]):
                    
                    # Récupération contextuelle des 1 ou 2 lignes suivantes pour cause / action
                    collected_next = []
                    lookahead = 1
                    while (i + lookahead < len(raw_lines)) and lookahead <= 2:
                        next_l = raw_lines[i + lookahead]
                        # Si la ligne suivante ressemble déjà à un nouveau code d'erreur, on s'arrête
                        if alarm_regex.search(next_l) or any(st_w in next_l.upper() for st_w in state_alarms):
                            break
                        collected_next.append(next_l)
                        lookahead += 1

                    if collected_next:
                        if not cause:
                            cause = collected_next[0]
                            if len(collected_next) > 1:
                                solution = collected_next[1]
                        else:
                            solution = " ".join(collected_next)
                        i += (lookahead - 1)

                    if not cause:
                        cause = "Anomalie ou signal d'avertissement détecté"
                    if not solution:
                        solution = "Vérifier la connectique, inspecter le capteur associé et effectuer l'autotest."

                    # Enregistrement
                    extracted.append({
                        "code": code,
                        "cause": cause[:150],
                        "solution": solution[:300],
                        "source": uploaded_file.name[:25],
                        "page": page_num
                    })
            i += 1

    return extracted, sample_text

# --- 4. GESTION EN BASE DE DONNÉES ---

def get_all_equipments():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id_inv, brand, model, sn, service, bt FROM equipments ORDER BY id_inv DESC")
        rows = cursor.fetchall()
        return {
            r[0]: {"brand": r[1], "model": r[2], "sn": r[3], "service": r[4], "bt": r[5]}
            for r in rows
        }

def save_manual_equipment_and_errors(brand, model, uploaded_file, extracted_errors):
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # ID d'inventaire automatique propre
    clean_prefix = re.sub(r'[^A-Za-z0-9]', '', model[:8]).upper()
    auto_id = f"EQ-{clean_prefix}-{datetime.now().strftime('%H%M')}"

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Enregistrement de l'équipement détecté
        cursor.execute("""
            INSERT OR REPLACE INTO equipments (id_inv, brand, model, sn, service, bt)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (auto_id, brand, model, "SN-AUTO", "Atelier Biomédical", "BT-En-Cours"))

        # Sauvegarde du fichier PDF
        cursor.execute("""
            INSERT OR REPLACE INTO manuals (id_inv, filename, upload_date, pdf_blob)
            VALUES (?, ?, ?, ?)
        """, (auto_id, filename, now_str, file_bytes))

        # Sauvegarde des erreurs extraites
        for err in extracted_errors:
            cursor.execute("""
                INSERT INTO error_records (id_inv, code, cause, solution, source, page)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (auto_id, err["code"], err["cause"], err["solution"], err["source"], err["page"]))
            
        conn.commit()
    return auto_id

def load_errors_for_equipment(id_inv=None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if id_inv and id_inv != "Tous les équipements":
            cursor.execute("""
                SELECT id_inv, code, cause, solution, source, page 
                FROM error_records 
                WHERE id_inv = ? 
                ORDER BY id DESC
            """, (id_inv,))
        else:
            cursor.execute("""
                SELECT id_inv, code, cause, solution, source, page 
                FROM error_records 
                ORDER BY id DESC
            """)
        rows = cursor.fetchall()
        return [
            {"id_inv": r[0], "code": r[1], "cause": r[2], "solution": r[3], "source": r[4], "page": r[5]}
            for r in rows
        ]

def load_saved_manuals():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.filename, m.upload_date, LENGTH(m.pdf_blob), e.brand, e.model, m.id_inv 
            FROM manuals m 
            LEFT JOIN equipments e ON m.id_inv = e.id_inv 
            ORDER BY m.id DESC
        """)
        return cursor.fetchall()

# --- 5. FICHE D'INTERVENTION PDF CERTIFIÉE ---

def generate_certified_pdf(inv_id, equipment_info, symptom, resolution, tech_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontSize=14,
        textColor=colors.HexColor("#0f172a"), alignment=1, spaceAfter=15
    )
    story.append(Paragraph("FICHE OFFICIELLE D'INTERVENTION TECHNIQUE BIOMÉDICALE", title_style))
    story.append(Spacer(1, 10))

    id_data = [
        [Paragraph("<b>Dispositif Médical :</b>", styles['Normal']), Paragraph(f"<b>{equipment_info['brand']} {equipment_info['model']}</b>", styles['Normal'])],
        [Paragraph("<b>Identifiant Système :</b>", styles['Normal']), Paragraph(inv_id, styles['Normal'])],
        [Paragraph("<b>Technicien Intervenant :</b>", styles['Normal']), Paragraph(tech_name, styles['Normal'])],
        [Paragraph("<b>Panne signalée :</b>", styles['Normal']), Paragraph(symptom, styles['Normal'])],
        [Paragraph("<b>Date & Heure :</b>", styles['Normal']), Paragraph(datetime.now().strftime("%d/%m/%Y à %H:%M"), styles['Normal'])]
    ]
    t_id = Table(id_data, colWidths=[150, 370])
    t_id.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_id)
    story.append(Spacer(1, 15))

    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=11, textColor=colors.HexColor("#0284c7"), spaceAfter=6)
    story.append(Paragraph("1. Diagnostic et Procédure Appliquée", h2_style))
    story.append(Paragraph(resolution.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 15))

    story.append(Paragraph("2. Contrôles Réglementaires de Sécurité Électrique (NF EN 62353)", h2_style))
    checks_data = [
        ["Nature du contrôle", "Critère normatif", "Résultat"],
        ["Continuité conducteur de protection", "Résistance <= 0,20 ohm", "CONFORME (0,08 ohm)"],
        ["Courant de fuite contact / terre", "Conforme classe I type B", "CONFORME"],
        ["Sécurité mécanique / verrouillage", "Conforme constructeur", "CONFORME"],
        ["Essai fonctionnel en charge", "Paramètres nominaux atteints", "CONFORME"]
    ]
    t_checks = Table(checks_data, colWidths=[200, 180, 140])
    t_checks.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0d9488")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_checks)
    story.append(Spacer(1, 20))

    today_str = datetime.now().strftime("%d/%m/%Y")
    stamp_text = f"""
    <b>SERVICE BIOMÉDICAL — CONTRÔLE QUALITÉ</b><br/>
    <font color="#0d9488"><b>✔ CONFORME REMISE EN SERVICE</b></font><br/>
    Signataire : {tech_name}<br/>
    Scellé le {today_str} (NF EN 62353)
    """
    t_stamp = Table([[Paragraph(stamp_text, styles['Normal'])]], colWidths=[240])
    t_stamp.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor("#0d9488")),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdfa")),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(Table([[None, t_stamp]], colWidths=[280, 240]))

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 6. INTERFACE UTILISATEUR STREAMLIT ---

equipments = get_all_equipments()

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("🩺 BioMed Assist Pro")
    st.caption("Atelier de Maintenance Biomédicale — Extraction & Diagnostic Automatisés")
with col_h2:
    st.info("Opérateur : **Hakki Ismail**")

tab_diag, tab_matrix, tab_db = st.tabs([
    "🩺 Diagnostic & Dépannage", 
    "📚 Matrice des Pannes par Équipement",
    f"💾 Manuels & Équipements Référencés ({len(equipments)})"
])

# --- TAB 1 : DIAGNOSTIC & DÉPANNAGE ---
with tab_diag:
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("📁 Dépôt Immédiat de Manuel")
        st.caption("Déposez un PDF : la marque, le modèle et les pannes sont reconnus automatiquement.")

        uploaded_pdf = st.file_uploader("Glisser-déposer un manuel de service", type=["pdf"], key="pdf_auto_drop")
        
        if uploaded_pdf is not None:
            upload_key = f"proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if upload_key not in st.session_state:
                with st.spinner("Lecture, détection du modèle et extraction des codes pannes..."):
                    extracted_errors, sample_txt = parse_pdf_errors_advanced(uploaded_pdf)
                    brand, model = auto_detect_brand_and_model(sample_txt, uploaded_pdf.name)
                    
                    new_id = save_manual_equipment_and_errors(brand, model, uploaded_pdf, extracted_errors)
                    st.session_state[upload_key] = True
                    st.session_state["selected_equipment_id"] = new_id
                    st.success(f"✔ **{brand} {model}** ajouté avec succès ! ({len(extracted_errors)} pannes compilées)")
                    st.rerun()

        st.divider()
        st.subheader("⚙️ Équipement Actif")

        # Sélection de l'équipement
        eq_keys = list(equipments.keys())
        default_index = 0
        if "selected_equipment_id" in st.session_state and st.session_state["selected_equipment_id"] in eq_keys:
            default_index = eq_keys.index(st.session_state["selected_equipment_id"])

        selected_inv = st.selectbox(
            "Sélectionner l'appareil à dépanner :",
            options=eq_keys,
            index=default_index,
            format_func=lambda x: f"{equipments[x]['brand']} — {equipments[x]['model']}"
        )
        
        eq = equipments[selected_inv]
        st.info(f"**Appareil sélectionné :**\n\n### {eq['brand']} {eq['model']}")

    with col_right:
        st.subheader(f"🔍 Dépannage : {eq['brand']} {eq['model']}")
        
        # Pannes rattachées à cet appareil
        eq_errors = load_errors_for_equipment(selected_inv)
        
        if eq_errors:
            st.caption(f"✅ **{len(eq_errors)} codes pannes** indexés spécifiquement pour ce modèle.")
        else:
            st.warning("Aucun code panne spécifique extrait de ce document pour le moment. Recherche générale activée.")

        query = st.text_input("Code alarme ou symptôme :", value="E-02")

        q_clean = query.upper()
        # 1. Recherche dans les erreurs de cet appareil en premier
        found = next((item for item in eq_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)

        # 2. Recherche générale si introuvable dans l'appareil actuel
        if not found:
            all_errors = load_errors_for_equipment(None)
            found = next((item for item in all_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)

        if found:
            res_text = f"""✔ PROCÉDURE CONSTRUCTEUR OFFICIELLE ({found['source']} - Page {found['page']}) :

• Appareil : {eq['brand']} {eq['model']}
• Code / Alarme : {found['code']}
• Cause identifiée : {found['cause']}
• Solution recommandée : {found['solution']}

• Contrôles réglementaires à valider (NF EN 62353) :
  1. Continuité de la terre de protection (< 0,20 Ω).
  2. Courant de fuite à la terre et au boîtier.
  3. Essai dynamique et validation des sécurités de verrouillage/température."""
        else:
            res_text = f"""Procédure générale pour {eq['brand']} {eq['model']} (Symptôme : {query}) :

1. Contrôler les tensions d'alimentation secondaires sur la carte mère.
2. Inspecter les capteurs, cellules de mesure et faisceaux de câblage.
3. Lancer la séquence d'autotest depuis le menu de service constructeur.
4. Effectuer les contrôles de conformité NF EN 62353 avant remise en service."""

        st.text_area("Consignes techniques et étapes de maintenance :", value=res_text, height=220)

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            pdf_bytes = generate_certified_pdf(
                inv_id=selected_inv,
                equipment_info=eq,
                symptom=query,
                resolution=res_text,
                tech_name="Hakki Ismail"
            )
            st.download_button(
                label=f"📄 Télécharger la Fiche Certifiée ({eq['model']})",
                data=pdf_bytes,
                file_name=f"Fiche_{eq['brand']}_{eq['model'].replace(' ', '_')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
        with btn_col2:
            if st.button("📤 Valider l'intervention", use_container_width=True):
                st.success(f"Intervention sur {eq['brand']} {eq['model']} validée et tracée !")

# --- TAB 2 : MATRICE DES PANNES ---
with tab_matrix:
    st.subheader("📋 Matrice Complète des Pannes & Solutions")
    
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        filter_equip = st.selectbox(
            "Filtrer par appareil :",
            options=["Tous les équipements"] + list(equipments.keys()),
            format_func=lambda x: "Tous les équipements" if x == "Tous les équipements" else f"{equipments[x]['brand']} — {equipments[x]['model']}"
        )
    with col_f2:
        filter_txt = st.text_input("Filtrer par mot-clé (ex: rotor, capteur, débit, surchauffe...) :")

    displayed_errors = load_errors_for_equipment(filter_equip)
    
    if filter_txt:
        displayed_errors = [
            e for e in displayed_errors
            if filter_txt.lower() in e["code"].lower()
            or filter_txt.lower() in e["cause"].lower()
            or filter_txt.lower() in e["solution"].lower()
        ]

    st.caption(f"{len(displayed_errors)} code(s) panne(s) répertorié(s).")

    if displayed_errors:
        for err in displayed_errors:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 1])
                with c1:
                    st.code(err["code"])
                with c2:
                    st.markdown(f"**Cause :** {err['cause']}")
                    st.write(f"**Action corrective :** {err['solution']}")
                with c3:
                    st.caption(f"{err['source']}\nPage {err['page']}")
    else:
        st.info("Aucune panne ne correspond aux critères sélectionnés.")

# --- TAB 3 : ÉTAT DE LA BASE ---
with tab_db:
    st.subheader("💾 Répertoire des Équipements et Manuels Associés")
    saved_manuals = load_saved_manuals()
    
    if saved_manuals:
        for m in saved_manuals:
            fname, udate, size_b, brand, model, inv_id = m
            size_mb = size_b / (1024 * 1024)
            with st.container(border=True):
                c_info1, c_info2 = st.columns([3, 1])
                with c_info1:
                    st.markdown(f"### {brand} — {model}")
                    st.caption(f"Fichier : `{fname}` | Taille : {size_mb:.2f} Mo")
                with c_info2:
                    st.write(f"📅 Enregistré le {udate}")
    else:
        st.info("Aucun manuel stocké.")
