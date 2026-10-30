# Plugins Galaris — conception de distribution et activation

- Statut : `design`
- Revue des sources : 2026-10-30.

## Résultat recherché

Installer un bundle backend/frontend versionné sans l'activer, vérifier identité,
intégrité, compatibilité et permissions, puis appliquer une génération cohérente au
redémarrage. Désactivation et retrait conservent les données ; purge séparée et explicite.
Le store signé réutilise exactement cette chaîne.

Le bootstrap statique de `back/modules.py` et `front/modules.ts` reste le socle courant ;
il ne constitue pas une infrastructure d'installation de plugins.
`plugins` représente une origine de distribution/confiance, pas une quatrième couche
métier. Les contributions passent par les surfaces publiques de core/app/bridge.
Le [chantier d'écosystème](cible.md#écosystème-signé) porte la direction produit.

## Familles de contributions

Un plugin est une unité de distribution ; il peut fournir plusieurs contributions
typées. Un même bundle pourrait associer un stockage, un Tool préconfiguré, un lecteur
et un éditeur. Une famille n'impose ni un package distinct ni un nouveau domaine métier.
Les familles ci-dessous sont une cible de conception, pas des extensions déjà disponibles.

| Famille | Contributions envisagées | Domaine hôte / frontière |
|---|---|---|
| Interfaces File Share | Transports de stockage, navigation paginée, métadonnées, lecture/écriture, copie, déplacement, suppression et partage selon capacités réelles. Google Drive, Dropbox, Proton Drive, autres clouds ou stockages spécialisés. | `app.file_share` conserve les URI et opérations génériques ; `app.connection` possède configuration et secrets. |
| Fournisseurs | Modèles LLM, embeddings, reranking, image, vidéo, transcription et synthèse vocale. | Ports publics des domaines IA/média ; résolution, admission, coûts et suivi restent gouvernés par l'hôte. |
| Tools et préréglages | Outils natifs, adaptateurs MCP/HTTP et définitions de Tools préconfigurées pour un service. Un préréglage peut être purement déclaratif. | `app.tools`, `app.mcp` et `app.connection` ; installation, connexion et autorisation d'appel sont distinctes. |
| Visualisation de fichiers | Lecteurs pour formats spécialisés, miniatures, inspection de métadonnées, navigation dans une archive ou un assemblage, rendu 2D/3D. | Extension des aperçus et lecteurs ; la source peut appartenir à n'importe quel provider File Share autorisé. |
| Édition de fichiers | Éditeurs spécialisés d'image, audio, vidéo, CAO ou scène 3D, opérant sur une URI externe sans imposer son import dans Documents. | Sauvegarde par le provider propriétaire ; capacités et contrôle de concurrence vérifiés avant de proposer l'édition. |
| Types de Documents | Types créables et éditables dans la bibliothèque : CAO, MAO, image, vidéo, scène 3D et autres projets spécialisés. | `app.document` conserve identité, métadonnées, ACL, classification et révisions ; le plugin apporte le format et ses comportements. |
| Import, export et analyse | Convertisseurs de formats, OCR, extraction de texte/structure, indexation spécialisée et export d'un projet ou d'un rendu. | Ports des domaines Document, aperçu et acquisition/recherche ; dérivés traçables, bornés et soumis aux droits de la source. |
| Exécution agentique | Drivers, harnais, capacités et adaptateurs de runtimes externes. | Contrat `app.agent` ; persistance, transitions et leases restent dans `app.task`. |
| Canaux et événements externes | Bridges Messenger/voix, calendriers, webhooks et sources d'événements. | Traduction vers les façades canoniques, sans workflow Task parallèle dans le plugin. |
| Processus métier | Adaptateurs de moteurs, activités métier et préréglages de véritables workflows. | `app.process` possède définitions BPMN, historique et grants ; un outil technique isolé ne devient pas un Process. |
| Interfaces et packages métier | Vues, panneaux spécialisés, tableaux de bord, skills, modèles d'agents ou packs métier combinant plusieurs contributions. | Slots SDK et façades des domaines concernés ; aucun accès implicite aux données ou aux Tools du fait du pack. |

Priorité de qualification : File Share, fournisseurs, Tools préconfigurés,
visualisation, puis édition et types documentaires. Les autres familles constituent
un inventaire des points d'extension possibles, sans imposer leur livraison au premier palier.

### Réemploi de connecteurs de stockage

Évaluer un bridge Galaris vers **Rclone** afin de réutiliser ses connecteurs Google Drive,
Dropbox et d'autres stockages, plutôt que réimplémenter chaque API. Le plugin expose des
profils de fournisseurs explicites ; les locators Rclone et sa configuration restent internes.
Le schéma d'une connexion reste le code du Tool, conformément au contrat File Share.
Une interface commune ne prouve pas des garanties identiques : qualifier pagination,
identité des fichiers de même nom, exports Google Docs/Sheets/Slides, renouvellement OAuth,
fraîcheur des métadonnées, taille des transferts et écritures concurrentes par fournisseur.

Pour **Proton Drive**, comparer ce réemploi à un bridge vers le **CLI officiel Proton**.
Lors de la revue, le backend Rclone Proton est classé expérimental et documente des limites
de cache en présence d'autres clients ; le SDK Proton direct n'est pas encore présenté
comme prêt pour les applications tierces en production. Le CLI officiel fournit une piste
de prototype, pas une intégration Galaris déjà qualifiée. Vérifier connexion par navigateur,
persistance/renouvellement de session et fonctionnement sans interface graphique dans Docker.
Références à revalider au prototype : [support Rclone](https://rclone.org/tiers/),
[backend Proton](https://rclone.org/protondrive/),
[CLI Proton](https://proton.me/support/drive-cli),
[SDK Proton](https://github.com/ProtonDriveApps/sdk#current-status).

La première expérience vise Google Drive via Rclone : connexion, navigation, lecture,
création, modification et copie vers un autre provider, avec refus d'accès et conflits.
Comparer ensuite Dropbox et Proton sans annoncer les opérations non vérifiées. Galaris
conserve l'isolation des connexions/agents, les secrets côté serveur, les limites de
transfert et les erreurs explicites. Les binaires doivent être versionnés et fournis par
l'image/SDK au premier palier, ou par un service externe supervisé explicitement supporté ;
le plugin n'installe pas arbitrairement des dépendances au démarrage.

### Tools préconfigurés

Un plugin peut distribuer une définition de Tool, ses schémas, libellés FR/EN,
instructions, paramètres non secrets et références aux capacités requises, avec ou sans
code exécutable. Les identifiants distribués sont stables et les contributions ont un
propriétaire connu ; leur réconciliation est idempotente et préserve les réglages locaux.
La politique de mise à jour distingue valeurs par défaut du fournisseur et choix locaux.

Le bundle ne contient ni secrets, ni sessions, ni connexions nominatives d'agents.
L'installation n'accorde aucun droit d'appel et ne connecte pas automatiquement des agents.
Les modes Actif/Bloqué/Sur demande, les accords de contexte et les ACL restent applicables ;
les services système obligatoires ne peuvent pas être remplacés ou désactivés par un plugin.
Un Tool existant ne devient pas nécessairement un plugin : le plugin est son mode facultatif
de distribution et de configuration.

### Lecteurs, éditeurs et types documentaires

Séparer trois contrats composables : **visualiser une ressource**, **éditer son format**
et **créer un type de Document révisé**. Un lecteur seul reste utile sans éditeur ; un éditeur
de fichier externe ne crée pas automatiquement de Document. Exemple de bundle CAO : lecteur
d'assemblages, miniature, import/export, éditeur et type documentaire partageant le même codec.
Autres cas : session MAO multipiste avec médias liés, image à calques, montage vidéo avec
sources et rendus, scène 3D avec géométries, matériaux, textures et animations.

Le descripteur de contribution précise formats/MIME et versions acceptés, détection bornée,
capacités lecture/édition/création/export, version du codec et du schéma de contenu,
composant frontend et éventuel convertisseur/runtime serveur. La sélection entre plusieurs
lecteurs/éditeurs est déterministe, respecte le choix utilisateur et ne remplace pas implicitement
les formats natifs. Définir un port d'édition pour l'UI et, si pertinent, des opérations typées
utilisables par les agents, soumises aux mêmes validations et autorisations.

Pour les nouveaux Documents, concevoir un registre extensible sous l'autorité de `app.document`.
Le registre actuel de types Texte/Données et ses discriminants/contraintes ne constituent pas
encore ce contrat d'extension. Prévoir leur évolution via DbAdmin et les contrats API/frontend ;
ne pas persister arbitrairement un code de plugin dans les champs actuels. Les nouveaux types
apparaissent dans la bibliothèque commune et réutilisent partage, classification, recherche,
historique et révisions ; ne pas créer une bibliothèque ou des ACL parallèles par format.

Les binaires restent des fichiers immuables de `core.storage` retenus par leurs révisions.
Un projet multifichier demande un snapshot cohérent de son fichier principal et de ses assets,
avec références validées et sans accès implicite aux fichiers externes. Arbitrer archive autonome
ou manifeste d'assets immuables avant le premier type multifichier ; toute sauvegarde publie
une révision complète ou conserve la précédente en cas d'échec. Une référence externe ne transmet
jamais ses droits ; les snapshots et rendus ne doivent pas contourner ces droits.
Les Documents Texte et Données gardent leurs contrats ; les Process restent des ressources
BPMN de `app.process`, sans nouveau type documentaire exécutable pour les héberger.

Contrat de sauvegarde : validation du format, contrôle de révision/ETag adapté au propriétaire,
conflit explicite, état modifié conservé après erreur et fermeture/navigation gérées sans perte
silencieuse. Pas de promesse de collaboration temps réel ni d'édition sans perte pour tout format.
Un export avec perte est explicite et ne remplace pas le projet natif sans choix utilisateur.
Le lecteur conserve un mode lecture seule lorsque l'édition ou l'autorisation manque.

Les aperçus, miniatures, caches et rendus sont des dérivés distincts du projet source.
Le port `core.preview.PreviewConverter` offre déjà une base de conversion temporaire, avec
conservation de la source et nettoyage testé ; il ne fournit ni éditeur ni type documentaire.
Les parseurs, codecs et moteurs lourds requièrent limites de taille/CPU/mémoire/temps et,
selon leur confiance, un worker isolé. Le réseau et les secrets ne sont accessibles que par
les capacités accordées ; un asset ou projet ne peut pas charger librement scripts ou plugins.
Le frontend respecte les mêmes garanties d'isolation que les autres contributions du bundle.

Après désactivation ou retrait, conserver type/version du contenu, métadonnées, révisions
et assets. Prévoir une fiche générique et un téléchargement/export des originaux encore
autorisés sans exécuter le plugin absent ; signaler l'éditeur indisponible et permettre sa
réinstallation compatible. Ne pas convertir silencieusement un projet en Texte/Données.

## Contrats proposés

| Objet | Rôle |
|---|---|
| Plugin / release | Identité stable ; version immuable et digest du bundle. |
| Installation / deployment | Présence locale vérifiée ; version désirée distincte de la version effective. |
| Génération | Snapshot atomique des releases effectives, schémas retenus et dernière génération fonctionnelle. |
| Permissions / événement | Grants locaux de version précise ; décisions et erreurs administratives expurgées. |
| Catalogue / store | Métadonnées distantes et interface locale, sans autorité d'activation distante. |

Domaine candidat `app.plugin` pour workflow, persistance, RBAC et administration.
Infrastructure core indépendante pour archives, manifests, stockage immuable, boot
et contrats techniques ; composition racine avec les ports des domaines.

Bundles : manifeste versionné, sources backend/frontend, licences/crédits,
frontend précompilé et attestations (digests, SBOM, provenance, signature).
Manifeste : identifiant global/code/module sûrs, SemVer, métadonnées FR/EN,
compatibilités Galaris/SDK/Python, entrypoints, contributions, dépendances,
permissions, objets SQL possédés et contrat de rollback. Aucun secret/binding local.
Déclarer chaque contribution avec sa famille, un identifiant stable, sa version de contrat,
ses capacités et ses dépendances. Distinguer plugin de code, préréglage déclaratif et bundle
composite dans la validation, sans créer des pipelines d'installation concurrents.

Conserver des releases externes sur volume dédié, hors checkout/image, avec staging,
quarantaine, versions par digest et registres desired/effective/last-known-good.
Le frontend n'accède qu'aux artefacts publics, jamais au volume général de données.

## Backend, frontend et schéma

- Entrypoint backend typé décrivant modèles, routes, privilèges, DbAdmin, MCP, paramètres,
  i18n, runtime supervisé et ports publics. Contributions réelles identiques au manifeste.
- Imports publics déclarés ; aucun import core/app/bridge vers un plugin, monkeypatch,
  collision ou modification implicite des registres/dépendances du cœur.
  Première version limitée aux dépendances déjà fournies par l'image/SDK.
- Espaces réservés pour routes, tables, contraintes, outils, privilèges, paramètres et i18n.
  Dépendances inter-plugins déclarées et acycliques si retenues.
- Frontend précompilé reproductible et content-addressé ; aucune compilation npm en
  production. SDK borné pour routes/navigation/i18n/slots/services/stores et nettoyage,
  avec une seule instance des runtimes Vue/Quasar/Pinia/Router/i18n fournie par l'hôte.
- Manifeste frontend des seules releases effectives ; cache immuable des artefacts,
  manifeste frais, nouvelle URL par génération et rafraîchissement des clients ouverts.
  Aucune route d'un plugin désactivé après recharge.
- DbAdmin reste l'autorité du schéma public, sans Alembic ni Atlas autonome.
  Distinguer `schema_installed` de `runtime_enabled` : désactivation/import défaillant/retrait
  ne donnent jamais un droit de DROP.
- Modèles retenus même sans runtime ; datasets/reconcilers fonctionnels arrêtés.
  Interdire mutation des objets d'un autre propriétaire ; FK externes exceptionnelles.
  Évolutions expand/contract et actions/reconcilers idempotents pour transformations avancées.
  Rollback seulement si compatibilité démontrée, sans annulation fictive des données.

## Cycle de vie et confiance

Installer : ZIP borné, refus traversal/symlinks/types spéciaux/bombes de compression,
staging non exécutable, validation manifeste/digests/signature/compatibilité/collisions,
TCK/imports isolés, publication atomique, état installé inactif.
Crash/retry laisse la génération courante intacte.

Activer : sérialiser par plugin/génération, revalider grants et artefacts, calculer
delta DbAdmin candidat, refuser par défaut destruction/hors-périmètre, publier frontend
et génération désirée, redémarrer, converger avant API, vérifier readiness/probes,
puis promouvoir ou restaurer last-known-good.
Aucun chargement backend à chaud ni socket Docker général remis au backend.

Désactiver/retirer : supprimer surfaces/runtime, conserver données et inventaire SQL.
Purger : inventaire, dépendances, privilèges, confirmation et sauvegarde selon politique,
action DbAdmin gouvernée et journal de l'effet.

Le mode initial est natif de confiance : signature et permissions déclaratives
n'isolent pas Python in-process ni JavaScript de même origine.
Ouverture à des tiers non fiables après runner isolé, identité limitée, réseau,
secrets/volumes/quotas imposés et frontend isolé si nécessaire.
Élargissement des permissions à une mise à jour soumis à approbation locale.

Store initial administré/configuré : cache de métadonnées, versions et révocations,
vérification indépendante du TLS, puis installateur local.
Pas de marché public, paiement, notation ou activation automatique dans le premier palier.

## Lots et réception

| Lot | Preuve de sortie |
|---|---|
| 0 — ADR/SDK/contrats | Manifeste, familles composables, namespaces, confiance, permissions, DbAdmin et rollback décrivent un plugin sans imports privés ; contrats séparés de lecteur, éditeur et type documentaire ; threat model d'installation de code. |
| 1 — Bundle et registre | Installation inactive et idempotente ; crash à chaque étape sans corruption de release/génération. |
| 2 — Backend natif | Contributions, runtime et schéma cohérents au redémarrage ; échec d'import/probe avec cœur administrable et aucun DROP implicite. |
| 3 — Frontend runtime | Activation/désactivation visibles après application/recharge, sans rebuild du frontend ; cohérence back/front/cache et séparation des volumes. |
| 4 — Administration et TCK | Import, permissions, activation, update, rollback, retrait et purge ; refus RBAC et parcours complet d'un plugin de référence hors monorepo. |
| 5 — Catalogue signé | Bundle altéré, révoqué, incompatible ou permissions élargies non approuvées refusés par le pipeline commun. |
| 6 — Mode isolé | TCK adversarial : aucun accès non accordé, mutation du cœur ou survie après désactivation. |

Administration : versions désirées/effectives, manifeste/permissions, erreurs expurgées,
progression/readiness, rollback, retrait/purge et journal. Distinguer privilèges de lecture,
installation, approbation, activation, rollback et purge.
Corréler version/digest/génération/opération ; readiness distingue candidat requis invalide,
composant facultatif dégradé, configuration et révocation.

TCK : archives/intégrité/reproductibilité, imports/namespaces, contributions, Pyright/types,
FR/EN, RBAC, cycle complet, interruptions et conservation des données.
Qualifications propres aux familles : isolement de deux connexions de stockage et copie
inter-provider ; Tool préconfiguré installé deux fois sans secrets ni grants automatiques ;
source préservée par un aperçu ; ouverture/sauvegarde/réouverture d'un projet avec assets,
conflit concurrent, erreur de sauvegarde et refus d'écriture ; originaux et révisions
récupérables après désactivation/retrait de l'éditeur ; réinstallation compatible.
Employer uniquement des ressources synthétiques et exercer le parcours dans l'application
assemblée, y compris permissions, clavier, petit viewport et dépendance indisponible.
Cartographie du dépôt déterministe ; release externe avec son propre rapport et inventaire runtime.

Arbitrages avant implémentation : autorités de signature, partage des runtimes frontend,
inventaire de schéma après retrait du code, dépendances entre plugins, superviseur borné,
slots SDK stables, sauvegardes/purges et catalogues autorisés.
Pour les formats spécialisés : registre et migration des types, identité des assets,
snapshot multifichier, choix de lecteur/éditeur, récupération sans plugin, licences des
codecs et répartition frontend/worker/service externe. La collaboration temps réel et les
formats couverts seront qualifiés séparément, sans prérequis implicite pour tout plugin.
Retirer les lots réalisés vers décisions, SDK, guides et tests.
