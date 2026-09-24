# ADR 0129 — Décisions spécialisées pour les topics et la mémoire

- Statut : Accepted
- Date : 2026-09-24
- Étend [0127](0127-optional-dispatcher-decision-model.md).

## Périmètre et garanties

Le modèle `decision_llm_id` du profil effectif sert aux choix sémantiques fermés.
Les textes nouveaux continuent d'utiliser leur modèle génératif. Aucun réglage de modèle
supplémentaire n'est ajouté. Un profil personnel vide ne récupère pas la spécialisation du
profil global. Si Décision est vide, les parcours texte existants restent utilisés : un seul
LLM local peut donc continuer à tout traiter.

L'inventaire des consommateurs conduit au partage suivant :

| Parcours | Décision spécialisée | Travail conservé |
| --- | --- | --- |
| Dispatcher Task et porte des pairs IA | Choix autorisés du dispatcher | Règles déterministes, harnais, droits et court-circuit humain |
| Topic d'une activité/Task | Réutiliser un dossier fourni ou demander une création | Rédaction du titre, description et mots-clés par le texte |
| Topic des messages | Même sujet ou changement ; sélection parmi les dossiers fournis | Fenêtre temporelle et résolution canonique ; rédaction des nouveaux dossiers |
| Dream extraction mémoire | Ignorer, rattacher des sources ou demander une extraction | Rédaction des faits nouveaux et validation métier |
| Acquisition d'un souvenir proche | Confirmer l'équivalence ou conserver séparément | Recherche vectorielle, contrôle d'accès, écriture idempotente |
| Planner, briefing, réflexion, suivi de Goal, apprentissage de Skill | Pas de substitution | Le résultat exige un contenu rédigé ; ajouter un filtre serait un coût sans suppression garantie d'appel |
| Maintenance déterministe, projections, seuils et transitions | Aucun appel ajouté | Les règles restent du code |

La façade `run_profile_decision` résout le couple spécialisé/texte depuis un même profil,
puis utilise l'inférence durable commune. Le repli récupérable suit la politique existante
du profil et le niveau texte propre à l'usage (`low` pour le dispatcher, `ultra-low` pour
Dream). Les annulations et refus d'accès ne deviennent pas un repli. Les probabilités et la
confiance absentes restent absentes ; la continuité peut être appliquée comme choix explicite
sans inventer une probabilité ni ajouter un seuil universel.

## Dream : conserver les faits, éviter les rédactions inutiles

Une requête regroupe la décision de rétention et un choix de rattachement par souvenir
candidat. `ignore` exige l'absence de tout fait durable dans la source courante ; `link`
exige que tous les faits durables soient entièrement présents dans les candidats. Un fait
nouveau, une contradiction, une couverture partielle ou une incertitude appelle l'extracteur
texte avec l'entrée complète. Des réponses incohérentes, notamment `link` sans cible, font
également poursuivre l'extraction. Les validations des opérations et les listes de cibles
autorisées restent appliquées avant toute écriture.

La similarité vectorielle fournit un candidat de dédoublonnage. Avec Décision configurée,
une équivalence sémantique complète doit être confirmée avant de transformer CREATE en LINK.
La révision du candidat est revérifiée sous verrou après l'attente réseau. Un changement
concurrent fait conserver le nouveau souvenir. Cette « fusion » ajoute uniquement une
provenance : elle ne réécrit ni ne supprime le souvenir existant. Sans spécialisation, le
comportement antérieur de dédoublonnage est conservé.

Les décisions restent traçables par les `LLMCall` durables et les métadonnées de préparation
ou d'acquisition. Les appels pendant l'application sont rattachés au reçu Dream et leurs
coûts ajoutés au coût de préparation, y compris lorsqu'une application échoue.

## Lab, délais et qualification

Les candidats Décision sont admis dans les mécanismes Dispatcher, Topics et Extraction mémoire.
Pour les deux parcours hybrides, le modèle texte Dream courant est figé à l'admission avec
son empreinte. Changer de profil ensuite ne redirige pas l'essai ; modifier ou supprimer le
modèle figé fait échouer le candidat. Un candidat texte n'emploie jamais implicitement le
modèle Décision du profil. Le repli d'un candidat spécialisé reste désactivé. Le coût candidat
comprend les choix et les rédactions réellement nécessaires.

Les plafonds pilotes de 10/30 secondes décrits dans l'ADR 0127 sont supprimés. La requête
Décision et son transport n'imposent aucun délai par défaut ; une échéance explicite du
propriétaire reste respectée. Les leases, annulations et limites générales déjà présentes
dans les workflows continuent de s'appliquer. Aucun nouveau paramètre de délai n'est ajouté.

Le pilote Dispatcher réel a réussi 14 cas synthétiques sur 14, en environ 0,624 s par choix
et 0,000806 USD au total, sur une seule répétition sans témoin texte. Ce résultat motive
l'extension, mais ne qualifie pas la qualité du classement ou de la rétention mémoire.
Les tests automatisés remplacent le transport fournisseur et prouvent les branchements,
le repli, les coûts, les refus de substitution et les effets durables. Les nouveaux parcours
restent à mesurer avec Jev réel dans le Lab. Un filtrage suivi d'une rédaction ajoute un
appel : un gain systématique de latence ou de coût n'est pas garanti.
