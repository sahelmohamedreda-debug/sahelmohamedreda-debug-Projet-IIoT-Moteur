from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ============================================================
# CHEMINS DU PROJET
# ============================================================

DOSSIER_SCRIPT = Path(__file__).resolve().parent
DOSSIER_PROJET = DOSSIER_SCRIPT.parent
DOSSIER_RESULTATS = DOSSIER_SCRIPT / "resultats"

FICHIER_SOURCE = (
    DOSSIER_PROJET
    / "data"
    / "mesures_prediction.csv"
)

FICHIER_DONNEES_ANALYSEES = (
    DOSSIER_RESULTATS
    / "donnees_analysees.csv"
)

FICHIER_RESUME = (
    DOSSIER_RESULTATS
    / "resume_analyse.txt"
)

GRAPHIQUE_TEMPERATURE = (
    DOSSIER_RESULTATS
    / "analyse_temperature.png"
)

GRAPHIQUE_VIBRATION = (
    DOSSIER_RESULTATS
    / "analyse_vibration.png"
)

GRAPHIQUE_RISQUE = (
    DOSSIER_RESULTATS
    / "score_risque.png"
)

DOSSIER_RESULTATS.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# PARAMETRES DE L'ANALYSE
# ============================================================

# Une mesure est enregistrée toutes les 5 secondes.
# Six mesures correspondent à environ 30 secondes.
FENETRE_MOYENNE = 6

# Douze mesures correspondent à environ une minute.
FENETRE_TENDANCE = 12

TEMP_ATTENTION = 60.0
TEMP_CRITIQUE = 75.0

VIBRATION_ATTENTION = 4.0
VIBRATION_CRITIQUE = 7.0

PENTE_TEMP_AVERTISSEMENT = 0.25
PENTE_VIB_AVERTISSEMENT = 0.04


# ============================================================
# CHARGEMENT ET NETTOYAGE DES DONNEES
# ============================================================

def charger_donnees():
    if not FICHIER_SOURCE.exists():
        raise FileNotFoundError(
            "\nFichier introuvable :\n"
            f"{FICHIER_SOURCE}\n\n"
            "Vérifie que mesures_prediction.csv "
            "se trouve dans le dossier data."
        )

    donnees = pd.read_csv(
        FICHIER_SOURCE,
        sep=";",
        encoding="utf-8-sig",
        skip_blank_lines=True
    )

    donnees.columns = [
        str(colonne)
        .replace("\ufeff", "")
        .strip()
        .lower()
        for colonne in donnees.columns
    ]

    colonnes_obligatoires = [
        "date",
        "heure",
        "temperature",
        "vibration",
        "etat",
        "fonctionnement",
        "alerte"
    ]

    colonnes_manquantes = [
        colonne
        for colonne in colonnes_obligatoires
        if colonne not in donnees.columns
    ]

    if colonnes_manquantes:
        raise ValueError(
            "\nColonnes absentes du fichier CSV : "
            + ", ".join(colonnes_manquantes)
            + "\nColonnes détectées : "
            + ", ".join(donnees.columns)
        )

    donnees["date_heure"] = pd.to_datetime(
        donnees["date"].astype(str).str.strip()
        + " "
        + donnees["heure"].astype(str).str.strip(),
        dayfirst=True,
        errors="coerce"
    )

    for colonne in ["temperature", "vibration"]:
        donnees[colonne] = (
            donnees[colonne]
            .astype(str)
            .str.strip()
            .str.replace(",", ".", regex=False)
        )

        donnees[colonne] = pd.to_numeric(
            donnees[colonne],
            errors="coerce"
        )

    for colonne in [
        "etat",
        "fonctionnement",
        "alerte"
    ]:
        donnees[colonne] = (
            donnees[colonne]
            .astype(str)
            .str.strip()
            .str.upper()
        )

    nombre_initial = len(donnees)

    donnees = donnees.dropna(
        subset=[
            "date_heure",
            "temperature",
            "vibration"
        ]
    )

    donnees = donnees[
        donnees["temperature"].between(-20, 150)
        & donnees["vibration"].between(0, 10)
    ]

    donnees = donnees.sort_values(
        "date_heure"
    ).reset_index(drop=True)

    donnees = donnees.drop_duplicates(
        subset=[
            "date_heure",
            "temperature",
            "vibration",
            "etat",
            "fonctionnement",
            "alerte"
        ]
    ).reset_index(drop=True)

    nombre_final = len(donnees)

    print(f"Lignes initiales : {nombre_initial}")
    print(f"Lignes valides : {nombre_final}")
    print(
        "Lignes éliminées : "
        f"{nombre_initial - nombre_final}"
    )

    if nombre_final < FENETRE_TENDANCE:
        raise ValueError(
            "Le fichier ne contient pas assez de mesures."
        )

    return donnees


# ============================================================
# CALCUL DE LA PENTE
# ============================================================

def calculer_pente(valeurs):
    valeurs = np.asarray(
        valeurs,
        dtype=float
    )

    if len(valeurs) < 2:
        return 0.0

    x = np.arange(
        len(valeurs),
        dtype=float
    )

    pente, _ = np.polyfit(
        x,
        valeurs,
        1
    )

    return float(pente)


# ============================================================
# ANALYSE PREDICTIVE
# ============================================================

def analyser_donnees(donnees):
    # Moyennes mobiles.
    donnees["temp_moyenne_mobile"] = (
        donnees["temperature"]
        .rolling(
            window=FENETRE_MOYENNE,
            min_periods=1
        )
        .mean()
    )

    donnees["vib_moyenne_mobile"] = (
        donnees["vibration"]
        .rolling(
            window=FENETRE_MOYENNE,
            min_periods=1
        )
        .mean()
    )

    # Écarts-types mobiles.
    donnees["temp_ecart_type"] = (
        donnees["temperature"]
        .rolling(
            window=FENETRE_MOYENNE,
            min_periods=2
        )
        .std()
        .fillna(0)
    )

    donnees["vib_ecart_type"] = (
        donnees["vibration"]
        .rolling(
            window=FENETRE_MOYENNE,
            min_periods=2
        )
        .std()
        .fillna(0)
    )

    # Tendances sur environ une minute.
    donnees["pente_temperature"] = (
        donnees["temperature"]
        .rolling(
            window=FENETRE_TENDANCE,
            min_periods=FENETRE_TENDANCE
        )
        .apply(
            calculer_pente,
            raw=True
        )
        .fillna(0)
    )

    donnees["pente_vibration"] = (
        donnees["vibration"]
        .rolling(
            window=FENETRE_TENDANCE,
            min_periods=FENETRE_TENDANCE
        )
        .apply(
            calculer_pente,
            raw=True
        )
        .fillna(0)
    )

    # Détection des tendances progressives.
    donnees["tendance_temperature"] = (
        (
            donnees["pente_temperature"]
            >= PENTE_TEMP_AVERTISSEMENT
        )
        & (
            donnees["temp_moyenne_mobile"] >= 40
        )
    )

    donnees["tendance_vibration"] = (
        (
            donnees["pente_vibration"]
            >= PENTE_VIB_AVERTISSEMENT
        )
        & (
            donnees["vib_moyenne_mobile"] >= 2.5
        )
    )

    # Détection adaptative par moyenne mobile et écart-type.
    donnees["anomalie_temperature"] = (
        donnees["temperature"]
        > (
            donnees["temp_moyenne_mobile"]
            + 2 * donnees["temp_ecart_type"]
        )
    )

    donnees["anomalie_vibration"] = (
        donnees["vibration"]
        > (
            donnees["vib_moyenne_mobile"]
            + 2 * donnees["vib_ecart_type"]
        )
    )

    # Dépassements des seuils fixes.
    donnees["temp_attention"] = (
        donnees["temperature"]
        > TEMP_ATTENTION
    )

    donnees["temp_critique"] = (
        donnees["temperature"]
        > TEMP_CRITIQUE
    )

    donnees["vib_attention"] = (
        donnees["vibration"]
        > VIBRATION_ATTENTION
    )

    donnees["vib_critique"] = (
        donnees["vibration"]
        > VIBRATION_CRITIQUE
    )

    # Calcul initial du score de risque.
    score = pd.Series(
        0.0,
        index=donnees.index
    )

    score += np.clip(
        donnees["temperature"] / TEMP_CRITIQUE,
        0,
        1
    ) * 25

    score += np.clip(
        donnees["vibration"] / VIBRATION_CRITIQUE,
        0,
        1
    ) * 25

    score += (
        donnees["tendance_temperature"]
        .astype(int)
        * 15
    )

    score += (
        donnees["tendance_vibration"]
        .astype(int)
        * 15
    )

    score += (
        donnees["anomalie_temperature"]
        .astype(int)
        * 10
    )

    score += (
        donnees["anomalie_vibration"]
        .astype(int)
        * 10
    )

    donnees["score_risque"] = np.clip(
        score,
        0,
        100
    ).round(1)

    # Toute mesure critique doit obtenir au moins 80/100.
    condition_critique = (
        donnees["temp_critique"]
        | donnees["vib_critique"]
    )

    donnees.loc[
        condition_critique,
        "score_risque"
    ] = np.maximum(
        donnees.loc[
            condition_critique,
            "score_risque"
        ],
        80.0
    )

    # Classification du risque.
    conditions = [
        donnees["score_risque"] >= 75,
        donnees["score_risque"] >= 50,
        donnees["score_risque"] >= 30
    ]

    niveaux = [
        "RISQUE_CRITIQUE",
        "RISQUE_ELEVE",
        "RISQUE_MODERE"
    ]

    donnees["niveau_predictif"] = np.select(
        conditions,
        niveaux,
        default="RISQUE_FAIBLE"
    )

    # Recommandations automatiques.
    def creer_recommandation(ligne):
        if (
            ligne["temp_critique"]
            or ligne["vib_critique"]
        ):
            return (
                "Arrêter le moteur et effectuer "
                "une inspection immédiate"
            )

        if (
            ligne["tendance_temperature"]
            and ligne["tendance_vibration"]
        ):
            return (
                "Dégradation globale probable : "
                "planifier rapidement une maintenance"
            )

        if ligne["tendance_vibration"]:
            return (
                "Contrôler les roulements, "
                "l'alignement et les fixations"
            )

        if ligne["tendance_temperature"]:
            return (
                "Contrôler la charge, le refroidissement "
                "et l'alimentation du moteur"
            )

        if (
            ligne["anomalie_temperature"]
            or ligne["anomalie_vibration"]
        ):
            return (
                "Mesure inhabituelle : vérifier "
                "le moteur et les capteurs"
            )

        return "Fonctionnement stable"

    donnees["recommandation"] = donnees.apply(
        creer_recommandation,
        axis=1
    )

    return donnees


# ============================================================
# GRAPHIQUE DE TEMPERATURE
# ============================================================

def graphique_temperature(donnees):
    figure, axe = plt.subplots(
        figsize=(13, 6)
    )

    axe.plot(
        donnees["date_heure"],
        donnees["temperature"],
        label="Température mesurée",
        linewidth=1
    )

    axe.plot(
        donnees["date_heure"],
        donnees["temp_moyenne_mobile"],
        label="Moyenne mobile",
        linewidth=2
    )

    points_tendance = donnees[
        donnees["tendance_temperature"]
    ]

    axe.scatter(
        points_tendance["date_heure"],
        points_tendance["temperature"],
        label="Tendance croissante",
        s=25
    )

    points_anormaux = donnees[
        donnees["anomalie_temperature"]
        | donnees["temp_critique"]
    ]

    axe.scatter(
        points_anormaux["date_heure"],
        points_anormaux["temperature"],
        label="Anomalie thermique",
        s=35
    )

    axe.axhline(
        TEMP_ATTENTION,
        linestyle="--",
        label="Seuil d'attention : 60 °C"
    )

    axe.axhline(
        TEMP_CRITIQUE,
        linestyle="--",
        label="Seuil critique : 75 °C"
    )

    axe.set_title(
        "Maintenance prédictive - Température"
    )

    axe.set_xlabel(
        "Date et heure"
    )

    axe.set_ylabel(
        "Température (°C)"
    )

    axe.legend()
    axe.grid(True)

    figure.autofmt_xdate()
    figure.tight_layout()

    figure.savefig(
        GRAPHIQUE_TEMPERATURE,
        dpi=200,
        bbox_inches="tight"
    )

    plt.close(figure)


# ============================================================
# GRAPHIQUE DE VIBRATION
# ============================================================

def graphique_vibration(donnees):
    figure, axe = plt.subplots(
        figsize=(13, 6)
    )

    axe.plot(
        donnees["date_heure"],
        donnees["vibration"],
        label="Vibration mesurée",
        linewidth=1
    )

    axe.plot(
        donnees["date_heure"],
        donnees["vib_moyenne_mobile"],
        label="Moyenne mobile",
        linewidth=2
    )

    points_tendance = donnees[
        donnees["tendance_vibration"]
    ]

    axe.scatter(
        points_tendance["date_heure"],
        points_tendance["vibration"],
        label="Tendance croissante",
        s=25
    )

    points_anormaux = donnees[
        donnees["anomalie_vibration"]
        | donnees["vib_critique"]
    ]

    axe.scatter(
        points_anormaux["date_heure"],
        points_anormaux["vibration"],
        label="Anomalie vibratoire",
        s=35
    )

    axe.axhline(
        VIBRATION_ATTENTION,
        linestyle="--",
        label="Seuil d'attention : 4 mm/s"
    )

    axe.axhline(
        VIBRATION_CRITIQUE,
        linestyle="--",
        label="Seuil critique : 7 mm/s"
    )

    axe.set_title(
        "Maintenance prédictive - Vibrations"
    )

    axe.set_xlabel(
        "Date et heure"
    )

    axe.set_ylabel(
        "Vibration (mm/s)"
    )

    axe.legend()
    axe.grid(True)

    figure.autofmt_xdate()
    figure.tight_layout()

    figure.savefig(
        GRAPHIQUE_VIBRATION,
        dpi=200,
        bbox_inches="tight"
    )

    plt.close(figure)


# ============================================================
# GRAPHIQUE DU SCORE DE RISQUE
# ============================================================

def graphique_risque(donnees):
    figure, axe = plt.subplots(
        figsize=(13, 5)
    )

    axe.plot(
        donnees["date_heure"],
        donnees["score_risque"],
        label="Score de risque",
        linewidth=2
    )

    axe.axhline(
        30,
        linestyle="--",
        label="Risque modéré"
    )

    axe.axhline(
        50,
        linestyle="--",
        label="Risque élevé"
    )

    axe.axhline(
        75,
        linestyle="--",
        label="Risque critique"
    )

    axe.set_ylim(
        0,
        105
    )

    axe.set_title(
        "Évolution du score prédictif de risque"
    )

    axe.set_xlabel(
        "Date et heure"
    )

    axe.set_ylabel(
        "Score de risque / 100"
    )

    axe.legend()
    axe.grid(True)

    figure.autofmt_xdate()
    figure.tight_layout()

    figure.savefig(
        GRAPHIQUE_RISQUE,
        dpi=200,
        bbox_inches="tight"
    )

    plt.close(figure)


# ============================================================
# RESUME TEXTUEL
# ============================================================

def generer_resume(donnees):
    total = len(donnees)

    lignes_normales = int(
        (donnees["etat"] == "NORMAL").sum()
    )

    lignes_attention = int(
        (donnees["etat"] == "ATTENTION").sum()
    )

    lignes_critiques = int(
        (donnees["etat"] == "CRITIQUE").sum()
    )

    tendances_temperature = int(
        donnees["tendance_temperature"].sum()
    )

    tendances_vibration = int(
        donnees["tendance_vibration"].sum()
    )

    anomalies_temperature = int(
        donnees["anomalie_temperature"].sum()
    )

    anomalies_vibration = int(
        donnees["anomalie_vibration"].sum()
    )

    score_maximal = float(
        donnees["score_risque"].max()
    )

    indice_maximal = donnees[
        "score_risque"
    ].idxmax()

    ligne_maximale = donnees.loc[
        indice_maximal
    ]

    derniere_ligne = donnees.iloc[-1]

    pourcentage_normal = (
        lignes_normales / total * 100
    )

    pourcentage_attention = (
        lignes_attention / total * 100
    )

    pourcentage_critique = (
        lignes_critiques / total * 100
    )

    contenu = [
        "RÉSUMÉ DE L'ANALYSE PRÉDICTIVE",
        "=" * 45,
        "",
        f"Nombre de mesures valides : {total}",
        (
            "Période analysée : "
            f"{donnees['date_heure'].min()} "
            f"à {donnees['date_heure'].max()}"
        ),
        "",
        "RÉPARTITION DES ÉTATS",
        (
            f"- Mesures normales : {lignes_normales} "
            f"({pourcentage_normal:.1f} %)"
        ),
        (
            f"- Mesures en attention : {lignes_attention} "
            f"({pourcentage_attention:.1f} %)"
        ),
        (
            f"- Mesures critiques : {lignes_critiques} "
            f"({pourcentage_critique:.1f} %)"
        ),
        "",
        "TEMPÉRATURE",
        (
            "- Minimum : "
            f"{donnees['temperature'].min():.2f} °C"
        ),
        (
            "- Maximum : "
            f"{donnees['temperature'].max():.2f} °C"
        ),
        (
            "- Moyenne : "
            f"{donnees['temperature'].mean():.2f} °C"
        ),
        (
            "- Tendances croissantes détectées : "
            f"{tendances_temperature}"
        ),
        (
            "- Anomalies adaptatives détectées : "
            f"{anomalies_temperature}"
        ),
        "",
        "VIBRATIONS",
        (
            "- Minimum : "
            f"{donnees['vibration'].min():.2f} mm/s"
        ),
        (
            "- Maximum : "
            f"{donnees['vibration'].max():.2f} mm/s"
        ),
        (
            "- Moyenne : "
            f"{donnees['vibration'].mean():.2f} mm/s"
        ),
        (
            "- Tendances croissantes détectées : "
            f"{tendances_vibration}"
        ),
        (
            "- Anomalies adaptatives détectées : "
            f"{anomalies_vibration}"
        ),
        "",
        "RISQUE MAXIMAL",
        (
            "- Score maximal : "
            f"{score_maximal:.1f}/100"
        ),
        (
            "- Date du risque maximal : "
            f"{ligne_maximale['date_heure']}"
        ),
        (
            "- Température correspondante : "
            f"{ligne_maximale['temperature']:.2f} °C"
        ),
        (
            "- Vibration correspondante : "
            f"{ligne_maximale['vibration']:.2f} mm/s"
        ),
        (
            "- Niveau : "
            f"{ligne_maximale['niveau_predictif']}"
        ),
        (
            "- Recommandation : "
            f"{ligne_maximale['recommandation']}"
        ),
        "",
        "ÉTAT FINAL DE L'HISTORIQUE",
        (
            "- Température finale : "
            f"{derniere_ligne['temperature']:.2f} °C"
        ),
        (
            "- Vibration finale : "
            f"{derniere_ligne['vibration']:.2f} mm/s"
        ),
        (
            "- Niveau prédictif : "
            f"{derniere_ligne['niveau_predictif']}"
        ),
        (
            "- Recommandation : "
            f"{derniere_ligne['recommandation']}"
        ),
        "",
        "INTERPRÉTATION",
        (
            "Une hausse progressive détectée avant le "
            "dépassement des seuils représente un signe "
            "précoce de dégradation. Les seuils fixes "
            "déclenchent l'alerte lorsque le danger est "
            "déjà présent, tandis que la moyenne mobile "
            "et la pente permettent une détection anticipée."
        )
    ]

    FICHIER_RESUME.write_text(
        "\n".join(contenu),
        encoding="utf-8"
    )


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    print()
    print("==========================================")
    print(" ANALYSE PREDICTIVE DU MOTEUR INDUSTRIEL")
    print("==========================================")
    print()

    print("1. Chargement des données...")
    donnees = charger_donnees()

    print()
    print("2. Calcul des indicateurs...")
    donnees = analyser_donnees(
        donnees
    )

    print()
    print("3. Enregistrement des données analysées...")

    donnees.to_csv(
        FICHIER_DONNEES_ANALYSEES,
        sep=";",
        index=False,
        encoding="utf-8"
    )

    print()
    print("4. Génération des graphiques...")

    graphique_temperature(
        donnees
    )

    graphique_vibration(
        donnees
    )

    graphique_risque(
        donnees
    )

    print()
    print("5. Génération du résumé...")

    generer_resume(
        donnees
    )

    print()
    print("Analyse terminée avec succès.")
    print()
    print("Résultats disponibles dans :")
    print(DOSSIER_RESULTATS)
    print()
    print("Fichiers créés :")
    print(
        f"- {FICHIER_DONNEES_ANALYSEES.name}"
    )
    print(
        f"- {GRAPHIQUE_TEMPERATURE.name}"
    )
    print(
        f"- {GRAPHIQUE_VIBRATION.name}"
    )
    print(
        f"- {GRAPHIQUE_RISQUE.name}"
    )
    print(
        f"- {FICHIER_RESUME.name}"
    )


if __name__ == "__main__":
    main()