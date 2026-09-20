# Fiabilisation conversationnelle — travaux restants

> **Statut :** `partial` — corrections réalisées ; extensions et qualifications encore ouvertes.
> **Revue documentaire :** 19 septembre 2026.

Ce plan conserve uniquement le travail restant. Les contrats et preuves des corrections sont
dans la [matrice projet](../audits/2026-09-19-fiabilisation-transversale.md), les décisions
[0029](../decisions/0029-unified-conversation-rounds.md),
[0101](../decisions/0101-dispatch-without-action-judgment.md),
[0102](../decisions/0102-harness-dispatch-choices.md),
[0103](../decisions/0103-tool-errors-return-to-agent.md) et
[0123](../decisions/0123-explicit-task-replacement.md), ainsi que le
[catalogue fonctionnel](../../docs/fr/dev/functional-tests.md).

Les dix lots de corrections ne sont plus des tâches à réaliser. La qualification restante
du dispatcher est regroupée ici ; ses contrats sont portés par 0101 et 0102.

## Travaux restant à réaliser

### L0 — Mesures du parcours, dont la qualification du dispatcher

- Constituer un corpus synthétique multilingue avec témoins nominaux et perturbés :
  humain/pair IA, question/action, racine/enfant, contraintes et capacités différentes.
- Mesurer admission, préparation, premier texte/outil, confirmation d'arrêt et démarrage du
  successeur ; séparer attente fournisseur, verrou, scheduler et temps local.
- Comparer les appels LLM, coûts, faux lancements et latences du dispatcher, à configuration
  constante. Son absence d'inférence pour un round humain ou un choix unique est déjà testée.
- Reprendre la matrice de 0101/0102 : ancien résultat, modèle absent, choix incompatible,
  effort explicite, briefing, reprise et livraison unique. Mesurer le gain jusqu'au premier
  texte/outil ; un ancien indicateur de relance n'est pas une vérité terrain.

**Sortie :** mesures avant/après reproductibles et limites explicites, sans rejouer d'effets
sur une conversation réelle ni présenter une mesure locale comme une preuve de production.

### L1–L3 — Arrêt externe, reprise et remplacement coordonné

- Qualifier l'arrêt physique des runtimes externes, au-delà des probes de démarrage et de
  terminaison normale : demande refusée, accusé sans arrêt, perte réseau et crash/reprise.
- Concevoir séparément le remplacement d'un arbre Task/Goal/Process avec ses propriétaires :
  capture du périmètre, arrêt des descendants et effets distants, preuve durable et admission
  unique du successeur. L'ADR 0123 ne couvre actuellement que le remplacement simple.
- Étendre les scénarios de reprise aux nouvelles coordinations retenues : arrêt manuel ou fin
  naturelle concurrente, redelivery, ancien worker, changement de portée et effet incertain.

**Sortie :** preuve d'arrêt correspondant au run avant démarrage du successeur ; effets et
entrées conservés ; travaux indépendants et pauses utilisateur préservés. Ne pas élargir les
verrous, supprimer les révisions ni déduire un arrêt physique d'un état terminal logique.

### L4 — Capacités pendant la construction des autres harnais

- Qualifier les annonces initiales, les runtimes externes et les activations/révocations
  pendant la construction d'un run ; distinguer fonction autorisée et fonction montée.
- Vérifier les exemples de skills et les capacités différées sur les fonctions réellement
  exposées. Privilégier un nouveau run sûr ; tout ajout à chaud demande un contrat distinct.
- Couvrir droits limités, autre agent et redémarrage, sans confondre Browser, Search et HTTPS.

**Sortie :** aucun outil annoncé immédiatement utilisable alors qu'il est absent ; accès
légitimes conservés. La révocation à l'appel des outils natifs est déjà réalisée et testée.

### L5 — Compléments de diagnostics et effets incertains

- Qualifier les erreurs non HTTP et les signaux antibot encore non couverts, en FR/EN.
  Un statut 403 seul ne prouve pas la cause antibot.
- Vérifier les frontières restantes entre effet confirmé, rejet avant effet et résultat
  inconnu, notamment lorsqu'une persistance échoue après un transfert réussi.

**Sortie :** diagnostic corrélable et expurgé, prochaine action compatible avec la cause,
sans incitation au rejeu d'un effet incertain. Réutiliser les tests d'evidence et de ressources.

### L6 — Recherche dans l'environnement cible et livraison d'images

- Après application autorisée de la configuration, exécuter le corpus varié de
  `make check-search` sur l'environnement cible et relire la pertinence des sources.
  Les refus fournisseurs et les choix administrés restent visibles et préservés.
- Qualifier téléchargement, attribution/licence, attachement et lecture d'une image réelle
  par son destinataire, y compris refus de copie et droits différents.
- Qualifier les alternatives autorisées quand un site est bloqué ; conserver un échec
  explicite lorsqu'aucune source exploitable n'est disponible.

**Sortie :** sources reliées à la requête et image réellement accessible ; aucune annonce
d'attachement réussi après échec. Les erreurs Browser et l'expiration sans rejeu sont déjà testées.

### L7 — Utilité du contexte de reprise

- Évaluer recherches bloquées, recherches longues mais productives, corrections de droits,
  sources déjà valides, plusieurs documents et demandes sans livrable documentaire.
- Mesurer les répétitions improductives et la réutilisation effective des documents, sans
  seuil arbitraire d'erreurs ni juge ajouté après une réponse réussie.

**Sortie :** contexte utile et progression fondée sur des effets vérifiés, sans abandon
prématuré. Le filtrage des sondes techniques dans les objectifs est un acquis à préserver.

### L8 — Langue, sortie structurée et effort

- Qualifier le résultat validé lorsqu'une sortie partielle précède une sortie complète,
  la politique des champs absents et la lecture des anciens résultats.
- Étendre la matrice FR/EN aux commentaires, objectifs, notifications, suggestions de sujet
  et reprises, avec préférences absentes ou demandeur différent.

**Sortie :** langue et décision cohérentes avec la sortie retenue, les choix du harnais et
les forçages utilisateur. Conserver les schémas historiques et le modèle résolu une fois ;
aucune augmentation générale d'effort pour compenser un problème de parsing.

### L9 — Frictions et parcours documentaire intégral

- Évaluer les propositions de sujet après salutation et leur répétition dans un autre
  travail, sans perdre les choix en attente ni contourner leurs droits.
- Qualifier le parcours demande → capacité manquante → activation → correction → remplacement
  → recherche → document illustré → partage → consultation après reconnexion.
- Inclure un témoin sans interruption et un fournisseur d'embeddings indisponible ; le repli
  lexical doit permettre de retrouver les documents avec un diagnostic fidèle.

**Sortie :** document et image accessibles, historique cohérent, absence de relance parasite
et latences mesurées. Les E2E Chat déjà réussis ne prouvent pas seuls ce parcours illustré.

## Méthode et clôture

Pour chaque travail : vérifier un manque actuel, préserver la matrice projet, reproduire avant
de corriger et adapter une règle générale. Aucun ajout de prompt pour un cas particulier.
Réutiliser les suites existantes ; qualifier séparément les frontières externes réelles.

Les contrôles complets du 19 septembre ont réussi sur leur instantané. Leur rapport reste
`STALE` après une modification documentaire concurrente ; il ne qualifie pas une publication
du worktree courant. Une publication demandée requiert `make validate` sur un nouvel instantané.

Supprimer ce plan lorsque les lignes restantes sont réalisées, transférées vers un chantier
identifié ou explicitement abandonnées. Aucun déploiement n'est autorisé par ce nettoyage.
