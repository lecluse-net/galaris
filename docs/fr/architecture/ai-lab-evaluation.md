<p align="right"><strong>Français</strong> · <a href="../../en/architecture/ai-lab-evaluation.md">English</a></p>

# Architecture et théorie d’évaluation du Lab IA

Le Lab expose onze traitements évaluables avec un contrat commun : **une variable métier par
item**, son contexte propre, des paramètres partagés et une sortie à évaluer.
Le [guide opérateur](../user/lab-ai.md) décrit l’écran ; l’[ADR 0078](../../../project/decisions/0078-lab-variable-and-judgment-campaigns.md)
décrit la séparation des deux passes. Les contrats et tests du dépôt font foi.

## 1. Contrats des traitements

Le catalogue exhaustif est déclaré dans `back/app/lab/contracts.py`. Chaque descripteur expose
le traitement, la variable, son schéma, la sortie et tous les paramètres éditables. Le registre
complète ce contrat avec le schéma de configuration de l’algorithme, les limites d’inférence,
le schéma de sortie et la rubrique.

| Traitement | Variable unique | Résultat évalué |
|---|---|---|
| Dispatcher | Demande | Décision de routage |
| Briefing | Objectif | Préparation et choix de ressources |
| Planner | Objectif | Plan ou demande de clarification |
| Classification thématique | Textes de l’échange | Affectations thématiques |
| Extraction mémoire | Contenu source | Classement et opérations mémoire |
| Apprentissage | Résultat d’exécution et observations | Leçons étayées |
| Suivi d’objectif | Résultat du cycle | Évaluation du progrès et continuation |
| Exécuteur de tâches | Demande | Réponse et appels d’outils enregistrés |
| Exécuteur conversationnel | Tour courant | Réponse et actions proposées |
| Exécuteur vocal | Transcription du tour | Réponse et actions proposées |
| Analyse de Tasks | Dossier de preuves | Diagnostic structuré |

Une variable peut être structurée : un dossier ou un résultat d’exécution est un seul objet
métier. L’objectif initial de l’apprentissage reste un paramètre ; il ne devient pas une
seconde variable. Le texte des messages thématiques reste dans la variable, leurs métadonnées
dans le contexte. La référence attendue est séparée des intrants candidats.

## 2. Jeu, item et provenance

Un jeu possède tous les paramètres, la configuration de l’algorithme et, pour un exécuteur,
son suffixe de consignes. L’entrée d’un item contient `{variable_value, context}` ;
son résultat attendu est séparé. L’API et le modèle refusent les paramètres sur un item.
La résolution valide les champs inconnus et les contraintes de chaque traitement.
Les paramètres structurels d’un algorithme composé sont au niveau jeu.

`context_schema` et `context_defaults` décrivent les données propres à l’item. Les historiques
(`history`, `messages`), clarifications, médias historiques, Topic initial, métadonnées des
messages et suivi antérieur du Goal y résident selon le traitement. Les champs sont disjoints
des paramètres du jeu et validés sans accepter de surcharge. Les captures conservent ce contexte ;
seuls les réglages partagés font l’objet du contrôle d’écart. Les snapshots figent le contexte
pour les deux passes et le rejeu du juge ; l’empreinte du corpus inclut son contenu.

L’IHM édite les paramètres sur le jeu, la variable, le contexte et la sortie attendue sur l’item, avec une prévisualisation de l’entrée
résolue. Les consignes rendues sont consultables ; pour les algorithmes composés, les étapes
suivantes dépendent aussi des résultats intermédiaires.

Les captures comparent les paramètres observés aux paramètres du jeu. Un écart renvoie
HTTP 409 avec les différences et un jeton lié au jeu, à sa révision et à la source.
Seule une nouvelle requête portant ce jeton confirme l’ajout avec les paramètres du jeu ;
l’item devient un brouillon à vérifier. Un changement du jeu ou de la source exige une nouvelle
confirmation. La restauration d’une capture utilise le même contrôle. Les paramètres d’origine
restent dans la provenance et ne sont jamais des surcharges exécutables.

Les captures copient les preuves disponibles sans modifier la source. Les traces insuffisantes
restent des brouillons à revoir : un texte historique ne permet pas de reconstruire silencieusement
tous ses paramètres. Le diagnostic peut être capturé depuis une Task. L’analyse interactive d’une Task reste disponible.

## 3. Fondements théoriques

### 3.1 Validité : mesurer le bon construit

Une mesure est utile si elle représente le phénomène que l’on veut piloter. Comparer deux chaînes
répond à la question « se ressemblent-elles ? », pas à la question « satisfont-elles le même
objectif ? ». Le Lab part donc du construit métier, puis l’opérationnalise :

```text
objectif métier
    → exigences observables
    → dimensions propres au mécanisme
    → scores par dimension
    → agrégat versionné
    → décision humaine contextualisée
```

Cette approche rejoint la discipline **TEVV** — test, evaluation, validation and verification — du
[NIST](https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv) : les métriques,
datasets et méthodes dépendent du contexte d’usage, et aucune mesure unique ne couvre précision,
robustesse, sécurité, explicabilité ou biais.

### 3.2 Couverture : scénarios multiples plutôt qu’une moyenne abstraite

[HELM](https://crfm.stanford.edu/2022/11/17/helm.html) recommande une évaluation couvrant plusieurs
scénarios et plusieurs métriques, tout en rendant explicite ce qui manque. Galaris applique ce
principe à l’échelle d’un mécanisme : un dataset doit représenter les situations réellement
rencontrées, leurs frontières et leurs risques, pas seulement des cas nominaux faciles.

La moyenne d’un benchmark n’est donc interprétable qu’avec sa matrice de couverture. Un score de
95 % sur cinq cas homogènes ne prouve pas la robustesse du système sur les langues, longueurs,
ambiguïtés ou contraintes absentes du dataset.

### 3.3 Mesures exactes pour les choix fermés

Une égalité exacte reste la meilleure mesure lorsqu’un contrat n’accepte qu’un ensemble fini de
valeurs et que ces valeurs ont un sens normatif. C’est le cas du Dispatcher pour :

- la route active `EXEC` ou `PLAN` ;
- l’effort `standard` ou `high` ;
- la nécessité d’une action ;
- la langue normalisée.

Le Lab n’utilise pas un juge sémantique pour rendre équivalentes deux routes qui produiraient des
workflows différents.

### 3.4 Évaluation sémantique pour les sorties ouvertes

Pour les textes, plans, listes de souvenirs ou décisions argumentées, une référence unique ne
décrit pas tout l’espace des bonnes réponses. [G-Eval](https://aclanthology.org/2023.emnlp-main.153/)
montre notamment que les métriques classiques fondées sur le recouvrement corrèlent mal avec le
jugement humain pour des générations ouvertes et diverses.

Galaris traite donc la référence comme une source d’exigences possibles, jamais comme un gabarit à
imiter. Le juge doit accepter une formulation, un ordre, un nombre d’items, une taxonomie, une
confiance ou une stratégie différents lorsqu’ils satisfont autant l’objectif et le contrat.

### 3.5 Rubriques multidimensionnelles

Un verdict global du type « cette réponse semble bonne » est difficile à auditer. Les approches
[LLM-Rubric](https://aclanthology.org/2024.acl-long.745/) et
[Prometheus](https://arxiv.org/abs/2310.08491) soutiennent l’usage de critères explicites et
personnalisés. [PaperBench](https://openai.com/index/paperbench/) décompose de même un objectif
complexe en exigences gradables et évalue séparément la qualité du juge.

Le Lab impose donc cinq dimensions par mécanisme. Chaque dimension possède :

- un code stable ;
- un critère observable ;
- un poids explicite ;
- un score de 0 à 100 ;
- une appréciation courte fondée sur les données fournies.

Le modèle ne calcule pas le score global. Le serveur contrôle les codes retournés et applique les
poids versionnés.

### 3.6 Jugement pointwise

Le juge évalue une sortie candidate indépendamment, contre l’entrée, l’objectif, le contrat et la
rubrique. Il ne choisit pas un « gagnant » entre deux modèles. Ce format pointwise évite de faire de
l’ordre des candidats un élément direct de la décision.

Le prompt du juge :

- traite toutes les données comme non fiables et non comme des instructions ;
- ne reçoit pas l’identité du modèle candidat ;
- interdit de récompenser la ressemblance lexicale, la verbosité, l’assurance ou l’identité ;
- fournit les ancres 0, 25, 50, 75 et 100 ;
- demande exactement une note par dimension ;
- réserve les défaillances critiques aux défauts capables d’invalider le résultat.

### 3.7 Le juge n’est pas une vérité terrain

Les LLM juges peuvent favoriser une position, une réponse plus longue, un style plus fluide ou
leurs propres productions. Ces phénomènes sont documentés par les études sur le
[biais de position](https://aclanthology.org/2025.ijcnlp-long.18/), le
[biais de surface et de verbosité](https://aclanthology.org/2024.ccl-1.101/) et
[l’auto-préférence](https://aclanthology.org/2025.emnlp-main.86/).

Conséquence : le pourcentage du Lab est une estimation instrumentée, pas une vérité absolue. Il
doit être calibré sur des jugements humains et relu lorsque l’enjeu est important. Même les
benchmarks experts comme GDPval décrivent le juge LLM comme une estimation et conservent la
[préférence d’experts humains comme standard](https://evals.openai.com/gdpval/grading).


## 4. Exécution puis jugement

```text
jeu + items prêts → instantané des entrées, paramètres et modèles
                  → passe 1 : toutes les sorties candidates + contrôles objectifs
                  → passe 2 : jugement de chaque sortie persistée
                  → agrégats, verdicts, couverture, coûts et analyse facultative
```

Le candidat reçoit uniquement son entrée résolue. Les outils des exécuteurs sont des enregistreurs
avec réponses simulées configurables ; ils ne créent ni Task, ni Process, ni message.
Les autres mécanismes utilisent leurs contrats métier et les services partagés correspondants.

Le run fige les cas, les consignes, les paramètres, la rubrique, le profil de raisonnement et les
liaisons des modèles. Des empreintes distinctes identifient corpus, contexte, candidat et juge.
La liaison au fournisseur est vérifiée avant chaque inférence ; sa modification provoque une
erreur explicite. Les credentials ne sont pas copiés. Ces instantanés ne figent pas les poids
distants d’un fournisseur ni une ancienne version du code.

Le worker commun réclame une unité de travail sous verrou, libère la transaction pendant
l’inférence et publie uniquement s’il possède encore le bail. Un heartbeat renouvelle ce bail.
Tous les candidats sont publiés avant le début des jugements. Une annulation conserve les
résultats acquis ; la reprise ne recalcule que les unités manquantes.

Une campagne de jugement possède son modèle, sa configuration, sa séquence et ses résultats.
**Rejuger** crée une campagne supplémentaire à partir des sorties enregistrées sans rappeler
le candidat. L’ancienne campagne reste consultable. Le run expose la dernière évaluation et
cumule séparément les coûts candidat et juge.

## 5. Contrôles, scores et verdicts

La première passe conserve les erreurs candidates, le schéma de sortie, les contrôles propres
au traitement et la similarité structurelle avec la référence. Les comparaisons fermées du
Dispatcher sont critiques ; les références des productions ouvertes sont des exemples.

La seconde passe applique une rubrique pondérée versionnée. Le serveur calcule la moyenne des
dimensions ; un défaut critique signalé par le juge plafonne ce score à 50 %. Un contrôle
objectif critique en échec interdit également un verdict favorable, même si la note sémantique
est élevée. Le seuil initial de réussite est 75 %.

`completed` signifie que le traitement technique du run est terminé ; cela ne signifie pas que
le candidat a réussi les tests. Les verdicts distinguent réussite, échec et jugement inconclusif.
Une panne du juge ne reçoit pas artificiellement une note nulle : le score reste absent, la
couverture baisse et le run peut être `partial`. Les échecs candidats restent visibles.
L’interface sépare progression des deux passes, score, couverture, verdicts et coûts.

La similarité de référence reste un diagnostic ; elle ne remplace jamais un jugement manquant.
L’analyse Markdown est un rapport facultatif fondé sur les résultats enregistrés.

## 8. Construire un dataset capable de détecter les dérives

### 8.1 Partir des risques, pas du volume

Avant d’ajouter des cas, écrire les échecs que le benchmark doit détecter. Par exemple :

- Briefing qui oublie une interdiction mais cite tous les outils ;
- Planner techniquement élégant qui change le livrable demandé ;
- extraction mémoire qui conserve une information éphémère ou sensible ;
- apprentissage qui conclut à une cause non prouvée ;
- suivi d’objectif qui arrête après un texte enthousiaste sans preuve de fin.

Chaque risque important doit être représenté par au moins un cas qui échoue lorsqu’il survient.

### 8.2 Matrice de couverture recommandée

Un dataset robuste mélange :

| Famille | Exemples |
|---|---|
| Cas nominaux | entrée claire, preuve complète, solution attendue évidente |
| Alternatives valides | ordre différent, autre taxonomie, autre découpage ou autre outil justifié |
| Frontières | deux routes plausibles, ambiguïté de rattachement, confiance intermédiaire |
| Entrées incomplètes | contexte absent, ressource manquante, preuve insuffisante |
| Contraintes en tension | rapidité contre vérification, concision contre couverture |
| Négatifs plausibles | réponse fluide mais hors objectif, invention crédible, succès non prouvé |
| Robustesse | contexte long, champs inutiles, ordre perturbé, caractères ou JSON limites |
| Multilingue | cas français et anglais représentatifs de la production |
| Sécurité | contenu tentant d’instruire le juge, donnée sensible à ne pas mémoriser |
| Régressions réelles | incident ou mauvaise décision déjà observés en production |

Une simple duplication avec quelques mots changés ne crée pas une nouvelle couverture. Elle est
utile seulement si elle isole une hypothèse : longueur, langue, ambiguïté, contrainte ou structure.

### 8.3 Séparer mise au point et validation

Si tous les cas servent à corriger le prompt, ils cessent progressivement de mesurer la
généralisation. Pour une utilisation exigeante, maintenir :

- un jeu **de travail**, visible et utilisé pour le tuning ;
- un jeu **de validation**, relancé avant livraison ;
- si possible un petit jeu **holdout**, non utilisé lors des corrections quotidiennes.

Le champ `purpose` matérialise ces rôles (`work`, `validation`, `holdout`) sans modifier
les droits d'accès. Les catégories d'items permettent de filtrer les cas et de compter
les items prêts et actifs par famille ; elles sont figées dans les snapshots.

### 8.4 Qualité d’une référence

Une bonne référence :

- satisfait réellement l’entrée ;
- rend visibles les exigences critiques ;
- ne contient pas d’invention ou de dépendance indisponible ;
- n’impose pas artificiellement une forme lorsque plusieurs formes sont valides ;
- est relue par un humain compétent lorsque le cas devient un garde de livraison.

Générer une référence avec le modèle du Lab accélère la saisie mais ne crée pas une vérité terrain.
La même famille de modèle peut reproduire les mêmes biais lors de la génération et du jugement.

### 8.5 Dataset vivant mais benchmark interprétable

Un dataset évolue quand une nouvelle dérive est observée. Pour conserver l’interprétation :

- ne modifiez jamais un ancien run ;
- dupliquez un cas avant une expérimentation radicale ;
- relancez une baseline après toute modification du dataset ;
- comparez uniquement des runs ayant la même version de score et des snapshots de cas équivalents ;
- documentez la raison d’un ajout, d’une suppression ou d’un changement de référence.

Le Lab conserve les snapshots mais ne calcule pas encore un fingerprint de comparabilité. Cette
vérification relève actuellement de l’opérateur.

## 9. Étalonner le juge avec des humains

### 9.1 Constituer un jeu d’étalonnage

Sélectionner des cas couvrant tout le spectre : excellents, acceptables, limites, mauvais et
critiques. Pour chaque cas, conserver plusieurs sorties candidates lorsque c’est possible, y
compris des alternatives valides très différentes de la référence.

### 9.2 Écrire un protocole humain

Les évaluateurs humains doivent recevoir exactement :

- la définition du mécanisme ;
- l’entrée ;
- la rubrique et ses ancres ;
- la sortie candidate ;
- la référence en précisant son rôle non normatif.

Ils notent chaque dimension indépendamment avant de voir la note du LLM. Deux évaluateurs ou plus
permettent d’identifier les critères ambigus ; leurs désaccords doivent être arbitrés et utilisés
pour améliorer la rubrique.

### 9.3 Mesurer l’accord

Ne pas vérifier seulement la moyenne globale. Comparer au minimum :

- l’erreur absolue moyenne par dimension ;
- le biais moyen — juge systématiquement trop généreux ou trop sévère ;
- la corrélation de rang entre modèles ou versions ;
- les faux passages au-dessus d’un seuil opérationnel ;
- les défaillances critiques manquées ou inventées ;
- les désaccords selon langue, longueur, type de cas et origine du modèle.

Une bonne corrélation globale peut masquer un juge dangereux sur les cas critiques.

### 9.4 Réétalonner

Répéter l’étalonnage lorsque :

- l’usage **Lab** du profil courant change ;
- une rubrique ou son poids change ;
- le prompt du mécanisme change matériellement ;
- le dataset change de domaine ou de langue ;
- un biais ou un incident nouveau est découvert.

Le changement d’une formule crée une nouvelle version de score. Les anciens pourcentages ne sont
jamais recalculés silencieusement.

## 10. Détecter une dérive

Une dérive est une variation durable de comportement par rapport au construit visé. Elle peut
venir du candidat, du mécanisme, du dataset ou du juge.

### 10.1 Conditions minimales de comparaison

Deux runs ne sont directement comparables que si les éléments suivants sont contrôlés :

- même mécanisme et même version de score ;
- mêmes cas, entrées et références ;
- même configuration pertinente du mécanisme ;
- même juge, ou juge réétalonné ;
- paramètres d’inférence comparables ;
- couverture de jugement complète ou différence explicitement prise en compte.

Changer de modèle candidat est la variable voulue lors d’un benchmark de modèles. Changer le
dataset et le modèle en même temps empêche d’attribuer la variation.

### 10.2 Lire la dérive par dimension

Une moyenne stable peut cacher une compensation : +15 en style de plan, −15 en fidélité à
l’objectif. Toujours examiner :

- la moyenne par dimension ;
- les cas qui changent de classe qualitative ;
- les nouvelles défaillances critiques ;
- les erreurs candidat et juge ;
- la dispersion et les cas extrêmes ;
- les motifs récurrents dans l’analyse Markdown.

### 10.3 Variance des modèles

Un benchmark accepte de 1 à 20 répétitions par item, sur les mêmes entrées figées.
L'identité de publication inclut la répétition pour préserver la reprise et le rejugement.
L'interface affiche les réussites sur les répétitions prévues, la couverture, la moyenne,
les extrêmes et l'écart-type des scores disponibles. Les intervalles de confiance et
l'accord entre sorties ne sont pas calculés. La dispersion ne mesure pas la généralisation.

Un budget USD facultatif couvre les coûts enregistrés du candidat et des campagnes de
jugement. Sous verrou, le worker arrête les nouvelles évaluations lorsque ce seuil est
atteint. Une évaluation en cours peut le dépasser ; l'analyse Markdown est séparée.
Le run devient `partial`, avec `stop_reason=budget_exhausted`, et conserve ses résultats.

### 10.4 Seuils de décision

Un seuil comme 80 % n’a de sens qu’après calibration sur le domaine et analyse du coût des erreurs.
Un système de mémoire peut exiger zéro invention critique même avec une moyenne élevée. Un outil de
classement exploratoire peut tolérer davantage de cas ambigus.

Établir les seuils à partir des décisions humaines, pas à partir de la couleur de la jauge. Une
politique possible distingue :

- garde critique : aucun faux passage sur les violations invalidantes ;
- garde dimensionnelle : aucun recul matériel sur une dimension prioritaire ;
- garde agrégée : baisse moyenne bornée sur un dataset stable ;
- garde de fiabilité : taux maximal d’erreurs candidat et couverture minimale du juge.

Ces gardes ne sont pas encore automatisées par le Lab.


## 11. Persistance, API et droits

Les jeux, cas et runs existants sont conservés. `LabJudgmentCampaign` et
`LabJudgmentResult` portent les campagnes et leurs appréciations. Les relations utilisent de
vraies clés étrangères. Le schéma est déclaratif et appliqué par DbAdmin.

Les routes de `app.lab` couvrent jeux, paramètres, items, captures, aperçu,
lancement, annulation, reprise, résultats et nouveau jugement. Les assertions contrôlent les
droits LAB et la portée des agents sources. L’interface ne remplace jamais ces contrôles API.

## 12. Limites et travaux distincts

Les tendances par dimension, l’alerte automatique de non-comparabilité, les juges en ensemble,
l’export standard des résultats et les gardes CI restent des travaux du
[plan qualité](../../../project/plans/lab-evaluation-mecanismes-ia.md).
La revue humaine masque le modèle et le juge jusqu'à la soumission, conserve une appréciation
immuable par utilisateur, résultat et campagne, puis affiche les écarts dimensionnels,
les désaccords de verdict et l'écart absolu moyen. Elle n'efface pas l'exposition préalable
aux résultats et ne remplace pas un protocole d'étalonnage. Voir l'[ADR 0082](../../../project/decisions/0082-lab-stability-human-review.md).
Les empreintes sont persistées, mais ne constituent pas encore un écran de comparaison automatique.
Les validations automatisées utilisent des réponses contrôlées ; elles ne qualifient pas la qualité
d’un modèle distant.

## 13. Autorité dans le code

| Contrat | Fichiers sous `back/app/lab/` |
|---|---|
| Intrants et portées | `contracts.py` |
| Algorithmes et rubriques | `mechanism_registry.py`, `mechanism_rubrics.py` |
| Schéma et API | `models.py`, `schemas.py`, `router.py`, `assertions.py` |
| Résolution et captures | `mechanism_evaluation_service.py`, `dispatcher_evaluation_service.py` |
| Deux passes | `run_claims.py`, `run_inference.py`, `run_publication.py`, `run_lease.py` |
| Nouveau jugement et reprise | `judgment_service.py` |
| Contrôles et empreintes | `objective_checks.py`, `inference_profile.py` |

L’IHM commune est `front/app/lab/components/LabWorkbench.vue`.
Les tests de contrat et de persistance sont sous `back/app/lab/tests/` ; les parcours navigateur
sont dans `e2e/specs/lab.spec.mjs`.

## 17. Références

- NIST, [AI Test, Evaluation, Validation and Verification](https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv).
- Stanford CRFM, [Holistic Evaluation of Language Models](https://crfm.stanford.edu/2022/11/17/helm.html).
- Liu et al., [G-Eval](https://aclanthology.org/2023.emnlp-main.153/), EMNLP 2023.
- Kim et al., [Prometheus](https://arxiv.org/abs/2310.08491), 2023.
- Hashemi et al., [LLM-Rubric](https://aclanthology.org/2024.acl-long.745/), ACL 2024.
- Zheng et al., [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685), 2023.
- OpenAI, [PaperBench](https://openai.com/index/paperbench/).
- Shi et al., [Judging the Judges: Position Bias](https://aclanthology.org/2025.ijcnlp-long.18/), 2025.
- Zhou et al., [Mitigating the Bias of LLM Evaluation](https://aclanthology.org/2024.ccl-1.101/), 2024.
- Chen et al., [Beyond the Surface: Measuring Self-Preference](https://aclanthology.org/2025.emnlp-main.86/), 2025.
- Pydantic AI, [Datasets and evaluators](https://ai.pydantic.dev/evals/how-to/dataset-serialization/).
