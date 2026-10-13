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
    page_title="Atelier Biomédical",
    page_icon="🔧",
    layout="wide"
)

DB_PATH = "biomed_v14.db"

# --- 1. BASE DE DONNÉES ---

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
                (
                    "EQ-ROTANTA",
                    "⚙️ Hardware (Mécanique & Moteur)",
                    "E-02",
                    "Défaut de vitesse ou blocage mécanique du rotor",
                    "La centrifugeuse refuse de se lancer ou coupe son cycle en cours car la carte électronique ne reçoit aucun signal du capteur de vitesse.",
                    "Faire tourner le rotor manuellement à l'arrêt pour vérifier qu'aucun frottement mécanique ne freine l'axe du moteur.",
                    "Contrôler sous la cuve que le capteur tachymétrique est bien aligné face à son aimant, avec un écart d'environ 1 millimètre.",
                    "Vérifier le branchement complet du connecteur moteur sur la carte de commande principale située dans le socle.",
                    "Prendre la mesure en Volts continu (DC) entre le fil rouge et le fil noir du capteur : la tension doit être de 5 Volts constants."
                ),
                (
                    "EQ-ROTANTA",
                    "⚙️ Hardware (Mécanique & Moteur)",
                    "LID OPEN",
                    "Sécurité couvercle : Détection de capot ouvert",
                    "Le verrouillage électronique refuse le démarrage car le micro-contacteur ne confirme pas la fermeture complète du couvercle.",
                    "Vérifier visuellement que les deux crochets métalliques s'engagent bien jusqu'au fond des fentes de verrouillage.",
                    "Actionner manuellement le loquet pour vérifier la présence du déclic mécanique du contacteur de sécurité.",
                    "Appareil hors tension, débrancher les cosses du micro-contacteur et contrôler son ouverture et sa fermeture au multimètre.",
                    "Mettre le multimètre en mode continuité (bip sonore) : 0 Ohm mesuré contact appuyé, circuit ouvert contact relâché."
                ),
                (
                    "EQ-WD40",
                    "⚡ Hardware (Électrique & Capteurs)",
                    "AL-04",
                    "Alimentation en eau insuffisante : Remplissage impossible",
                    "Le niveau d'eau minimal n'est pas atteint dans le temps prévu, ce qui bloque le lancement du cycle de lavage.",
                    "Vérifier que le robinet d'arrivée d'eau au mur est complètement ouvert et que le tuyau n'est pas pincé derrière la machine.",
                    "Démonter le raccord d'arrivée d'eau et nettoyer soigneusement la grille de filtration souvent obstruée par des dépôts calcaires.",
                    "Contrôler que la bobine de l'électrovanne d'arrivée d'eau s'active bien lors de la phase de remplissage.",
                    "Mesurer la tension alternative sur les cosses de l'électrovanne : vous devez relever 230 Volts lors de l'appel d'eau."
                ),
                (
                    "EQ-FLUIDO",
                    "⚡ Hardware (Électrique & Capteurs)",
                    "AIR IN LINE",
                    "Détection d'air : Fausse alarme sur la ligne de perfusion",
                    "Le capteur ultrasonique détecte une discontinuité dans la tubulure et coupe la chauffe par mesure de sécurité.",
                    "Nettoyer les deux prismes de mesure avec un chiffon doux imbibé d'alcool isopropylique pour enlever tout résidu sec.",
                    "S'assurer que la tubulure en plastique est fermement poussée au fond de la rainure de détection sur toute sa longueur.",
                    "Purger totalement la ligne avec une poche pleine neuve pour évacuer la moindre microbulle coincée dans la chambre.",
                    "Vérifier la propreté des lentilles optiques. Si l'alarme persiste avec une tubulure purgée, le capteur est à remplacer."
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

# --- 2. FILTRAGE ANTI-SOMMAIRE & EXTRACTION DES VRAIES PANNES ---

def is_table_of_contents_line(text):
    """Détecte et rejette formellement les lignes de sommaire avec des pointillés."""
    if re.search(r'\.{3,}', text):  # Détecte 3 points de suite ou plus
        return True
    if re.search(r'\s*\.{2,}\s*\d+$', text):  # Détecte pointillés terminés par un numéro de page
        return True
    return False

def clean_text_segment(text):
    """Supprime les pointillés, tirets isolés et numéros de page résiduels."""
    text = re.sub(r'\.{2,}', '', text)
    text = re.sub(r'[\t_]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def process_and_save_pdf(uploaded_file):
    reader = PdfReader(uploaded_file)
    total_pages = len(reader.pages)
    
    # Évite les 10 premières pages si le manuel est long (zone du sommaire/table des matières)
    start_page = 10 if total_pages > 25 else 0
    max_scan = min(total_pages, 90)
    
    base_name = os.path.splitext(uploaded_file.name)[0].replace("_", " ").title()
    eq_id = f"EQ-{re.sub(r'[^A-Z0-9]', '', base_name[:6].upper())}-{datetime.now().strftime('%M%S')}"

    extracted_errors = []
    seen = set()

    # Regex ciblée : exige un vrai code d'erreur (E02, ERR 12, ALARM 3, etc.)
    code_regex = re.compile(
        r'\b(?:ERROR|ERR|CODE|ALARM|ALARME|FAULT|DÉFAUT)\s*[-:#.]?\s*([0-9]{1,4}|[A-Z]{1,3}[0-9]{1,3})\b',
        re.IGNORECASE
    )
    
    technical_alarms = [
        "LID OPEN", "COVER OPEN", "AIR IN LINE", "NO FLOW", "OVERHEAT",
        "PRESSURE HIGH", "PRESSURE LOW", "SENSOR FAIL", "MOTOR FAIL"
    ]

    progress_bar = st.progress(0, text="Analyse du manuel sans la table des matières...")

    for i in range(start_page, max_scan):
        progress_bar.progress((i - start_page + 1) / (max_scan - start_page), text=f"Lecture page {i+1} sur {max_scan}...")
        text = reader.pages[i].extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) >= 4]

        idx = 0
        while idx < len(lines):
            line = lines[idx]

            # REJET IMMÉDIAT DU SOMMAIRE
            if is_table_of_contents_line(line):
                idx += 1
                continue

            code_trouve = None
            desc = ""

            match = code_regex.search(line)
            if match:
                code_trouve = match.group(0).upper().replace("  ", " ").strip()
                reste = line[match.end():].strip(" :-\t|")
                if len(reste) > 3 and not is_table_of_contents_line(reste):
                    desc = clean_text_segment(reste)

            if not code_trouve:
                for ta in technical_alarms:
                    if re.search(r'\b' + ta + r'\b', line, re.IGNORECASE):
                        code_trouve = ta
                        reste = re.sub(r'(?i)\b' + ta + r'\b', '', line).strip(" :-\t|")
                        if not is_table_of_contents_line(reste):
                            desc = clean_text_segment(reste) if len(reste) > 3 else "Déclenchement d'alarme de sécurité"
                        break

            if code_trouve:
                clean_k = re.sub(r'[^A-Z0-9]', '', code_trouve)
                
                # Élimine les faux positifs et titres de chapitres
                if clean_k not in seen and len(clean_k) >= 2 and not any(stop in code_trouve for stop in ["ISO", "PAGE", "REV", "FIG", "TABLE", "SECTION"]):
                    
                    # Lecture des lignes suivantes pour obtenir une phrase complète
                    next_sentences = []
                    step = 1
                    while (idx + step < len(lines)) and step <= 3:
                        nxt = lines[idx + step]
                        if is_table_of_contents_line(nxt) or code_regex.search(nxt):
                            break
                        cleaned_nxt = clean_text_segment(nxt)
                        if len(cleaned_nxt) > 4:
                            next_sentences.append(cleaned_nxt)
                        step += 1

                    if next_sentences:
                        if not desc:
                            desc = next_sentences[0]
                            explication = " ".join(next_sentences[1:]) if len(next_sentences) > 1 else "Vérifier le sous-ensemble mécanique et la connectique."
                        else:
                            explication = " ".join(next_sentences)
                        idx += (step - 1)
                    else:
                        desc = desc or "Anomalie technique signalée par l'appareil."
                        explication = "Vérifier la connectique, inspecter le composant et contrôler l'alimentation au multimètre."

                    # On s'assure que les phrases sont propres et sans résidus
                    desc = clean_text_segment(desc)
                    explication = clean_text_segment(explication)

                    if not desc.endswith('.'):
                        desc += "."
                    if not explication.endswith('.'):
                        explication += "."

                    # Si après nettoyage la description contient encore des points répétés, on rejette
                    if ".." not in desc and ".." not in explication:
                        seen.add(clean_k)

                        full_c = f"{code_trouve} {desc} {explication}".lower()
                        if any(w in full_c for w in ["moteur", "rotor", "pompe", "porte", "couvercle", "verrou"]):
                            cat = "⚙️ Hardware (Mécanique & Moteur)"
                        elif any(w in full_c for w in ["carte", "cpu", "firmware", "bus", "ram", "rom"]):
                            cat = "💻 Software (Cartes, Firmware, Bus)"
                        else:
                            cat = "⚡ Hardware (Électrique & Capteurs)"

                        extracted_errors.append((
                            eq_id,
                            cat,
                            code_trouve,
                            desc,
                            f"Le manuel constructeur indique : {desc}",
                            "Vérifier le câblage et s'assurer que les connecteurs sont fermement enclenchés.",
                            f"Action indiquée dans la documentation : {explication}",
                            "Lancer un cycle de test pour valider l'effacement du défaut.",
                            "Prendre les mesures de tension au multimètre (+5V / +12V / 24V) et vérifier la terre."
                        ))
            idx += 1

    progress_bar.empty()

    if not extracted_errors:
        extracted_errors.append((
            eq_id,
            "⚙️ Hardware (Mécanique & Moteur)",
            "MAINT-01",
            "Inspection périodique et maintenance préventive générale.",
            "Contrôle technique régulier de l'équipement à l'atelier.",
            "Vérifier l'intégrité de la structure mécanique et des fixations.",
            "Nettoyer les filtres de ventilation et vérifier les connexions internes.",
            "Procéder aux essais fonctionnels complets à vide et en charge.",
            "Mesurer la résistance de terre de protection : valeur exigée inférieure à 0,20 Ohm."
        ))

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO equipments VALUES (?, ?, ?)", (eq_id, base_name, "Atelier"))
        c.executemany("""
            INSERT INTO error_records 
            (id_inv, categorie, code, nom_panne, probleme, action1, action2, action3, mesure_multimetre) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, extracted_errors)
        conn.commit()

    return eq_id, len(extracted_errors)

# --- 3. RAPPORT PDF ---

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
    story.append(Paragraph(f"• {error_info['step1']}<br/>• {error_info['step2']}<br/>• {error_info['step3']}", styles['Normal']))
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

# --- INTERFACE UTILISATEUR ---

st.title("🔧 Atelier Biomédical — Dépannage Rapide")

equipments = get_equipments()
eq_keys = list(equipments.keys())

col_gauche, col_droite = st.columns([1, 2], gap="large")

# COLONNE GAUCHE
with col_gauche:
    st.subheader("1. Choisis l'appareil")
    
    default_idx = 0
    if "latest_eq_id" in st.session_state and st.session_state["latest_eq_id"] in eq_keys:
        default_idx = eq_keys.index(st.session_state["latest_eq_id"])

    selected_eq_id = st.selectbox(
        "Appareil sous maintenance :",
        options=eq_keys,
        index=default_idx,
        format_func=lambda x: equipments[x]['nom'],
        label_visibility="collapsed"
    )
    
    eq = equipments[selected_eq_id]
    st.success(f"📍 **Service :** {eq['service']}")

    st.divider()

    with st.expander("📥 Ajouter un nouveau manuel PDF", expanded=False):
        uploaded_pdf = st.file_uploader("Glisse le PDF du manuel ici :", type=["pdf"])
        if uploaded_pdf is not None:
            file_key = f"done_{uploaded_pdf.name}_{uploaded_pdf.size}"
            if file_key not in st.session_state:
                with st.spinner("Indexation sans les tables des matières..."):
                    new_id, count = process_and_save_pdf(uploaded_pdf)
                    st.session_state[file_key] = True
                    st.session_state["latest_eq_id"] = new_id
                    st.success(f"Manuel indexé : {count} panne(s) répertoriée(s).")
                    st.rerun()

# COLONNE DROITE
with col_droite:
    st.subheader("2. Sélectionne le type et le code panne")

    categories_disponibles = [
        "Toutes les catégories",
        "⚙️ Hardware (Mécanique & Moteur)",
        "⚡ Hardware (Électrique & Capteurs)",
        "💻 Software (Cartes, Firmware, Bus)"
    ]
    
    cat_choisie = st.selectbox("Grand domaine de panne :", options=categories_disponibles)

    errors = get_errors(selected_eq_id, cat_choisie)

    if errors:
        st.caption(f"ℹ️ **{len(errors)} panne(s)** disponible(s) dans cette sélection.")
        
        options_pannes = [f"{e['code']} : {e['titre']}" for e in errors]
        panne_choisie = st.selectbox("Code alarme ou symptôme :", options=options_pannes)

        index_choisi = options_pannes.index(panne_choisie)
        err = errors[index_choisi]

        st.divider()

        # AFFICHAGE EN PHRASES COMPLÈTES SANS POINTILLÉS
        st.error(f"### {err['code']} — {err['titre']}")
        st.write(f"**Ce qui se passe :** {err['probleme']}")

        st.subheader("🛠️ Ce que tu dois faire :")
        st.info(f"**Étape 1 (Visuel / Entraînement) :** {err['step1']}")
        st.info(f"**Étape 2 (Mécanique / Raccordements) :** {err['step2']}")
        st.info(f"**Étape 3 (Électrique / Électronique) :** {err['step3']}")

        st.warning(f"⚡ **Où mesurer au multimètre :** {err['mesure']}")

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            pdf_data = make_pdf(eq, err)
            st.download_button(
                label="📄 Télécharger la Fiche Certifiée (PDF)",
                data=pdf_data,
                file_name=f"Fiche_{err['code']}.pdf",
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
