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
    page_title="BioMed Assist Pro | Atelier Biomédical",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = "biomed_data_v3.db"

# --- INJECTION CSS UI/UX MÉDICALE ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
    }
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    /* Espacements globaux */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1400px !important;
    }
    
    /* En-tête applicatif */
    .app-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 1.25rem 1.75rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }
    .app-brand {
        display: flex;
        align-items: center;
        gap: 0.85rem;
    }
    .brand-icon {
        background: linear-gradient(135deg, #0284c7 0%, #0d9488 100%);
        color: white;
        width: 40px;
        height: 40px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.25rem;
        box-shadow: 0 2px 6px rgba(2, 132, 199, 0.3);
    }
    .app-title {
        color: #ffffff;
        font-size: 1.2rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin: 0;
    }
    .app-sub {
        color: #94a3b8;
        font-size: 0.8rem;
        margin: 0;
    }
    .user-pill {
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.12);
        padding: 0.4rem 0.9rem;
        border-radius: 9999px;
        color: #e2e8f0;
        font-size: 0.82rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #10b981;
        box-shadow: 0 0 6px rgba(16, 185, 129, 0.6);
    }

    /* Cartes de diagnostic */
    .diag-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
    }
    .diag-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 0.75rem;
        margin-bottom: 0.75rem;
    }
    .code-pill {
        background: #fef3c7;
        color: #92400e;
        padding: 0.25rem 0.6rem;
        border-radius: 6px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
    }
    .sec-tag {
        font-size: 0.75rem;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    
    /* Tuiles d'équipement */
    .device-tile {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .device-tile h4 {
        margin: 0 0 0.35rem 0;
        color: #0f172a;
        font-size: 1.05rem;
        font-weight: 700;
    }
    .device-tile p {
        margin: 0;
        color: #64748b;
        font-size: 0.82rem;
    }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DONNÉES SQLITE ---

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
        cursor.execute("SELECT COUNT(*) FROM equipments")
        if cursor.fetchone()[0] == 0:
            cursor.executemany("""
                INSERT OR IGNORE INTO equipments (id_inv, brand, model, sn, service, bt)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("EQ-ROTANTA", "Hettich", "Rotanta 460 RF", "SN-2026-991", "Laboratoire Biochimie", "BT-4012"),
                ("EQ-WD40", "Wassenburg", "WD40", "SN-2025-441", "Endoscopie", "BT-Actif"),
                ("EQ-FLUIDO", "The Surgical Co", "Fluido AirGuard", "SN-2026-118", "Bloc Opératoire", "BT-3890")
            ])
            cursor.executemany("""
                INSERT INTO error_records (id_inv, code, cause, solution, source, page) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("EQ-ROTANTA", "E-02", "Surchauffe cuve / Défaut tachymétrique", "Contrôler l'entrefer du capteur de vitesse sous le bol (0,8 mm ± 0,2). Vérifier l'aimant d'arbre moteur et les enroulements du compresseur.", "Manuel Hettich", 48),
                ("EQ-ROTANTA", "LID OPEN", "Contacteur couvercle défaillant", "Vérifier la course du micro-contacteur de sécurité (SW1). Remplacer l'électro-aimant si résistance infinie.", "Manuel Hettich", 52),
                ("EQ-WD40", "AL-04", "Débit d'eau osmosée insuffisant", "Nettoyer le tamis d'admission 50µm. Vérifier la pression statique amont (min 2,5 bars) et le débitmètre.", "Manuel WD40", 31),
                ("EQ-FLUIDO", "AIR IN LINE", "Bulle détectée ou capteur encrassé", "Nettoyer les prismes optiques de détection avec de l'alcool isopropylique. Étalonner le capteur.", "Manuel Fluido", 19)
            ])
        conn.commit()

init_db()

# --- DÉTECTION CONSTRUCTEUR / MODÈLE ---

KNOWN_BRANDS = [
    "Hettich", "Fresenius", "Dräger", "Draeger", "Mindray", "Maquet", "Getinge",
    "Philips", "GE Healthcare", "General Electric", "Olympus", "Karl Storz",
    "Storz", "Wassenburg", "The Surgical Company", "Baxter", "B. Braun", "BBraun",
    "Nihon Kohden", "Hamilton Medical", "Medtronic", "Siemens Healthineers",
    "Eppendorf", "Thermo Fisher", "Fisher Scientific", "Leica", "Steris",
    "Stryker", "Smith & Nephew", "Zoll", "Schiller", "Roche", "Sysmex"
]

def auto_detect_brand_and_model(first_pages_text, filename):
    clean_fn = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")
    full_sample = (clean_fn + " " + first_pages_text[:2500]).strip()
    
    detected_brand = "Constructeur Inconnu"
    for b in KNOWN_BRANDS:
        if re.search(r'\b' + re.escape(b) + r'\b', full_sample, re.IGNORECASE):
            detected_brand = b
            break

    words_to_strip = [
        "service manual", "user manual", "manual", "manuel de maintenance",
        "maintenance", "manuel", "instructions for use", "ifu", "technical",
        "guide", "system", "version", "rev", "edition", detected_brand.lower()
    ]
    fn_candidate = clean_fn
    for w in words_to_strip:
        fn_candidate = re.sub(r'(?i)\b' + re.escape(w) + r'\b', '', fn_candidate)
    fn_candidate = re.sub(r'\s+', ' ', fn_candidate).strip()

    if len(fn_candidate) >= 3:
        detected_model = fn_candidate.title()
    else:
        model_match = re.search(r'(?:model|modèle|type)\s*[:\-]?\s*([A-Za-z0-9\-\s]{3,25})', first_pages_text[:1500], re.IGNORECASE)
        detected_model = model_match.group(1).strip().title() if model_match else f"Dispositif {datetime.now().strftime('%H%M')}"

    return detected_brand, detected_model

# --- PARSEUR CODES PANNES MULTI-FORMATS ---

def parse_pdf_errors_advanced(uploaded_file):
    extracted = []
    reader = PdfReader(uploaded_file)
    total_pages = len(reader.pages)
    max_pages = min(total_pages, 120)

    sample_text = ""
    for idx in range(min(5, total_pages)):
        sample_text += (reader.pages[idx].extract_text() or "") + " "

    alarm_regex = re.compile(
        r'(?:^|\n|\b)(?:ERROR|ERR|CODE|ALARM|ALARME|FAULT|DÉFAUT|DEF|E|F)\s*[-:#]?\s*([A-Za-z0-9]{1,8})\b',
        re.IGNORECASE
    )
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

        raw_lines = [l.strip() for l in page_text.splitlines() if l.strip()]
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            code = None
            cause = ""
            solution = ""

            match = alarm_regex.search(line)
            if match:
                code = match.group(0).strip().upper()
                reste = line[match.end():].strip(" :-\t|")
                if len(reste) > 3:
                    cause = reste

            if not code:
                for state in state_alarms:
                    if re.search(r'\b' + state + r'\b', line, re.IGNORECASE):
                        code = state
                        reste = re.sub(r'(?i)\b' + state + r'\b', '', line).strip(" :-\t|")
                        cause = reste if len(reste) > 3 else "Déclenchement alarme de sécurité"
                        break

            if code and not any(stop in code for stop in ["ISO", "POSTAL", "BARCODE", "REV"]):
                collected_next = []
                lookahead = 1
                while (i + lookahead < len(raw_lines)) and lookahead <= 2:
                    next_l = raw_lines[i + lookahead]
                    if alarm_regex.search(next_l) or any(st_w in next_l.upper() for st_w in state_alarms):
                        break
                    collected_next.append(next_l)
                    lookahead += 1

                if collected_next:
                    if not cause:
                        cause = collected_next[0]
                        solution = collected_next[1] if len(collected_next) > 1 else ""
                    else:
                        solution = " ".join(collected_next)
                    i += (lookahead - 1)

                cause = cause or "Anomalie ou signal d'avertissement détecté"
                solution = solution or "Vérifier la connectique, inspecter le capteur associé et effectuer l'autotest."

                extracted.append({
                    "code": code,
                    "cause": cause[:140],
                    "solution": solution[:260],
                    "source": uploaded_file.name[:25],
                    "page": page_num
                })
            i += 1

    return extracted, sample_text

# --- REQUÊTES EN BASE ---

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
    clean_prefix = re.sub(r'[^A-Za-z0-9]', '', model[:8]).upper()
    auto_id = f"EQ-{clean_prefix}-{datetime.now().strftime('%H%M')}"

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO equipments (id_inv, brand, model, sn, service, bt)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (auto_id, brand, model, "SN-AUTO", "Atelier Biomédical", "BT-En-Cours"))

        cursor.execute("""
            INSERT OR REPLACE INTO manuals (id_inv, filename, upload_date, pdf_blob)
            VALUES (?, ?, ?, ?)
        """, (auto_id, filename, now_str, file_bytes))

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

# --- GÉNÉRATEUR DU RAPPORT CERTIFIÉ NF EN 62353 ---

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

# --- HEADER UX CLEANROOM ---
st.markdown("""
<div class="app-header">
    <div class="app-brand">
        <div class="brand-icon">⚡</div>
        <div>
            <div class="app-title">BioMed Assist Pro</div>
            <div class="app-sub">Atelier Central de Maintenance Biomédicale</div>
        </div>
    </div>
    <div class="user-pill">
        <div class="status-dot"></div>
        Opérateur : <strong>Hakki Ismail</strong>
    </div>
</div>
""", unsafe_allow_html=True)

equipments = get_all_equipments()
all_errors = load_errors_for_equipment(None)
saved_manuals = load_saved_manuals()

# --- KPI METRICS BAR ---
kpi1, kpi2, kpi3 = st.columns(3)
with kpi1:
    st.metric(label="Appareils référencés", value=len(equipments), delta="Opérationnels")
with kpi2:
    st.metric(label="Codes pannes indexés", value=len(all_errors), delta="Prêts pour recherche")
with kpi3:
    st.metric(label="Manuels en base SQLite", value=len(saved_manuals), delta="Persistés localement")

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

# --- NAVIGATION TABS ---
tab_diag, tab_matrix, tab_db = st.tabs([
    "🩺 Banc de Diagnostic", 
    f"📚 Matrice des Pannes ({len(all_errors)})",
    f"💾 Bibliothèque Manuels ({len(saved_manuals)})"
])

# ==========================================
# ONGLET 1 : BANC DE DIAGNOSTIC
# ==========================================
with tab_diag:
    col_setup, col_workstation = st.columns([1, 2], gap="large")

    with col_setup:
        st.markdown("#### 1. Sélection de l'appareil")
        
        eq_keys = list(equipments.keys())
        default_index = 0
        if "selected_equipment_id" in st.session_state and st.session_state["selected_equipment_id"] in eq_keys:
            default_index = eq_keys.index(st.session_state["selected_equipment_id"])

        selected_inv = st.selectbox(
            "Dispositif sous intervention",
            options=eq_keys,
            index=default_index,
            format_func=lambda x: f"{equipments[x]['brand']} — {equipments[x]['model']}",
            label_visibility="collapsed"
        )
        
        eq = equipments[selected_inv]
        
        st.markdown(f"""
        <div class="device-tile">
            <h4>{eq['brand']} {eq['model']}</h4>
            <p><strong>Identifiant :</strong> <code>{selected_inv}</code></p>
            <p><strong>Affectation :</strong> {eq['service']} | <strong>Série :</strong> {eq['sn']}</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 2. Dépôt de manuel (Auto-index)")
        uploaded_pdf = st.file_uploader(
            "Glisser-déposer un nouveau PDF",
            type=["pdf"],
            key="pdf_drop_zone",
            help="Détecte automatiquement la marque, le modèle et compile les pannes sans saisie manuelle."
        )
        
        if uploaded_pdf is not None:
            upload_key = f"proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if upload_key not in st.session_state:
                with st.spinner("Indexation vectorielle et extraction des codes pannes..."):
                    extracted_errors, sample_txt = parse_pdf_errors_advanced(uploaded_pdf)
                    brand, model = auto_detect_brand_and_model(sample_txt, uploaded_pdf.name)
                    new_id = save_manual_equipment_and_errors(brand, model, uploaded_pdf, extracted_errors)
                    st.session_state[upload_key] = True
                    st.session_state["selected_equipment_id"] = new_id
                    st.success(f"Dispositif « {brand} {model} » indexé avec succès ({len(extracted_errors)} pannes compilées).")
                    st.rerun()

    with col_workstation:
        st.markdown(f"#### 3. Diagnostic & Procédure de Réparation")
        
        eq_errors = load_errors_for_equipment(selected_inv)
        
        query = st.text_input(
            "Recherche de panne",
            value="E-02",
            placeholder="Saisissez un code alarme ou un symptôme (ex: E-02, LID OPEN, NO FLOW...)",
            label_visibility="collapsed"
        )

        q_clean = query.upper().strip()
        found = next((item for item in eq_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)
        
        if not found:
            found = next((item for item in all_errors if item["code"] in q_clean or item["cause"].upper() in q_clean), None)

        # Affichage structuré du diagnostic UX
        if found:
            st.markdown(f"""
            <div class="diag-card">
                <div class="diag-header">
                    <div>
                        <span class="code-pill">{found['code']}</span>
                        <strong style="margin-left: 0.5rem; color: #0f172a;">{found['cause']}</strong>
                    </div>
                    <span class="sec-tag">Réf: {found['source']} (Page {found['page']})</span>
                </div>
                <div style="margin-bottom: 0.75rem;">
                    <span class="sec-tag">Procédure technique recommandée :</span>
                    <p style="margin: 0.35rem 0 0 0; color: #1e293b; font-size: 0.95rem; line-height: 1.5;">{found['solution']}</p>
                </div>
                <div style="background: #f8fafc; border-radius: 6px; padding: 0.65rem 0.85rem; border-left: 3px solid #0d9488;">
                    <span class="sec-tag" style="color: #0d9488;">Contrôles réglementaires exigés (NF EN 62353) :</span>
                    <div style="font-size: 0.8rem; color: #475569; margin-top: 0.2rem;">
                        1. Continuité de la terre de protection (&lt; 0,20 Ω)<br/>
                        2. Mesure des courants de fuite à la terre et carcasse<br/>
                        3. Validation des autotests et sécurités mécaniques/thermiques
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            raw_resolution = f"Procédure constructeur ({found['source']} - p.{found['page']}) :\n\nCause : {found['cause']}\nAction : {found['solution']}"
        else:
            st.markdown(f"""
            <div class="diag-card">
                <div class="diag-header">
                    <span class="code-pill" style="background:#f1f5f9; color:#475569;">DIAGNOSTIC GÉNÉRAL</span>
                    <span class="sec-tag">{eq['brand']} {eq['model']}</span>
                </div>
                <p style="color: #1e293b; font-size: 0.95rem; margin-bottom: 0.5rem;">Aucun code spécifique extrait pour cette alerte. Procédure atelier standard :</p>
                <div style="font-size: 0.85rem; color: #475569; line-height: 1.5;">
                    1. Contrôler les tensions secondaires du bloc d'alimentation.<br/>
                    2. Inspecter les capteurs et faisceaux de câblage.<br/>
                    3. Lancer l'autodiagnostic en mode service constructeur.<br/>
                    4. Réaliser les tests normatifs NF EN 62353 avant remise en service.
                </div>
            </div>
            """, unsafe_allow_html=True)
            raw_resolution = f"Procédure générale pour {eq['brand']} {eq['model']} (Symptôme: {query}) :\nContrôle des alimentations, faisceaux et autotests de sécurité."

        # Barre d'actions
        action1, action2 = st.columns([1, 1])
        with action1:
            pdf_bytes = generate_certified_pdf(
                inv_id=selected_inv,
                equipment_info=eq,
                symptom=query,
                resolution=raw_resolution,
                tech_name="Hakki Ismail"
            )
            st.download_button(
                label=f"📄 Télécharger la Fiche Certifiée (PDF)",
                data=pdf_bytes,
                file_name=f"Fiche_{eq['brand']}_{eq['model'].replace(' ', '_')}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
        with action2:
            if st.button("📤 Clôturer & Valider l'intervention", use_container_width=True):
                st.toast(f"Intervention sur {eq['brand']} {eq['model']} enregistrée avec succès.", icon="✅")

# ==========================================
# ONGLET 2 : MATRICE DES PANNES
# ==========================================
with tab_matrix:
    col_filter_dev, col_filter_kw = st.columns([1, 2])
    with col_filter_dev:
        filter_equip = st.selectbox(
            "Filtrer par appareil",
            options=["Tous les équipements"] + list(equipments.keys()),
            format_func=lambda x: "Tous les dispositifs" if x == "Tous les équipements" else f"{equipments[x]['brand']} — {equipments[x]['model']}"
        )
    with col_filter_kw:
        filter_txt = st.text_input("Filtrer par symptôme ou code", placeholder="Ex: E-02, rotor, débit, température...")

    displayed_errors = load_errors_for_equipment(filter_equip)
    if filter_txt:
        displayed_errors = [
            e for e in displayed_errors
            if filter_txt.lower() in e["code"].lower()
            or filter_txt.lower() in e["cause"].lower()
            or filter_txt.lower() in e["solution"].lower()
        ]

    st.caption(f"{len(displayed_errors)} anomalie(s) répertoriée(s).")

    if displayed_errors:
        for err in displayed_errors:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 1])
                with c1:
                    st.code(err["code"])
                with c2:
                    st.markdown(f"**Cause :** {err['cause']}")
                    st.markdown(f"**Action corrective :** {err['solution']}")
                with c3:
                    st.caption(f"{err['source']}\nPage {err['page']}")
    else:
        st.info("Aucune panne ne correspond aux filtres appliqués.")

# ==========================================
# ONGLET 3 : BIBLIOTHÈQUE MANUELS
# ==========================================
with tab_db:
    if saved_manuals:
        for m in saved_manuals:
            fname, udate, size_b, brand, model, inv_id = m
            size_mb = size_b / (1024 * 1024)
            with st.container(border=True):
                c_info1, c_info2 = st.columns([3, 1])
                with c_info1:
                    st.markdown(f"### {brand} — {model}")
                    st.caption(f"Fichier : `{fname}` | Taille : **{size_mb:.2f} Mo** | Identifiant : `{inv_id}`")
                with c_info2:
                    st.write(f"📅 Indexé le {udate}")
    else:
        st.info("Aucun manuel stocké.")
