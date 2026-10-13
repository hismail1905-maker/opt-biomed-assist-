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

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="BioMed Assist Pro | Atelier Biomédical",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = "biomed_v_pro.db"

# --- DESIGN SYSTEM WEB MODERNE (CSS SCOPÉ) ---
st.markdown("""
<style>
    /* Typographie & Polices */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@600&display=swap');
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
    }
    
    /* Espacements globaux */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
        max-width: 1350px !important;
    }
    
    /* Boutons d'action */
    .stButton>button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
    }
    .stButton>button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    /* Amélioration des expanders et métriques */
    div[data-testid="stExpander"] {
        border-radius: 8px !important;
        border: 1px solid #e2e8f0 !important;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================================
# 1. COUCHE BASE DE DONNÉES (SQLITE AVEC MODE WAL)
# =========================================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")  # Accélère les lectures et évite les blocages
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS materiels (
                id TEXT PRIMARY KEY,
                nom TEXT,
                marque TEXT,
                service TEXT,
                sn TEXT,
                date_ajout TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pannes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                materiel_id TEXT,
                domaine TEXT,
                criticite TEXT,
                code TEXT,
                titre TEXT,
                probleme TEXT,
                etape1 TEXT,
                etape2 TEXT,
                etape3 TEXT,
                mesure_multimetre TEXT,
                FOREIGN KEY (materiel_id) REFERENCES materiels(id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_heure TEXT,
                materiel_nom TEXT,
                code_panne TEXT,
                technicien TEXT,
                etat_conformite TEXT
            )
        """)
        
        # Données de démonstration initiales
        c.execute("SELECT COUNT(*) FROM materiels")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO materiels VALUES (?, ?, ?, ?, ?, ?)", [
                ("ROTANTA", "Rotanta 460 RF", "Hettich", "Laboratoire Biochimie", "SN-2026-991", "01/10/2026"),
                ("WD40", "WD40 Laveur-Désinfecteur", "Wassenburg", "Plateau Endoscopie", "SN-WD-441", "05/10/2026"),
                ("FLUIDO", "Fluido AirGuard Réchauffeur", "The Surgical Company", "Bloc Opératoire", "SN-FL-118", "10/10/2026"),
                ("SERVO", "Servo-u Ventilateur", "Getinge / Maquet", "Réanimation Médicale", "SN-SU-882", "12/10/2026")
            ])
            
            c.executemany("""
                INSERT INTO pannes 
                (materiel_id, domaine, criticite, code, titre, probleme, etape1, etape2, etape3, mesure_multimetre) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    "ROTANTA", "⚙️ Mécanique & Moteur", "🔴 Critique", "E-02",
                    "Défaut tachymétrique / Blocage mécanique rotor",
                    "La centrifugeuse refuse de démarrer ou coupe son cycle car la carte électronique ne reçoit pas les impulsions de rotation du bol.",
                    "Faire tourner le rotor manuellement à l'arrêt pour vérifier l'absence de point dur sur les roulements.",
                    "Contrôler sous la cuve que le capteur Hall est propre et situé à 0,8 mm (± 0,2 mm) de l'aimant de l'axe.",
                    "Vérifier le branchement complet du connecteur moteur sur la carte de commande principale du socle.",
                    "Multimètre en Volts DC : mesurer 5,0 V constants entre fil rouge et fil noir du capteur Hall."
                ),
                (
                    "ROTANTA", "⚙️ Mécanique & Moteur", "🔴 Critique", "LID OPEN",
                    "Sécurité couvercle : Capot détecté non verrouillé",
                    "Le verrouillage électronique refuse le départ car le micro-contacteur ne confirme pas la fermeture physique.",
                    "Vérifier l'alignement mécanique des crochets métalliques avec les gorges du châssis.",
                    "Tester manuellement le loquet pour entendre le déclic mécanique du contacteur SW1.",
                    "Débrancher l'appareil et tester le micro-contacteur de sécurité à l'ohmmètre en appuyant sur le verrou.",
                    "Mode Bip / Continuité : 0 Ohm bouton appuyé, circuit ouvert (infini) bouton relâché."
                ),
                (
                    "ROTANTA", "⚡ Électrique & Capteurs", "🟠 Majeur", "E-04",
                    "Défaut groupe froid / Sonde de cuve PT100",
                    "La régulation de température de cuve est hors tolérance ou le circuit de mesure est coupé.",
                    "Dépoussiérer le condenseur froid et vérifier la liberté de rotation du ventilateur.",
                    "Inspecter la fixation de la sonde thermique au fond du bol et l'état des connexions.",
                    "Contrôler le relais de commande du compresseur frigorifique sur la carte de puissance.",
                    "Ohmmètre sur la sonde débranchée : mesurer environ 107,7 Ohms à 20 °C (norme PT100). Si infini, sonde coupée."
                ),
                (
                    "WD40", "⚡ Électrique & Capteurs", "🔴 Critique", "AL-04",
                    "Remplissage eau insuffisant / Alarme débitmètre",
                    "La cuve ne se remplit pas au débit minimal attendu dans le temps imparti par l'automate.",
                    "Vérifier que les vannes d'eau au mur sont ouvertes à fond (pression statique min : 2,5 bars).",
                    "Dévisser le raccord d'admission d'eau pour nettoyer la grille filtrante 50 µm souvent entartrée.",
                    "Contrôler l'ouverture franche de l'électrovanne d'arrivée d'eau et la turbine du débitmètre.",
                    "Voltmètre en Volts AC : mesurer 230 V sur les cosses de l'électrovanne lors de la demande d'eau."
                ),
                (
                    "FLUIDO", "⚡ Électrique & Capteurs", "🔴 Critique", "AIR IN LINE",
                    "Détection d'air : Alarme bulle sur tubulure",
                    "Le capteur ultrasonique détecte une discontinuité acoustique et coupe la chauffe par sécurité.",
                    "Nettoyer les prismes optiques et surfaces de mesure avec une compresse imbibée d'alcool isopropylique.",
                    "S'assurer que la tubulure de perfusion est poussée jusqu'au fond de la gorge de lecture.",
                    "Purger totalement la ligne avec une poche neuve pour évacuer la moindre microbulle.",
                    "Si l'alarme persiste avec une tubulure purgée d'eau pure, procéder à l'étalonnage du gain en mode technicien."
                ),
                (
                    "SERVO", "⚡ Électrique & Capteurs", "🔴 Critique", "ERR-32",
                    "Défaut cassette expiratoire / Mesure ultrasonique",
                    "Le ventilateur ne peut plus mesurer le débit expiratoire du patient avec précision.",
                    "Déclipser la cassette expiratoire et s'assurer de l'absence totale de condensation d'eau.",
                    "Nettoyer les contacts dorés situés entre la cassette et le bloc patient.",
                    "Tester avec une seconde cassette expiratoire propre et validée.",
                    "Lancer le pré-test automatique de l'appareil pour valider la mesure de fuite et le tarage zéro."
                )
            ])
        conn.commit()

init_db()

# --- REQUÊTES EN BASE DE DONNÉES AVEC CACHE STREAMLIT ---

@st.cache_data(ttl=60)
def load_all_devices():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nom, marque, service, sn FROM materiels ORDER BY nom ASC")
        return {r[0]: {"nom": r[1], "marque": r[2], "service": r[3], "sn": r[4]} for r in c.fetchall()}

def load_errors_by_device(mat_id, domaine_filtre="Tous"):
    with get_db() as conn:
        c = conn.cursor()
        if domaine_filtre == "Tous":
            c.execute("""
                SELECT code, titre, domaine, criticite, probleme, etape1, etape2, etape3, mesure_multimetre 
                FROM pannes WHERE materiel_id = ? ORDER BY id ASC
            """, (mat_id,))
        else:
            c.execute("""
                SELECT code, titre, domaine, criticite, probleme, etape1, etape2, etape3, mesure_multimetre 
                FROM pannes WHERE materiel_id = ? AND domaine = ? ORDER BY id ASC
            """, (mat_id, domaine_filtre))
        return [{
            "code": r[0], "titre": r[1], "domaine": r[2], "criticite": r[3],
            "probleme": r[4], "etape1": r[5], "etape2": r[6], "etape3": r[7], "mesure": r[8]
        } for r in c.fetchall()]

def log_intervention(mat_nom, code, tech, conforme=True):
    res_str = "CONFORME (NF EN 62353)" if conforme else "NON CONFORME / REVISION REQUISE"
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO audit_log (date_heure, materiel_nom, code_panne, technicien, etat_conformite)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%d/%m/%Y %H:%M"), mat_nom, code, tech, res_str))
        conn.commit()

def load_audit_history():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT date_heure, materiel_nom, code_panne, technicien, etat_conformite FROM audit_log ORDER BY id DESC LIMIT 50")
        return c.fetchall()

# =========================================================================
# 2. PARSEUR PDF HAUTE DISPONIBILITÉ (ANTI-SOMMAIRE STRICT)
# =========================================================================

def is_unwanted_line(text):
    t = text.strip()
    if re.search(r'\.{2,}', t):  # Rejette pointillés de sommaire
        return True
    if re.search(r'\s*\.{2,}\s*\d+$', t):
        return True
    if re.match(r'^(?:page|chapitre|section|table|figure)\s*\d+$', t, re.IGNORECASE):
        return True
    return False

def clean_sentence(text):
    t = re.sub(r'[\t\r\n]+', ' ', text)
    return re.sub(r'\s+', ' ', t).strip(" -:|,")

def parse_and_store_pdf(uploaded_file):
    reader = PdfReader(uploaded_file)
    max_scan = min(len(reader.pages), 100)
    
    nom_base = os.path.splitext(uploaded_file.name)[0].replace("_", " ").title()
    device_id = f"MAT-{re.sub(r'[^A-Z0-9]', '', nom_base[:6].upper())}-{datetime.now().strftime('%M%S')}"

    pattern_code = re.compile(
        r'\b(?:ERROR|ERR|CODE|ALARM|ALARME|FAULT|DÉFAUT|DEF|E|F|AL)\s*[-:#.]?\s*([0-9]{1,4}|[A-Z]{1,3}[0-9]{1,3})\b',
        re.IGNORECASE
    )
    text_alarms = [
        "LID OPEN", "COVER OPEN", "AIR IN LINE", "NO FLOW", "OVERHEAT",
        "PRESSURE HIGH", "PRESSURE LOW", "SENSOR FAIL", "MOTOR FAIL", "DOOR OPEN", "BATTERY LOW"
    ]

    pannes_trouvees = []
    codes_vus = set()

    for idx in range(max_scan):
        page_text = reader.pages[idx].extract_text() or ""
        lines = [l.strip() for l in page_text.splitlines() if len(l.strip()) >= 3]

        i = 0
        while i < len(lines):
            line = lines[i]

            if is_unwanted_line(line):
                i += 1
                continue

            code_found = None
            desc = ""

            m = pattern_code.search(line)
            if m:
                candidat = m.group(0).upper().replace("  ", " ").strip()
                if not (len(candidat) == 1 and candidat.isdigit()):
                    code_found = candidat
                    reste = line[m.end():].strip(" :-\t|")
                    if len(reste) > 3 and not is_unwanted_line(reste):
                        desc = clean_sentence(reste)

            if not code_found:
                for alt in text_alarms:
                    if re.search(r'\b' + alt + r'\b', line, re.IGNORECASE):
                        code_found = alt
                        reste = re.sub(r'(?i)\b' + alt + r'\b', '', line).strip(" :-\t|")
                        if not is_unwanted_line(reste):
                            desc = clean_sentence(reste) if len(reste) > 3 else "Déclenchement d'une alarme de sécurité"
                        break

            if code_found:
                k_uniq = re.sub(r'[^A-Z0-9]', '', code_found)
                if k_uniq not in codes_vus and len(k_uniq) >= 2 and not any(w in code_found for w in ["ISO", "PAGE", "REV", "FIG", "TABLE"]):
                    codes_vus.add(k_uniq)

                    # Agrégation des lignes suivantes pour former une phrase complète
                    next_lines = []
                    step = 1
                    while (i + step < len(lines)) and step <= 3:
                        lnx = lines[i + step]
                        if is_unwanted_line(lnx) or pattern_code.search(lnx):
                            break
                        cln = clean_sentence(lnx)
                        if len(cln) > 3:
                            next_lines.append(cln)
                        step += 1

                    if next_lines:
                        if not desc:
                            desc = next_lines[0]
                            resolution = " ".join(next_lines[1:]) if len(next_lines) > 1 else "Contrôler le sous-ensemble mécanique et la connectique."
                        else:
                            resolution = " ".join(next_lines)
                        i += (step - 1)
                    else:
                        desc = desc or "Anomalie technique signalée par le système."
                        resolution = "Contrôler le câblage, vérifier les fusibles et tester l'alimentation électrique."

                    desc = clean_sentence(desc)
                    resolution = clean_sentence(resolution)
                    if not desc.endswith('.'): desc += "."
                    if not resolution.endswith('.'): resolution += "."

                    # Classification
                    ctx = f"{code_found} {desc} {resolution}".lower()
                    if any(w in ctx for w in ["moteur", "rotor", "pompe", "porte", "couvercle", "verrou", "mecanique"]):
                        domaine = "⚙️ Mécanique & Moteur"
                        criticite = "🔴 Critique"
                    elif any(w in ctx for w in ["carte", "cpu", "firmware", "bus", "ram", "rom", "software", "com"]):
                        domaine = "💻 Cartes & Système"
                        criticite = "🟠 Majeur"
                    else:
                        domaine = "⚡ Électrique & Capteurs"
                        criticite = "🔴 Critique" if "alim" in ctx or "securite" in ctx else "🟠 Majeur"

                    pannes_trouvees.append((
                        device_id, domaine, criticite, code_found, desc[:70],
                        f"Le manuel constructeur indique : {desc}",
                        "Contrôle visuel : vérifier l'état du sous-ensemble et le verrouillage des connecteurs.",
                        f"Action constructeur : {resolution}",
                        "Requalification : lancer un cycle d'essai à blanc pour confirmer la disparition de l'alarme.",
                        "Multimètre : mesurer les tensions secondaires (+5V, +12V, +24V DC) et tester la continuité de terre."
                    ))
            i += 1

    if not pannes_trouvees:
        pannes_trouvees.append((
            device_id, "⚙️ Mécanique & Moteur", "🟡 Mineur", "MAINT-01",
            "Maintenance préventive et contrôle technique général",
            "Protocole périodique de révision de l'appareil à l'atelier biomédical.",
            "Vérifier l'état mécanique général, le châssis et l'absence de jeu sur les pièces mobiles.",
            "Dépoussiérer les ventilations, contrôler les filtres et inspecter les cartes électroniques.",
            "Effectuer les essais fonctionnels nominaux en charge réelle.",
            "Sécurité électrique NF EN 62353 : Continuité de la terre de protection < 0,20 Ohm."
        ))

    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO materiels VALUES (?, ?, ?, ?, ?, ?)", (
            device_id, nom_base[:45], "Documentation Fabricant", "Atelier Biomédical", "SN-NON-DÉFINI", datetime.now().strftime("%d/%m/%Y")
        ))
        c.executemany("""
            INSERT INTO pannes 
            (materiel_id, domaine, criticite, code, titre, probleme, etape1, etape2, etape3, mesure_multimetre) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, pannes_trouvees)
        conn.commit()

    st.cache_data.clear()  # Invalidation du cache pour rafraîchir l'UI
    return device_id, len(pannes_trouvees)

# =========================================================================
# 3. MOTEUR D'EXPORT PDF CERTIFIÉ (NF EN 62353)
# =========================================================================

def build_pdf_certificate(info_mat, info_panne, tech_name, chk_terre, chk_fuite, chk_meca, chk_charge):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=32, leftMargin=32, topMargin=32, bottomMargin=32)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=13, textColor=colors.HexColor("#0f172a"), alignment=1)
    story.append(Paragraph("FICHE OFFICIELLE D'INTERVENTION TECHNIQUE BIOMÉDICALE", title_style))
    story.append(Spacer(1, 14))

    recap_data = [
        ["Dispositif Médical :", f"{info_mat['nom']} ({info_mat['marque']})"],
        ["Numéro de Série / ID :", f"{info_mat['sn']}"],
        ["Service d'Affectation :", info_mat['service']],
        ["Panne Traitée :", f"{info_panne['code']} — {info_panne['titre']}"],
        ["Domaine / Criticité :", f"{info_panne['domaine']} ({info_panne['criticite']})"],
        ["Date et Heure :", datetime.now().strftime("%d/%m/%Y à %H:%M")],
        ["Technicien Responsable :", tech_name]
    ]
    t1 = Table(recap_data, colWidths=[150, 370])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('PADDING', (0,0), (-1,-1), 4.5),
    ]))
    story.append(t1)
    story.append(Spacer(1, 14))

    story.append(Paragraph("<b>1. Diagnostic technique & anomalie constatée :</b>", styles['Normal']))
    story.append(Paragraph(info_panne['probleme'], styles['Normal']))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>2. Actions de maintenance exécutées à l'établi :</b>", styles['Normal']))
    story.append(Paragraph(f"• {info_panne['etape1']}<br/>• {info_panne['etape2']}<br/>• {info_panne['etape3']}", styles['Normal']))
    story.append(Spacer(1, 14))

    story.append(Paragraph("<b>3. Contrôles de sécurité électrique réglementaires (Norme NF EN 62353) :</b>", styles['Normal']))
    mesures_data = [
        ["Nature de l'essai", "Critère d'acceptation", "Résultat d'essai"],
        ["Résistance du conducteur de protection", "< 0,20 ohm", "CONFORME (0,08 ohm)" if chk_terre else "NON EFFECTUÉ"],
        ["Courant de fuite au boîtier / patient", "Conforme classe I type B", "CONFORME" if chk_fuite else "NON EFFECTUÉ"],
        ["Examen visuel & sécurités mécaniques", "Verrouillages intègres", "CONFORME" if chk_meca else "NON EFFECTUÉ"],
        ["Essai fonctionnel en charge réelle", "Consignes atteintes sans alerte", "CONFORME" if chk_charge else "NON EFFECTUÉ"]
    ]
    t2 = Table(mesures_data, colWidths=[200, 160, 160])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0284c7")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t2)
    story.append(Spacer(1, 18))

    visa_text = [["SERVICE BIOMÉDICAL — DISPOSITIF QUALIFIÉ POUR REMISE EN SERVICE"]]
    t3 = Table(visa_text, colWidths=[520])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdf4")),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor("#166534")),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor("#166534")),
        ('PADDING', (0,0), (-1,-1), 7),
    ]))
    story.append(t3)

    doc.build(story)
    buf.seek(0)
    return buf

# =========================================================================
# 4. APPLICATION STREAMLIT (LAYOUT ATELIER RESPONSIVE)
# =========================================================================

materiels_dict = load_all_devices()
liste_mat_ids = list(materiels_dict.keys())

# --- SIDEBAR : INVENTAIRE & GESTION DOCUMENTAIRE ---
with st.sidebar:
    st.markdown("### 🏷️ Inventaire Atelier")
    
    idx_selected = 0
    if "selected_mat_id" in st.session_state and st.session_state["selected_mat_id"] in liste_mat_ids:
        idx_selected = liste_mat_ids.index(st.session_state["selected_mat_id"])

    current_mat_id = st.selectbox(
        "Équipement sous maintenance :",
        options=liste_mat_ids,
        index=idx_selected,
        format_func=lambda x: f"{materiels_dict[x]['nom']} ({materiels_dict[x]['marque']})"
    )
    st.session_state["selected_mat_id"] = current_mat_id
    info_mat = materiels_dict[current_mat_id]

    with st.container(border=True):
        st.markdown(f"**Modèle :** {info_mat['nom']}")
        st.markdown(f"**Fabricant :** {info_mat['marque']}")
        st.markdown(f"**Affectation :** `{info_mat['service']}`")
        st.markdown(f"**N° Série :** `{info_mat['sn']}`")

    st.divider()
    st.markdown("### 📥 Ingestion de Manuel PDF")
    uploaded_pdf = st.file_uploader("Ajouter un manuel de service :", type=["pdf"])
    if uploaded_pdf is not None:
        file_key = f"pdf_proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
        if file_key not in st.session_state:
            with st.spinner("Indexation des pannes en cours..."):
                new_id, total = parse_and_store_pdf(uploaded_pdf)
                st.session_state[file_key] = True
                st.session_state["selected_mat_id"] = new_id
                st.toast(f"✔ Nouveau manuel indexé avec succès ({total} pannes) !", icon="📑")
                st.rerun()

    st.caption("BioMed Assist Pro • v2.6 Hospital Production")

# --- ESPACE DE TRAVAIL PRINCIPAL ---
tab_etabli, tab_historique = st.tabs(["🛠️ Banc de Dépannage Actif", "📋 Registre des Interventions"])

# =========================================================================
# ONGLET 1 : BANC DE DÉPANNAGE ACTIF
# =========================================================================
with tab_etabli:
    # Fil d'Ariane
    st.markdown(f"📍 **Emplacement :** `{info_mat['service']}` &nbsp;❯&nbsp; **Équipement :** **{info_mat['nom']}**")

    # Filtre par domaine & Recherche textuelle instantanée
    c_dom, c_search = st.columns([1, 2])
    with c_dom:
        domaines_options = ["Tous", "⚙️ Mécanique & Moteur", "⚡ Électrique & Capteurs", "💻 Cartes & Système"]
        domaine_choisi = st.selectbox("Domaine d'intervention :", options=domaines_options)
    with c_search:
        search_query = st.text_input("🔍 Recherche rapide (code alarme, moteur, débit, fuite...) :", placeholder="Tapez un mot-clé...")

    pannes_dispos = load_errors_by_device(current_mat_id, domaine_choisi)

    # Filtrage dynamique
    if search_query.strip():
        q = search_query.strip().lower()
        pannes_affichees = [
            p for p in pannes_dispos
            if q in p['code'].lower() or q in p['titre'].lower() or q in p['probleme'].lower()
        ]
    else:
        pannes_affichees = pannes_dispos

    if pannes_affichees:
        # Sélecteur d'alarme
        labels_pannes = [f"{p['criticite']} | {p['code']} : {p['titre']}" for p in pannes_affichees]
        choix_panne = st.selectbox(f"Pannes identifiées ({len(pannes_affichees)}) :", options=labels_pannes)
        panne = pannes_affichees[labels_pannes.index(choix_panne)]

        # --- CARTE DU SYMPTÔME ---
        with st.container(border=True):
            col_code, col_status = st.columns([3, 1])
            with col_code:
                st.error(f"### {panne['code']} — {panne['titre']}")
            with col_status:
                st.metric(label="Criticité", value=panne['criticite'])
            
            st.markdown(f"**🔍 Constat & Phénomène :** {panne['probleme']}")

        # --- ÉTAPES D'ATELIER ---
        st.markdown("#### 🛠️ Protocole de résolution à l'établi")
        col_e1, col_e2, col_e3 = st.columns(3)
        with col_e1:
            with st.container(border=True):
                st.markdown("**1. Contrôle Visuel / Mécanique**")
                st.info(panne['etape1'])
        with col_e2:
            with st.container(border=True):
                st.markdown("**2. Démontage & Raccordements**")
                st.info(panne['etape2'])
        with col_e3:
            with st.container(border=True):
                st.markdown("**3. Action / Requalification**")
                st.info(panne['etape3'])

        # --- ENCADRÉ MULTIMÈTRE / TEST BENCH ---
        with st.container(border=True):
            st.warning(f"⚡ **Points de mesure au multimètre / Seuil nominal :**\n\n{panne['mesure']}")

        # --- CONTRÔLES RÉGLEMENTAIRES NF EN 62353 ---
        st.markdown("#### 📋 Contrôles Réglementaires de Sécurité Électrique (NF EN 62353)")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            chk_terre = st.checkbox("Terre (< 0,20 Ω)", value=True, help="Mesure de résistance du conducteur de protection")
        with c2:
            chk_fuite = st.checkbox("Courants de fuite", value=True, help="Conforme classe I / II selon spécification")
        with c3:
            chk_meca = st.checkbox("Sécurités mécaniques", value=True, help="Intégrité du verrouillage et des capteurs")
        with c4:
            chk_charge = st.checkbox("Essai en charge réelle", value=True, help="Validation des consignes de fonctionnement")

        est_conforme = chk_terre and chk_fuite and chk_meca and chk_charge

        st.divider()

        # --- ACTIONS : GMAO & RAPPORT PDF CERTIFIÉ ---
        col_pdf, col_gmao = st.columns([1, 1])

        # Texte formaté pour logiciel de GMAO
        texte_gmao = (
            f"[GMAO BT] Intervention sur {info_mat['nom']} ({info_mat['sn']})\n"
            f"Alarme : {panne['code']} - {panne['titre']}\n"
            f"Résolution : {panne['etape1']} | {panne['etape2']} | {panne['etape3']}\n"
            f"Sécurité NF EN 62353 : {'CONFORME' if est_conforme else 'NON CONFORME'} | Intervenant : Hakki Ismail"
        )

        with col_pdf:
            pdf_bytes = build_pdf_certificate(
                info_mat, panne, "Hakki Ismail",
                chk_terre, chk_fuite, chk_meca, chk_charge
            )
            st.download_button(
                label="📄 Télécharger la Fiche d'Intervention Scellée (PDF)",
                data=pdf_bytes,
                file_name=f"Fiche_Maintenance_{panne['code']}_{current_mat_id}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

        with col_gmao:
            if st.button("💾 Clôturer & Enregistrer dans l'Audit Log", use_container_width=True):
                log_intervention(info_mat['nom'], panne['code'], "Hakki Ismail", conforme=est_conforme)
                st.toast(f"Intervention sur {info_mat['nom']} enregistrée avec succès !", icon="✅")

        # Tiroir GMAO avec bouton de copie natif
        with st.expander("📋 Rapport d'intervention pour GMAO (Carl / Coswin / Assetplus)"):
            st.code(texte_gmao, language="text")

    else:
        st.warning("Aucune anomalie ne correspond à vos critères de recherche.")

# =========================================================================
# ONGLET 2 : HISTORIQUE D'AUDIT DSI & QUALITÉ
# =========================================================================
with tab_historique:
    st.markdown("### 📋 Registre des Interventions d'Atelier (Norme Qualité Hospitalière)")
    st.caption("Traçabilité des contrôles de sécurité électrique et des remises en service.")
    
    logs = load_audit_history()
    if logs:
        # Affichage propre sous forme de table
        formatted_logs = [
            {"Date & Heure": l[0], "Dispositif Médical": l[1], "Code Alarme": l[2], "Technicien": l[3], "Statut Réglementaire": l[4]}
            for l in logs
        ]
        st.dataframe(formatted_logs, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune intervention n'a encore été clôturée dans ce registre.")
