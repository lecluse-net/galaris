# Qualification du parcours Goal natif — 24 octobre 2026

Le parcours **Goal → dispatcher → exécution → question au référent → attente → réponse
authentifiée → reprise → suivi → clôture** est exercé avec les services réels et des
données entièrement synthétiques. La qualification a permis de retirer une activité
redondante : l'exécuteur mettait lui-même à jour le suivi, puis Galaris le réécrivait lors
du jugement normal de fin de cycle.

La correction C8 précise uniquement le contrat du cycle : transmettre les preuves et la
réponse du référent dans le résultat de Task, utilisé par le suivi automatique. Une
modification de ressource ou une livraison explicitement exigée par le Goal reste à faire.
Les autorisations, les outils disponibles et le fonctionnement du suivi ne sont pas modifiés.

## Périmètre et critères

L'agent est créé par son service normal, avec sa fiche de poste, son profil de modèle et
ses connexions obligatoires. Les scénarios utilisent PostgreSQL isolé avec des transactions
réellement validées, le scheduler, le dispatcher, le harness interne, le serveur MCP natif,
le journal du Chat, les interactions, la coordination des Tasks, le worker d'autorisations
et le jugement du Goal. Le droit `goal_ask_referrer` est activé explicitement ; les autres
fonctions conservent leur politique d'autorisation normale.

La mission demande d'obtenir un choix humain et d'en conserver la preuve. Les cas FR/EN
comprennent une réponse immédiate et une réponse après rappel et pause automatique,
avec trois répétitions par combinaison. Les dates futures sont fournies au worker réel ;
le test n'attend pas vingt-quatre heures. Les entrées humaines et les consentements sont
simulés par les contrats réels, exclusivement pour le référent synthétique habilité.

Les assertions lisent les effets persistés : une réponse admise malgré une livraison
dupliquée, rejet d'un tiers, un rappel maximum, aucune clôture pendant l'attente, réponse
reprise correctement, Task réussie, décision conservée, Goal terminé et absence de nouveau
cycle ou de jugement répété. Seuls les deux documents nécessaires au Goal sont créés ;
aucun document métier supplémentaire n'est produit.

## Comparaison C7 / C8

Modèle identique : **DeepSeek V4.1 Flash via OpenRouter**. Même mission, services, droits,
schémas, fiche de poste, profil et critères. Seule la consigne relative au suivi automatique
change. Les campagnes sont successives, sans graine commune imposée au fournisseur.

| Mesure sur les mêmes 12 parcours | C7 | C8 |
|---|---:|---:|
| Parcours réussis, dont 6 FR et 6 EN | 12/12 | 12/12 |
| Mises à jour manuelles redondantes du suivi | 12 | 0 |
| Confirmations non demandées | 2 | 0 |
| Autorisations auxiliaires demandées au responsable | 14 | 0 |
| Appels physiques au modèle | 86 | 64 |
| Documents métier supplémentaires | 0 | 0 |
| Coût enregistré de la campagne | 0,112263 USD | 0,053792 USD |
| Durée médiane du parcours | 22,66 s | 14,23 s |

La réussite est conservée et les appels diminuent de **25,6 %**. Les coûts observés baissent
de **52,1 %**, mais cache et charge fournisseur ne sont pas isolés : coût et délai sont
indicatifs. La suppression des **14 consentements et 12 écritures redondantes** est vérifiée
directement dans les données, sans attribuer un gain à une simple réduction de texte.

Une campagne distincte impose explicitement l'envoi d'une confirmation : **6/6 réussites**,
trois répétitions par langue. L'envoi conserve son consentement ponctuel et son reçu réel.
La réduction des confirmations superflues ne supprime donc pas les livraisons nécessaires
dans ces scénarios.

Un témoin supplémentaire reprend l'ancienne consigne générique de cycle : **5/6 réussites**.
Dans l'échec français, le modèle interprète la réponse corrélée comme une sortie de Task
synthétique et repose la question. Cet échec est conservé, sans nouvel essai de ce cas.
Il ne démontre pas un défaut systématique de la langue française ; les identités et la
provenance restent un sujet plus large que cette clarification.

## Protections durables

[Le scénario d'intégration](../../back/app/goal/tests/test_complete_referrer_journey.py)
couvre cinq familles FR/EN : réponse immédiate, réponse tardive, révocation du droit de
question entre annonce et effet, confirmation soumise à autorisation, et lecture de la
révision suivie d'une écriture du suivi autorisée. Il remplace seulement le HTTP fournisseur,
en conservant les inférences, la comptabilisation et les services internes réels.

Le contrôle ciblé des contrats Goal, des prompts, du corpus et des oracles d'effets passe :
**177 tests**. Les contrôles Ruff ciblés et le typage strict du contrat modifié passent.
Le lint global initial signalait **13 erreurs** dans d'autres surfaces. La revue
complémentaire les corrige : suppression d'exports Document déclarés en double, liaison
explicite des variables de projection des compétences et déclaration statique d'un export
de stockage. Les mêmes fonctions restent disponibles. Les lints backend/frontend et le
typage strict des quatre fichiers corrigés passent ; **80 tests ciblés supplémentaires**
sur les compétences, les ressources et les frontières Document passent également.

La préparation documentaire vérifie le corpus bilingue et l'architecture dans son
instantané. Les premières publications ont été refusées parce que les sources avaient
changé pendant la génération ; aucun résultat périmé n'a été publié.

Le contrôle apparié conserve 36 cas FR/EN et leurs oracles, répétés trois fois par variante :
**107/108 pour C7 et 108/108 pour C8**, sans effet interdit observé dans les deux variantes.
Le seul échec du témoin dépasse la borne du cas en ajoutant un catalogue inutile avant
la lecture d'un préalable et la question. C8 conserve les éditions documentaires,
corrections de Dataset, inspections de Process, livrables nécessaires et contrôles de
droits de ces scénarios ; aucune régression appariée n'est observée.

## Limites et essais écartés

Les premiers pilotes utilisaient un agent construit directement en base, sans toutes ses
connexions obligatoires ; ils ne qualifient pas la création normale d'agent. Ils ont aussi
exposé un délai de test insuffisant et l'oubli du worker qui réveille les Tasks après
consentement. Ces limites de montage sont corrigées, leurs échecs et coûts conservés dans
les diagnostics locaux. Les assertions ne sont pas remplacées par les déclarations du modèle.

Les traces détaillées et les scénarios de campagne restent sous `artifacts/`. Le présent
audit ne conserve que des agrégats et des conclusions techniques. Un appel interrompu
n'a pas remonté de coût facturé ; un coût enregistré nul ne prouve pas une facturation
externe nulle. Le budget autorisé conserve une réserve.

Le coût cumulé enregistré, essais écartés et interruptions compris, atteint **3,16428 USD
sur les 4 USD autorisés**. Les copies temporaires de la connexion fournisseur utilisées
pour les bases de qualification sont supprimées.

Le contrôle de non-régression a subi une interruption de flux fournisseur. Son observation
a finalement réussi avant l'arrêt contrôlé ; 92 observations achevées ont été conservées,
et deux observations encore incomplètes ont repris avec leurs fixtures sans effets réels
réinitialisées. Les 216 observations finales sont uniques. La reprise passe de deux à six
requêtes concurrentes, sans modifier sources, données, prompts ni oracles vérifiés par
empreintes. Les **516 appels physiques** de ce contrôle sont tous terminaux : 513 réussis,
une erreur fournisseur et deux annulés ; leurs coûts persistés sont réconciliés, y compris
ceux des observations interrompues. Ces incidents techniques ne sont pas comptés comme
des régressions métier.

Cette qualification n'exerce pas le navigateur, la connexion HTTP/RBAC complète, les
bridges externes, les autres harnesses ni le provisionnement d'une Console. Les parcours
Dataset, Process et révision documentaire restent des contrôles de modèle avec outils
simulés dans cette campagne, complétés par leurs tests de domaine. Ce corpus n'est pas un
holdout indépendant et ne clôt pas le plan de fiabilisation conversationnelle.
