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

## Complément du 26 septembre 2026 — réorienter après trois répétitions

Trois résultats d’outil identiques consécutifs déclenchent une consigne au modèle,
pas une interruption ni un bilan forcé sans outils. La consigne distingue une même
erreur répétée d’un appel réussi sans progrès. Elle demande de changer d’approche,
de relire les skills pertinents ou de vérifier les arguments ; si aucune voie ne
permet de poursuivre, l’agent explique les trois erreurs et le travail restant.
Les références de diagnostic propres à chaque erreur ne constituent pas un progrès.

Les consommateurs sont les Tasks, conversations texte et sessions temps réel utilisant
le runtime interne, avec outils natifs ou MCP, avec ou sans checkpoint. Les drivers
externes conservent leur propre politique. Garanties à préserver : terminer le lot
d’outils courant, conserver chaque résultat et effet durable, ne pas rejouer d’effet,
ne pas redémarrer le run ni son budget, et maintenir annulation et reprise. Le bilan
sans outils reste réservé à l’épuisement du budget global. Le garde de répétition de
prose temps réel est distinct et reste inchangé.

Les tests qui exigeaient un arrêt au troisième succès sont remplacés par la détection
au même seuil et par un dialogue réel modèle/outils : après trois répétitions, le
modèle reçoit la consigne, peut relire un skill puis exécuter une alternative, ou
choisir un compte rendu honnête. Un autre appel du même lot doit toujours se terminer.

## Complément du 12 octobre 2026 — retours externes hétérogènes

Le harnais interne reconnaît les erreurs explicites renvoyées comme données, sous forme
de JSON texte ou d’objet : le marqueur dédié `galaris.tool-error/v1`, `isError=true`, ou
`ok=false`/`success=false` accompagné d’un diagnostic `error`. L’enveloppe d’avertissement
sur les arguments reste transparente à cette détection. Un simple mot d’erreur, le statut
d’une ressource consultée ou l’échec d’un élément d’une collection ne constitue pas un
échec de l’appel entier. Les exceptions et le bit d’erreur MCP restent pris en charge.
Quand un MCP fournit un JSON d’erreur incomplet et un texte explicatif, les deux atteignent
le modèle. Les erreurs explicites sont journalisées comme `error_reported`, avec leurs
données originales, sans consommation du budget de correction de schéma ni rejeu automatique.
Seuls une preuve native vérifiée ou le contrat de lecture autorisent `rejected` ; une
affirmation externe d’absence d’effet ne remplace pas la vérification d’une mutation.
Les consignes d’erreur restent écrites par Galaris, même si le provider imite son schéma.
Les arguments d’un appel ayant renvoyé une erreur restent disponibles pour sa correction,
qu’il s’agisse d’un refus SDK ou d’une erreur reconnue dans le résultat.

Le compactage de l’historique conserve en priorité les contrôles d’issue, de pagination
et de révision de tous les outils, dans des aperçus JSON valides. Profondeur, collections
et chaînes sont bornées ; du texte JSON mal formé reste une donnée textuelle. Les quatre
retours les plus récents restent complets en situation normale. Si leur taille menace
le budget de contexte, leurs corps reçoivent également un aperçu sans supprimer les
identités appel/retour ni modifier les données enregistrées. Chaque aperçu signale ses
omissions ; celles-ci ne prouvent ni une source vide ni un succès. Son marqueur est refusé
avant toute écriture File Sharing. Cette protection ne fournit pas un cache de résultats
ni une réparation des permissions ou du service distant ; le modèle garde la décision
de vérifier, de corriger ou d’utiliser une autre méthode autorisée.

La validation combine les tests de compactage et des dialogues avec un vrai agent
Pydantic AI et un MCP synthétique : continuation ou arrêt honnête, diagnostic conservé,
erreur visible, reprise sans double effet et refus d’écriture d’un aperçu. Les tests
d’autorisation, de preuve native, d’annulation et de réconciliation restent applicables.
