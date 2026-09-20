# Qualification mémoire et multimédia — 11 septembre 2026

Périmètre autorisé : premier incrément mémoire fondé sur un défaut reproductible et qualification
du parcours multimédia existant. Les chantiers équipes, livraison publique, prompts et Lab
conservent leur suivi séparé. Les changements sont dans le worktree ; aucun commit ni déploiement
ne fait partie de cette qualification.

## Mémoire : renouveler un fait expiré

Garantie : enregistrer un fait avec une nouvelle période de validité doit permettre son rappel,
même si un ancien souvenir expiré contient exactement le même texte. L'ancien souvenir garde
ses dates ; répéter le nouvel enregistrement réutilise la nouvelle identité.

- Reproduction : ajout du cas `renewed-fact` au scénario DB existant de
  `back/app/memory/tests/test_recall_evaluation.py` ; assertion Recall@5 rouge avant correction.
- Cause : `service.create_item` ne comparait que le propriétaire et l'empreinte du contenu,
  parmi les souvenirs ordinaires non gérés par une source.
- Correction : comparer aussi les deux bornes de validité avec une égalité SQL acceptant NULL.
- Mesure sur les neuf cas : Recall@5 de 88,9 % avant à 100 % après ; aucune fuite mesurée.
- Limite : corpus déterministe synthétique et repli lexical explicite. Aucun gain général
  de qualité sémantique ou de comportement d'un LLM n'est déduit de cette mesure.

## Multimédia : parcours de livraison local

Le premier passage a donné 70 succès et un échec : le scénario de transfert de 100 Mo n'avait
aucun salon/destinataire persistant, requis par le contrat de contact en cours d'intégration.
La fixture crée désormais un utilisateur vérifié, manager de l'agent, et son appartenance au
salon canonique. Les contrôles de contact restent exécutés ; seul le transport fournisseur est
simulé comme auparavant.

Les 26 tests multimédias passent : catalogue et autorisations, configuration, soumission
idempotente, réponse perdue, résultat terminal, validation des conteneurs média, callbacks,
livraison canonique, réparation et transfert de 100 Mo. Cette recette ne prouve ni la réussite
d'un appel payant ni la réception effective sur un téléphone.

L'inventaire en lecture seule de l'instance trouve une ressource de génération musicale chez
OpenRouter actif. Aucun secret n'a été lu ou imprimé et aucun appel fournisseur n'a été effectué.

Recette réelle à terminer après choix du fournisseur/capacité et plafond de dépense :

1. vérifier le modèle assigné, le tarif et les limites actuelles, l'agent et sa destination ;
2. soumettre une génération bornée avec une clé d'invocation stable ;
3. suivre le Process et conserver son identifiant, le modèle résolu et le coût connu ou inconnu ;
4. relire le fichier par son URI canonique et vérifier son type, sa durée et son contenu ;
5. confirmer l'absence de nouvelle génération lors d'une relecture du Process ;
6. qualifier séparément l'envoi Messenger si un destinataire de test est autorisé.

## Validation automatisée

La suite ciblée compte **132 tests réussis** : rappel, recherche sémantique, scopes Topic/contact,
service mémoire, acquisitions et tous les tests multimédias. Ils utilisent la base éphémère
de `make tests`, sans modification de la base de développement.

`make typecheck` réussit, y compris les 214 tests frontend de cette cible et la parité des
traductions. `make architecture-check` confirme la cartographie à jour puis échoue sur
`new frontend module dependency: app/chat -> app/agent`, issue des changements du chantier
équipes dans le worktree. Aucun fichier frontend ni baseline n'a été modifié par cette
qualification ; les tests d'architecture de la cible ne sont donc pas atteints. Les liens
locaux des plans et `git diff --check` passent.
