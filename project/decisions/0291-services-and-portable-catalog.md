# 0291 — Services et catalogue YAML autonome

Statut : accepté, implémenté.

## Contrat

Le domaine Galaris auparavant nommé Tool devient **Service** : un fournisseur ou une
fonction intégrée, ses protocoles, paramètres et connexions. Une fonction appelable MCP
reste un tool au sens du protocole. Les toolsets, événements de tool calls et index de
fonctions ne sont pas renommés en services.

Les surfaces canoniques sont `app.services`, `/api/services`, `/services`, `Service`,
`service_id`, `service_code`, `SERVICE_ACCESS`, `SERVICE_EDIT`, `service_admin` et
`services_list`. L'ancienne page `/tools` redirige les liens humains. Les clients API et
MCP administratifs doivent utiliser les nouveaux contrats. Les clés historiques des
actions DbAdmin restent stables pour reprendre une synchronisation interrompue.

Une action DbAdmin `BEFORE_EXPAND` renomme les tables, séquences et colonnes existantes
sans copier les lignes ni changer leurs clés. Elle renomme les paramètres réservés,
les privilèges en conservant leurs identités et les règles des fonctions administratives.
Une collision entre ancien et nouveau nom bloque l'opération, sans fusion implicite.
Les accords en attente, liés aux anciennes empreintes, sont invalidés ; les décisions
par fonction, connexions et secrets restent conservés. La convergence ordinaire DbAdmin
applique ensuite la cible SQLAlchemy.

Les anciens BPMN et snapshots de runs sont lus par des adaptateurs ciblés : référence
REST `tool_code`, noms administratifs et arguments correspondants. Les écritures et
appels utilisent les noms canoniques ; les arguments des fonctions tierces restent
intacts. Les révisions historiques ne sont pas réécrites pour un changement de vocabulaire.

## Catalogue

`back/app/services/service_catalog/` contient l'index et une fiche YAML par service.
Chaque fiche est autonome : définition habituelle, métadonnées de version/compatibilité
et icône intégrée. Le SVG est du texte ; PNG et GIF sont encodés en base64. Les fichiers
ne contiennent aucun identifiant personnel ni valeur secrète. Les logos distribués
conservent leurs crédits et leur provenance dans la fiche.

La copie embarquée est toujours disponible. Une actualisation explicite consulte
`lecluse-net/galaris`, branche `main`, résout un commit puis lit tous les fichiers au même
commit. Le lot est borné et entièrement validé avant remplacement atomique du cache.
Une erreur conserve le dernier lot utilisable et la copie embarquée complète les entrées
absentes ou incompatibles. Les compatibilités sont revérifiées avec le logiciel courant.
Le catalogue distribue des paramètres déclaratifs, sans installer de code ou de commande.

Choisir un modèle ouvre l'éditeur standard et crée uniquement une copie locale sur
enregistrement. Un code déjà utilisé reçoit une suggestion distincte. Une actualisation
du catalogue ne modifie jamais un Service installé, ses connexions ou ses permissions.
Les services personnalisés utilisent le même format d'import/export, icône comprise.

Ce catalogue ne dépend pas du futur installateur de plugins et ne prétend pas fournir
les fonctionnalités d'un connecteur qui n'existe pas. Les fiches REST utilisent l'accès
API générique ; les fiches Messenger et File Share utilisent les bridges existants.
