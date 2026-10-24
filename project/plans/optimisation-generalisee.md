# Suite de la campagne d’optimisation généralisée

- Statut : `in-progress` ; exécution en pause pour la soirée du 24 octobre 2026.
- Reprise prévue : 25 octobre 2026, sans exécution programmée.
- Suivi des réalisations, mesures et limites : [audit de campagne](../audits/optimisation-generalisee/README.md).

Quinze lots sont réalisés et qualifiés sur leurs scénarios. Leur historique et leurs
preuves restent dans l’audit ; ce plan conserve seulement les travaux ouverts.
La revue exhaustive et la qualification combinée du système restent à terminer.

## Priorités de reprise

1. **Process/MCP** : mesurer les chargements et contrôles de droits encore réalisés
   par élément. Inventorier les consommateurs et préserver scopes, révocation,
   fraîcheur et contrats des listes avant toute généralisation.
2. **Tools et Contacts** : mesurer le coût des métadonnées globales et des grands
   ensembles de destinataires. Les gains supplémentaires restent à démontrer.
3. **Ressources et charge** : compléter la référence au repos, mesurer le RSS réel,
   la concurrence et l’endurance. Distinguer allocations locales, mémoire totale,
   croissance après cycles et capacité mesurée.
4. **Qualification combinée** : comparer les parcours cumulant plusieurs lots à
   leur référence, rechercher les coûts déplacés et les nouveaux goulots.
5. **Couverture restante** : poursuivre les unités encore ouvertes dans les
   [fichiers](../audits/optimisation-generalisee/couverture-fichiers.csv) et
   [surfaces](../audits/optimisation-generalisee/couverture-surfaces.csv).
   Le périmètre inclut toujours tous les modules backend/frontend, bridges,
   exécuteurs et infrastructures inventoriés. Les lots ciblés ne qualifient pas
   automatiquement leur module entier.

Les prototypes de pagination Topics écartés faute de bénéfice suffisant ne sont pas
à reprendre sans nouvelle hypothèse étayée. Les autres décisions restent dans le
[registre des pistes](../audits/optimisation-generalisee/pistes.csv).

## Première séance

- Lire l’état Git et les registres ; comparer leurs empreintes aux sources courantes.
  Réconcilier les ajouts et requalifier seulement les preuves affectées.
- Commencer par Process/MCP, avec un parcours complet et un budget de mesure borné.
  Choisir ensuite les lots selon le coût réellement observé.
- Reprendre `make docs-prepare` sur des sources stabilisées. Les dernières tentatives
  ont vérifié corpus et contrats sur leur instantané, puis refusé la publication
  après détection de changements concurrents.

## Qualification des prochains lots

Appliquer les règles du [guide des agents](../../AGENTS.md) et les skills du domaine.
Comparer avant/après sur données synthétiques, mêmes versions, droits, charges et
régimes de cache ; répéter les mesures et publier leur dispersion et leurs limites.
Préserver contenu, permissions, isolation, reprise et effets durables, puis exercer
les consommateurs et un parcours assemblé. Pour les parcours IA, préserver la qualité
et mesurer le coût par réussite. Ne retenir qu’un gain utile démontré.

Tenir séparément revue complète, revue partielle et qualification dynamique ; une
zone non mesurée reste ouverte. Consigner chaque décision, blocage et condition de
reprise dans les registres. Les diagnostics bruts restent sous `artifacts/`.
`make validate` est réservé à l’utilisateur ; il n’a pas été lancé par l’agent.

## Clôture et suppression du plan

- [ ] Inventaire réconcilié ; chaque unité revue ou explicitement bloquée, avec
  dénominateurs et exclusions justifiées.
- [ ] Pistes arbitrées ; lots retenus mesurés avant/après, consommateurs vérifiés
  et régressions résolues.
- [ ] Parcours combinés, charge, repos et endurance qualifiés dans les conditions
  convenues ; preuves manquantes et conséquences explicites.
- [ ] Bilan, contrôles pertinents et documentation consolidés dans l’audit.

Conserver le plan jusqu’à clôture, ou transfert explicite des travaux restants vers
un suivi plus court. Sa suppression devra préserver l’audit et les preuves, mettre
à jour l’index et réparer les liens. Un arrêt de campagne ne vaut pas optimisation
exhaustive terminée.
