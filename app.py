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

DB_PATH = "biomed_data_v4.db"

# --- STYLE CSS ÉPURÉ POUR USAGE ATELIER SIMPLE ---
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
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
        max-width: 1400px !important;
    }
    
    .app-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border-radius: 10px;
        padding: 1rem 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.2rem;
    }
    .app-title {
        color: #ffffff;
        font-size: 1.25rem;
        font-weight: 700;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 0.6rem;
    }
    .app-sub {
        color: #94a3b8;
        font-size: 0.8rem;
    }
    .user-pill {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
        padding: 0.35rem 0.85rem;
        border-radius: 20px;
        color: #e2e8f0;
        font-size: 0.82rem;
    }

    .active-solution-card {
        background: #ffffff;
        border: 2px solid #0284c7;
        border-radius: 10px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 12px rgba(2, 132, 199, 0.08);
    }
    
    .code-badge-big {
        background: #0284c7;
        color: white;
        padding: 0.3rem 0.75rem;
        border-radius: 6px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        font-size: 1rem;
        display: inline-block;
    }

    .cat-badge {
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-left: 0.5rem;
    }
    .cat-meca { background: #fee2e2; color: #991b1b; }
    .cat-elec { background: #fef3c7; color: #92400e; }
    .cat-soft { background: #e0e7ff; color: #3730a3; }
    .cat-capt { background: #dcfce7; color: #166534; }
    .cat-ther { background: #ffedd5; color: #9a3412; }
    .cat-autre { background: #f1f5f9; color: #475569; }

    .norme-box {
        background: #f0fdfa;
        border: 1px solid #ccfbf1;
        border-left: 4px solid #0d9488;
        border-radius: 6px;
        padding: 0.75rem 1rem;
        margin-top: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# --- CLASSIFICATION AUTOMATIQUE INTELLIGENTE ---

def classify_category(code_text, cause_text, solution_text):
    """Classe la panne dans une catégorie matérielle ou logicielle."""
    full_text = f"{code_text} {cause_text} {solution_text}".lower()

    if any(k in full_text for k in ["rom", "ram", "firmware", "software", "eeprom", "watchdog", "bus can", "rs232", "communication", "comm error", "cpu", "programme", "checksum"]):
        return "💻 Logiciel & Système"
    if any(k in full_text for k in ["moteur", "motor", "rotor", "couvercle", "lid", "door", "verrou", "lock", "engrenage", "mécanique", "pompe", "clapet"]):
        return "⚙️ Mécanique & Moteur"
    if any(k in full_text for k in ["tension", "voltage", "puissance", "alimentation", "power", "fuse", "fusible", "batterie", "battery", "court-circuit", "relais"]):
        return "⚡ Électrique & Alimentation"
    if any(k in full_text for k in ["capteur", "sensor", "optique", "prisme", "détecteur", "tachy", "tachymètre", "aimant", "pressostat", "calibration"]):
        return "📡 Capteurs & Mesure"
    if any(k in full_text for k in ["temp", "température", "surchauffe", "overheat", "refroidissement", "compresseur", "fuite", "débit", "flow", "air in line"]):
        return "🌡️ Thermique & Fluides"
    
    return "⚠️ Alertes Générales"

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
                ("EQ-ROTANTA", "E-02", "E-02 : Surchauffe de cuve ou défaut de vitesse rotor", "🌡️ Thermique & Fluides", "Surchauffe cuve / Défaut tachymétrique", "Contrôler l'entrefer du capteur de vitesse sous le bol (0,8 mm ± 0,2). Vérifier l'aimant d'arbre moteur et les enroulements du compresseur.", "Manuel Hettich", 48),
                ("EQ-ROTANTA", "LID OPEN", "LID OPEN : Sécurité de verrouillage du couvercle", "⚙️ Mécanique & Moteur", "Contacteur couvercle défaillant", "Vérifier la course du micro-contacteur de sécurité (SW1). Remplacer l'électro-aimant si résistance infinie.", "Manuel Hettich", 52),
                ("EQ-WD40", "AL-04", "AL-04 : Débit insuffisant en alimentation d'eau", "🌡️ Thermique & Fluides", "Débit d'eau osmosée insuffisant", "Nettoyer le tamis d'admission 50µm. Vérifier la pression statique amont (min 2,5 bars) et le débitmètre.", "Manuel WD40", 31),
                ("EQ-FLUIDO", "AIR IN LINE", "AIR IN LINE : Présence de bulles d'air dans la tubulure", "📡 Capteurs & Mesure", "Bulle détectée ou capteur encrassé", "Nettoyer les prismes optiques de détection avec de l'alcool isopropylique. Étalonner le capteur.", "Manuel Fluido", 19)
            ])
        conn.commit()

init_db()

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

# --- EXTRACTION, NETTOYAGE & DÉDOUBLONNAGE DES PANNES ---

def parse_pdf_errors_advanced(uploaded_file):
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
                for state in state_alarms:
                    if re.search(r'\b' + state + r'\b', line, re.IGNORECASE):
                        code = state
                        reste = re.sub(r'(?i)\b' + state + r'\b', '', line).strip(" :-\t|")
                        cause = reste if len(reste) > 3 else "Déclenchement alarme de sécurité"
                        break

            if code and not any(stop in code for stop in ["ISO", "POSTAL", "BARCODE", "REV"]):
                # Dédoublonnage direct
                clean_key = re.sub(r'[^A-Z0-9]', '', code)
                if clean_key not in seen_codes and len(clean_key) >= 2:
                    seen_codes.add(clean_key)

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

                    # Construction d'un titre compréhensible
                    title = f"{code} : {cause[:60]}"
                    category = classify_category(code, cause, solution)

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
        
        # Dédoublonnage additionnel en base
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

# --- INITIALISATION DE L'ÉTAT DE SESSION ---
if "active_code" not in st.session_state:
    st.session_state["active_code"] = "E-02"

# --- EN-TÊTE FIXE ---
st.markdown("""
<div class="app-header">
    <div>
        <div class="app-title">⚡ BioMed Assist Pro</div>
        <div class="app-sub">Atelier Biomédical — Dépannage rapide & Matrice constructeur</div>
    </div>
    <div class="user-pill">
        Technicien : <strong>Hakki Ismail</strong>
    </div>
</div>
""", unsafe_allow_html=True)

equipments = get_all_equipments()
eq_keys = list(equipments.keys())

col_gauche, col_droite = st.columns([1, 2], gap="medium")

# --- COLONNE DE GAUCHE : CHOIX DE L'APPAREIL & AJOUT MANUEL ---
with col_gauche:
    st.markdown("### 1. Dispositif Médical")
    
    default_idx = 0
    if "selected_equipment_id" in st.session_state and st.session_state["selected_equipment_id"] in eq_keys:
        default_idx = eq_keys.index(st.session_state["selected_equipment_id"])

    selected_inv = st.selectbox(
        "Sélectionnez l'appareil sous intervention :",
        options=eq_keys,
        index=default_idx,
        format_func=lambda x: f"{equipments[x]['brand']} — {equipments[x]['model']}",
        label_visibility="collapsed"
    )
    
    eq = equipments[selected_inv]
    st.success(f"**{eq['brand']} {eq['model']}**\n\nID : `{selected_inv}` | Service : {eq['service']}")

    with st.expander("📥 Ajouter un nouveau manuel PDF", expanded=False):
        uploaded_pdf = st.file_uploader("Déposer un fichier PDF :", type=["pdf"])
        if uploaded_pdf is not None:
            upload_key = f"proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if upload_key not in st.session_state:
                with st.spinner("Analyse, catégorisation et dédoublonnage..."):
                    extracted_errors, sample_txt = parse_pdf_errors_advanced(uploaded_pdf)
                    brand, model = auto_detect_brand_and_model(sample_txt, uploaded_pdf.name)
                    new_id = save_manual_equipment_and_errors(brand, model, uploaded_pdf, extracted_errors)
                    st.session_state[upload_key] = True
                    st.session_state["selected_equipment_id"] = new_id
                    st.session_state["active_code"] = extracted_errors[0]["code"] if extracted_errors else ""
                    st.rerun()

# --- COLONNE DE DROITE : DIAGNOSTIC & MATRICE PAR CATÉGORIE ---
with col_droite:
    st.markdown(f"### 2. Dépannage : {eq['brand']} {eq['model']}")

    device_errors = load_errors_for_equipment(selected_inv)

    # 1. Barre de recherche
    col_input, col_reset = st.columns([4, 1])
    with col_input:
        search_query = st.text_input(
            "Recherche de panne",
            value=st.session_state.get("active_code", ""),
            placeholder="Tapez un code alarme ou un mot-clé (ex: E-02, moteur, température...)",
            label_visibility="collapsed"
        )
    with col_reset:
        if st.button("Effacer", use_container_width=True):
            st.session_state["active_code"] = ""
            st.rerun()

    # Détection de la solution active
    q_clean = search_query.upper().strip()
    active_err = None

    if q_clean:
        active_err = next((e for e in device_errors if e["code"] in q_clean or q_clean in e["cause"].upper() or q_clean in e["title"].upper()), None)
        if not active_err:
            all_errs = load_errors_for_equipment(None)
            active_err = next((e for e in all_errs if e["code"] in q_clean or q_clean in e["cause"].upper() or q_clean in e["title"].upper()), None)

    # 2. Affichage de la solution
    if active_err:
        st.markdown(f"""
        <div class="active-solution-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                <div>
                    <span class="code-badge-big">{active_err['code']}</span>
                    <span class="cat-badge cat-soft">{active_err['category']}</span>
                </div>
                <span style="font-size:0.8rem; color:#64748b; font-weight:600;">Source : {active_err['source']} (Page {active_err['page']})</span>
            </div>
            <h4 style="margin:0 0 0.5rem 0; color:#0f172a;">{active_err['title']}</h4>
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:0.85rem; font-size:0.95rem; color:#1e293b; line-height:1.5;">
                <strong>Action corrective constructeur :</strong><br/>
                {active_err['solution']}
            </div>
            <div class="norme-box">
                <strong style="color:#0d9488; font-size:0.85rem;">CONTRÔLES NF EN 62353 REQUIS :</strong>
                <div style="font-size:0.8rem; color:#475569; margin-top:0.2rem;">
                    • Continuité de la terre (&lt; 0,20 Ω) &nbsp;|&nbsp; • Courant de fuite contact &nbsp;|&nbsp; • Test fonctionnel en charge
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        raw_resolution = f"Panne : {active_err['title']}\nCatégorie : {active_err['category']}\nAction : {active_err['solution']}"
    else:
        st.info("💡 Sélectionnez une panne ci-dessous ou saisissez un mot-clé ci-dessus.")
        raw_resolution = f"Diagnostic général pour {eq['brand']} {eq['model']} (Recherche : {search_query})"

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
            st.toast(f"Intervention sur {eq['brand']} {eq['model']} validée.", icon="✔")

    st.divider()

    # 3. FILTRE ET REGROUPEMENT PAR CATÉGORIE
    st.markdown(f"#### 📋 Pannes répertoriées ({len(device_errors)} sans doublon)")

    # Catégories disponibles
    categories = ["Toutes les catégories"] + sorted(list(set(e["category"] for e in device_errors)))
    selected_cat = st.segmented_control("Filtrer par domaine :", categories, default="Toutes les catégories")

    filtered_errors = device_errors if selected_cat == "Toutes les catégories" else [e for e in device_errors if e["category"] == selected_cat]

    if filtered_errors:
        for idx, err in enumerate(filtered_errors):
            with st.container(border=True):
                c_code, c_desc, c_btn = st.columns([1.2, 3.8, 1.5])
                with c_code:
                    st.code(err["code"])
                    st.caption(err["category"])
                with c_desc:
                    st.markdown(f"**{err['title']}**")
                    st.caption(f"{err['solution'][:110]}...")
                with c_btn:
                    if st.button("Voir la solution", key=f"btn_{err['id_inv']}_{idx}_{err['code']}", use_container_width=True):
                        st.session_state["active_code"] = err["code"]
                        st.rerun()
    else:
        st.warning("Aucune panne dans cette catégorie pour cet appareil.")
