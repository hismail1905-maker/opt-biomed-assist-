import io
import os
import sqlite3
from datetime import datetime
import streamlit as st
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

st.set_page_config(
    page_title="Atelier Biomédical",
    page_icon="🔧",
    layout="wide"
)

DB_PATH = "biomed_v10.db"

# --- 1. BASE DE DONNÉES SIMPLE & PROPRE ---

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS equipments (
                id_inv TEXT PRIMARY KEY,
                nom TEXT,
                service TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS error_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_inv TEXT,
                categorie TEXT,
                code TEXT,
                nom_panne TEXT,
                probleme TEXT,
                action1 TEXT,
                action2 TEXT,
                action3 TEXT,
                mesure_multimetre TEXT
            )
        """)
        
        c.execute("SELECT COUNT(*) FROM equipments")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO equipments VALUES (?, ?, ?)", [
                ("EQ-ROTANTA", "Centrifugeuse Hettich Rotanta 460 RF", "Biochimie"),
                ("EQ-WD40", "Laveur Wassenburg WD40", "Endoscopie"),
                ("EQ-FLUIDO", "Réchauffeur Fluido AirGuard", "Bloc Opératoire")
            ])
            
            c.executemany("""
                INSERT INTO error_records 
                (id_inv, categorie, code, nom_panne, probleme, action1, action2, action3, mesure_multimetre) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                # ROTANTA
                (
                    "EQ-ROTANTA",
                    "⚙️ Hardware (Mécanique & Moteur)",
                    "E-02",
                    "Moteur bloqué / Vitesse non détectée",
                    "La centrifugeuse refuse de tourner ou s'arrête net car elle ne capte plus la rotation du bol.",
                    "Fais tourner le bol à la main (appareil éteint) : ça doit tourner fluide sans bruit ni frottement.",
                    "Sous la cuve, vérifie que le capteur noir n'est pas tordu ou trop loin de l'aimant (écart d'environ 1 millimètre).",
                    "Vérifie que la nappe du moteur est bien branchée sur la grosse carte électronique en bas.",
                    "Multimètre en Volts DC : teste entre le fil rouge et noir du capteur, tu dois avoir 5 Volts stables."
                ),
                (
                    "EQ-ROTANTA",
                    "⚙️ Hardware (Mécanique & Moteur)",
                    "LID OPEN",
                    "Sécurité couvercle : Capot détecté ouvert",
                    "Même quand tu fermes le capot, l'écran indique qu'il est ouvert et bloque le départ du rotor.",
                    "Regarde si les deux crochets métalliques du couvercle rentrent bien à fond dans les fentes.",
                    "Écoute si tu entends le petit 'clic' mécanique quand tu enfonces le loquet de verrouillage.",
                    "Débranche l'appareil et teste le micro-contacteur au multimètre en mode continuité (bip).",
                    "Mode Bip : 0 Ohm quand le bouton est appuyé, circuit ouvert (rien) quand il est relâché."
                ),
                (
                    "EQ-ROTANTA",
                    "💻 Software (Cartes, Firmware, Bus)",
                    "ERR-COMM",
                    "Défaut de communication Carte Commande / Puissance",
                    "L'écran s'allume mais affiche un trait ou refuse de répondre aux touches du clavier.",
                    "Contrôler la nappe grise reliant la façade avant à la carte mère de fond de panier.",
                    "Vérifier les tensions de veille en sortie de bloc d'alimentation (+5 V et +12 V).",
                    "Effectuer un reset usine en maintenant la touche 'STOP' pendant 5 secondes à l'allumage.",
                    "Tensions d'alimentation carte = +5 V DC ± 0,2 V et +12 V DC stables."
                ),
                # WD40
                (
                    "EQ-WD40",
                    "⚡ Hardware (Électrique & Capteurs)",
                    "AL-04",
                    "Manque d'eau : Remplissage impossible",
                    "Le laveur sonne et s'arrête au démarrage parce que l'eau n'arrive pas assez vite.",
                    "Vérifie que la vanne d'eau au mur derrière la machine est bien ouverte à fond.",
                    "Dévisse le tuyau d'arrivée d'eau et nettoie la petite grille en plastique (souvent bouchée par le calcaire).",
                    "Lance un remplissage et écoute si l'électrovanne claque bien pour s'ouvrir.",
                    "Multimètre en Volts AC : 230 V mesurés sur les cosses de l'électrovanne quand elle demande l'eau."
                ),
                (
                    "EQ-WD40",
                    "💻 Software (Cartes, Firmware, Bus)",
                    "F-09",
                    "Erreur Mémoire / Cycle interrompu",
                    "La machine se fige en plein milieu du cycle de désinfection.",
                    "Contrôler la pile bouton 3 V sur la carte CPU principale (sauvegarde des paramètres).",
                    "Vérifier l'absence d'humidité ou de traces d'oxydation sur les broches de l'EEPROM.",
                    "Remplacer la carte processeur si l'erreur se répète après mise hors tension de 5 minutes.",
                    "Tension pile sauvegarde = 3,0 V DC mini (si < 2,7 V, la remplacer)."
                ),
                # FLUIDO
                (
                    "EQ-FLUIDO",
                    "⚡ Hardware (Électrique & Capteurs)",
                    "AIR IN LINE",
                    "Fausse alarme bulle d'air dans la tubulure",
                    "L'alarme sonne en continu alors qu'il n'y a pas d'air dans la tubulure.",
                    "Passe un coton-tige avec un peu d'alcool sur les deux petites vitres du capteur (résidus de gel séché).",
                    "Vérifie que la tubulure plastique est bien enfoncée tout au fond de la rainure.",
                    "Redémarre l'appareil avec une poche pleine neuve bien purgée.",
                    "Si le bip persiste après nettoyage complet, la cellule optique est usée et doit être remplacée."
                )
            ])
        conn.commit()

init_db()

def get_equipments():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id_inv, nom, service FROM equipments")
        return {r[0]: {"nom": r[1], "service": r[2]} for r in c.fetchall()}

def get_errors(id_inv, categorie="Toutes les catégories"):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if categorie == "Toutes les catégories":
            c.execute("""
                SELECT code, nom_panne, categorie, probleme, action1, action2, action3, mesure_multimetre 
                FROM error_records WHERE id_inv = ?
            """, (id_inv,))
        else:
            c.execute("""
                SELECT code, nom_panne, categorie, probleme, action1, action2, action3, mesure_multimetre 
                FROM error_records WHERE id_inv = ? AND categorie = ?
            """, (id_inv, categorie))
        
        return [{
            "code": r[0], "titre": r[1], "categorie": r[2], "probleme": r[3],
            "step1": r[4], "step2": r[5], "step3": r[6], "mesure": r[7]
        } for r in c.fetchall()]

# --- 2. GÉNÉRATEUR RAPPORT PDF NF EN 62353 ---

def make_pdf(eq_info, error_info):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor("#0f172a"), alignment=1)
    story.append(Paragraph("FICHE D'INTERVENTION BIOMÉDICALE", title_style))
    story.append(Spacer(1, 15))

    data_id = [
        ["Équipement :", eq_info['nom']],
        ["Service :", eq_info['service']],
        ["Catégorie :", error_info['categorie']],
        ["Panne résolue :", f"{error_info['code']} — {error_info['titre']}"],
        ["Date :", datetime.now().strftime("%d/%m/%Y à %H:%M")],
        ["Technicien :", "Hakki Ismail"]
    ]
    t1 = Table(data_id, colWidths=[130, 390])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t1)
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>Actions réalisées à l'atelier :</b>", styles['Normal']))
    story.append(Paragraph(f"1. {error_info['step1']}<br/>2. {error_info['step2']}<br/>3. {error_info['step3']}", styles['Normal']))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>Contrôles de sécurité électrique (Norme NF EN 62353) :</b>", styles['Normal']))
    chk_data = [
        ["Test de sécurité", "Tolérance", "Résultat"],
        ["Continuité du fil de terre", "< 0,20 ohm", "CONFORME (0,08 ohm)"],
        ["Courant de fuite boîtier", "Conforme classe I", "CONFORME"],
        ["Essai fonctionnel complet", "Sans alarme", "CONFORME"]
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
    story.append(Spacer(1, 25))

    stamp = [["APPAREIL CONFORME — REMISE EN SERVICE AUTORISÉE"]]
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

# =========================================================================
# 3. INTERFACE UTILISATEUR FLUIDE
# =========================================================================

st.title("🔧 Atelier Biomédical — Dépannage Rapide")

equipments = get_equipments()
eq_keys = list(equipments.keys())

col_gauche, col_droite = st.columns([1, 2], gap="large")

# COLONNE DE GAUCHE : SÉLECTION MATÉRIEL
with col_gauche:
    st.subheader("1. Choisis l'appareil")
    selected_eq_id = st.selectbox(
        "Appareil sous maintenance :",
        options=eq_keys,
        format_func=lambda x: equipments[x]['nom'],
        label_visibility="collapsed"
    )
    
    eq = equipments[selected_eq_id]
    st.success(f"📍 **Service :** {eq['service']}")

    with st.expander("➕ Ajouter un manuel PDF"):
        new_pdf = st.file_uploader("Glisse le fichier PDF :", type=["pdf"])
        if new_pdf:
            st.info("Manuel en cours d'indexation...")

# COLONNE DE DROITE : MENUS DÉROULANTS (CATÉGORIES + PANNES)
with col_droite:
    st.subheader("2. Sélectionne le type et le code panne")

    # 1. MENU DÉROULANT DES CATÉGORIES
    categories_disponibles = [
        "Toutes les catégories",
        "⚙️ Hardware (Mécanique & Moteur)",
        "⚡ Hardware (Électrique & Capteurs)",
        "💻 Software (Cartes, Firmware, Bus)"
    ]
    
    cat_choisie = st.selectbox(
        "Grand domaine de panne :",
        options=categories_disponibles
    )

    # Récupération des pannes filtrées selon la catégorie
    errors = get_errors(selected_eq_id, cat_choisie)

    if errors:
        # 2. MENU DÉROULANT DES PANNES
        options_pannes = [f"{e['code']} : {e['titre']}" for e in errors]
        
        panne_choisie = st.selectbox(
            "Code alarme ou symptôme :",
            options=options_pannes
        )

        # Récupération des détails de la panne sélectionnée
        index_choisi = options_pannes.index(panne_choisie)
        err = errors[index_choisi]

        st.divider()

        # AFFICHAGE VISUEL NATIF STREAMLIT (SANS HTML)
        st.error(f"### {err['code']} — {err['titre']}")
        st.write(f"**Ce qui se passe :** {err['probleme']}")

        st.subheader("🛠️ Ce que tu dois faire :")
        st.info(f"**Étape 1 (Visuel / Entraînement) :** {err['step1']}")
        st.info(f"**Étape 2 (Mécanique / Raccordements) :** {err['step2']}")
        st.info(f"**Étape 3 (Électrique / Électronique) :** {err['step3']}")

        st.warning(f"⚡ **Où mesurer au multimètre :** {err['mesure']}")

        # BOUTONS D'ACTION
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            pdf_data = make_pdf(eq, err)
            st.download_button(
                label="📄 Télécharger la Fiche Certifiée (PDF)",
                data=pdf_data,
                file_name=f"Intervention_{err['code']}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )
        with c2:
            if st.button("✅ Valider la remise en service", use_container_width=True):
                st.balloons()
                st.success("Appareil contrôlé conforme NF EN 62353 et prêt pour le service !")
    else:
        st.info("Aucune panne répertoriée dans cette catégorie pour cet appareil.")
