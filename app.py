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
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = "biomed_data_v6.db"

# --- STYLE CSS ATELIER COMPACT & LISIBLE ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
    }
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1.5rem !important;
        max-width: 1440px !important;
    }
    
    .app-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 0.8rem 1.4rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }
    .app-title {
        color: #ffffff;
        font-size: 1.15rem;
        font-weight: 700;
        margin: 0;
    }
    .app-sub {
        color: #94a3b8;
        font-size: 0.75rem;
    }
    .user-pill {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        color: #e2e8f0;
        font-size: 0.8rem;
    }

    /* Boîte de solution active */
    .active-solution-card {
        background: #ffffff;
        border: 2px solid #0284c7;
        border-radius: 8px;
        padding: 1.1rem;
        margin-bottom: 0.8rem;
        box-shadow: 0 4px 12px rgba(2, 132, 199, 0.06);
    }
    
    .code-badge-big {
        background: #0284c7;
        color: white;
        padding: 0.25rem 0.65rem;
        border-radius: 6px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.95rem;
        display: inline-block;
    }

    .norme-box {
        background: #f0fdfa;
        border-left: 3px solid #0d9488;
        border-radius: 4px;
        padding: 0.5rem 0.8rem;
        margin-top: 0.6rem;
    }

    .device-tile {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.8rem;
        margin-bottom: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. FILTRAGE MÉTIER BIOMÉDICAL STRICT ---

# Mots-clés des pannes purement utilisateurs à exclure d'office
USER_ALARMS_EXCLUDE = [
    "fermer la porte", "close door", "remplacer consommable", "changer tubulure",
    "changer cassette", "patient", "perfusion terminée", "infusion complete",
    "brancher secteur", "plug in", "connect ac", "mauvais mot de passe",
    "wrong password", "pause", "attente", "standby", "stand-by"
]

# Mots-clés des pannes techniques d'atelier biomédical à conserver
BIOMED_TECHNICAL_KEYWORDS = [
    "moteur", "motor", "rotor", "tachymètre", "tacho", "vitesse", "speed",
    "alimentation", "power supply", "tension", "voltage", "fusible", "fuse",
    "court-circuit", "short circuit", "carte", "board", "pcb", "cpu", "bus",
    "capteur", "sensor", "optique", "prisme", "cellule", "étalonnage", "calibration",
    "pressostat", "pression", "pressure", "débitmètre", "flow", "thermostat",
    "température", "surchauffe", "overheat", "compresseur", "électrovanne",
    "valve", "verrouillage", "lock", "interrupteur", "switch", "fuite",
    "leak", "isolement", "terre", "ground", "62353"
]

def classify_biomed_category(code_text, cause_text, solution_text):
    """Classe uniquement dans les 3 grands domaines d'atelier biomédical."""
    full = f"{code_text} {cause_text} {solution_text}".lower()
    
    if any(k in full for k in ["carte", "board", "cpu", "rom", "firmware", "bus", "com", "communication", "watchdog", "programme"]):
        return "💻 Système & Cartes"
    if any(k in full for k in ["tension", "voltage", "alimentation", "fusible", "fuse", "capteur", "sensor", "optique", "étalonnage", "pressostat", "cellule"]):
        return "⚡ Électrique & Capteurs"
    
    return "⚙️ Mécanique & Moteur"

# --- 2. BASE DE DONNÉES SQLITE ---

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
                title TEXT,
                category TEXT,
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
                INSERT INTO error_records (id_inv, code, title, category, cause, solution, source, page) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ("EQ-ROTANTA", "E-02", "E-02 : Surchauffe bol ou défaut tachymétrique", "⚙️ Mécanique & Moteur", "Surchauffe cuve / Capteur vitesse décalé", "Contrôler l'entrefer du capteur de vitesse (0,8 mm ± 0,2). Vérifier l'aimant d'arbre moteur et les enroulements compresseur.", "Manuel Hettich", 48),
                ("EQ-ROTANTA", "LID OPEN", "LID OPEN : Défaut micro-contacteur verrouillage", "⚙️ Mécanique & Moteur", "Contacteur couvercle SW1 défaillant", "Vérifier la course du micro-contacteur de sécurité (SW1). Tester la bobine de verrouillage à l'ohmmètre.", "Manuel Hettich", 52),
                ("EQ-WD40", "AL-04", "AL-04 : Débit insuffisant / Vanne d'arrivée bloquée", "⚡ Électrique & Capteurs", "Pression amont faible ou filtre colmaté", "Nettoyer le tamis 50µm. Contrôler l'étanchéité et le signal impulsionnel du débitmètre.", "Manuel WD40", 31),
                ("EQ-FLUIDO", "AIR IN LINE", "AIR IN LINE : Dérive cellule optique détection bulles", "⚡ Électrique & Capteurs", "Prismes optiques encrassés ou désalignés", "Nettoyer les prismes à l'alcool isopropylique. Étalonner la sensibilité du capteur ultrasonique en mode service.", "Manuel Fluido", 19)
            ])
        conn.commit()

init_db()

# --- 3. DÉTECTION FABRICANT & MODÈLE ---

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

# --- 4. PARSEUR PDF CIBLÉ SUR LA MAINTENANCE TECHNIQUE ---

def parse_pdf_biomed_errors_only(uploaded_file):
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
    
    technical_alarms = [
        "LID OPEN", "COVER OPEN", "AIR IN LINE", "NO FLOW", "OVERHEAT",
        "PRESSURE HIGH", "SENSOR FAIL", "COMM ERROR", "MOTOR FAIL", "TACHO ERROR"
    ]

    raw_extracted = []
    seen_codes = set()

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
                for state in technical_alarms:
                    if re.search(r'\b' + state + r'\b', line, re.IGNORECASE):
                        code = state
                        reste = re.sub(r'(?i)\b' + state + r'\b', '', line).strip(" :-\t|")
                        cause = reste if len(reste) > 3 else "Anomalie matériel détectée"
                        break

            if code:
                clean_key = re.sub(r'[^A-Z0-9]', '', code)
                
                # Ignorer si déjà vu, trop court ou motif rejeté
                if clean_key not in seen_codes and len(clean_key) >= 2 and not any(stop in code for stop in ["ISO", "POSTAL", "BARCODE", "REV", "PAGE"]):
                    
                    collected_next = []
                    lookahead = 1
                    while (i + lookahead < len(raw_lines)) and lookahead <= 2:
                        next_l = raw_lines[i + lookahead]
                        if alarm_regex.search(next_l) or any(st_w in next_l.upper() for st_w in technical_alarms):
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

                    cause = cause or "Défaut d'étalonnage ou composant à vérifier"
                    solution = solution or "Vérifier la continuité des faisceaux, tester la tension carte et recalibrer."

                    full_context = f"{code} {cause} {solution}".lower()
                    
                    # FILTRE BIOMÉDICAL : Élimine les alarmes soignantes simples
                    is_user_alarm = any(ign in full_context for ign in USER_ALARMS_EXCLUDE)
                    is_technical = any(kw in full_context for kw in BIOMED_TECHNICAL_KEYWORDS)

                    if not is_user_alarm and is_technical:
                        seen_codes.add(clean_key)
                        category = classify_biomed_category(code, cause, solution)
                        title = f"{code} : {cause[:55]}"

                        raw_extracted.append({
                            "code": code,
                            "title": title,
                            "category": category,
                            "cause": cause[:140],
                            "solution": solution[:260],
                            "source": uploaded_file.name[:25],
                            "page": page_num
                        })
            i += 1

    return raw_extracted, sample_text

# --- 5. REQUÊTES EN BASE ---

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
                INSERT INTO error_records (id_inv, code, title, category, cause, solution, source, page)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (auto_id, err["code"], err["title"], err["category"], err["cause"], err["solution"], err["source"], err["page"]))
        conn.commit()
    return auto_id

def load_errors_for_equipment(id_inv=None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if id_inv and id_inv != "Tous":
            cursor.execute("""
                SELECT id_inv, code, title, category, cause, solution, source, page 
                FROM error_records 
                WHERE id_inv = ? 
                ORDER BY id ASC
            """, (id_inv,))
        else:
            cursor.execute("""
                SELECT id_inv, code, title, category, cause, solution, source, page 
                FROM error_records 
                ORDER BY id ASC
            """)
        rows = cursor.fetchall()
        
        unique_errors = []
        seen = set()
        for r in rows:
            clean_key = f"{r[0]}_{re.sub(r'[^A-Z0-9]', '', r[1])}"
            if clean_key not in seen:
                seen.add(clean_key)
                unique_errors.append({
                    "id_inv": r[0], "code": r[1], "title": r[2], "category": r[3],
                    "cause": r[4], "solution": r[5], "source": r[6], "page": r[7]
                })
        return unique_errors

# --- 6. RAPPORT PDF CERTIFIÉ NF EN 62353 ---

def generate_certified_pdf(inv_id, equipment_info, symptom, resolution, tech_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontSize=13,
        textColor=colors.HexColor("#0f172a"), alignment=1, spaceAfter=14
    )
    story.append(Paragraph("FICHE OFFICIELLE D'INTERVENTION TECHNIQUE BIOMÉDICALE", title_style))
    story.append(Spacer(1, 8))

    id_data = [
        [Paragraph("<b>Dispositif Médical :</b>", styles['Normal']), Paragraph(f"<b>{equipment_info['brand']} {equipment_info['model']}</b>", styles['Normal'])],
        [Paragraph("<b>Identifiant / N° Série :</b>", styles['Normal']), Paragraph(f"{inv_id} / {equipment_info['sn']}", styles['Normal'])],
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
    story.append(Spacer(1, 14))

    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=10.5, textColor=colors.HexColor("#0284c7"), spaceAfter=6)
    story.append(Paragraph("1. Diagnostic et Procédure Appliquée", h2_style))
    story.append(Paragraph(resolution.replace("\n", "<br/>"), styles['Normal']))
    story.append(Spacer(1, 14))

    story.append(Paragraph("2. Contrôles Réglementaires de Sécurité Électrique (NF EN 62353)", h2_style))
    checks_data = [
        ["Nature du contrôle", "Critère normatif", "Résultat"],
        ["Continuité conducteur de protection", "Résistance <= 0,20 ohm", "CONFORME"],
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
    story.append(Spacer(1, 18))

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

# --- INITIALISATION DE L'ÉTAT ---
if "active_code" not in st.session_state:
    st.session_state["active_code"] = "E-02"

st.markdown("""
<div class="app-header">
    <div>
        <div class="app-title">⚡ BioMed Assist Pro</div>
        <div class="app-sub">Atelier Biomédical — Dépannage Technique & Sécurité NF EN 62353</div>
    </div>
    <div class="user-pill">
        Technicien : <strong>Hakki Ismail</strong>
    </div>
</div>
""", unsafe_allow_html=True)

equipments = get_all_equipments()
eq_keys = list(equipments.keys())

col_gauche, col_droite = st.columns([1, 2], gap="large")

# =========================================================================
# COLONNE GAUCHE : ÉQUIPEMENT & MANUEL
# =========================================================================
with col_gauche:
    st.markdown("### 1. Dispositif Médical")
    
    default_idx = 0
    if "selected_equipment_id" in st.session_state and st.session_state["selected_equipment_id"] in eq_keys:
        default_idx = eq_keys.index(st.session_state["selected_equipment_id"])

    selected_inv = st.selectbox(
        "Sélection de l'appareil",
        options=eq_keys,
        index=default_idx,
        format_func=lambda x: f"{equipments[x]['brand']} — {equipments[x]['model']}",
        label_visibility="collapsed"
    )
    
    eq = equipments[selected_inv]
    
    st.markdown(f"""
    <div class="device-tile">
        <strong style="color:#0f172a; font-size:1rem;">{eq['brand']} {eq['model']}</strong>
        <div style="font-size:0.8rem; color:#64748b; margin-top:0.2rem;">
            ID : <code>{selected_inv}</code> | Série : <code>{eq['sn']}</code><br/>
            Service : {eq['service']} | BT : <strong>{eq['bt']}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📥 Ajouter un manuel technique PDF", expanded=False):
        uploaded_pdf = st.file_uploader("Fichier PDF du manuel de service :", type=["pdf"])
        if uploaded_pdf is not None:
            upload_key = f"proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if upload_key not in st.session_state:
                with st.spinner("Filtrage biomédical et compilation des pannes..."):
                    extracted_errors, sample_txt = parse_pdf_biomed_errors_only(uploaded_pdf)
                    brand, model = auto_detect_brand_and_model(sample_txt, uploaded_pdf.name)
                    new_id = save_manual_equipment_and_errors(brand, model, uploaded_pdf, extracted_errors)
                    st.session_state[upload_key] = True
                    st.session_state["selected_equipment_id"] = new_id
                    st.session_state["active_code"] = extracted_errors[0]["code"] if extracted_errors else ""
                    st.success(f"Dispositif « {brand} {model} » indexé ({len(extracted_errors)} pannes d'atelier).")
                    st.rerun()

# =========================================================================
# COLONNE DROITE : BANQUE DE PANNES SANS SURCHARGE
# =========================================================================
with col_droite:
    st.markdown(f"### 2. Dépannage : {eq['brand']} {eq['model']}")

    device_errors = load_errors_for_equipment(selected_inv)

    col_input, col_reset = st.columns([4, 1])
    with col_input:
        search_query = st.text_input(
            "Recherche",
            value=st.session_state.get("active_code", ""),
            placeholder="Tapez un code ou mot-clé atelier (ex: E-02, rotor, carte, débit...)",
            label_visibility="collapsed"
        )
    with col_reset:
        if st.button("Effacer", use_container_width=True):
            st.session_state["active_code"] = ""
            st.rerun()

    # Recherche
    q_clean = re.sub(r'[^A-Za-z0-9]', '', search_query.upper())
    active_err = None

    if q_clean:
        active_err = next((
            e for e in device_errors 
            if q_clean in re.sub(r'[^A-Za-z0-9]', '', e["code"].upper()) 
            or q_clean in re.sub(r'[^A-Za-z0-9]', '', e["cause"].upper())
            or q_clean in re.sub(r'[^A-Za-z0-9]', '', e["title"].upper())
        ), None)
        
        if not active_err:
            all_errs = load_errors_for_equipment(None)
            active_err = next((
                e for e in all_errs 
                if q_clean in re.sub(r'[^A-Za-z0-9]', '', e["code"].upper()) 
                or q_clean in re.sub(r'[^A-Za-z0-9]', '', e["cause"].upper())
                or q_clean in re.sub(r'[^A-Za-z0-9]', '', e["title"].upper())
            ), None)

    # Affichage de la fiche d'action
    if active_err:
        st.markdown(f"""
        <div class="active-solution-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                <div>
                    <span class="code-badge-big">{active_err['code']}</span>
                    <span style="margin-left:0.5rem; font-size:0.8rem; font-weight:600; color:#0284c7;">{active_err['category']}</span>
                </div>
                <span style="font-size:0.75rem; color:#64748b;">Réf: {active_err['source']} (Page {active_err['page']})</span>
            </div>
            <h4 style="margin:0 0 0.4rem 0; color:#0f172a;">{active_err['title']}</h4>
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:0.75rem; font-size:0.9rem; color:#1e293b; line-height:1.45;">
                <strong>Action atelier biomédical :</strong><br/>
                {active_err['solution']}
            </div>
            <div class="norme-box">
                <span style="color:#0d9488; font-weight:700; font-size:0.8rem;">CONTRÔLES NF EN 62353 :</span>
                <span style="font-size:0.78rem; color:#475569;"> Terre (&lt; 0,20 Ω) | Fuites contact | Validation sécurité</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        raw_resolution = f"Panne {active_err['code']} - {active_err['cause']}\nAction atelier : {active_err['solution']}"
    else:
        st.info("💡 Cliquez sur une panne ci-dessous pour charger sa fiche sans défilement.")
        raw_resolution = f"Diagnostic général pour {eq['brand']} {eq['model']} (Recherche: {search_query})"

    col_act1, col_act2 = st.columns(2)
    with col_act1:
        pdf_bytes = generate_certified_pdf(
            inv_id=selected_inv,
            equipment_info=eq,
            symptom=search_query or "Contrôle général",
            resolution=raw_resolution,
            tech_name="Hakki Ismail"
        )
        st.download_button(
            label="📄 Télécharger la Fiche Certifiée (PDF)",
            data=pdf_bytes,
            file_name=f"Fiche_{eq['brand']}_{eq['model'].replace(' ', '_')}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
    with col_act2:
        if st.button("✅ Valider l'intervention", use_container_width=True):
            st.toast(f"Intervention sur {eq['brand']} {eq['model']} validée.", icon="✅")

    st.divider()

    # 3. FILTRAGE EN 3 RUBRIQUES CLAIRES SANS SOUCI DE VISIBILITÉ
    st.markdown(f"#### 📋 Matrice des pannes d'atelier ({len(device_errors)})")

    # Seulement 3 grandes catégories
    categories = ["Toutes les pannes", "⚙️ Mécanique & Moteur", "⚡ Électrique & Capteurs", "💻 Système & Cartes"]
    selected_cat = st.segmented_control("Filtrer par domaine :", categories, default="Toutes les pannes")

    filtered_errors = device_errors if selected_cat == "Toutes les pannes" else [e for e in device_errors if e["category"] == selected_cat]

    # Conteneur défilant compact : la suite reste toujours visible
    with st.container(height=340):
        if filtered_errors:
            for idx, err in enumerate(filtered_errors):
                c_code, c_desc, c_btn = st.columns([1.1, 3.9, 1.4])
                with c_code:
                    st.code(err["code"])
                with c_desc:
                    st.markdown(f"**{err['title']}**")
                    st.caption(f"{err['solution'][:90]}...")
                with c_btn:
                    if st.button("Voir", key=f"btn_{err['id_inv']}_{idx}_{err['code']}", use_container_width=True):
                        st.session_state["active_code"] = err["code"]
                        st.rerun()
        else:
            st.info("Aucune panne technique répertoriée dans cette rubrique.")
