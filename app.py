import io
import os
import re
import csv
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
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = "biomed_v_ultimate.db"

# =========================================================================
# 1. BASE DE DONNÉES SQLITE (ÉQUIPEMENTS, PANNES, REX & PAGES PDF)
# =========================================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
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
                outils TEXT,
                piece_rechange TEXT,
                etape1 TEXT,
                etape2 TEXT,
                etape3 TEXT,
                mesure_multimetre TEXT,
                astuce_terrain TEXT,
                FOREIGN KEY (materiel_id) REFERENCES materiels(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS pages_manuel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                materiel_id TEXT,
                num_page INTEGER,
                contenu TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_heure TEXT,
                materiel_nom TEXT,
                code_panne TEXT,
                terre_ohm REAL,
                fuite_ua REAL,
                technicien TEXT,
                etat_conformite TEXT
            )
        """)
        
        c.execute("SELECT COUNT(*) FROM materiels")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO materiels VALUES (?, ?, ?, ?, ?, ?)", [
                ("ROTANTA", "Rotanta 460 RF (Centrifugeuse)", "Hettich", "Laboratoire Biochimie", "SN-2026-991", "01/10/2026"),
                ("WD40", "WD40 (Laveur-Désinfecteur)", "Wassenburg", "Plateau Endoscopie", "SN-WD-441", "05/10/2026"),
                ("FLUIDO", "Fluido AirGuard (Réchauffeur)", "The Surgical Company", "Bloc Opératoire", "SN-FL-118", "10/10/2026"),
                ("SERVO", "Servo-u (Respirateur)", "Getinge / Maquet", "Réanimation Médicale", "SN-SU-882", "12/10/2026")
            ])
            
            c.executemany("""
                INSERT INTO pannes 
                (materiel_id, domaine, criticite, code, titre, probleme, outils, piece_rechange, etape1, etape2, etape3, mesure_multimetre, astuce_terrain) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    "ROTANTA", "⚙️ Mécanique & Moteur", "🔴 Critique", "E-02",
                    "Défaut tachymétrique ou blocage du rotor",
                    "La centrifugeuse refuse de se lancer ou coupe son cycle car la carte électronique ne reçoit plus les impulsions de rotation du bol.",
                    "Clé Allen 4 mm, Jeu de cales d'épaisseur, Multimètre",
                    "Capteur tachymétrique à effet Hall (Réf. Hettich E-994)",
                    "Faire tourner le rotor manuellement hors tension pour vérifier l'absence totale de point dur sur les roulements du moteur.",
                    "Contrôler sous la cuve que le capteur de vitesse est propre et réglé à 0,8 mm (± 0,2 mm) de l'aimant de l'axe.",
                    "Vérifier l'état et le bon verrouillage du connecteur moteur sur la carte variateur située dans le socle.",
                    "Multimètre en Volts DC : mesurer 5,0 V constants entre le fil rouge et le fil noir du capteur. En tournant le bol à la main, le signal doit basculer entre 0 V et 5 V.",
                    "Astuce atelier : Vérifier si de la poussière métallique ou de la rouille ne s'est pas collée sur le petit aimant de l'arbre moteur."
                ),
                (
                    "ROTANTA", "⚙️ Mécanique & Moteur", "🔴 Critique", "LID OPEN",
                    "Sécurité couvercle : Capot détecté non verrouillé",
                    "Le verrouillage électronique refuse le départ du cycle car le micro-contacteur ne confirme pas la fermeture physique du capot.",
                    "Tournevis Torx T20, Multimètre, Bombe contact",
                    "Micro-switch de sécurité SW1 ou Bobine de verrouillage",
                    "Vérifier l'alignement mécanique des deux crochets métalliques du couvercle avec les fentes du châssis.",
                    "Actionner manuellement le loquet pour entendre le déclic mécanique franc du micro-contacteur de sécurité.",
                    "Appareil débranché, contrôler le micro-contacteur et la bobine de l'électro-aimant de rappel à l'ohmmètre.",
                    "Mode Continuité (Bip) : 0 Ohm contact appuyé, circuit ouvert relâché. Résistance de la bobine de verrouillage = environ 35 Ohms.",
                    "Astuce atelier : Souvent les techniciens de labo appuient trop fort sur le capot à gauche, ce qui tord légèrement la patte métallique du switch SW1."
                ),
                (
                    "ROTANTA", "⚡ Électrique & Capteurs", "🟠 Majeur", "E-04",
                    "Défaut régulation froid / Sonde thermique PT100",
                    "La température de la cuve dérive hors de la consigne ou la sonde de mesure présente une coupure électrique.",
                    "Soufflette air comprimé, Multimètre, Tournevis cruciforme",
                    "Sonde de cuve PT100 ou Relais statique compresseur",
                    "Dépoussiérer complètement le condenseur du groupe froid et vérifier la libre rotation du ventilateur d'extraction.",
                    "Inspecter le bornier de la sonde thermique sous la cuve pour détecter toute trace d'humidité ou de vert-de-gris.",
                    "Tester la commande du relais statique alimentant le compresseur frigorifique sur la carte de puissance.",
                    "Ohmmètre sur la sonde débranchée : mesurer environ 107,7 Ohms à 20 °C (standard PT100). Si la valeur est infinie, la sonde est coupée.",
                    "Astuce atelier : Un condenseur encrassé par la poussière déclenche souvent ce code au bout de 15 minutes de centrifugation à 4 °C."
                ),
                (
                    "WD40", "⚡ Électrique & Capteurs", "🔴 Critique", "AL-04",
                    "Remplissage en eau insuffisant / Alarme débitmètre",
                    "La cuve ne se remplit pas au volume minimal attendu dans le délai imparti par l'automate de lavage.",
                    "Clé plate 24 mm, Pince multiprise, Multimètre",
                    "Tamis d'entrée 50 µm ou Électrovanne d'admission 24V",
                    "Vérifier que les vannes murales d'eau froide et d'eau osmosée sont ouvertes à fond (pression réseau min : 2,5 bars).",
                    "Fermer l'eau, dévisser le flexible d'admission et nettoyer la petite grille filtrante 50 µm souvent bouchée par le calcaire.",
                    "Contrôler l'ouverture de l'électrovanne et vérifier que la roue à aubes du débitmètre tourne sans blocage.",
                    "Voltmètre : mesurer 24 V DC (ou 230 V AC selon version) sur les cosses de la bobine d'électrovanne lors de la demande d'eau.",
                    "Astuce atelier : Après des travaux sur le réseau d'eau de l'hôpital, le filtre d'entrée se bouche systématiquement avec du sable."
                ),
                (
                    "FLUIDO", "⚡ Électrique & Capteurs", "🔴 Critique", "AIR IN LINE",
                    "Détection d'air : Alarme bulle sur la ligne de perfusion",
                    "Le capteur ultrasonique détecte une discontinuité dans la tubulure et coupe le réchauffement par sécurité patient.",
                    "Compresses non tissées, Alcool isopropylique, Poche de test",
                    "Bloc capteur ultrasonique de gouttière",
                    "Nettoyer soigneusement les deux faces de la gouttière optique/ultrasonique avec de l'alcool isopropylique pour retirer tout gel ou dépôt.",
                    "Vérifier que la tubulure de la cassette est bien enfoncée jusqu'au fond de la gorge de détection.",
                    "Tester avec une cassette neuve parfaitement purgée de toute microbulle d'air.",
                    "Menu Service (Code technicien) : vérifier que la valeur du signal ultrasonique à vide puis en eau est dans la plage constructeur.",
                    "Astuce atelier : Ne jamais utiliser d'acétone sur les prismes, cela opacifie le plastique et déclenche l'alarme en permanence."
                ),
                (
                    "SERVO", "⚡ Électrique & Capteurs", "🔴 Critique", "ERR-32",
                    "Défaut cassette expiratoire / Mesure de débit ultrasonique",
                    "Le ventilateur ne parvient plus à mesurer le débit expiratoire ou perd la communication avec la cassette.",
                    "Alcool isopropylique, Coton-tiges, Cassette étalon de test",
                    "Cassette expiratoire complète ou Membrane clapet",
                    "Retirer la cassette expiratoire et vérifier l'absence d'eau de condensation stagnante au fond du canal ultrasonique.",
                    "Nettoyer les contacts électriques dorés sur la cassette et au fond du logement du respirateur.",
                    "Insérer une cassette expiratoire sèche issue de la stérilisation et relancer l'appareil.",
                    "Lancer le contrôle avant utilisation (Pré-test automatique) complet avec circuit patient bouché pour qualifier l'étanchéité et le débit.",
                    "Astuce atelier : Si la cassette sort tout juste de l'autoclave et est encore chaude/humide, elle met systématiquement l'appareil en erreur ERR-32."
                )
            ])
        conn.commit()

init_db()

# --- FONCTIONS D'ACCÈS AUX DONNÉES ---

@st.cache_data(ttl=30)
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
                SELECT id, code, titre, domaine, criticite, probleme, outils, piece_rechange, etape1, etape2, etape3, mesure_multimetre, astuce_terrain 
                FROM pannes WHERE materiel_id = ? ORDER BY id ASC
            """, (mat_id,))
        else:
            c.execute("""
                SELECT id, code, titre, domaine, criticite, probleme, outils, piece_rechange, etape1, etape2, etape3, mesure_multimetre, astuce_terrain 
                FROM pannes WHERE materiel_id = ? AND domaine = ? ORDER BY id ASC
            """, (mat_id, domaine_filtre))
        return [{
            "id": r[0], "code": r[1], "titre": r[2], "domaine": r[3], "criticite": r[4],
            "probleme": r[5], "outils": r[6], "piece": r[7], "etape1": r[8], "etape2": r[9],
            "etape3": r[10], "mesure": r[11], "astuce": r[12]
        } for r in c.fetchall()]

def update_astuce_terrain(panne_id, nouvelle_astuce):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE pannes SET astuce_terrain = ? WHERE id = ?", (nouvelle_astuce, panne_id))
        conn.commit()

def add_custom_panne(mat_id, domaine, criticite, code, titre, probleme, outils, piece, etape1, etape2, etape3, mesure, astuce):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO pannes 
            (materiel_id, domaine, criticite, code, titre, probleme, outils, piece_rechange, etape1, etape2, etape3, mesure_multimetre, astuce_terrain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mat_id, domaine, criticite, code.upper(), titre, probleme, outils, piece, etape1, etape2, etape3, mesure, astuce))
        conn.commit()

def search_in_manual_pages(mat_id, keyword):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT num_page, contenu FROM pages_manuel 
            WHERE materiel_id = ? AND contenu LIKE ? 
            ORDER BY num_page ASC LIMIT 15
        """, (mat_id, f"%{keyword}%"))
        return c.fetchall()

def log_intervention(mat_nom, code, terre_val, fuite_val, tech, conforme=True):
    res_str = "CONFORME (NF EN 62353)" if conforme else "NON CONFORME - REMISE EN SERVICE BLOQUÉE"
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO audit_log (date_heure, materiel_nom, code_panne, terre_ohm, fuite_ua, technicien, etat_conformite)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%d/%m/%Y %H:%M"), mat_nom, code, terre_val, fuite_val, tech, res_str))
        conn.commit()

def load_audit_history():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT date_heure, materiel_nom, code_panne, terre_ohm, fuite_ua, technicien, etat_conformite FROM audit_log ORDER BY id DESC LIMIT 100")
        return c.fetchall()

# =========================================================================
# 2. PARSEUR PDF INTELLIGENT (ANTI-SOMMAIRE + INDEXATION PLEIN TEXTE)
# =========================================================================

def is_unwanted_line(text):
    t = text.strip()
    if re.search(r'\.{2,}', t):
        return True
    if re.search(r'\s*\.{2,}\s*\d+$', t):
        return True
    if re.match(r'^(?:page|chapitre|section|table|figure|index|sommaire)\s*\d*$', t, re.IGNORECASE):
        return True
    return False

def clean_sentence(text):
    t = re.sub(r'[\t\r\n]+', ' ', text)
    return re.sub(r'\s+', ' ', t).strip(" -:|,")

def parse_and_store_pdf(uploaded_file):
    reader = PdfReader(uploaded_file)
    max_scan = min(len(reader.pages), 120)
    
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
    pages_a_stocker = []
    codes_vus = set()

    progress = st.progress(0, text="Analyse du manuel et indexation des pages...")

    for idx in range(max_scan):
        progress.progress((idx + 1) / max_scan, text=f"Lecture de la page {idx+1} sur {max_scan}...")
        page_text = reader.pages[idx].extract_text() or ""
        
        if len(page_text.strip()) > 20:
            pages_a_stocker.append((device_id, idx + 1, clean_sentence(page_text)))

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
                            desc = clean_sentence(reste) if len(reste) > 3 else "Déclenchement d'une sécurité"
                        break

            if code_found:
                k_uniq = re.sub(r'[^A-Z0-9]', '', code_found)
                if k_uniq not in codes_vus and len(k_uniq) >= 2 and not any(w in code_found for w in ["ISO", "PAGE", "REV", "FIG", "TABLE"]):
                    codes_vus.add(k_uniq)

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
                            resolution = " ".join(next_lines[1:]) if len(next_lines) > 1 else "Contrôler le sous-ensemble et la connectique."
                        else:
                            resolution = " ".join(next_lines)
                        i += (step - 1)
                    else:
                        desc = desc or "Anomalie technique détectée par l'appareil."
                        resolution = "Contrôler le câblage, vérifier les fusibles et tester l'alimentation électrique."

                    desc = clean_sentence(desc)
                    resolution = clean_sentence(resolution)
                    if not desc.endswith('.'): desc += "."
                    if not resolution.endswith('.'): resolution += "."

                    ctx = f"{code_found} {desc} {resolution}".lower()
                    if any(w in ctx for w in ["moteur", "rotor", "pompe", "porte", "couvercle", "verrou", "mecanique"]):
                        domaine = "⚙️ Mécanique & Moteur"
                        criticite = "🔴 Critique"
                        outils = "Jeu de clés Allen, Tournevis, Multimètre"
                        piece = "Sous-ensemble moteur / Verrouillage mécanique"
                    elif any(w in ctx for w in ["carte", "cpu", "firmware", "bus", "ram", "rom", "software", "com"]):
                        domaine = "💻 Cartes & Système"
                        criticite = "🟠 Majeur"
                        outils = "Bracelet antistatique, Multimètre, Bombe contact"
                        piece = "Carte électronique / Nappe de liaison"
                    else:
                        domaine = "⚡ Électrique & Capteurs"
                        criticite = "🔴 Critique" if "alim" in ctx or "securite" in ctx else "🟠 Majeur"
                        outils = "Multimètre, Tournevis isolé, Pince"
                        piece = "Capteur / Fusible / Alimentation"

                    pannes_trouvees.append((
                        device_id, domaine, criticite, code_found, desc[:75],
                        f"Extrait du manuel (Page {idx+1}) : {desc}",
                        outils, piece,
                        "Contrôle visuel : vérifier l'état mécanique du sous-ensemble et le verrouillage des connecteurs.",
                        f"Procédure constructeur : {resolution}",
                        "Requalification : lancer un cycle d'essai complet pour valider l'effacement du code défaut.",
                        "Multimètre : vérifier les tensions d'alimentation (+5V, +12V, +24V DC) et la continuité.",
                        f"Page source dans le PDF : Page {idx+1}."
                    ))
            i += 1

    progress.empty()

    if not pannes_trouvees:
        pannes_trouvees.append((
            device_id, "⚙️ Mécanique & Moteur", "🟡 Mineur", "MAINT-01",
            "Maintenance préventive et contrôle technique général",
            "Protocole périodique de révision de l'appareil à l'atelier biomédical.",
            "Outillage standard biomédical, Analyseur NF EN 62353",
            "Kit de maintenance préventive constructeur",
            "Vérifier l'état mécanique général, le châssis, le cordon secteur et l'absence de jeu.",
            "Dépoussiérer les ventilations, nettoyer les filtres et inspecter les cartes électroniques.",
            "Effectuer les essais fonctionnels nominaux en charge réelle.",
            "Sécurité électrique NF EN 62353 : Continuité de la terre de protection < 0,20 Ohm.",
            "Utilisez l'onglet 'Recherche dans le PDF' pour chercher un mot précis dans ce manuel."
        ))

    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO materiels VALUES (?, ?, ?, ?, ?, ?)", (
            device_id, nom_base[:45], "Manuel Importé", "Atelier Biomédical", "SN-AUTO", datetime.now().strftime("%d/%m/%Y")
        ))
        c.executemany("""
            INSERT INTO pannes 
            (materiel_id, domaine, criticite, code, titre, probleme, outils, piece_rechange, etape1, etape2, etape3, mesure_multimetre, astuce_terrain) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, pannes_trouvees)
        if pages_a_stocker:
            c.executemany("INSERT INTO pages_manuel (materiel_id, num_page, contenu) VALUES (?, ?, ?)", pages_a_stocker)
        conn.commit()

    st.cache_data.clear()
    return device_id, len(pannes_trouvees)

# =========================================================================
# 3. GÉNÉRATEUR RAPPORT PDF CERTIFIÉ (AVEC VALEURS MESURÉES)
# =========================================================================

def build_pdf_certificate(info_mat, info_panne, tech_name, terre_val, fuite_val, chk_meca, chk_charge, conforme_global):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=32, leftMargin=32, topMargin=32, bottomMargin=32)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=13, textColor=colors.HexColor("#0f172a"), alignment=1)
    story.append(Paragraph("RAPPORT OFFICIEL D'INTERVENTION & SÉCURITÉ BIOMÉDICALE", title_style))
    story.append(Spacer(1, 14))

    recap_data = [
        ["Dispositif Médical :", f"{info_mat['nom']} ({info_mat['marque']})"],
        ["Numéro de Série :", f"{info_mat['sn']}"],
        ["Service d'Affectation :", info_mat['service']],
        ["Panne Traitée :", f"{info_panne['code']} — {info_panne['titre']}"],
        ["Pièce / Sous-ensemble :", info_panne['piece']],
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
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>1. Diagnostic technique & anomalie constatée :</b>", styles['Normal']))
    story.append(Paragraph(info_panne['probleme'], styles['Normal']))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>2. Actions de maintenance exécutées à l'établi :</b>", styles['Normal']))
    story.append(Paragraph(f"• {info_panne['etape1']}<br/>• {info_panne['etape2']}<br/>• {info_panne['etape3']}", styles['Normal']))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>3. Mesures de sécurité électrique réglementaires (Norme NF EN 62353) :</b>", styles['Normal']))
    mesures_data = [
        ["Nature de l'essai", "Seuil Normatif", "Valeur Mesurée", "Verdict"],
        ["Résistance de terre de protection", "<= 0,20 Ohm", f"{terre_val:.2f} Ohm", "CONFORME" if terre_val <= 0.20 else "NON CONFORME"],
        ["Courant de fuite équipement", "<= 500 µA", f"{int(fuite_val)} µA", "CONFORME" if fuite_val <= 500 else "NON CONFORME"],
        ["Intégrité mécanique & verrouillages", "Conforme constructeur", "Vérifié", "CONFORME" if chk_meca else "NON CONFORME"],
        ["Essai fonctionnel en charge réelle", "Consignes atteintes", "Vérifié", "CONFORME" if chk_charge else "NON CONFORME"]
    ]
    t2 = Table(mesures_data, colWidths=[180, 110, 110, 120])
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

    if conforme_global:
        visa_text = [["VISA BIOMÉDICAL : APPAREIL CONFORME — REMISE EN SERVICE AUTORISÉE"]]
        bg_col = colors.HexColor("#f0fdf4")
        txt_col = colors.HexColor("#166534")
    else:
        visa_text = [["ATTENTION : APPAREIL NON CONFORME — MISE EN QUARANTAINE"]]
        bg_col = colors.HexColor("#fef2f2")
        txt_col = colors.HexColor("#991b1b")

    t3 = Table(visa_text, colWidths=[520])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg_col),
        ('TEXTCOLOR', (0,0), (-1,-1), txt_col),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('BOX', (0,0), (-1,-1), 1.5, txt_col),
        ('PADDING', (0,0), (-1,-1), 7),
    ]))
    story.append(t3)

    doc.build(story)
    buf.seek(0)
    return buf

# =========================================================================
# 4. INTERFACE UTILISATEUR STREAMLIT (100% NATIVE, FLUIDE & COMPLÈTE)
# =========================================================================

materiels_dict = load_all_devices()
liste_mat_ids = list(materiels_dict.keys())

# --- BARRE LATÉRALE : CHOIX DE L'APPAREIL & AJOUTS ---
with st.sidebar:
    st.title("🔧 BioMed Assist")
    st.caption("Poste de Dépannage & Qualification")
    
    st.subheader("1. Appareil sur l'établi")
    idx_selected = 0
    if "selected_mat_id" in st.session_state and st.session_state["selected_mat_id"] in liste_mat_ids:
        idx_selected = liste_mat_ids.index(st.session_state["selected_mat_id"])

    current_mat_id = st.selectbox(
        "Sélectionner l'équipement :",
        options=liste_mat_ids,
        index=idx_selected,
        format_func=lambda x: f"{materiels_dict[x]['nom']}"
    )
    st.session_state["selected_mat_id"] = current_mat_id
    info_mat = materiels_dict[current_mat_id]

    with st.container(border=True):
        st.write(f"**Marque :** {info_mat['marque']}")
        st.write(f"**Service :** `{info_mat['service']}`")
        st.write(f"**N° Série :** `{info_mat['sn']}`")

    st.divider()

    # Ajout rapide d'une panne découverte à l'atelier
    with st.expander("➕ Créer une fiche panne manuelle"):
        with st.form("form_new_panne", clear_on_submit=True):
            new_code = st.text_input("Code ou Symptôme court", placeholder="Ex: E-09 ou FUITE POMPE")
            new_dom = st.selectbox("Domaine", ["⚙️ Mécanique & Moteur", "⚡ Électrique & Capteurs", "💻 Cartes & Système"])
            new_crit = st.selectbox("Criticité", ["🔴 Critique", "🟠 Majeur", "🟡 Mineur"])
            new_titre = st.text_input("Titre clair de la panne", placeholder="Ex: Fuite sur raccord pompe")
            new_prob = st.text_area("Explication du problème")
            new_outils = st.text_input("Outils nécessaires", value="Tournevis, Multimètre")
            new_piece = st.text_input("Pièce à contrôler / remplacer", value="Sous-ensemble concerné")
            new_e1 = st.text_input("Étape 1 (Visuel / Mécanique)")
            new_e2 = st.text_input("Étape 2 (Action / Dépannage)")
            new_e3 = st.text_input("Étape 3 (Test de validation)")
            new_mes = st.text_input("Mesure au multimètre")
            new_ast = st.text_input("Astuce terrain")
            
            if st.form_submit_button("💾 Enregistrer cette panne", use_container_width=True):
                if new_code and new_titre:
                    add_custom_panne(
                        current_mat_id, new_dom, new_crit, new_code, new_titre,
                        new_prob or new_titre, new_outils, new_piece,
                        new_e1 or "Vérifier l'état visuel.", new_e2 or "Remplacer ou régler le composant.",
                        new_e3 or "Tester en fonctionnement.", new_mes or "Vérifier les tensions nominales.",
                        new_ast or "Ajouté par l'atelier."
                    )
                    st.toast("Nouvelle fiche panne ajoutée !", icon="✅")
                    st.rerun()

    # Import PDF
    with st.expander("📥 Importer un manuel PDF"):
        uploaded_pdf = st.file_uploader("Glisser le manuel technique :", type=["pdf"])
        if uploaded_pdf is not None:
            file_key = f"pdf_proc_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if file_key not in st.session_state:
                new_id, total = parse_and_store_pdf(uploaded_pdf)
                st.session_state[file_key] = True
                st.session_state["selected_mat_id"] = new_id
                st.toast(f"Manuel indexé ({total} pannes extraites) !", icon="📑")
                st.rerun()

# --- ZONE PRINCIPALE EN 3 ONGLETS ---
tab_depannage, tab_manuel, tab_registre = st.tabs([
    "🛠️ 1. Banc de Dépannage & Mesures",
    "📖 2. Recherche libre dans le Manuel PDF",
    "📋 3. Registre & Export GMAO"
])

# =========================================================================
# ONGLET 1 : BANC DE DÉPANNAGE ACTIF
# =========================================================================
with tab_depannage:
    st.subheader(f"Dépannage : {info_mat['nom']} ({info_mat['marque']})")

    # Menus de filtrage
    col_dom, col_search = st.columns([1, 2])
    with col_dom:
        domaines_options = ["Tous", "⚙️ Mécanique & Moteur", "⚡ Électrique & Capteurs", "💻 Cartes & Système"]
        domaine_choisi = st.selectbox("1. Filtrer par grand domaine :", options=domaines_options)
    with col_search:
        search_query = st.text_input("2. Filtrer par mot-clé ou code :", placeholder="Tapez un code (ex: E-02) ou un mot (ex: eau, capot, sonde)...")

    pannes_dispos = load_errors_by_device(current_mat_id, domaine_choisi)

    if search_query.strip():
        q = search_query.strip().lower()
        pannes_affichees = [
            p for p in pannes_dispos
            if q in p['code'].lower() or q in p['titre'].lower() or q in p['probleme'].lower() or q in p['piece'].lower()
        ]
    else:
        pannes_affichees = pannes_dispos

    if pannes_affichees:
        labels_pannes = [f"{p['criticite']} | {p['code']} — {p['titre']}" for p in pannes_affichees]
        choix_panne = st.selectbox(f"3. Sélectionner la panne ({len(pannes_affichees)} trouvées) :", options=labels_pannes)
        panne = pannes_affichees[labels_pannes.index(choix_panne)]

        st.divider()

        # --- EN-TÊTE DE LA PANNE & OUTILLAGE ---
        with st.container(border=True):
            c_titre, c_crit = st.columns([4, 1])
            with c_titre:
                st.error(f"### {panne['code']} : {panne['titre']}")
            with c_crit:
                st.metric("Priorité", panne['criticite'])

            st.write(f"**🔍 Ce qui se passe sur l'appareil :** {panne['probleme']}")
            
            col_out, col_pce = st.columns(2)
            with col_out:
                st.markdown(f"🧰 **Outils à préparer :** `{panne['outils']}`")
            with col_pce:
                st.markdown(f"🔩 **Composant / Pièce ciblée :** `{panne['piece']}`")

        # --- LES 3 ÉTAPES CLAIRES ---
        st.markdown("#### 🛠️ Actions à réaliser à l'établi")
        c_et1, c_et2, c_et3 = st.columns(3)
        with c_et1:
            with st.container(border=True):
                st.markdown("**Étape 1 : Contrôle Visuel & Mécanique**")
                st.info(panne['etape1'])
        with c_et2:
            with st.container(border=True):
                st.markdown("**Étape 2 : Intervention Technique**")
                st.info(panne['etape2'])
        with c_et3:
            with st.container(border=True):
                st.markdown("**Étape 3 : Test & Requalification**")
                st.info(panne['etape3'])

        # --- MULTIMÈTRE & REX TERRAIN ---
        col_multi, col_rex = st.columns([1.2, 1])
        with col_multi:
            st.warning(f"⚡ **Où mesurer au multimètre / Valeurs attendues :**\n\n{panne['mesure']}")
        with col_rex:
            st.success(f"💡 **Astuce Terrain (REX Atelier) :**\n\n{panne['astuce']}")
            with st.popover("✏️ Modifier / Ajouter une astuce collègue"):
                new_note = st.text_area("Note terrain pour les collègues :", value=panne['astuce'])
                if st.button("Enregistrer l'astuce"):
                    update_astuce_terrain(panne['id'], new_note)
                    st.toast("Astuce mise à jour !", icon="💡")
                    st.rerun()

        st.divider()

        # --- BANC DE MESURE NF EN 62353 AVEC SEUILS AUTOMATIQUES ---
        st.markdown("#### 📋 Relevé de Sécurité Électrique (Norme NF EN 62353)")
        
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            val_terre = st.number_input("Résistance Terre (Ω) [Max 0.20]", min_value=0.01, max_value=2.00, value=0.08, step=0.01)
            ok_terre = val_terre <= 0.20
            if ok_terre:
                st.caption("✅ Terre Conforme")
            else:
                st.caption("❌ HORS TOLÉRANCE (> 0.20 Ω)")
                
        with col_m2:
            val_fuite = st.number_input("Courant de fuite (µA) [Max 500]", min_value=1.0, max_value=2000.0, value=45.0, step=5.0)
            ok_fuite = val_fuite <= 500.0
            if ok_fuite:
                st.caption("✅ Fuite Conforme")
            else:
                st.caption("❌ HORS TOLÉRANCE (> 500 µA)")

        with col_m3:
            chk_meca = st.checkbox("Verrouillages & Capots OK", value=True)
            chk_charge = st.checkbox("Essai en charge OK", value=True)

        conforme_global = ok_terre and ok_fuite and chk_meca and chk_charge

        with col_m4:
            if conforme_global:
                st.success("✔ APTE AU SERVICE")
            else:
                st.error("⛔ NON CONFORME")

        # --- BOUTONS D'EXPORT PDF & GMAO ---
        col_act1, col_act2 = st.columns(2)

        texte_gmao = (
            f"=== COMPTE-RENDU D'INTERVENTION BIOMÉDICALE ===\n"
            f"Équipement : {info_mat['nom']} ({info_mat['marque']}) - Série : {info_mat['sn']}\n"
            f"Service : {info_mat['service']}\n"
            f"Panne traitée : {panne['code']} - {panne['titre']}\n"
            f"Pièce contrôlée : {panne['piece']}\n"
            f"Actions réalisées :\n"
            f"  1. {panne['etape1']}\n"
            f"  2. {panne['etape2']}\n"
            f"  3. {panne['etape3']}\n"
            f"Mesures NF EN 62353 : Terre = {val_terre:.2f} Ohm | Fuite = {int(val_fuite)} µA\n"
            f"Verdict : {'CONFORME POUR REMISE EN SERVICE' if conforme_global else 'NON CONFORME'}\n"
            f"Intervenant : Hakki Ismail - Date : {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )

        with col_act1:
            pdf_bytes = build_pdf_certificate(
                info_mat, panne, "Hakki Ismail",
                val_terre, val_fuite, chk_meca, chk_charge, conforme_global
            )
            st.download_button(
                label="📄 Télécharger le Certificat d'Intervention (PDF)",
                data=pdf_bytes,
                file_name=f"Certificat_{panne['code']}_{current_mat_id}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

        with col_act2:
            if st.button("💾 Enregistrer et Clôturer dans le Registre", use_container_width=True):
                log_intervention(info_mat['nom'], panne['code'], val_terre, val_fuite, "Hakki Ismail", conforme=conforme_global)
                st.toast("Intervention archivée dans le registre !", icon="✅")

        with st.expander("📋 Copier le compte-rendu prêt pour la GMAO"):
            st.code(texte_gmao, language="text")

    else:
        st.warning("Aucune panne ne correspond à ce filtre. Tu peux l'ajouter via le bouton '➕ Créer une fiche panne manuelle' à gauche.")

# =========================================================================
# ONGLET 2 : RECHERCHE PLEIN TEXTE DANS LE MANUEL PDF
# =========================================================================
with tab_manuel:
    st.subheader(f"📖 Recherche libre dans le manuel : {info_mat['nom']}")
    st.caption("Utile si l'appareil n'affiche pas de code d'erreur mais que tu cherches un mot précis (ex: fusible, calibration, mot de passe, courroie).")

    mot_cle_pdf = st.text_input("Tapez un mot à chercher dans toutes les pages du PDF importé :", placeholder="Ex: calibration, fuse, password, belt, sensor...")
    
    if mot_cle_pdf.strip():
        resultats_pages = search_in_manual_pages(current_mat_id, mot_cle_pdf.strip())
        if resultats_pages:
            st.success(f"{len(resultats_pages)} page(s) trouvée(s) contenant « {mot_cle_pdf} » :")
            for num_p, texte_p in resultats_pages:
                with st.container(border=True):
                    st.markdown(f"**📄 Page {num_p} du manuel :**")
                    st.write(texte_p)
        else:
            st.info("Aucun résultat trouvé dans les pages enregistrées pour cet appareil (ou aucun PDF n'a encore été importé pour ce modèle).")

# =========================================================================
# ONGLET 3 : REGISTRE & EXPORT CSV
# =========================================================================
with tab_registre:
    st.subheader("📋 Historique des Interventions & Mesures NF EN 62353")
    
    logs = load_audit_history()
    if logs:
        formatted_logs = [
            {
                "Date & Heure": l[0],
                "Dispositif": l[1],
                "Code Panne": l[2],
                "Terre (Ω)": f"{l[3]:.2f}",
                "Fuite (µA)": f"{int(l[4])}",
                "Technicien": l[5],
                "Statut": l[6]
            }
            for l in logs
        ]
        st.dataframe(formatted_logs, use_container_width=True, hide_index=True)

        # Génération d'un export CSV pour Excel
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=formatted_logs[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(formatted_logs)
        
        st.download_button(
            label="📊 Exporter l'historique pour Excel (CSV)",
            data=csv_buffer.getvalue().encode("utf-8-sig"),
            file_name=f"Registre_Biomedical_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("Aucune intervention enregistrée pour le moment.")
