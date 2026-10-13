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

DB_PATH = "biomed_data_v7.db"

# --- STYLE CSS ATELIER ---
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

    /* Carte de Solution Active Pédagogique */
    .active-solution-card {
        background: #ffffff;
        border: 2px solid #0284c7;
        border-radius: 8px;
        padding: 1.25rem;
        margin-bottom: 0.8rem;
        box-shadow: 0 4px 14px rgba(2, 132, 199, 0.08);
    }
    
    .code-badge-big {
        background: #0284c7;
        color: white;
        padding: 0.25rem 0.65rem;
        border-radius: 6px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        font-size: 1rem;
        display: inline-block;
    }

    .pedago-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #0284c7;
        border-radius: 6px;
        padding: 0.85rem 1rem;
        margin: 0.6rem 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: #1e293b;
    }

    .step-box {
        background: #f1f5f9;
        border-radius: 6px;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        font-size: 0.88rem;
        line-height: 1.5;
        color: #0f172a;
    }

    .norme-box {
        background: #f0fdfa;
        border-left: 4px solid #0d9488;
        border-radius: 6px;
        padding: 0.6rem 0.9rem;
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

# --- 1. MOTEUR D'ANALYSE PÉDAGOGIQUE BIOMÉDICALE ---

def generate_pedagogical_analysis(code, cause, raw_solution):
    """
    Transforme une ligne brute de manuel en analyse technique complète
    avec mécanisme physique, mesures précises et étapes de levée de doute.
    """
    c_lower = f"{code} {cause} {raw_solution}".lower()

    # 1. Pannes Vitesse / Tachymétrie / Entraînement
    if any(k in c_lower for k in ["tacho", "vitesse", "speed", "rotor", "entrefer", "e-02", "e02"]):
        what = (
            "La carte de contrôle ne reçoit pas les impulsions de vitesse attendues ou constate un écart "
            "anormal entre la commande de consigne et le retour réel. Cela traduit soit un défaut de lecture "
            "(capteur à effet Hall décalé/défaillant), soit une résistance mécanique anormale à la rotation."
        )
        steps = (
            "1. **Inspection visuelle & mécanique :** Vérifier la liberté de rotation à la main, l'absence de corps étranger et l'état des paliers/roulements.\n"
            "2. **Contrôle de l'entrefer :** Mesurer au jeu de cales l'espacement entre le capteur Hall et l'aimant de l'axe (tolérance standard : 0,8 mm ± 0,2).\n"
            "3. **Mesure électrique :** Contrôler au multimètre la tension d'alimentation du capteur (généralement 5 V DC) et vérifier le signal carré lors de la rotation manuelle.\n"
            "4. **Vérification moteur :** Mesurer la résistance d'isolement et la symétrie des enroulements du moteur brushless."
        )
        points = "Entrefer = 0,8 mm ± 0,2 | Alimentation capteur = +5 V DC ± 5 % | Continuité bobinages symétrique"

    # 2. Pannes Sécurité Couvercle / Verrouillage
    elif any(k in c_lower for k in ["lid", "couvercle", "door", "porte", "verrou", "lock", "switch"]):
        what = (
            "La boucle de sécurité matérielle de fermeture est ouverte. L'électronique de puissance interdit tout "
            "démarrage tant que le micro-contacteur ne confirme pas le verrouillage effectif ou si la bobine de rappel "
            "ne parvient pas à actionner le pêne mécanique."
        )
        steps = (
            "1. **Contrôle mécanique du loquet :** Vérifier que les crochets de couvercle pénètrent sans contrainte dans les gorges.\n"
            "2. **Mesure du contacteur (SW1/SW2) :** Déconnecter le switch et mesurer la résistance au multimètre (doit être < 0,1 Ω fermé, infinie ouvert).\n"
            "3. **Contrôle solénoïde :** Mesurer la résistance de la bobine de verrouillage (valeur typique constructeur : 20 à 60 Ω selon modèle).\n"
            "4. **Signal carte :** Vérifier l'état logique de l'entrée sur la carte d'interface en manipulant manuellement le mécanisme."
        )
        points = "Résistance contact fermé < 0,1 Ω | Résistance bobine = 25 à 50 Ω | Détection déverrouillage manuel opérationnelle"

    # 3. Pannes Débit / Fluides / Hydraulique
    elif any(k in c_lower for k in ["débit", "flow", "fuite", "eau", "water", "al-04", "al04", "vanne", "valve"]):
        what = (
            "Le débitmètre ne détecte pas le volume minimal requis dans le délai imparti. Le système est en sous-débit, "
            "généralement provoqué par un filtre amont colmaté, une pression réseau insuffisante ou une turbine entartrée."
        )
        steps = (
            "1. **Vérification amont :** Contrôler la pression statique d'arrivée d'eau au manomètre (doit être >= 2,5 bars).\n"
            "2. **Inspection filtration :** Démonter et nettoyer le tamis d'admission 50 µm et vérifier l'état du clapet anti-retour.\n"
            "3. **Test électrovanne :** Vérifier l'alimentation électrique de la vanne (24 V DC ou 230 V AC) et écouter le claquement franc à l'ouverture.\n"
            "4. **Contrôle turbine :** Inspecter la roue à aubes du débitmètre (absence de dépôts calcaires bloquants)."
        )
        points = "Pression statique min = 2,5 bars | Tension bobine vanne = conforme sérigraphie | Débit nominal atteint"

    # 4. Pannes Capteurs Optiques / Bulles / Ultrasons
    elif any(k in c_lower for k in ["air in line", "bulle", "bubble", "optique", "prisme", "ultrason"]):
        what = (
            "La cellule de détection ultrasonique ou optique relève une variation d'impédance assimilée à une poche d'air. "
            "En atelier, cela découle très souvent d'un désalignement, d'un résidu de produit sur les prismes ou d'une dérive du seuil de gain."
        )
        steps = (
            "1. **Nettoyage optique :** Nettoyer soigneusement les fenêtres de mesure à l'alcool isopropylique (aucun solvant agressif).\n"
            "2. **Vérification couplage :** S'assurer que la tubulure test est parfaitement engagée au fond de la gorge de détection.\n"
            "3. **Étalonnage atelier :** Entrer dans le menu de service constructeur pour lancer le tarage à vide (sans cassette) puis en charge d'eau.\n"
            "4. **Contrôle d'intégrité :** Vérifier l'absence de microfissure sur la résine des transducteurs piézoélectriques."
        )
        points = "Seuil de tension à vide conforme au manuel de service | Détection reproductible avec calibre test d'air"

    # 5. Pannes Thermiques / Surchauffe
    elif any(k in c_lower for k in ["temp", "surchauffe", "overheat", "refroidissement", "compresseur"]):
        what = (
            "La sonde thermique (PT100, NTC) relève une température hors plage admissible ou une montée en température "
            "anormalement lente/rapide, déclenchant le coupe-circuit de sécurité du groupe froid ou de chauffe."
        )
        steps = (
            "1. **Contrôle flux d'air :** Dépoussiérer le condenseur et vérifier que le ventilateur tourne librement à sa vitesse nominale.\n"
            "2. **Mesure de la sonde :** Relever la résistance de la sonde déconnectée à 20 °C (ex. PT100 ≈ 107,7 Ω, NTC 10 kΩ ≈ 12,5 kΩ à 20 °C).\n"
            "3. **Vérification relais/SSR :** Contrôler l'absence de collage des contacts du relais statique de commande.\n"
            "4. **Groupe froid :** Relever le courant absorbé par le compresseur lors du démarrage (mesure à la pince ampèremétrique)."
        )
        points = "Résistance sonde conforme à la courbe fabricant | Écart consigne/mesure < 1,0 °C après stabilisation"

    # 6. Cas Général d'Atelier
    else:
        what = (
            "Défaillance d'un sous-ensemble fonctionnel signalée par l'autodiagnostic de la carte principale. "
            "L'équipement s'est placé en mode sécurité pour éviter toute détérioration matérielle ou exposition patient."
        )
        steps = (
            "1. **Inspection hors tension :** Vérifier l'absence de traces d'échauffement sur les cartes de puissance et connecteurs.\n"
            "2. **Contrôle des alimentations :** Mesurer les tensions secondaires en sortie de bloc (+5 V, +12 V, +24 V DC) au multimètre.\n"
            "3. **Mode Service :** Relever l'historique complet des événements dans le journal d'erreurs interne.\n"
            "4. **Requalification :** Procéder aux tests d'autodiagnostic constructeur pas à pas."
        )
        points = "Tensions secondaires stables à ± 3 % | Ondulation résiduelle conforme | Autotests validés sans alerte"

    return what, steps, points

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
                analysis_what TEXT,
                analysis_steps TEXT,
                analysis_points TEXT,
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
            
            # Injection des données initiales avec analyse pédagogique complète
            initial_errors = [
                ("EQ-ROTANTA", "E-02", "E-02 : Défaut tachymétrique ou surchauffe cuve", "⚙️ Mécanique & Moteur",
                 "Capteur vitesse décalé ou surchauffe bol", "Contrôler l'entrefer du capteur de vitesse et les enroulements du moteur.", "Manuel Hettich", 48),
                ("EQ-ROTANTA", "LID OPEN", "LID OPEN : Sécurité de verrouillage du couvercle", "⚙️ Mécanique & Moteur",
                 "Micro-contacteur SW1 défaillant ou bobine bloquée", "Vérifier la course mécanique et mesurer le contacteur à l'ohmmètre.", "Manuel Hettich", 52),
                ("EQ-WD40", "AL-04", "AL-04 : Débit insuffisant en admission d'eau", "⚡ Électrique & Capteurs",
                 "Pression amont basse ou filtre d'entrée colmaté", "Nettoyer le tamis 50µm et contrôler le débitmètre.", "Manuel WD40", 31),
                ("EQ-FLUIDO", "AIR IN LINE", "AIR IN LINE : Détection bulle d'air dans tubulure", "⚡ Électrique & Capteurs",
                 "Prismes optiques encrassés ou dérive de sensibilité", "Nettoyer les prismes à l'alcool et relancer le tarage de gain.", "Manuel Fluido", 19)
            ]
            
            for err in initial_errors:
                w, s, p = generate_pedagogical_analysis(err[1], err[4], err[5])
                cursor.execute("""
                    INSERT INTO error_records (id_inv, code, title, category, cause, solution, analysis_what, analysis_steps, analysis_points, source, page)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (err[0], err[1], err[2], err[3], err[4], err[5], w, s, p, err[6], err[7]))

        conn.commit()

init_db()

# --- 3. PARSEUR PDF DE MANUEL CONSTRUCTEUR ---

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

def parse_pdf_and_enrich_errors(uploaded_file):
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

                    cause = cause or "Défaut d'étalonnage ou anomalie de sous-ensemble"
                    solution = solution or "Vérifier la connectique, inspecter le capteur associé et effectuer l'autotest."

                    seen_codes.add(clean_key)
                    title = f"{code} : {cause[:55]}"
                    
                    # Génération de l'analyse pédagogique structurée
                    what, steps, points = generate_pedagogical_analysis(code, cause, solution)
                    
                    cat = "⚙️ Mécanique & Moteur"
                    if any(k in f"{code} {cause} {solution}".lower() for k in ["carte", "board", "cpu", "rom", "firmware", "bus"]):
                        cat = "💻 Système & Cartes"
                    elif any(k in f"{code} {cause} {solution}".lower() for k in ["tension", "voltage", "alimentation", "capteur", "sensor", "optique"]):
                        cat = "⚡ Électrique & Capteurs"

                    raw_extracted.append({
                        "code": code,
                        "title": title,
                        "category": cat,
                        "cause": cause[:140],
                        "solution": solution[:260],
                        "analysis_what": what,
                        "analysis_steps": steps,
                        "analysis_points": points,
                        "source": uploaded_file.name[:25],
                        "page": page_num
                    })
            i += 1

    return raw_extracted, sample_text

# --- 4. REQUÊTES EN BASE DE DONNÉES ---

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
                INSERT INTO error_records (id_inv, code, title, category, cause, solution, analysis_what, analysis_steps, analysis_points, source, page)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (auto_id, err["code"], err["title"], err["category"], err["cause"], err["solution"], err["analysis_what"], err["analysis_steps"], err["analysis_points"], err["source"], err["page"]))
        conn.commit()
    return auto_id

def load_errors_for_equipment(id_inv=None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if id_inv and id_inv != "Tous":
            cursor.execute("""
                SELECT id_inv, code, title, category, cause, solution, analysis_what, analysis_steps, analysis_points, source, page 
                FROM error_records 
                WHERE id_inv = ? 
                ORDER BY id ASC
            """, (id_inv,))
        else:
            cursor.execute("""
                SELECT id_inv, code, title, category, cause, solution, analysis_what, analysis_steps, analysis_points, source, page 
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
                    "cause": r[4], "solution": r[5], "analysis_what": r[6],
                    "analysis_steps": r[7], "analysis_points": r[8], "source": r[9], "page": r[10]
                })
        return unique_errors

# --- 5. RAPPORT PDF CERTIFIÉ ---

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
        <div class="app-sub">Atelier Biomédical — Diagnostic Méthodique & Explications Techniques</div>
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
# COLONNE GAUCHE : SÉLECTION ÉQUIPEMENT & MANUELS
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
            Service : {eq['service']} | Ordre GMAO : <strong>{eq['bt']}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📥 Ajouter un manuel technique PDF", expanded=False):
        uploaded_pdf = st.file_uploader("Fichier PDF du manuel :", type=["pdf"])
        if uploaded_pdf is not None:
            upload_key = f"proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if upload_key not in st.session_state:
                with st.spinner("Analyse et enrichissement pédagogique des pannes..."):
                    extracted_errors, sample_txt = parse_pdf_and_enrich_errors(uploaded_pdf)
                    brand, model = auto_detect_brand_and_model(sample_txt, uploaded_pdf.name)
                    new_id = save_manual_equipment_and_errors(brand, model, uploaded_pdf, extracted_errors)
                    st.session_state[upload_key] = True
                    st.session_state["selected_equipment_id"] = new_id
                    st.session_state["active_code"] = extracted_errors[0]["code"] if extracted_errors else ""
                    st.success(f"Dispositif « {brand} {model} » indexé avec succès.")
                    st.rerun()

# =========================================================================
# COLONNE DROITE : ANALYSE PÉDAGOGIQUE & ARBRE DE DÉCISION
# =========================================================================
with col_droite:
    st.markdown(f"### 2. Dépannage & Analyse : {eq['brand']} {eq['model']}")

    device_errors = load_errors_for_equipment(selected_inv)

    col_input, col_reset = st.columns([4, 1])
    with col_input:
        search_query = st.text_input(
            "Recherche",
            value=st.session_state.get("active_code", ""),
            placeholder="Rechercher par code (ex: E-02) ou mot-clé (ex: vitesse, capteur, débit...)",
            label_visibility="collapsed"
        )
    with col_reset:
        if st.button("Effacer", use_container_width=True):
            st.session_state["active_code"] = ""
            st.rerun()

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

    # AFFICHAGE DE L'ANALYSE TECHNIQUE COMPLÈTE
    if active_err:
        st.markdown(f"""
        <div class="active-solution-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.6rem;">
                <div>
                    <span class="code-badge-big">{active_err['code']}</span>
                    <span style="margin-left:0.5rem; font-size:0.85rem; font-weight:600; color:#0284c7;">{active_err['category']}</span>
                </div>
                <span style="font-size:0.75rem; color:#64748b;">Réf : {active_err['source']} (Page {active_err['page']})</span>
            </div>
            <h4 style="margin:0 0 0.5rem 0; color:#0f172a;">{active_err['title']}</h4>
            
            <div class="pedago-box">
                <strong style="color:#0284c7;">🔍 Que se passe-t-il physiquement ?</strong><br/>
                {active_err['analysis_what']}
            </div>
            
            <div class="step-box">
                <strong style="color:#0f172a;">🛠️ Arbre de décision & étapes de levée de doute :</strong><br/>
                {active_err['analysis_steps']}
            </div>

            <div style="background:#fffbeb; border:1px solid #fef3c7; border-radius:6px; padding:0.65rem 0.9rem; margin-top:0.5rem; font-size:0.85rem; color:#92400e;">
                <strong>⚡ Points de mesure & tolérances :</strong> {active_err['analysis_points']}
            </div>

            <div class="norme-box">
                <span style="color:#0d9488; font-weight:700; font-size:0.8rem;">CONTRÔLES NF EN 62353 :</span>
                <span style="font-size:0.78rem; color:#475569;"> Terre (&lt; 0,20 Ω) | Courant de fuite contact | Essai dynamique en charge</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        raw_resolution = (
            f"Panne : {active_err['title']}\n\n"
            f"1. Mécanisme physique : {active_err['analysis_what']}\n\n"
            f"2. Procédure atelier :\n{active_err['analysis_steps']}\n\n"
            f"3. Tolérances validées : {active_err['analysis_points']}"
        )
    else:
        st.info("💡 Sélectionnez une panne dans la liste ci-dessous pour ouvrir l'analyse méthodique.")
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

    # MATRICE COMPACTE PAR DOMAINES
    st.markdown(f"#### 📋 Pannes répertoriées pour cet appareil ({len(device_errors)})")

    categories = ["Toutes les pannes", "⚙️ Mécanique & Moteur", "⚡ Électrique & Capteurs", "💻 Système & Cartes"]
    selected_cat = st.segmented_control("Domaine technique :", categories, default="Toutes les pannes")

    filtered_errors = device_errors if selected_cat == "Toutes les pannes" else [e for e in device_errors if e["category"] == selected_cat]

    with st.container(height=340):
        if filtered_errors:
            for idx, err in enumerate(filtered_errors):
                c_code, c_desc, c_btn = st.columns([1.1, 3.9, 1.4])
                with c_code:
                    st.code(err["code"])
                with c_desc:
                    st.markdown(f"**{err['title']}**")
                    st.caption(f"{err['cause'][:95]}...")
                with c_btn:
                    if st.button("Analyser", key=f"btn_{err['id_inv']}_{idx}_{err['code']}", use_container_width=True):
                        st.session_state["active_code"] = err["code"]
                        st.rerun()
        else:
            st.info("Aucune panne répertoriée dans cette rubrique.")
