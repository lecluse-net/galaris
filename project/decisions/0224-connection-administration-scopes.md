# 0224 — Portées d'administration locales aux connexions

Date : 23 octobre 2026. Statut : accepté.

## Contrat

Le paramètre existant `tools.management_scope`, validé pour Skills, configure aussi
`process_admin`, `tool_admin`, `goal_management`, `galaris_admin` et `agent_admin`.
Il conserve son stockage EAV et le formulaire commun de connexion ; aucune colonne
de politique ou seconde interface de délégation n'est ajoutée.

Les quatre niveaux sont `usage` (aucune administration), `personal` (ressources de
l'appelant), `team` (appelant et agents partageant une équipe active), `all` (global).
AgentAdmin propose seulement `usage`, `team`, `all`, et exclut toujours l'appelant
des modifications. L'appartenance seule à une équipe ne donne aucun droit nouveau.
La connexion active, sa valeur locale et les appartenances sont relues à chaque appel.
Une valeur absente ou inconnue n'accorde aucune administration. Les droits ordinaires
de propriété, de partage et de travail sur ses ressources restent indépendants.

La délégation reste réservée à un humain authentifié par session web avec édition
des connexions et gestion globale des agents. Elle n'a ni valeur globale ni héritage.
La sauvegarde atomique, la protection contre la réaffectation d'une connexion et le
refus d'écriture agentique du paramètre existants restent applicables.

## Règles des domaines

- Process : la définition appartient à son agent affecté ; un run à son lanceur.
  Les filtres s'appliquent avant pagination et les mutations vérifient aussi toute
  nouvelle affectation. Les définitions sans agent et la synchronisation du catalogue
  des moteurs nécessitent `all`. Les états terminaux, contrôles et ACL ordinaires restent
  applicables. Les fichiers et vues de run utilisent la même délégation.
- ToolAdmin : `personal` et `team` administrent les connexions des agents concernés.
  Les définitions partagées, paramètres globaux, permissions globales et inventaires
  d'impact nécessitent `all`. La définition d'un Tool n'a pas de propriétaire agent.
  Les délégations administratives, services système et exécutions stdio gardent leurs
  protections. Les rafraîchissements bornés revérifient chaque cible.
- Goal : la portée suit l'agent responsable, indépendamment du référent. Elle couvre
  les commandes, les listes et les projections File Share des Goals et cycles.
  Une réaffectation doit rester dans le périmètre ; les mutations verrouillent le Goal.
- Galaris Admin : Tasks, conversations texte/voix et appels LLM sont filtrés par leur
  agent propriétaire. Les listes et résolutions de préfixes LLM filtrent avant leur
  limite. Les traces sans propriétaire et les sources globales du Lab exigent `all`.
  La documentation conserve son autorisation de lecture distincte ; les permissions
  Document, Dataset et Memory ne sont pas élargies.
- AgentAdmin : la portée déléguée est intersectée avec les droits et agents gérables
  par le responsable humain. `team` autorise la création dans une équipe explicitement
  choisie parmi celles de l'appelant. Un agent ne peut modifier ni son profil, ni son
  avatar, ni ses connexions ou harnais par AgentAdmin. Les mutations des titres et
  équipes partagés ne doivent pas le modifier indirectement. Les délégations des
  autres agents restent humaines.

## Adoption et preuves

Les connexions administratives existantes sans paramètre doivent recevoir une portée
explicite via leur formulaire humain : leur activation ne vaut plus administration
globale. La création initiale de l'assistant système configure explicitement `all`
pour ses trois connexions d'administration déjà prévues ; la synchronisation ordinaire
ne réactive ni n'élargit les connexions existantes. Skills conserve sa migration propre.

`app/tools/tests/test_management_scopes.py` couvre les refus, la séparation entre Tools,
les lectures indirectes, la pagination et les révocations avec PostgreSQL réel.
Les scénarios AgentAdmin administrent désormais une cible distincte : l'ancienne
possibilité de se modifier soi-même est retirée, tandis que les garanties de transfert,
révision, chiffrement, génération d'avatar et révocation sont conservées sur cette cible.
Les tests communs du formulaire de connexion couvrent sauvegarde, erreur et réouverture.
