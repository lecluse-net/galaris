# 0135 — Agent Galaris proposé une seule fois

Statut : accepté. Date : 2026-09-25.

## Garantie

L'installation propose un agent **Galaris**, utilisant le harnais interne et le
profil LLM courant par défaut. L'utilisateur peut modifier son identité, son
profil, son harnais, ses droits, ou le supprimer : aucune synchronisation ne
réinitialise cette proposition.

## Décision

Le dataset `app.agent.initial_galaris` appartient à `app.agent`. Il attend un
administrateur actif et une civilité existante, puis rattache l'agent au premier
administrateur actif. Les installations existantes reçoivent également cette
proposition à la prochaine synchronisation. Une collision de code reçoit un
suffixe sans modifier ni augmenter les droits de l'agent préexistant.

`agents.initialization_key` est un marqueur interne unique, nullable pour les
agents ordinaires, absent des contrats API éditables. La recherche inclut les
lignes historisées : le renommage et la suppression logique ne rendent jamais
la proposition à nouveau éligible. Aucun comportement d'exécution ne dépend de
ce marqueur. La suppression physique hors contrat applicatif n'est pas couverte.

Le profil reste `NULL` pour suivre le profil courant, le driver vaut `internal`,
et aucun harnais externe n'est affecté. Les connexions et skills ordinaires sont
initialisés ; seule la création active en plus `galaris_admin`, qui autorise
notamment la consultation de la documentation, et l’autorisation individuelle des
skills `galaris-lab` et `galaris-knowledge`. Leurs défauts globaux et la connexion Lab restent désactivés.
Les synchronisations ultérieures respectent la révocation de ces droits et les réglages
utilisateur ; elles n’ajoutent pas ce nouveau défaut aux agents déjà initialisés.

Sur une installation neuve, aucun responsable humain n'existe encore pendant
DbAdmin. Un observateur du cycle de vie utilisateur rejoue le même dataset après
la création du premier administrateur. Le verrou transactionnel partagé avec
DbAdmin empêche deux propositions concurrentes. L'agent et ses affectations sont
créés atomiquement ; un échec reste réessayable sans laisser de marqueur partiel.

## Vérification

`app/agent/tests/test_default_agent.py` couvre l'inscription, la création, les
collisions, les modifications, la révocation des droits, la suppression, la
reprise après échec et les appels concurrents.
