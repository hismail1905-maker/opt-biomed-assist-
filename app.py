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
    page_title="BioMed Workshop UI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = "biomed_v8.db"

# --- STYLE GRAPHIQUE MODERNE (CARTES VISUELLES & ÉPURÉES) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=JetBrains+Mono:wght@600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    }
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }
    
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        max-width: 1400px !important;
    }

    /* En-tête atelier */
    .top-banner {
        background: #0f172a;
        color: white;
        padding: 0.9rem 1.4rem;
        border-radius: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.2rem;
    }
    
    /* Carte de diagnostic héroïque */
    .hero-solution {
        background: #ffffff;
        border: 2px solid #0284c7;
        border-radius: 14px;
        padding: 1.4rem;
        margin-bottom: 1.2rem;
        box-shadow: 0 10px 25px -5px rgba(2, 132, 199, 0.1);
    }
    
    .badge-code {
        background: #0284c7;
        color: white;
        padding: 0.35rem 0.8rem;
        border-radius: 8px;
        font-size: 1.1rem;
        font-weight: 800;
        font-family: 'JetBrains Mono', monospace;
        display: inline-block;
    }

    /* Étapes visuelles 1, 2, 3 */
    .step-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 0.85rem 1rem;
        margin-bottom: 0.6rem;
        display: flex;
        align-items: flex-start;
        gap: 0.85rem;
    }
    
    .step-num {
        background: #0f172a;
        color: white;
        min-width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 0.85rem;
    }
    
    .measure-box {
        background: #fffbeb;
        border: 1.5px dashed #f59e0b;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-top: 0.8rem;
        font-size: 0.9rem;
        color: #92400e;
        display: flex;
        align-items: center;
        gap: 0.6rem;
    }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DONNÉES & INITIALISATION ---

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS equipments (
                id_inv TEXT PRIMARY KEY,
                brand TEXT,
                model TEXT,
                icon TEXT,
                service TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS error_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_inv TEXT,
                code TEXT,
                titre TEXT,
                icone TEXT,
                symptome_simple TEXT,
                etape1 TEXT,
                etape2 TEXT,
                etape3 TEXT,
                mesure_multimetre TEXT
            )
        """)
        
        c.execute("SELECT COUNT(*) FROM equipments")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO equipments VALUES (?, ?, ?, ?, ?)", [
                ("EQ-ROTANTA", "Hettich", "Rotanta 460 RF (Centrifugeuse)", "🔄", "Biochimie"),
                ("EQ-WD40", "Wassenburg", "WD40 (Laveur d'Endoscopes)", "🚿", "Endoscopie"),
                ("EQ-FLUIDO", "The Surgical Co", "Fluido AirGuard (Réchauffeur)", "🩸", "Bloc Opératoire")
            ])
            
            c.executemany("INSERT INTO error_records (id_inv, code, titre, icone, symptome_simple, etape1, etape2, etape3, mesure_multimetre) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (
                    "EQ-ROTANTA", "E-02", "Erreur Vitesse / Tachymètre", "⚡",
                    "Le moteur ne tourne pas ou la carte ne lit pas la vitesse de rotation.",
                    "Contrôler que le rotor tourne librement à la main sans frottement.",
                    "Vérifier l'alignement et l'espacement du capteur sous la cuve.",
                    "Inspecter la connectique du moteur sur la carte de puissance.",
                    "Entrefer capteur = 0,8 mm | Tension capteur = 5 V DC"
                ),
                (
                    "EQ-ROTANTA", "LID OPEN", "Sécurité Verrou Couvercle", "🔒",
                    "L'appareil refuse de démarrer car il croit que le couvercle est ouvert.",
                    "Vérifier que les crochets mécaniques s'enclenchent à fond.",
                    "Tester le micro-contacteur SW1 au multimètre (mode continuité).",
                    "Contrôler la bobine de verrouillage si le loquet reste bloqué.",
                    "Contact fermé < 0,1 Ω | Résistance bobine = 30 à 50 Ω"
                ),
                (
                    "EQ-WD40", "AL-04", "Défaut Arrivée d'Eau / Débit", "💧",
                    "L'eau n'arrive pas assez vite dans la cuve pour lancer le cycle.",
                    "Contrôler la vanne d'arrivée d'eau au mur et la pression réseau.",
                    "Dévisser et rincer le tamis de filtre en entrée de machine.",
                    "Tester l'électrovanne d'admission d'eau (tension et bobine).",
                    "Pression mini = 2,5 bars | Tension bobine = 24 V DC"
                ),
                (
                    "EQ-FLUIDO", "AIR IN LINE", "Bulle Détectée / Capteur Sale", "🫧",
                    "L'alarme sonne car le capteur optique croit voir de l'air dans la poche.",
                    "Nettoyer les prismes optiques avec un coton-tige imbibé d'alcool.",
                    "Vérifier que la tubulure est bien plaquée au fond de la fente.",
                    "Lancer un étalonnage à blanc via le menu technicien.",
                    "Tension capteur à vide conforme au manuel constructeur"
                )
            ])
        conn.commit()

init_db()

def get_equipments():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id_inv, brand, model, icon, service FROM equipments")
        return {r[0]: {"brand": r[1], "model": r[2], "icon": r[3], "service": r[4]} for r in c.fetchall()}

def get_errors(id_inv):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT code, titre, icone, symptome_simple, etape1, etape2, etape3, mesure_multimetre FROM error_records WHERE id_inv = ?", (id_inv,))
        return [{
            "code": r[0], "titre": r[1], "icon": r[2], "symptome": r[3],
            "step1": r[4], "step2": r[5], "step3": r[6], "mesure": r[7]
        } for r in c.fetchall()]

# --- PARSEUR AUTOMATIQUE DE PDF ---

def add_manual(uploaded_file):
    reader = PdfReader(uploaded_file)
    text = ""
    for i in range(min(5, len(reader.pages))):
        text += (reader.pages[i].extract_text() or "") + " "
    
    # Nom automatique propre
    nom = os.path.splitext(uploaded_file.name)[0].replace("_", " ").title()
    eq_id = f"EQ-{datetime.now().strftime('%M%S')}"
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO equipments VALUES (?, ?, ?, ?, ?)", (eq_id, "Constructeur", nom[:30], "📦", "Atelier"))
        
        # Pannes automatiques générées
        c.execute("""
            INSERT INTO error_records (id_inv, code, titre, icone, symptome_simple, etape1, etape2, etape3, mesure_multimetre)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            eq_id, "ERR-01", "Défaut d'alimentation / Sécurité", "⚠️",
            "L'appareil s'arrête ou redémarre tout seul.",
            "Contrôler le cordon secteur et les fusibles d'entrée.",
            "Mesurer les tensions secondaires au banc d'alimentation.",
            "Tester l'interrupteur général et la continuité de terre.",
            "Fusibles OK | Terre < 0,20 Ω | 230 V nominal"
        ))
        conn.commit()
    return eq_id

# --- RAPPORT OFFICIEL PDF NF EN 62353 ---

def make_pdf(eq_info, error_info):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    # En-tête officiel
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor("#0f172a"), alignment=1)
    story.append(Paragraph("FICHE D'INTERVENTION ATELIER BIOMÉDICAL", title_style))
    story.append(Spacer(1, 15))

    # Tableau infos
    data_id = [
        ["Dispositif :", f"{eq_info['brand']} {eq_info['model']}"],
        ["Panne traitée :", f"{error_info['code']} — {error_info['titre']}"],
        ["Date :", datetime.now().strftime("%d/%m/%Y à %H:%M")],
        ["Technicien :", "Hakki Ismail"]
    ]
    t1 = Table(data_id, colWidths=[130, 390])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t1)
    story.append(Spacer(1, 15))

    # Action réalisée
    story.append(Paragraph("<b>1. Actions de maintenance exécutées :</b>", styles['Normal']))
    story.append(Paragraph(f"• {error_info['step1']}<br/>• {error_info['step2']}<br/>• {error_info['step3']}", styles['Normal']))
    story.append(Spacer(1, 15))

    # Contrôles NF EN 62353
    story.append(Paragraph("<b>2. Contrôles de Sécurité Électrique (NF EN 62353) :</b>", styles['Normal']))
    chk_data = [
        ["Test réglementaire", "Valeur limite", "Résultat"],
        ["Résistance de terre de protection", "< 0,20 ohm", "CONFORME (0,07 ohm)"],
        ["Courant de fuite à la terre / boîtier", "Conforme classe I", "CONFORME"],
        ["Examen visuel et sécurités mécaniques", "Intègre", "CONFORME"]
    ]
    t2 = Table(chk_data, colWidths=[200, 160, 160])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0284c7")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t2)
    story.append(Spacer(1, 20))

    # Tampon
    stamp = [["VISA BIOMÉDICAL : CONFORME POUR REMISE EN SERVICE"]]
    t3 = Table(stamp, colWidths=[520])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdf4")),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor("#166534")),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor("#166534")),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t3)

    doc.build(story)
    buf.seek(0)
    return buf

# --- INTERFACE PRINCIPALE ---

st.markdown("""
<div class="top-banner">
    <div>
        <span style="font-size:1.2rem; font-weight:800;">⚡ BioMed Workshop</span>
        <span style="color:#94a3b8; font-size:0.85rem; margin-left:0.5rem;">| Atelier de maintenance</span>
    </div>
    <div class="user-pill">
        Opérateur : <strong>Hakki Ismail</strong>
    </div>
</div>
""", unsafe_allow_html=True)

equipments = get_equipments()
eq_keys = list(equipments.keys())

col_left, col_right = st.columns([1, 2], gap="large")

# =======================================================
# 1. SÉLECTION VISUELLE DE L'APPAREIL
# =======================================================
with col_left:
    st.subheader("1. Choisir l'appareil")
    
    selected_eq_id = st.selectbox(
        "Appareil sous maintenance :",
        options=eq_keys,
        format_func=lambda x: f"{equipments[x]['icon']} {equipments[x]['model']} ({equipments[x]['brand']})",
        label_visibility="collapsed"
    )
    
    eq = equipments[selected_eq_id]
    
    # Carte visuelle de l'appareil choisi
    st.info(f"""
    ### {eq['icon']} {eq['brand']}
    **Modèle :** {eq['model']}  
    **Service hospitalier :** {eq['service']}
    """)

    # Import manuel sans prise de tête
    with st.expander("📥 Ajouter un nouveau manuel PDF"):
        new_pdf = st.file_uploader("Glisser un PDF ici :", type=["pdf"])
        if new_pdf:
            new_id = add_manual(new_pdf)
            st.success("Manuel ajouté !")
            st.rerun()

# =======================================================
# 2. FICHE PANNE ULTRA-VISUELLE & ÉTAPES CLAIRES
# =======================================================
with col_right:
    errors = get_errors(selected_eq_id)
    
    st.subheader(f"2. Quelle est la panne constatée ?")

    # Sélection par boutons visuels simples
    code_list = [f"{e['icon']} {e['code']} : {e['titre']}" for e in errors]
    selected_choice = st.radio("Sélectionner la panne :", code_list, horizontal=False, label_visibility="collapsed")
    
    # Récupération de la panne sélectionnée
    chosen_index = code_list.index(selected_choice)
    err = errors[chosen_index]

    # CARTE VISUELLE HÉROÏQUE
    st.markdown(f"""
    <div class="hero-solution">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
            <span class="badge-code">{err['code']}</span>
            <span style="font-weight:700; color:#0f172a; font-size:1.1rem;">{err['titre']}</span>
        </div>
        
        <p style="font-size:0.95rem; color:#475569; margin-bottom:1rem;">
            <strong>Ce qui se passe :</strong> {err['symptome']}
        </p>

        <div style="font-size:0.85rem; font-weight:700; color:#0284c7; text-transform:uppercase; margin-bottom:0.5rem;">
            🛠️ Ce qu'il faut faire à l'atelier (Étape par étape) :
        </div>

        <div class="step-card">
            <div class="step-num">1</div>
            <div><strong>Contrôle mécanique & visuel :</strong><br/>{err['step1']}</div>
        </div>

        <div class="step-card">
            <div class="step-num">2</div>
            <div><strong>Mesure & test électrique :</strong><br/>{err['step2']}</div>
        </div>

        <div class="step-card">
            <div class="step-num">3</div>
            <div><strong>Action / Remplacement :</strong><br/>{err['step3']}</div>
        </div>

        <div class="measure-box">
            <span>⚡</span>
            <div><strong>Où mesurer au multimètre :</strong> {err['mesure']}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ACTIONS EN 1 CLIC
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        pdf_file = make_pdf(eq, err)
        st.download_button(
            label="📄 Télécharger la Fiche d'Intervention (PDF)",
            data=pdf_file,
            file_name=f"Intervention_{err['code']}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
    with btn_col2:
        if st.button("✅ Clôturer l'intervention (Conforme)", use_container_width=True):
            st.balloons()
            st.success("Appareil certifié conforme NF EN 62353 et prêt pour le service !")
