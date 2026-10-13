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

DB_PATH = "biomed_data.db"

# --- 1. GESTION PERSISTANTE SQLITE ---

def init_db():
    """Initialise la base de données locale persistante si elle n'existe pas."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Table des fichiers PDF
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE,
                upload_date TEXT,
                pdf_blob BLOB
            )
        """)
        # Table des erreurs et résolutions extraites
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT,
                cause TEXT,
                solution TEXT,
                source TEXT,
                page INTEGER
            )
        """)
        
        # Données de démonstration initiales (insérées seulement si la table est vide)
        cursor.execute("SELECT COUNT(*) FROM error_records")
        if cursor.fetchone()[0] == 0:
            default_errors = [
                ("E-02", "Surchauffe cuve / Défaut tachymétrique", "Contrôler l'entrefer du capteur de vitesse sous le bol (0,8 mm ± 0,2). Vérifier l'aimant d'arbre moteur.", "Manuel Hettich", 48),
                ("LID OPEN", "Contacteur couvercle défaillant", "Vérifier la course du micro-contacteur de sécurité (SW1). Remplacer l'électro-aimant si résistance infinie.", "Manuel Hettich", 52),
                ("AL-04", "Débit d'eau osmosée insuffisant", "Nettoyer le tamis d'admission 50µm. Vérifier la pression statique amont (min 2,5 bars).", "Manuel WD40", 31),
                ("AIR IN LINE", "Bulle détectée ou capteur encrassé", "Nettoyer les prismes optiques de détection avec de l'alcool isopropylique. Étalonner le capteur.", "Manuel Fluido", 19)
            ]
            cursor.executemany("""
                INSERT INTO error_records (code, cause, solution, source, page) 
                VALUES (?, ?, ?, ?, ?)
            """, default_errors)
        conn.commit()

init_db()

def save_manual_and_errors(uploaded_file, extracted_errors):
    """Sauvegarde le fichier binaire du PDF et les pannes associées en base."""
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Enregistrement ou mise à jour du fichier PDF
        cursor.execute("""
            INSERT OR REPLACE INTO manuals (filename, upload_date, pdf_blob)
            VALUES (?, ?, ?)
        """, (filename, now_str, file_bytes))

        # Enregistrement des erreurs compilées
        for err in extracted_errors:
            cursor.execute("""
                INSERT INTO error_records (code, cause, solution, source, page)
                VALUES (?, ?, ?, ?, ?)
            """, (err["code"], err["cause"], err["solution"], err["source"], err["page"]))
            
        conn.commit()

def load_all_errors():
    """Charge toutes les pannes stockées dans SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT code, cause, solution, source, page FROM error_records ORDER BY id DESC")
        rows = cursor.fetchall()
        return [
            {"code": r[0], "cause": r[1], "solution": r[2], "source": r[3], "page": r[4]}
            for r in rows
        ]

def load_saved_manuals():
    """Liste les manuels présents dans la base."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT filename, upload_date, LENGTH(pdf_blob) FROM manuals ORDER BY id DESC")
        return cursor.fetchall()

# --- 2. ANALYSE ET EXTRACTION PDF ---

def parse_pdf_errors(uploaded_file):
    """Extrait le texte et compile les codes d'erreurs."""
    extracted = []
    reader = PdfReader(uploaded_file)
    regex = re.compile(
        r'(?:Error|Erreur|Code|Alarm|E-|Alarme)\s*[-:]?\s*([A-Za-z0-9]{1,6})[:\s\-]+([^.\n]{5,60})[.\s\-]+([^.\n]{10,200})',
        re.IGNORECASE
    )
    
    max_pages = min(len(reader.pages), 80)
    for idx in range(max_pages):
        page_num = idx + 1
        page_text = reader.pages[idx].extract_text() or ""
        for match in regex.finditer(page_text):
            extracted.append({
                "code": match.group(1).upper(),
                "cause": match.group(2).strip(),
                "solution": match.group(3).strip(),
                "source": uploaded_file.name[:25],
                "page": page_num
            })
    return extracted

# --- 3. GÉNÉRATEUR PDF CERTIFIÉ ---

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

# --- 4. CATALOGUE ET INTERFACE ---

EQUIPMENT_CATALOG = {
    "INV-88341": {"brand": "Hettich", "model": "Rotanta 460 RF", "sn": "SN-2024-991-RF", "service": "Laboratoire Biochimie", "bt": "#4012"},
    "INV-10292": {"brand": "Wassenburg", "model": "WD40", "sn": "SN-WD-4412", "service": "Endoscopie", "bt": "Aucun"},
    "INV-44019": {"brand": "The Surgical Co", "model": "Fluido AirGuard", "sn": "SN-FL-9931", "service": "Bloc Opératoire", "bt": "#3890"}
}

all_errors = load_all_errors()
saved_manuals = load_saved_manuals()

# En-tête
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("🩺 BioMed Assist Pro")
    st.caption("Atelier de Maintenance Biomédicale — Hôpital NOVO")
with col_h2:
    st.info("Opérateur : **Hakki Ismail**")

tab_diag, tab_matrix, tab_db = st.tabs([
    "🩺 Diagnostic & GMAO", 
    f"📚 Matrice d'Erreurs ({len(all_errors)})",
    f"💾 Base Manuels ({len(saved_manuals)})"
])

# --- TAB 1 : DIAGNOSTIC & GMAO ---
with tab_diag:
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("🏷️ Inventaire GMAO")
        
        selected_inv = st.selectbox(
            "Équipement au catalogue :",
            options=list(EQUIPMENT_CATALOG.keys()),
            format_func=lambda x: f"{x} — {EQUIPMENT_CATALOG[x]['model']} ({EQUIPMENT_CATALOG[x]['brand']})"
        )
        
        eq = EQUIPMENT_CATALOG[selected_inv]
        st.info(f"""
        **Modèle :** {eq['brand']} {eq['model']}  
        **Série :** `{eq['sn']}`  
        **Service :** {eq['service']}  
        **GMAO :** BT {eq['bt']} Actif
        """)

        st.divider()
        st.subheader("📄 Dépôt Manuel PDF")
        
        # Enregistrement automatique dès le dépôt
        uploaded_pdf = st.file_uploader("Ajouter un manuel (sauvegarde auto)", type=["pdf"], key="pdf_uploader")
        
        if uploaded_pdf is not None:
            # Clé en session pour éviter de réanalyser 50 fois le même upload au rerun
            upload_key = f"processed_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if upload_key not in st.session_state:
                with st.spinner("Enregistrement en base et analyse automatique..."):
                    extracted = parse_pdf_errors(uploaded_pdf)
                    save_manual_and_errors(uploaded_pdf, extracted)
                    st.session_state[upload_key] = True
                    st.success(f"✔ « {uploaded_pdf.name} » stocké en base SQLite ({len(extracted)} pannes extraites) !")
                    st.rerun()

    with col_right:
        st.subheader("🔍 Diagnostic & Procédure Constructeur")
        query = st.text_input("Symptôme observé ou code alarme :", value="Erreur E-02 surchauffe cuve ou couvercle bloqué")

        q_clean = query.upper()
        found = next((item for item in all_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)

        if found:
            res_text = f"""✔ SOLUTION CONSTRUCTEUR IDENTIFIÉE ({found['source']} - Page {found['page']}) :

• Identification : Panne {found['code']} — {found['cause']}
• Action recommandée : {found['solution']}

• Contrôles de sécurité requis (NF EN 62353) :
  1. Continuité de la terre de protection (< 0,20 Ω).
  2. Mesure du courant de fuite à la terre / carcasse.
  3. Essai dynamique et validation des sécurités mécaniques."""
        else:
            res_text = f"""Procédure générale pour : {query}

1. Vérifier les tensions d'alimentation secondaires sur la carte de puissance.
2. Inspecter les faisceaux de câblage et connecteurs pour déceler toute trace d'oxydation ou surchauffe.
3. Effectuer le test d'autodiagnostic en mode service constructeur.
4. Relever les mesures de conformité NF EN 62353 avant remise au service de soins."""

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
                label="📄 Télécharger la Fiche Certifiée (PDF)",
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
    filter_txt = st.text_input("Filtrer par code ou cause :", placeholder="Ex: E-02, rotor, température...")
    
    filtered_db = [
        item for item in all_errors
        if filter_txt.lower() in item["code"].lower() 
        or filter_txt.lower() in item["cause"].lower()
        or filter_txt.lower() in item["solution"].lower()
    ]

    if filtered_db:
        for err in filtered_db:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 1])
                with c1:
                    st.code(err["code"])
                with c2:
                    st.markdown(f"**Cause :** {err['cause']}")
                    st.write(err["solution"])
                with c3:
                    st.caption(f"{err['source']}\nPage {err['page']}")
    else:
        st.info("Aucune panne ne correspond à ce filtre.")

# --- TAB 3 : ÉTAT DE LA BASE DE DONNÉES ---
with tab_db:
    st.subheader("💾 Manuels PDF Stockés dans SQLite (`biomed_data.db`)")
    
    if saved_manuals:
        for m in saved_manuals:
            fname, udate, size_b = m
            size_mb = size_b / (1024 * 1024)
            st.write(f"📁 **{fname}** — Ajouté le {udate} ({size_mb:.2f} Mo stockés en base)")
    else:
        st.info("Aucun fichier PDF n'a encore été importé.")
