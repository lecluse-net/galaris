<p align="right"><strong>Français</strong> · <a href="../../en/dev/service-catalog.md">English</a></p>

# Catalogue de services autonome

Le catalogue est distribué dans `back/app/services/service_catalog/`. `index.yaml` contient
`format_version: 1` et `services`, une liste de noms de fichiers YAML. Une entrée contient
le contrat `ServiceCreate` utilisé par l'éditeur et l'import/export habituels, plus :

- `catalog` : `format_version`, version SemVer du modèle, `minimum_galaris_version`, résumés
  `summary.fr` et `summary.en`, URL `documentation` et crédit `icon_credit` ;
- `icon` : `media_type` (`image/svg+xml`, `image/png`, `image/gif`), `encoding` (`text` ou
  `base64`) et `data`, intégralement dans le YAML. Utiliser un bloc `|` pour le SVG lisible.

Les champs de configuration et les références de paramètres suivent les contrats existants.
Ne pas inclure de connexion personnelle ni de valeur secrète. Utiliser des noms génériques
(`url`, `login`, `password`, `token`, `user_id`). Une fiche doit décrire uniquement les
capacités et protocoles exécutables présents, avec les limites et adresses à compléter.
Conserver la provenance et la licence des icônes ; une marque n'est pas une approbation
de Galaris par son propriétaire.

Chaque fichier et réponse HTTP est limité à 512 Kio, l'index à 100 entrées et l'actualisation
à 60 secondes. Les icônes sont limitées à 128 Kio ; PNG/GIF à 1024 pixels et 100 frames.
Le sous-ensemble SVG accepte des formes et attributs explicites, sans DTD, script, style,
liens, références externes ou objets HTML. Le frontend affiche un élément image, jamais du
SVG injecté dans le DOM. Le catalogue officiel n'accepte pas de commande MCP stdio ni
d'identifiant littéral. L'import/export personnel conserve les contrats MCP existants.

`GET /api/services/catalog` exige `SERVICE_ACCESS` ou `SERVICE_EDIT`.
`POST /api/services/catalog/refresh` exige `SERVICE_EDIT`. La lecture n'accède pas au réseau.
L'actualisation cible uniquement le dépôt officiel `lecluse-net/galaris`, résout `main`
puis télécharge index et fiches au même SHA. Le snapshot JSON du cache est publié
atomiquement sous `/data/service-catalog/`. Aucun échec réseau ou de validation ne remplace
le cache précédent ; le résultat expose `refresh_failed`. Les entrées embarquées servent
de repli, y compris lorsqu'une fiche distante devient incompatible avec cette version.

Les métadonnées du modèle sont conservées sur une copie locale pour signaler les versions
différentes, sans mécanisme de remplacement automatique. La création reste l'enregistrement
ordinaire d'un Service dans l'éditeur standard. Les secrets restent locaux aux Connexions.

Le renommage du domaine est l'action DbAdmin `app.services.rename_domain` en `BEFORE_EXPAND`.
Elle est exécutée par `make sync-db` en développement et par `make update` au déploiement.
Les clients doivent migrer `app.tools` vers `app.services`, `/api/tools` vers `/api/services`,
`tool_id`/`tool_code` vers `service_id`/`service_code`, `TOOL_ACCESS`/`TOOL_EDIT` vers
`SERVICE_ACCESS`/`SERVICE_EDIT`, `tool_admin_*` vers `service_admin_*` et `tools_list` vers
`services_list`. Les outils MCP au sens du protocole, leurs appels et leurs index gardent
leur nom. Le journal historique DbAdmin conserve ses anciennes clés de reprise.

Les lecteurs des anciens BPMN et snapshots de runs adaptent les références REST et les
appels administratifs concernés, sans réécrire les révisions ni les données métier.

Les premières fiches REST suivent les références officielles :
[Qonto](https://docs.qonto.com/get-started/business-api/overview),
[GitLab](https://docs.gitlab.com/api/rest/authentication/),
[n8n](https://docs.n8n.io/api/authentication/),
[Redmine](https://www.redmine.org/projects/redmine/wiki/Rest_api).
