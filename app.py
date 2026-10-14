import csv
import io
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
import streamlit as st
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="BioMed Assist Pro | Atelier Biomédical",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = "biomed_v_ultimate.db"

# Compatibilité descendante pour @st.fragment
fragment_decorator = getattr(st, "fragment", lambda f: f)

# =========================================================================
# 1. EXPRESSIONS RÉGULIÈRES PRÉ-COMPILÉES (GAIN CPU MAJEUR SUR LES PDF)
# =========================================================================

RE_DOTS = re.compile(r'\.{2,}|\s*\.{2,}\s*\d+$')
RE_TOC_HEADERS = re.compile(r'^(?:page|chapitre|section|table|figure|index|sommaire)\s*\d*$', re.IGNORECASE)
RE_WHITESPACE = re.compile(r'[\t\r\n]+|\s{2,}')
RE_ALPHANUM = re.compile(r'[^A-Z0-9]')
RE_STOPWORDS = re.compile(r'\b(?:ISO|PAGE|REV|FIG|TABLE|SECTION)\b')

RE_CODE_PATTERN = re.compile(
    r'\b(?:ERROR|ERR|CODE|ALARM|ALARME|FAULT|DÉFAUT|DEF|E|F|AL)\s*[-:#.]?\s*([0-9]{1,4}|[A-Z]{1,3}[0-9]{1,3})\b',
    re.IGNORECASE
)

RE_TEXT_ALARMS = re.compile(
    r'\b(LID OPEN|COVER OPEN|AIR IN LINE|NO FLOW|OVERHEAT|PRESSURE HIGH|PRESSURE LOW|SENSOR FAIL|MOTOR FAIL|DOOR OPEN|BATTERY LOW)\b',
    re.IGNORECASE
)

# =========================================================================
# 2. GESTIONNAIRE SQLITE HAUTE PERFORMANCE (INDEXÉ + ROW FACTORY)
# =========================================================================

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    try:
        yield conn
    finally:
        conn.close()

@st.cache_resource
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

        # Index SQL pour accélérer les filtres et recherches
        c.execute("CREATE INDEX IF NOT EXISTS idx_pannes_mat ON pannes(materiel_id, domaine);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pages_mat ON pages_manuel(materiel_id);")
        
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

# --- REQUÊTES SQL EN CACHE ---

@st.cache_data(ttl=120)
def load_all_devices():
    with get_db() as conn:
        rows = conn.execute("SELECT id, nom, marque, service, sn FROM materiels ORDER BY nom ASC").fetchall()
        return {r["id"]: dict(r) for r in rows}

@st.cache_data(ttl=120)
def load_errors_by_device(mat_id, domaine_filtre="Tous"):
    with get_db() as conn:
        if domaine_filtre == "Tous":
            rows = conn.execute("""
                SELECT id, code, titre, domaine, criticite, probleme, outils,
                       piece_rechange AS piece, etape1, etape2, etape3,
                       mesure_multimetre AS mesure, astuce_terrain AS astuce
                FROM pannes WHERE materiel_id = ? ORDER BY id ASC
            """, (mat_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, code, titre, domaine, criticite, probleme, outils,
                       piece_rechange AS piece, etape1, etape2, etape3,
                       mesure_multimetre AS mesure, astuce_terrain AS astuce
                FROM pannes WHERE materiel_id = ? AND domaine = ? ORDER BY id ASC
            """, (mat_id, domaine_filtre)).fetchall()
        return [dict(r) for r in rows]

def update_astuce_terrain(panne_id, nouvelle_astuce):
    with get_db() as conn:
        conn.execute("UPDATE pannes SET astuce_terrain = ? WHERE id = ?", (nouvelle_astuce, panne_id))
        conn.commit()
    load_errors_by_device.clear()

def add_custom_panne(mat_id, domaine, criticite, code, titre, probleme, outils, piece, etape1, etape2, etape3, mesure, astuce):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO pannes 
            (materiel_id, domaine, criticite, code, titre, probleme, outils, piece_rechange, etape1, etape2, etape3, mesure_multimetre, astuce_terrain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mat_id, domaine, criticite, code.upper(), titre, probleme, outils, piece, etape1, etape2, etape3, mesure, astuce))
        conn.commit()
    load_errors_by_device.clear()

@st.cache_data(ttl=60)
def search_in_manual_pages(mat_id, keyword):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT num_page, contenu FROM pages_manuel 
            WHERE materiel_id = ? AND contenu LIKE ? 
            ORDER BY num_page ASC LIMIT 15
        """, (mat_id, f"%{keyword}%")).fetchall()
        return [(r["num_page"], r["contenu"]) for r in rows]

def log_intervention(mat_nom, code, terre_val, fuite_val, tech, conforme=True):
    res_str = "CONFORME (NF EN 62353)" if conforme else "NON CONFORME - REMISE EN SERVICE BLOQUÉE"
    with get_db() as conn:
        conn.execute("""
            INSERT INTO audit_log (date_heure, materiel_nom, code_panne, terre_ohm, fuite_ua, technicien, etat_conformite)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%d/%m/%Y %H:%M"), mat_nom, code, terre_val, fuite_val, tech, res_str))
        conn.commit()
    load_audit_history.clear()

@st.cache_data(ttl=60)
def load_audit_history():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date_heure, materiel_nom, code_panne, terre_ohm, fuite_ua, technicien, etat_conformite 
            FROM audit_log ORDER BY id DESC LIMIT 100
        """).fetchall()
        return [dict(r) for r in rows]

# =========================================================================
# 3. PARSEUR PDF VECTORISÉ (EXPRESSIONS PRÉ-COMPILÉES)
# =========================================================================

def is_unwanted_line(text):
    t = text.strip()
    return bool(RE_DOTS.search(t) or RE_TOC_HEADERS.match(t))

def clean_sentence(text):
    return RE_WHITESPACE.sub(' ', text).strip(" -:|,")

def classify_fault(context_lower):
    if any(w in context_lower for w in ("moteur", "rotor", "pompe", "porte", "couvercle", "verrou", "mecanique")):
        return "⚙️ Mécanique & Moteur", "🔴 Critique", "Jeu de clés Allen, Tournevis, Multimètre", "Sous-ensemble moteur / Verrouillage mécanique"
    if any(w in context_lower for w in ("carte", "cpu", "firmware", "bus", "ram", "rom", "software", "com")):
        return "💻 Cartes & Système", "🟠 Majeur", "Bracelet antistatique, Multimètre, Bombe contact", "Carte électronique / Nappe de liaison"
    crit = "🔴 Critique" if ("alim" in context_lower or "securite" in context_lower) else "🟠 Majeur"
    return "⚡ Électrique & Capteurs", crit, "Multimètre, Tournevis isolé, Pince", "Capteur / Fusible / Alimentation"

def parse_and_store_pdf(uploaded_file):
    reader = PdfReader(uploaded_file)
    max_scan = min(len(reader.
