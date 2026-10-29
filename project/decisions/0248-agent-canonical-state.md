# 0248 — État canonique des agents sans colonnes historiques

Statut : accepté. Date : 29 octobre 2026.

## Décision

`agents` ne conserve plus les colonnes `hermes_*`, `group_id`, `profile_media_type`,
`profile_legacy_source` ni `initialization_key`.

- `hermes_agent_configs` est l'unique configuration persistée d'Hermes. Le manager
  consomme cette configuration directement, sans attributs Hermes ajoutés à l'objet Agent.
- `agent_teams` est l'unique source des appartenances. Les entrées Agent utilisent `team_ids`
  avec les droits de modification des membres ; les portées déléguées restent vérifiées.
- Personnalité et fiche de poste suivent toujours le contrat HTML. Les ressources
  continuent d'annoncer `text/html`, sans colonne de format dans `agents`.
- Le paramètre global interne `galaris.agent_id` conserve l'ID de l'assistant initial.
  Il reste renseigné après renommage et suppression, sans recréer l'assistant ni ses droits.
  Son écriture et la création de l'agent font partie de la même transaction sous le verrou
  d'initialisation existant. Il ne détermine aucune permission d'exécution.

## Reprise

Les actions DbAdmin reprennent les appartenances, convertissent les profils et copient
les configurations Hermes manquantes ainsi que l'ancien marqueur d'initialisation avant
la contraction Atlas. Les lignes historisées sont incluses ; une configuration Hermes
existante n'est jamais écrasée. Les anciennes copies `profile_legacy_source` sont supprimées.
Une préparation échouée conserve les colonnes sources et peut être rejouée.

Les tests utilisent le véritable pipeline DbAdmin/Atlas sur PostgreSQL isolé, avec des
données synthétiques, interruption avant commit et reprise idempotente.
