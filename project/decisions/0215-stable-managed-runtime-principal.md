# 0215 — Identité MCP stable pendant la synchronisation des harnais

Statut : accepté — 22 octobre 2026.

## Problème

Les synchronisations de configuration remplaçaient le jeton système MCP en base avant
les écritures distantes et le démarrage du conteneur. Un échec intermédiaire pouvait
laisser un conteneur actif avec une identité déjà révoquée. Les tests des provisioners
simulaient la création du jeton sans vérifier l'authentification de l'identité précédente.

## Décision

`app.mcp` fournit `ensure_system_token` aux bridges DeepSeek, Claude Agent, Codex et
Hermès. Une synchronisation conserve le jeton actif et son identité persistée, également
référencée par les autorisations de run. L'initialisation et les opérations explicites de
rotation/révocation sont sérialisées par un verrou consultatif transactionnel PostgreSQL
dans un espace réservé aux jetons MCP de chaque agent. Aucune transaction réseau n'est
retenue par cette opération. Une incohérence de chiffrement ou d'empreinte échoue sans
rotation implicite. La suppression du runtime garde sa révocation explicite.

Les grants de `app.tools`, liés au run, à l'affectation, au contexte et à leur expiration,
restent obligatoires. Un jeton de principal stable ne suffit pas à autoriser une action.
La reconstruction d'un runtime conserve les contrôles existants de changement d'affectation.

Le harnais DeepSeek rend le refus HTTP 401/403 de son précontrôle comme une erreur de
configuration sans effet, avant démarrage du SDK. Le client commun conserve cette preuve
structurée. Les exceptions après démarrage et les anciens résultats incertains restent
des issues inconnues : aucune action n'est automatiquement rejouée.

## Récupération et vérification

Une installation déjà désynchronisée demande une recréation du runtime par l'action
Galaris **Redémarrer**, puis une relance explicite de la Task. **Actualiser** ne remplace
pas cette opération : cette commande demande la projection des skills. Les nouveaux
diagnostics de l'adaptateur nécessitent la reconstruction de son image.

Les tests synthétiques vérifient l'authentification précédente après synchronisation et
échec du manager, l'initialisation concurrente avec de vraies transactions indépendantes,
la révocation et la conservation des jetons clients externes. Un test HTTP traverse le
vrai serveur DeepSeek et le client commun ; un refus d'identité empêche tout démarrage
du SDK et ne divulgue ni URL sensible, ni secret, ni corps de réponse distant.
