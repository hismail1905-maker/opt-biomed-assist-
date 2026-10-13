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
    
    /* En-tête simplifié */
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

    /* Carte de diagnostic sélectionnée */
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

    /* Boîte de conformité */
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

# --- BASE DE DONNÉES ---

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
    fn_candidate = re
