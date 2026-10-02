# 0155 — Parcours de fichiers durables et enrichissement versionné

Statut : accepté. Date : 2026-10-01.

## Décision

File Share possède les runs de découverte et les journaux de réparation de ses projections.
Un run conserve agent, connexion, empreinte de configuration, runtime, racine, budget,
frontière et curseur. Le scheduler existant traite une page de 500 entrées au maximum par
itération, dans sa session isolée. Les runs alternent par date de dernier traitement ; les
échecs ont un backoff borné et deviennent terminaux après cinq tentatives. Les modifications
interactives restent prioritaires ; les contrôles Memory ne déclenchent aucun modèle.

Cette maintenance structurelle n'est pas un workflow métier externe : son état reste dans
File Share, sans créer de définition Process Galaris supplémentaire. L'API Memory permet de
lancer et suivre un run durable et de l'annuler. Les mutations et les lectures de diagnostic
vérifient les privilèges Memory et le périmètre humain de gestion de l'agent.

Le parcours automatique des racines admissibles se renouvelle après six heures. Seuls les
providers annonçant le mode récursif sont parcourus ; Console et les autres providers en
mode URI connues bénéficient d'une vérification des URI déjà rencontrées, sans exploration.
Une page tronquée sans curseur ou une profondeur/budget épuisé produit une couverture
partielle. La frontière durable est bornée à 4 096 répertoires en attente ; une arborescence
plus large conserve un état de couverture partielle et peut être traitée par racines plus
petites. Une liste directe complète permet de retirer seulement ses enfants absents,
à condition qu'aucune observation plus récente que le début du run ne les ait actualisés.
Une erreur réseau ou un refus d'accès ne constitue jamais une preuve de suppression.

L'observation d'une opération externe réussie journalise ses métadonnées et ses effets
prouvés avant d'appliquer la projection. Le journal ne contient ni octets de fichiers, ni
extraits de recherche, ni métadonnées arbitraires du provider. Une réparation rejoue uniquement
la projection, jamais une écriture ou une suppression externe. Si la base est indisponible,
le résultat externe reste réussi avec `indexing_status=failed` ; aucune durabilité fictive
n'est annoncée pour une preuve que la base n'a pas pu enregistrer.

Dream reçoit un port de catalogue lié à la composition, sans dépendance métier inverse.
Il enrichit une version de fichier par tour et conserve ses reçus/checkpoints habituels,
sa rotation et sa préemption Task/Voice. Les options de médias existantes gouvernent les
analyses textuelles, documentaires extractibles, images et audio/vidéo. La matérialisation
est temporaire et bornée à 32 MiB. Une modification source ou une révocation invalide
l'application du résultat ; une révision déjà acquise ne provoque pas une nouvelle analyse.
Les champs Memory édités manuellement restent préservés.

Les diagnostics terminaux sont conservés 30 jours. Les fiches et leurs contenus personnels
restent indépendants de cette rétention. Les performances sont qualifiées sur des données
synthétiques ; aucune cible de latence n'est revendiquée sans mesure conforme.

Le contrôle de binding SQL matérialise les connexions courantes pour calculer l'empreinte
une fois par connexion par requête, sans cache inter-requêtes susceptible de retarder une
révocation. La recherche matérialise ses candidats lexicaux avant les contrôles d'accès.
Les recherches littérales `ILIKE` conservent leur sémantique et utilisent deux index GIN
trigrammes, sur titre et texte. DbAdmin prépare l'extension PostgreSQL `pg_trgm` avant
la convergence des index déclarés dans les modèles. L'observation utilise un index partiel
des entrées absentes pour contrôler les réponses tardives sans parcourir les fiches présentes.
