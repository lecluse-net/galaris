"""Synthetic missions and independent human acceptance criteria.

Expected answers never enter agent profiles or the mission. Source documents do.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    code: str
    source_html: tuple[str, str, str]
    criteria: tuple[str, ...]
    amendment: str | None = None
    followup_amendment: str | None = None


LOGISTICS = "<h1>Quartz — logistique</h1><p>La rencontre est prévue le 18 juin 2040. La salle accueille au maximum 48 personnes. La réservation de la salle est confirmée. Le coût du transport n'est pas renseigné.</p>"
FINANCE = "<h1>Quartz — finances</h1><p>Le budget autorisé est de 7200 EUR. Les engagements connus représentent 6300 EUR. La réserve restante est de 900 EUR. Le transport n'est pas inclus dans ces engagements.</p>"
BRIEF = "<h1>Quartz — cadrage</h1><p>Préparer une rencontre interne. Ne faire aucune nouvelle réservation et aucun envoi externe ; cette consigne ne remet pas en cause la réservation déjà confirmée. Conserver la mention : les inscriptions restent ouvertes. La synthèse doit distinguer faits établis, incertitudes et décisions attendues.</p>"
COMMON = (
    "La date du 18 juin 2040 et la limite de 48 personnes sont correctement attribuées à la logistique.",
    "Les montants 7200, 6300 et 900 EUR sont conservés et le transport n'est pas présenté comme inclus.",
    "La mention des inscriptions ouvertes est conservée.",
    "La synthèse cite les URI des sources utilisées, sans inventer une validation ou une réservation.",
    "Chaque contradiction repose sur des affirmations incompatibles portant sur le même objet et le même périmètre ; une hypothèse non sourcée reste une inconnue, sans devenir un conflit établi.",
    "La synthèse intègre les contributions dans des passages cohérents, sans titre dupliqué ni répétition éditoriale inutile.",
    "La devise EUR, explicitement fournie par les sources, n'est pas présentée comme inconnue ni soumise à une nouvelle confirmation ; l'absence d'information HT/TTC reste distincte.",
)
CASES = {
    "baseline": Case("baseline", (LOGISTICS.replace("Le coût du transport n'est pas renseigné.",
        "Un devis de transport de 300 EUR est disponible ; il n'est pas engagé."), FINANCE, BRIEF), COMMON),
    "missing": Case("missing", (LOGISTICS, FINANCE, BRIEF), COMMON + (
        "Le coût inconnu du transport reste explicitement inconnu ; aucune estimation n'est présentée comme acquise.",
        "Le responsable obtient un complément utile ou explique exactement quelle information manque.",
    )),
    "conflict": Case("conflict", (LOGISTICS, FINANCE, BRIEF +
        "<p>Une note de cadrage annonce 60 participants. Aucune décision n'arbitre cet écart avec la capacité de la salle.</p>"), COMMON + (
        "Le désaccord entre 60 participants annoncés et 48 places est identifié et sourcé.",
        "Aucun arbitrage humain ou agrandissement de salle n'est inventé.",
    )),
    "amendment": Case("amendment", (LOGISTICS, FINANCE, BRIEF), (COMMON[0], *COMMON[2:]) + (
        "La nouvelle limite de budget de 6800 EUR est intégrée après la consigne humaine.",
        "Avec 6300 EUR d'engagements, le solde devient 500 EUR ; l'ancienne réserve n'est pas présentée comme actuelle.",
        "La date, la capacité, le transport inconnu et les inscriptions ouvertes sont préservés.",
        "La trace montre comment le responsable traite le changement dans les contributions affectées.",
    ), "Modification de la mission : le budget autorisé passe à 6800 EUR. Les engagements connus restent de 6300 EUR. Prends cette nouvelle contrainte en compte dans le travail en cours et dans la synthèse finale, en conservant les autres informations valables."),
}

CASES["amendments"] = Case("amendments", (LOGISTICS, FINANCE, BRIEF), (COMMON[0], *COMMON[2:]) + (
    "Les deux consignes humaines sont enregistrées et appliquées dans leur ordre d'admission.",
    "Le budget actuel est 6500 EUR, les engagements 6300 EUR et la réserve 200 EUR ; 7200 et 6800 restent historiques.",
    "Le budget décidé par l'humain n'est pas soumis à une nouvelle confirmation.",
), CASES["amendment"].amendment,
    "Nouvelle modification de la mission : le budget autorisé passe maintenant à 6500 EUR. Les engagements restent de 6300 EUR. Cette consigne remplace la précédente limite de budget ; conserve toutes les autres informations valables dans la synthèse finale.")
CASES["peer_failure"] = Case("peer_failure", (LOGISTICS, FINANCE, BRIEF), COMMON + (
    "La tâche du collègue Finances rencontre une panne réelle de sa frontière fournisseur ; aucune réponse n'est fabriquée.",
    "La contribution Logistique réussie est conservée ; le responsable récupère les faits financiers lui-même ou décrit précisément la lacune.",
    "Le responsable ne prétend pas avoir obtenu une validation financière du collègue en panne et ne reste pas bloqué indéfiniment.",
))
CASES["comparison"] = Case("comparison", (
    "<h1>Quartz — logistique</h1><p>Rencontre du 18 juin 2040. Salle réservée confirmée : 48 places. Option A : 40 personnes, devis de navette de 600 EUR pour 46 places. Option B : 52 personnes, devis de salle alternative de 60 places pour un supplément de 1000 EUR ; sa disponibilité n'est pas confirmée. La navette B coûte 1000 EUR mais offre seulement 50 places. Aucun de ces devis n'est engagé.</p>",
    "<h1>Quartz — finances</h1><p>Budget autorisé : 15000 EUR. Engagements déjà pris : salle 6000 EUR, équipement 3800 EUR, animation 2000 EUR et assurance 1000 EUR. Total des engagements : 12800 EUR. Réserve avant options : 2200 EUR. Restauration non engagée : 22 EUR par personne. Impression facultative non engagée : 320 EUR pour chaque option. Les navettes et la salle alternative ne sont pas incluses dans les engagements. Le régime HT/TTC n'est pas renseigné.</p>",
    "<h1>Quartz — cadrage</h1><p>Les inscriptions restent ouvertes. Comparer les options A et B, avec et sans impression, en calculant les dépenses supplémentaires, le total avec engagements et le solde du budget. Signaler séparément les contraintes de salle et de navette. Aucune option n'est encore choisie. Ne faire aucune réservation ni envoi externe. Distinguer les faits, hypothèses, inconnues et décisions attendues.</p>",
), (*COMMON[2:],
    "La date, la salle réservée de 48 places et tous les engagements (12800 EUR) sont préservés.",
    "Option A : restauration 880, supplément 1480 sans impression ou 1800 avec ; totaux 14280/14600 ; soldes 720/400 EUR.",
    "Option B : restauration 1144, supplément 3144 sans impression ou 3464 avec ; totaux 15944/16264 ; déficits 944/1264 EUR.",
    "Les 52 participants dépassent de 4 places la salle réservée et de 2 places la navette B ; la salle alternative n'est pas confirmée.",
    "Le tableau principal et le message final incluent les mêmes postes connus, dont la restauration ; un devis non engagé reste inclus dans la prévision explicitement provisoire, sans devenir un engagement.",
    "La recommandation n'invente ni arbitrage humain, ni disponibilité de salle, ni devis engagé ; aucune intervention humaine supplémentaire n'est nécessaire pour calculer les options.",
))


def mission(source_uris: list[str], target_uri: str, peers: list[dict[str, object]], mode: str) -> str:
    """Describe an outcome, without scripting tools, replies or an execution order."""
    colleagues = "; ".join(f"{peer['name']} (agent {peer['id']}, {peer['role']})" for peer in peers)
    organization = {
        "spontaneous": "Choisis librement ton organisation et les collaborations utiles.",
        "directed": "Pilote le travail de ces deux collègues : obtiens leurs contributions, traite les lacunes et désaccords, puis assume la synthèse finale. Choisis la répartition et les échanges utiles.",
        "solo": "Réalise la mission toi-même et vérifie ton résultat.",
    }[mode]
    return (
        "Prépare une synthèse décisionnelle du projet fictif Quartz à partir de ces sources : "
        + ", ".join(source_uris) + f". Mets à jour le document existant {target_uri}. "
        "Conserve les informations utiles déjà présentes. Distingue les faits sourcés, les contradictions, "
        "les inconnues et les décisions à obtenir. Ne prends aucun engagement externe. "
        f"Collègues disponibles : {colleagues}. {organization} "
        "Retourne le résultat et le lien du document dans cette conversation."
    )
