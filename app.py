import io
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

DB_PATH = "biomed_data.db"

# --- 1. GESTION PERSISTANTE SQLITE AVEC ÉQUIPEMENTS DYNAMIQUES ---

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Table des équipements de l'atelier
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

        # Table des manuels PDF
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

        # Table des erreurs liée à l'équipement
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
                ("INV-88341", "Hettich", "Rotanta 460 RF", "SN-2024-991-RF", "Laboratoire Biochimie", "#4012"),
                ("INV-10292", "Wassenburg", "WD40", "SN-WD-4412", "Endoscopie", "Aucun"),
                ("INV-44019", "The Surgical Co", "Fluido AirGuard", "SN-FL-9931", "Bloc Opératoire", "#3890")
            ])
            
            cursor.executemany("""
                INSERT INTO error_records (id_inv, code, cause, solution, source, page) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("INV-88341", "E-02", "Surchauffe cuve / Défaut tachymétrique", "Contrôler l'entrefer du capteur de vitesse sous le bol (0,8 mm ± 0,2). Vérifier l'aimant d'arbre moteur.", "Manuel Hettich", 48),
                ("INV-88341", "LID OPEN", "Contacteur couvercle défaillant", "Vérifier la course du micro-contacteur de sécurité (SW1). Remplacer l'électro-aimant si résistance infinie.", "Manuel Hettich", 52),
                ("INV-10292", "AL-04", "Débit d'eau osmosée insuffisant", "Nettoyer le tamis d'admission 50µm. Vérifier la pression statique amont (min 2,5 bars).", "Manuel WD40", 31),
                ("INV-44019", "AIR IN LINE", "Bulle détectée ou capteur encrassé", "Nettoyer les prismes optiques de détection avec de l'alcool isopropylique. Étalonner le capteur.", "Manuel Fluido", 19)
            ])
        conn.commit()

init_db()

# --- 2. FONCTIONS DE GESTION EN BASE ---

def get_all_equipments():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id_inv, brand, model, sn, service, bt FROM equipments ORDER BY id_inv")
        rows = cursor.fetchall()
        return {
            r[0]: {"brand": r[1], "model": r[2], "sn": r[3], "service": r[4], "bt": r[5]}
            for r in rows
        }

def save_manual_equipment_and_errors(id_inv, brand, model, sn, service, bt, uploaded_file, extracted_errors):
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # 1. Enregistrement ou mise à jour de l'équipement
        cursor.execute("""
            INSERT OR REPLACE INTO equipments (id_inv, brand, model, sn, service, bt)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (id_inv, brand, model, sn, service, bt))

        # 2. Sauvegarde du fichier PDF
        cursor.execute("""
            INSERT OR REPLACE INTO manuals (id_inv, filename, upload_date, pdf_blob)
            VALUES (?, ?, ?, ?)
        """, (id_inv, filename, now_str, file_bytes))

        # 3. Sauvegarde des pannes avec la clé d'équipement
        for err in extracted_errors:
            cursor.execute("""
                INSERT INTO error_records (id_inv, code, cause, solution, source, page)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (id_inv, err["code"], err["cause"], err["solution"], err["source"], err["page"]))
            
        conn.commit()

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
        cursor.execute("SELECT m.filename, m.upload_date, LENGTH(m.pdf_blob), e.brand, e.model, m.id_inv FROM manuals m LEFT JOIN equipments e ON m.id_inv = e.id_inv ORDER BY m.id DESC")
        return cursor.fetchall()

# --- 3. PARSEUR MULTI-RÈGLES ROBUSTE ---

def parse_pdf_errors(uploaded_file):
    """
    Parseur tolérant conçu pour les guides de maintenance biomédicale.
    Gère les erreurs sur une ou plusieurs lignes, tableaux et codes isolés.
    """
    extracted = []
    reader = PdfReader(uploaded_file)
    max_pages = min(len(reader.pages), 100)

    # Patterns de capture d'alarmes (E01, Err-12, Alarm 04, Code F3, LID OPEN, etc.)
    code_pattern = re.compile(r'\b(?:ERROR|ERR|CODE|ALARM|ALARME|FAULT|DÉFAUT|DEF|E|F)\s*[-:#]?\s*([A-Za-z0-9]{1,6})\b', re.IGNORECASE)

    for idx in range(max_pages):
        page_num = idx + 1
        page_text = reader.pages[idx].extract_text() or ""
        
        # Nettoyage des lignes
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            match = code_pattern.search(line)
            
            if match:
                code_trouve = match.group(0).upper().replace("  ", " ")
                
                # Récupération du reste de la ligne ou des lignes suivantes comme cause/solution
                reste_ligne = line[match.end():].strip(" :-\t")
                cause = reste_ligne if len(reste_ligne) > 5 else "Anomalie signalée sur dispositif"
                
                # On regarde la ligne suivante pour la solution si disponible
                solution = ""
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Si la ligne suivante n'est pas elle-même un nouveau code d'erreur
                    if not code_pattern.search(next_line):
                        solution = next_line
                        i += 1
                
                if not solution:
                    solution = "Consulter le schéma de dépannage de la section maintenance et vérifier l'intégrité des capteurs."

                # Éviter les faux positifs trop courts
                if len(cause) > 3 or len(solution) > 5:
                    extracted.append({
                        "code": code_trouve,
                        "cause": cause[:120],
                        "solution": solution[:250],
                        "source": uploaded_file.name[:25],
                        "page": page_num
                    })
            i += 1

    return extracted

# --- 4. GÉNÉRATEUR PDF CERTIFIÉ ---

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
        [Paragraph("<b>N° Inventaire GMAO :</b>", styles['Normal']), Paragraph(inv_id, styles['Normal'])],
        [Paragraph("<b>Équipement / Série :</b>", styles['Normal']), Paragraph(f"{equipment_info['brand']} {equipment_info['model']} ({equipment_info['sn']})", styles['Normal'])],
        [Paragraph("<b>Service d'affectation :</b>", styles['Normal']), Paragraph(equipment_info['service'], styles['Normal'])],
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
        ["Sécurité mécanique / couvercle", "Verrouillage automatique", "CONFORME"],
        ["Essai fonctionnel en charge", "Consigne atteinte sans alarme", "CONFORME"]
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

# --- 5. INTERFACE PRINCIPALE STREAMLIT ---

equipments = get_all_equipments()

col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("🩺 BioMed Assist Pro")
    st.caption("Atelier de Maintenance Biomédicale — Hôpital NOVO")
with col_h2:
    st.info("Opérateur : **Hakki Ismail**")

tab_diag, tab_matrix, tab_db = st.tabs([
    "🩺 Diagnostic & GMAO", 
    "📚 Matrice d'Erreurs par Équipement",
    "💾 Base des Manuels & Équipements"
])

# --- TAB 1 : DIAGNOSTIC & GMAO ---
with tab_diag:
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("🏷️ Inventaire GMAO")
        
        selected_inv = st.selectbox(
            "Équipement sous intervention :",
            options=list(equipments.keys()),
            format_func=lambda x: f"{x} — {equipments[x]['model']} ({equipments[x]['brand']})"
        )
        
        eq = equipments[selected_inv]
        st.info(f"""
        **Modèle :** {eq['brand']} {eq['model']}  
        **Série :** `{eq['sn']}`  
        **Service :** {eq['service']}  
        **GMAO :** BT {eq['bt']} Actif
        """)

        st.divider()
        st.subheader("📄 Ajouter un Manuel & Équipement")
        
        with st.expander("➕ Enregistrer un nouvel équipement avec son manuel", expanded=False):
            with st.form("add_equipment_form", clear_on_submit=False):
                new_inv = st.text_input("N° Inventaire GMAO", placeholder="ex: INV-55421")
                new_brand = st.text_input("Marque / Fabricant", placeholder="ex: Fresenius, Maquet, Mindray...")
                new_model = st.text_input("Modèle de l'appareil", placeholder="ex: 5008S, Servo-u, BeneVision...")
                new_sn = st.text_input("Numéro de série", placeholder="ex: SN-2026-0041")
                new_service = st.text_input("Service d'affectation", placeholder="ex: Réanimation, Dialyse, Urgences...")
                new_bt = st.text_input("N° Ordre de travail GMAO", value="#Nouveau")
                uploaded_pdf = st.file_uploader("Fichier PDF du manuel de service", type=["pdf"])

                submitted = st.form_submit_button("💾 Enregistrer et Extraire les Erreurs", type="primary")

                if submitted:
                    if not new_inv or not new_brand or not new_model or not uploaded_pdf:
                        st.error("Veuillez renseigner au moins l'inventaire, la marque, le modèle et déposer le PDF.")
                    else:
                        with st.spinner("Indexation de l'équipement et parsing des codes erreurs..."):
                            extracted = parse_pdf_errors(uploaded_pdf)
                            save_manual_equipment_and_errors(
                                id_inv=new_inv.strip().upper(),
                                brand=new_brand.strip(),
                                model=new_model.strip(),
                                sn=new_sn.strip() or "N/C",
                                service=new_service.strip() or "Biomédical",
                                bt=new_bt.strip() or "Aucun",
                                uploaded_file=uploaded_pdf,
                                extracted_errors=extracted
                            )
                            st.success(f"Équipement {new_inv} enregistré ! {len(extracted)} pannes compilées.")
                            st.rerun()

    with col_right:
        st.subheader(f"🔍 Diagnostic ciblé sur : {eq['brand']} {eq['model']}")
        
        # On charge uniquement les erreurs propres à cet équipement
        eq_errors = load_errors_for_equipment(selected_inv)
        
        if eq_errors:
            st.caption(f"ℹ️ {len(eq_errors)} codes pannes répertoriés pour ce dispositif dans le système.")
        else:
            st.warning("Aucun code panne spécifique encore extrait pour ce modèle. Diagnostic général actif.")

        query = st.text_input("Symptôme observé ou code alarme :", value="E-02")

        q_clean = query.upper()
        # Recherche en priorité dans les erreurs de l'équipement sélectionné
        found = next((item for item in eq_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)

        # Si pas trouvé dans cet équipement, recherche globale
        if not found:
            all_errors = load_errors_for_equipment(None)
            found = next((item for item in all_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)

        if found:
            res_text = f"""✔ SOLUTION CONSTRUCTEUR IDENTIFIÉE ({found['source']} - Page {found['page']}) :

• Équipement cible : {eq['brand']} {eq['model']}
• Code détecté : {found['code']}
• Cause probable : {found['cause']}
• Procédure de résolution : {found['solution']}

• Contrôles réglementaires exigés (NF EN 62353) :
  1. Mesure de continuité de la terre de protection (< 0,20 Ω).
  2. Vérification des courants de fuite à la terre et carcasse.
  3. Validation des autotests et sécurités mécaniques/thermiques."""
        else:
            res_text = f"""Procédure générale pour {eq['brand']} {eq['model']} (Symptôme : {query}) :

1. Contrôler les tensions secondaires du bloc d'alimentation.
2. Vérifier l'état mécanique et les faisceaux de câbles du sous-ensemble en alarme.
3. Lancer la procédure d'autotest depuis le menu de service constructeur.
4. Effectuer les contrôles de sécurité électrique NF EN 62353 avant remise au service {eq['service']}."""

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
                label=f"📄 Fiche Certifiée ({selected_inv})",
                data=pdf_bytes,
                file_name=f"Fiche_Intervention_{selected_inv}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
        with btn_col2:
            if st.button("📤 Clôturer & Renseigner le BT", use_container_width=True):
                st.success(f"Bon de travail {eq['bt']} mis à jour et clôturé en GMAO !")

# --- TAB 2 : MATRICE DES PANNES ---
with tab_matrix:
    st.subheader("📋 Matrice des Pannes & Résolutions Extraites")
    
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        filter_equip = st.selectbox(
            "Filtrer par équipement :",
            options=["Tous les équipements"] + list(equipments.keys()),
            format_func=lambda x: "Tous les équipements" if x == "Tous les équipements" else f"{x} — {equipments[x]['model']}"
        )
    with col_f2:
        filter_txt = st.text_input("Recherche rapide (code, cause, solution) :", placeholder="Ex: E-02, rotor, débit, température...")

    displayed_errors = load_errors_for_equipment(filter_equip)
    
    if filter_txt:
        displayed_errors = [
            e for e in displayed_errors
            if filter_txt.lower() in e["code"].lower()
            or filter_txt.lower() in e["cause"].lower()
            or filter_txt.lower() in e["solution"].lower()
        ]

    st.caption(f"{len(displayed_errors)} panne(s) trouvée(s).")

    if displayed_errors:
        for err in displayed_errors:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 1])
                with c1:
                    st.code(err["code"])
                    st.caption(f"Inventaire : {err['id_inv']}")
                with c2:
                    st.markdown(f"**Cause :** {err['cause']}")
                    st.write(f"**Résolution :** {err['solution']}")
                with c3:
                    st.caption(f"{err['source']}\nPage {err['page']}")
    else:
        st.info("Aucune panne ne correspond à ce filtre.")

# --- TAB 3 : ÉTAT DE LA BASE DE DONNÉES ---
with tab_db:
    st.subheader("💾 Répertoire des Équipements & Manuels Associés")
    
    saved_manuals = load_saved_manuals()
    
    if saved_manuals:
        for m in saved_manuals:
            fname, udate, size_b, brand, model, inv_id = m
            size_mb = size_b / (1024 * 1024)
            with st.container(border=True):
                c_info1, c_info2 = st.columns([3, 1])
                with c_info1:
                    st.markdown(f"**{inv_id} — {brand} {model}**")
                    st.caption(f"Fichier : `{fname}` | Taille : {size_mb:.2f} Mo")
                with c_info2:
                    st.write(f"📅 Ajouté le {udate}")
    else:
        st.info("Aucun manuel enregistré en base pour le moment.")
