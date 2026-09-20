# 0103 — Les erreurs d’outil reviennent à l’agent

Statut : accepté — 16 septembre 2026.

## Problème

Une tâche observée s’arrêtait sur
`ToolOutcomeUnknownError` après une copie SFTP vers un dossier absent. La protection
contre le rejeu d’effets incertains empêchait le modèle de recevoir une erreur d’outil
et de choisir une autre approche. Le compteur de retries et le garde de trois erreurs
identiques pouvaient également terminer le run avant cette décision.

## Décision

Cette décision remplace la terminaison sur erreur d’outil observée décrite dans 0093.
Pendant un run, une exception ordinaire de l’outil, y compris une réponse MCP d’erreur,
devient un résultat structuré `galaris.tool-error/v1`. Le modèle reçoit l’erreur,
l’issue `rejected` ou `unknown` et les indications pour poursuivre. Il décide de
corriger, vérifier, changer d’approche ou s’arrêter. Cette réponse ne consomme pas le
budget Pydantic AI de correction de schéma ; sa répétition ne déclenche pas d’arrêt
terminal supplémentaire. Les budgets globaux et les annulations restent applicables.

`unknown` ne signifie jamais succès ni absence d’effet. Le résultat demande une
vérification avant de répéter une mutation potentiellement non idempotente. Les erreurs
externes ne peuvent pas fournir une fausse preuve de rejet natif. Les exceptions brutes
non déjà formatées n’exposent que leur type, sans contenu potentiellement secret.

Le checkpoint interne v4 distingue `error_reported` de `outcome_unknown`. Le premier
conserve un résultat d’erreur durable et peut reprendre le dialogue. Le second représente
un appel interrompu sans réponse enregistrée et conserve les garanties de réconciliation
de 0093. Une reprise restitue le résultat enregistré, sans refaire l’appel. Les reçus
console peuvent encore remplacer une erreur observée par le résultat réel. Les anciennes
versions restent lisibles sans inventer une preuve d’exécution.

L’historique, le stream et le journal d’incidents présentent ces résultats comme des
erreurs, sans annoncer un retry automatique ni un faux succès.

Le transport SFTP vérifie l’existence des parents après `realpath`, crée les dossiers
manquants et conserve le confinement dans le home. Avant publication par renommage, un
échec dont le temporaire est nettoyé est un rejet récupérable ; une réponse perdue après
publication reste incertaine.

## Validation

- Un agent Pydantic AI réel reçoit quatre erreurs MCP, corrige son appel et termine,
  ou choisit de s’arrêter ; le scénario passe également sans checkpoint.
- Les tests de reprise vérifient la restitution des erreurs sans répétition de l’effet,
  les preuves natives, les refus de preuves externes et la récupération des reçus SSH.
- Les erreurs sont visibles comme telles dans le stream sans limite artificielle de retries.
- Un vrai serveur SFTP couvre envoi, append, copie et déplacement vers des dossiers
  imbriqués absents puis existants, et le refus des liens sortant du home.

Les tests qui exigeaient une exception terminale après une erreur MCP observée sont
remplacés par ces garanties. Les tests de crash sans réponse, d’annulation, de format
inconnu et de préservation des effets restent en place.
