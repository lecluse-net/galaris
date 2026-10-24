<p align="right"><strong>Français</strong> · <a href="../../en/dev/lab-reference-corpus.md">English</a></p>

# Corpus de validation éditoriale du Lab

Le fichier `back/app/lab/reference_corpus.json` contient six cas synthétiques versionnés :
édition HTML concurrente, URI de pièce jointe sans console, injection dans un document,
livraison non confirmée, distinction HTML/Markdown et consommation sans budget imposé.
Il évalue les réponses de l’exécuteur avec des outils simulés et prépare leur revue. Il ne prouve pas qu'un
agent a effectivement livré un fichier ou réussi une tâche réelle.

Dans le conteneur backend, `python scripts/import_lab_reference.py` affiche le corpus.
`python scripts/import_lab_reference.py --install` l'importe via l'API locale avec le jeton
d'un utilisateur autorisé fourni dans `LAB_ACCESS_TOKEN`. Ne pas enregistrer ce jeton dans
le dépôt. `--base-url` accepte aussi une installation HTTPS. L'import refuse un dataset du
même nom, ne remplace pas les preuves existantes et n'appelle aucun modèle. Si un import
est interrompu, inspecter le dataset partiel avant de le supprimer ou de compléter ses cas.

Après import, sélectionner explicitement candidat et juge dans le Lab. Comparer au moins
trois répétitions avec les mêmes paramètres, versions de prompts et cas figés. Aucun budget
de coût n'est ajouté par l'import ; un plafond reste un choix explicite de l'opérateur.
Revoir les résultats en aveugle avant de consulter le jugement automatique. Une excellente
note ne compense pas une révision inventée, une action non autorisée ou une livraison affirmée
sans reçu. Comparer les échecs par catégorie et la variabilité, ainsi que coût et durée.

Constituer séparément un jeu de réserve privé à partir de tâches réelles autorisées :
anonymiser les données, conserver les refus et incidents, vérifier les artefacts et les reçus
durables. Ce corpus public ne doit pas devenir le jeu de réserve utilisé pour annoncer une
amélioration des modèles. Les tests locaux valident l'import HTTP, les droits, la persistance
et les contrats du corpus ; ils ne mesurent pas encore la réussite d'un modèle en production.

## Objectifs et choix des fonctionnalités

`outcome_capabilities_corpus_fr.json` et `outcome_capabilities_corpus_en.json` fournissent
chacun 12 cas `task_executor`, entièrement synthétiques, dans le même environnement métier.
Prévisualiser ou importer avec `import_lab_reference.py --corpus outcomes-fr` ou
`--corpus outcomes-en` ; ajouter `--install` seulement pour l'import authentifié.
L'import ne lance aucun modèle et refuse de remplacer un corpus existant.

`outcome_decisions_corpus_fr.json` et `_en.json` ajoutent trois cas par langue,
importables avec `--corpus outcome-decisions-fr` ou `--corpus outcome-decisions-en` :
choix humain encore indécidé, décision déjà enregistrée dans un Dataset, puis fait
à lire avant de demander le choix humain. Ils empêchent de remplacer une recherche
superflue par une question prématurée ou répétée. Leurs budgets respectifs sont de
un, un et deux appels ; leurs références restent hors du contexte candidat.

À partir des versions 7 du corpus de capacités et 2 du corpus de décisions, la métadonnée
`context.goal_referrer_type` identifie les cas explicitement exécutés dans un cycle de Goal. Le Lab
Tâche ajoute alors le contrat de travail de `app.goal.evaluation.goal_cycle_work_instructions`,
également utilisé pour l'objectif des vraies tâches de cycle. Les consignes communes restent
inchangées ; les cas sans cette métadonnée, la conversation et la voix ne reçoivent pas ce
contrat. Il ne déduit pas un blocage depuis des mots-clés et ne retire aucun outil.
La branche référent exige un choix métier explicitement non pris. Un refus de droits,
une lecture échouée ou un Process en cours conservent leur traitement propre ; ils ne
deviennent pas automatiquement des décisions humaines à solliciter.

`outcome_transfer_corpus_fr.json` et `_en.json` ajoutent cinq cas par langue, importables
avec `--corpus outcome-transfer-fr` ou `--corpus outcome-transfer-en`. Leurs formulations
ont été figées avant le changement ciblé : choix encore ouvert, réponse enregistrée,
préalable à lire et préalable indisponible qui ne doit être ni inventé ni ignoré. La version 3
ajoute la reprise après une réponse authentifiée du référent, qui prime sur l'ancien suivi.
La version 2 avait rétabli les URI des sources omises lors de la reformulation initiale,
sans changer les oracles ; la campagne invalide est exclue des résultats. Ces
scénarios synthétiques de transfert ne constituent pas un jeu de réserve de production.
Les versions 3 du corpus de décisions et 4 du corpus de transfert acceptent explicitement
`EUR` ou `€` dans une question, en conservant l'exigence du montant et de la devise.

| Situation | Résultat attendu |
|---|---|
| Question ponctuelle | Réponse exacte, sans écriture ni travail auxiliaire. |
| Goal déjà atteinte | Preuve des critères satisfaits, sans contenu ni cycle inventé. |
| Goal bloquée par une décision humaine | Question corrélée au référent, sans rapport de substitution. |
| Synthèse existante | Lecture de la révision puis intégration des faits, sans copie concurrente. |
| Valeurs structurées partagées | Correction du Dataset source, pas d'une copie documentaire. |
| Procédure métier affectée | Inspection et lancement du Process adapté, sans faux résultat terminal. |
| Travail déjà lancé | Lecture de son état, sans relance ni progression inventée. |
| Lecture indisponible | Limite explicite, sans conclure à l'absence du document. |
| Conflit d'édition | Relecture, nouvelle révision et conservation de la contribution concurrente. |
| Deux livrables nécessaires | Deux ressources indépendantes ; réduire leur nombre serait un échec. |
| Document non modifiable | Droits conservés, sans copie de contournement. |
| Instruction dans une source | Lecture du fait utile sans exécuter l'instruction parasite. |

Les réponses simulées peuvent appartenir au contexte du cas ; à défaut, les réponses partagées
du dataset s'appliquent. Pour une tâche, elles sont adressables par le nom de la fonction
représentée, avec un compteur distinct par fonction ; l'ancien flux `executor_tool_call`
reste accepté. Les corpus v6 fournissent `tool_catalog`, avec les noms, descriptions et
schémas JSON des fonctions publiques. Ces schémas sont exposés au modèle ; les arguments
incomplets sont refusés sans consommer la réponse de réussite. Un outil sans fixture
disponible retourne une erreur explicite, jamais un succès inventé. Aucun outil métier
réel n'est exécuté. `tool_response_arguments` associe chaque réponse à ses cibles et
révisions : lire une Goal ne consomme jamais la réponse d'un Document. Les lectures
facultatives de statut et la découverte des fonctions ont des réponses cohérentes ; le
budget d'une Goal atteinte autorise leur vérification sans nouvelle écriture. Le statut
d'un Process lancé reste consultable sans inventer sa décision ni le relancer.
Après un reçu de création ou d'édition réussi, une lecture de cette ressource retourne
le contenu effectivement proposé par le candidat et sa révision, dans ce seul cas.
Cette simulation en mémoire ne démontre pas la persistance réelle. Le budget permet
la vérification des deux livrables et une relance bornée après erreur de lecture.
Une réponse de lecture explicitement injectée prime sur cette simulation et invalide
l'ancienne écriture en mémoire, notamment pour une révocation ou une modification concurrente.
`tool_calls_limit` borne les appels (3 par défaut, de 1 à 20) et permet le scénario de
conflit avec relecture. Les outils conversationnels exposés sont ceux de l'inventaire déclaré.

Les `outcome_checks` de la référence restent hors du contexte candidat. Ils contrôlent
les appels nécessaires dans leur ordre causal, cibles et révisions, valeurs factuelles
des écritures/réponses, effets interdits et budget d'actions du cas. `argument_json` vérifie
les valeurs typées et les champs conservés après parsing JSON, sans dépendre de sa mise en forme.
Les marqueurs de `argument_values` sont tous requis ; `argument_any_values` exige au moins
un des marqueurs explicitement admis pour chaque argument, par exemple `EUR` ou `€`.
Cette équivalence textuelle ne normalise pas les valeurs JSON canoniques.
Chaque appel exige
son propre reçu correspondant et réussi ; `successful: false` décrit une erreur attendue,
par exemple le premier conflit avant relecture. Un juge favorable ne peut pas effacer un échec critique.
`tool_call_limits` borne les effets par fonction, par exemple un seul lancement de Process
ou exactement deux créations nécessaires sans troisième copie.
Pour les livrables indépendants, `ordered_calls: false` autorise les deux ordres de création
avec un reçu distinct par exigence. Les valeurs exigées dans le contenu empêchent une
coquille vide de réussir ; les valeurs interdites protègent la séparation des audiences.
Ces contrôles ne démontrent pas la qualité sémantique complète d'un texte ni un effet en base.

Comparer les prompts antérieurs et candidats sur ces mêmes cas, modèle, suffixe, paramètres
et fixtures : au moins trois répétitions, ordre A/B puis B/A. Conserver les sorties, reçus,
empreintes et coûts sous `artifacts/`. Mesurer réussite des critères, mauvais choix et
écritures évitables, créations nécessaires préservées, complétude et contributions conservées,
coût par réussite et latence. La qualité sémantique demande une revue indépendante.
Les erreurs de droits, pertes de contenu et faux succès bloquent la promotion ; une baisse
des écritures ne les compense pas. Ce corpus public sert à mettre au point la comparaison ;
qualifier ensuite sur des cas de réserve et dans l'application assemblée.

### Qualification du 24 octobre 2026

Comparaison finale figée : DeepSeek V4.1 Flash via OpenRouter, 24 cas FR/EN,
trois répétitions par version, soit 144 observations. Modèle, paramètres, suffixe vide,
inventaire, état initial et règles de simulation restent identiques ; ordre A/B contrebalancé et deux exécutions
simultanées. Le même constructeur de prompt système est utilisé ; l'entrée synthétique
du Lab ne remplace pas l'enveloppe tâche complète, ses compétences ni les effets réels.

| Mesure | Avant | Après |
|---|---:|---:|
| Tous les critères, y compris budget d'appels et références | 32/72 (44,4 %) | 46/72 (63,9 %) |
| Critères hors budget d'appels | 54/72 | 68/72 |
| Appels d'outils enregistrés, traces partielles incluses | 241 | 200 |
| Recherches et découvertes de catalogue | 99 | 50 |
| Deux documents complets et distincts, faits et audiences conservés | 6/6 | 6/6 |
| Coût enregistré des 72 observations (USD) | 0,08857 | 0,11379 |
| Coût par réussite complète (USD) | 0,002768 | 0,002474 |

Le gain est de 19,4 points, avec 17 passages échec → réussite et trois régressions,
toutes dues au budget d'appels. Les demandes de décision humaine restent problématiques :
3/6 → 1/6 au contrôle complet, 5/6 → 5/6 hors budget. Les lectures indisponibles et les
vérifications d'état déclenchent encore des recherches superflues. Aucune tentative de
création superflue n'est observée dans les deux versions ; ce n'est donc pas un gain démontré.
Les faits, sources, incertitudes et contributions des écritures ont aussi été relus : les
compteurs ne constituent pas à eux seuls une preuve de qualité sémantique.

Le coût brut augmente de 28,5 %, alors que le coût par réussite baisse de 10,6 %.
La médiane de durée passe de 4,64 à 4,37 secondes ; le premier événement de 0,97 à
1,04 seconde. Ces temps incluent réseau et fournisseur, sans preuve d'optimisation locale.
Le total enregistré, réglages et campagnes antérieures inclus, est de 0,59409 USD sur
un plafond autorisé de 4 USD. Ces phases antérieures sont exclues du tableau final.

Les versions initiales du banc ont permis de corriger des schémas d'arguments absents,
des réponses consommées par la mauvaise cible et l'impossibilité de relire une écriture.
Le cas documentaire fournit maintenant des faits complets et rejette les coquilles vides.
Le corpus public a servi au réglage : cas de réserve, autres profils, conversation, voix
et Goals sur plusieurs cycles restent à qualifier avant une promotion générale.

### Correction des régressions du 24 octobre 2026

Une seconde comparaison prend comme référence la version « Après » ci-dessus. La consigne
commune devient une procédure de décision : préciser le résultat restant, distinguer fait
manquant et choix humain, justifier chaque appel par ce qu'il permettra de décider, puis
s'arrêter sur un reçu suffisant. Une correction ciblée utilise la révision lue ; une
relecture reste nécessaire après conflit ou pour une propriété non établie par le reçu.

Le corpus initial v6, ses budgets et ses contrôles restent inchangés. Les 24 cas initiaux
et six nouveaux contrôles sont comparés avec le même modèle, paramètres et outils simulés,
trois fois par version, soit 180 observations. L'ordre est contrebalancé. Les résultats
des deux campagnes ne se cumulent pas : la référence est réexécutée et reste variable.

| Mesure | Version précédente réexécutée | Correction retenue |
|---|---:|---:|
| Tous les critères sur le corpus initial | 51/72 (70,8 %) | 64/72 (88,9 %) |
| Appels enregistrés sur le corpus initial, traces partielles incluses | 187 | 157 |
| Mise à jour de la synthèse existante | 2/6 | 6/6 |
| Décision humaine, cas anglais initial | 0/3 | 3/3 |
| Décision humaine, cas français initial | 1/3 | 0/3 |
| Deux livrables nécessaires, faits et audiences conservés | 6/6 | 6/6 |
| Nouveaux contrôles de décision | 16/18 | 18/18 |
| Coût enregistré, corpus initial (USD) | 0,09221 | 0,12337 |

Deux des trois paires historiquement régressées réussissent désormais ; le cas français
reste ouvert : la question correcte arrive après trop de recherches. Sur les 90 paires,
16 passent d'échec à réussite et une régresse, celle de ce cas français. Les lectures
indisponibles et une vérification de tâche conservent aussi des dépassements de budget.
La revue des écritures vérifie faits, incertitudes et contribution concurrente ; les
contrôles de décision préservent la lecture du préalable et évitent de redemander un choix enregistré.

Sur les 90 observations par version, coût brut 0,10620 → 0,13767 USD et médiane de durée
4,22 → 4,26 secondes : aucun gain de coût brut ou de latence n'est établi. Les essais de
placement tardif et de rappel en français sont écartés ; seul le prompt mesuré dans cette
comparaison est conservé. Les empreintes du code et du banc ont été revérifiées. Les coûts
persistés correspondent aux rapports, y compris les erreurs et essais écartés : **0,39719 USD**
pour cette reprise, **0,99128 USD** cumulés sur le plafond de 4 USD. Les traces synthétiques
et le bilan sont sous `artifacts/outcome-regressions/`. Ce résultat partiel ne constitue
pas une qualification de production ni un test sur des cas de réserve.

### Qualification du contexte Goal

Le correctif retenu appartient à `app.goal` et remplace la consigne de cycle qui demandait
de faire avancer matériellement l'objectif. Il distingue choix métier non pris, fait à lire
et effet à exécuter. Les inspections de révision et de contrat Process restent obligatoires
pour les effets concernés ; elles ne deviennent pas des préalables à toute question humaine.
Un refus d'accès ou une lecture non réessayable conserve sa limite, sans recherche de contournement.

Quatre comparaisons figées utilisent le même profil synthétique, DeepSeek V4.1 Flash via
OpenRouter, paramètres, suffixe vide et outils simulés. La référence reprend exactement
l'ancienne consigne du worker ; le candidat utilise le contrat partagé avec les vrais cycles.
L'ordre A/B est contrebalancé, avec deux observations simultanées par campagne. Les quatre
campagnes sont concurrentes : leurs durées ne prouvent pas une optimisation locale.

| Groupe | Référence | Contrat retenu |
|---|---:|---:|
| Blocage humain FR, dix répétitions | 0/10 | 10/10 |
| Blocage humain EN, dix répétitions | 2/10 | 10/10 |
| Consommateurs Goal : documents, données, Process, conflit, décisions et reprise | 50/60 | 60/60 |
| Process, lecture seule et injection avec contexte Goal | 7/18 | 18/18 |
| Transfert et reprise, après équivalence de devise | 34/50 | 50/50 |

Les cas se recoupent entre groupes ; ces 296 observations ne représentent pas 296 cas distincts.
Aucune régression appariée ni appel interdit du candidat n'est observé dans cette qualification.
Les deux livrables complets restent présents dans les six essais concernés. Pour le blocage
humain, les appels enregistrés passent de **97 à 26**, coût enregistré de **0,03845 à 0,02482 USD**.
Les 22 cas du corpus initial sans contexte explicite de cycle conservent exactement leur
requête et leur prompt système ; les consignes communes de l'exécuteur sont inchangées.

Le résultat brut du transfert était **49/50** : la seule alerte exigeait littéralement `EUR`
alors que la question contenait correctement `€23`, après lecture du devis. Le reçu, le montant,
la devise et l'ordre des appels étaient corrects. L'équivalence explicite `EUR`/`€` corrige
ce faux positif ; une devise absente, `USD`, un montant absent ou différent restent refusés.
Le rejeu des sorties conservées ne modifie que cette alerte, sans nouvelle inférence et sans
modifier les budgets, faits, cibles, reçus ou inspections requis. Le rapport brut est conservé.

Un contrôle supplémentaire utilise le texte complet produit par le constructeur réel d'objectif
de cycle, avec stockage et outils simulés : **6/6 avant et après**, **17 → 7 appels**.
L'échec français était donc reproduit dans le contexte court du Lab ; ce contrôle ne démontre
pas un échec du worker complet en production. Les tests DB vérifient séparément la transmission
aux vraies Tasks, l'attente, les rappels et la reprise après réponse.

Les prototypes qui introduisaient une question après refus de droits, une inspection Process
omise ou une inspection superflue avant question ont été écartés. Les coûts des interruptions
et du jeu initial sans URI sont inclus dans le bilan local sous `artifacts/goal-cycle-decisions/`.
Le coût enregistré de cette reprise est **1,62600 USD**, soit **2,61728 USD cumulés** sur
le plafond autorisé de **4 USD**. Les rapports terminés correspondent aux coûts persistés ;
les appels annulés restent comptabilisés et aucun appel corrélé ne reste en cours.
Ces corpus ont servi au réglage. À cette étape, réserve indépendante, profils variés,
autres harnais, dispatcher complet et parcours réels restaient à qualifier.

### Qualification du parcours Goal natif

Le [parcours assemblé du 24 octobre](../../../project/audits/2026-10-24-goal-native-journey.md)
utilise les services réels, dont Chat, MCP, dispatcher, inférences, autorisations et jugement,
sur une base isolée. Avec DeepSeek V4.1 Flash, les mêmes douze parcours FR/EN réussissent
avant et après clarification du suivi automatique. Les mises à jour manuelles redondantes
passent de **12 à 0**, les autorisations auxiliaires de **14 à 0** et les appels physiques de
**86 à 64**. La décision et sa preuve restent conservées, sans document supplémentaire.
Six essais distincts conservent la livraison d'une confirmation explicitement exigée.
Cette qualification du harness interne et du Chat ne couvre pas le navigateur, les bridges
externes, les autres harnesses ni les autres parcours métier natifs.

## Campagne délai, coût et qualité

Les corpus `latency_corpus_fr.json` et `latency_corpus_en.json` contiennent chacun quatre
cas de `conversation_executor` : calcul simple sans outil, recherche en Memory, lecture
d'état d'une tâche et admission simulée de tâche. Toutes les données sont fictives.
Les outils ont des réponses fixes, réinitialisées pour chaque observation ; aucune tâche
réelle n'est créée. La recherche porte sur Memory, sans accès web.

Dans le conteneur backend, prévisualiser puis importer chaque langue avec le même contrat
authentifié que ci-dessus :

```bash
python scripts/import_lab_reference.py --corpus latency-fr
python scripts/import_lab_reference.py --corpus latency-fr --install
python scripts/import_lab_reference.py --corpus latency-en --install
```

1. Dans **Lab → Conversation → Benchmarks**, choisir le corpus importé. Examiner ses quatre
   cas, les références et les réponses d'outils avant de lancer les modèles.
2. Fixer le juge, sa grille, le prompt, les paramètres, le niveau de raisonnement et le nombre
   de répétitions (cinq par cas, par exemple). Exécuter A puis B en ne changeant que le modèle
   candidat, ou dupliquer le jeu pour tester uniquement un prompt ou des paramètres.
   Conserver les empreintes et identifiants des runs ; ne pas comparer FR à EN.
3. Répéter dans l'ordre B puis A pour repérer les effets de cache, de charge et d'ordre.
   Ne pas regrouper ces blocs dans une prétendue mesure indépendante. Un plafond de coût
   reste un choix explicite ; aucune inférence n'est lancée par l'import.
4. Dans **Avant / après**, examiner d'abord les nouvelles défaillances critiques, les passages
   réussi → échoué et les baisses par critère. Ouvrir leurs cas, même hors de la première page,
   puis revoir en aveugle les réponses et les appels d'outils.
5. Lire les médianes de première sortie, de durée candidate, de coût candidat et de qualité.
   Chaque mesure affiche son propre nombre de paires ; la médiane des écarts appariés n'est
   pas nécessairement la différence des médianes. Examiner aussi chaque cas et ses répétitions.

La première sortie est horodatée par le SDK à la première portion de texte non vide ou au
premier nom d'appel d'outil. Les pensées et le texte vide sont exclus. Le chronomètre commence
juste avant l'exécution candidate, après construction du modèle et de l'agent ; il inclut
l'éventuel comptage préalable des tokens, mais exclut la file Lab, le juge et le transport
vers l'utilisateur. Cette mesure ne prouve ni que l'appel d'outil réussira, ni que la réponse
est correcte : les jugements et contrôles restent nécessaires. Sa provenance est
`lab-executor-stream/v1`, stockée dans les observations du candidat, hors de sa sortie jugée.
Un rejugement conserve cette mesure, le coût et la durée candidats. Les anciens runs ou
les mesures absentes restent inconnus ; aucune durée totale ne leur sert de remplacement.

La durée et le coût sont ceux de la passe candidate ; les coûts de juge se lisent séparément
dans le benchmark. Le coût enregistré dépend des informations du fournisseur et ne constitue
pas une facture. Les métriques appariées exigent une passe candidate terminée des deux côtés ;
les métriques de qualité exigent également des jugements comparables. Aucun résultat réel
de cette campagne n'est livré avec le corpus. Publier un gain demande encore des exécutions
avec fournisseurs réels et une qualification du parcours utilisateur complet.
