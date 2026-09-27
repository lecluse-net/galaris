# 0143 — Suppression du briefing d’exécution

Statut : accepté. Date : 2026-09-27.

## Décision et garanties

Les agents créent les Tasks avec un objectif autonome. La préparation supplémentaire par
briefing est supprimée, y compris comme capacité réactivable ou mécanisme du Lab.
Le dispatcher conserve `EXEC standard`, `EXEC high` et `PLAN high`, selon le harnais.
Le planner conserve sa mission structurée et ses étapes ; cette mission ne constitue pas
un briefing d’exécution autonome.

Les consommateurs concernés sont le dispatcher et ses contrats d’inférence, la façade
agent et le harnais interne, le scheduler Task, l’admission conversationnelle, les
préférences, les détails Task, les outils et permissions du Lab, ses captures, jeux de
référence et workers, les traductions, les parcours FR/EN et les guides des agents.

Garanties conservées : effort et choix PLAN, autorisations des outils, pause et reprise,
immutabilité des états terminaux, captures des autres mécanismes du Lab, reprise
des évaluations restantes sans relancer un candidat déjà publié, et séparation entre
publication d’un résultat et réponses tardives.

## Suppression des données et mise à niveau

- Aucune nouvelle Task ne peut sélectionner la route ou créer la phase `BRIEFING`.
  `@briefing` redevient du texte ordinaire ; les modes d’outils n’exposent plus ce choix.
- DbAdmin convertit l’ancienne phase en `DISPATCH` avant de retirer sa valeur de l’enum
  PostgreSQL. Les objectifs, efforts et pauses des Tasks sont préservés ; les anciennes
  routes forcées et décisions structurées deviennent `EXEC`.
- La colonne JSON `briefing_result` est supprimée physiquement. Aucun lecteur de
  compatibilité ne subsiste dans l’application.
- L’action transactionnelle `app.agent.retire_execution_preparation`, déclenchée avant
  contraction de cette colonne, supprime les datasets du mécanisme et leurs dépendances,
  ses appels LLM et les inférences gelées devenues non rejouables. Cela comprend les
  requêtes du dispatcher en `active/v3`, dont le schéma autorisait l’ancienne route.
  Le contrat courant est `active/v4` ; les archives des autres contrats sont préservées.
- Les instantanés des Tasks, harnais, expériences restantes et historiques LLM perdent
  les anciens champs de configuration et blocs de contexte injectés. Les documents et
  messages rédigés par les utilisateurs ne sont pas des paramètres à réécrire.

La suppression physique est explicitement demandée. Les traces supprimées ne contribuent
plus aux statistiques calculées depuis les appels LLM ; les agrégats déjà enregistrés sur
les Tasks ne sont pas recalculés. Restaurer ces archives exige une sauvegarde antérieure.

Les seuls identifiants techniques du mécanisme conservés dans le code sont les sélecteurs
DbAdmin nécessaires pour nettoyer une installation existante et leurs tests. Ils ne
constituent ni une capacité d’exécution ni un chemin de compatibilité à la lecture.
La synchronisation locale utilise `make sync-db`. La production ne change qu’à son prochain
déploiement explicitement demandé, via `make update`.

## Couverture

Les tests dédiés à la génération et au classement du briefing sont supprimés : ils
décrivaient la fonctionnalité retirée. Les garanties communes d’inférence — contexte
d’autorisation, annulation, reprise et conservation des coûts — restent couvertes par
`test_inference_lifecycle.py`, `test_structured_inference.py` et
`test_dispatcher_inference.py`. Les tests génériques du Lab utilisent désormais le Planner.
Les six cas publics de frontières éditoriales et de ressources évaluent les réponses de
l’exécuteur avec des outils simulés ; leur corpus versionné ne prouve aucune livraison réelle.

Les anciens tests de compatibilité disparaissent avec leur contrat. Un test PostgreSQL
vérifie la purge, les dépendances, la conservation des Tasks, l’idempotence et le rollback.
Les scénarios de workflow, de façade et de portée des outils couvrent l’exécution directe.
Les parcours navigateur conservent les contrôles de droits, les erreurs,
la réouverture et les réponses tardives des préférences et du Lab.
