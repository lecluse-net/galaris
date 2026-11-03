<p align="right"><strong>Français</strong> · <a href="../../en/dev/security-validation.md">English</a></p>

# Validation de sécurité

`make security-check` exporte uniquement les fichiers du projet non ignorés par Git :
les données actives, `.env`, les références externes et les environnements locaux
n'entrent pas dans les scanners. Trivy vérifie les dépendances verrouillées et les
secrets ; Semgrep vérifie Python, JavaScript et TypeScript. Les scanners tournent dans
Docker, sans accès au socket Docker ni aux sources en écriture. Docker et jq sont requis.

La CI `Security` s'exécute sur PR, push de main, lancement manuel et chaque lundi.
Les alertes HIGH/CRITICAL des sources bloquent, même sans correctif, sauf exception
explicite dans `security/trivy-ignore.yaml`. Chaque exception décrit l'absence
d'exposition concernée et expire. Les exclusions SAST du SQL DbAdmin sont locales aux
instructions qui construisent des identifiants générés ou correctement échappés.

Les JWT applicatifs utilisent PyJWT avec une liste d’algorithmes fixée à HS256 et un secret
privé. La dépendance python-jose et sa dépendance inutilisée ecdsa sont retirées, ainsi que
l’ancienne exception Trivy associée. Les [garanties fonctionnelles](functional-tests.md)
couvrent la compatibilité des anciens jetons et le refus d’une clé publique DER utilisée
comme secret HMAC. Les annotations SAST de migrations justifient chaque instruction par ses
identifiants en liste fermée, issus des modèles ou échappés ; les valeurs externes restent
liées par paramètres. Elles ne désactivent pas la règle SQL globale et doivent être revues
si les fragments interpolés changent.

Les images backend, frontend, navigateur et SSH sont construites avec leurs paquets
actualisés. `bash bin/security-check.sh image IMAGE` conserve l'inventaire complet
dans `artifacts/security/` et échoue pour toute vulnérabilité HIGH/CRITICAL active,
même sans correctif. Chaque cause est également affichée dans les logs CI.
Les rapports CI sont conservés 30 jours.

Backend et SSH utilisent Ubuntu 26.04 LTS avec Python 3.14. Les clients PostgreSQL
restent en version 17 via le dépôt officiel signé PGDG. Le backend exclut le `.venv`
de l'hôte et ne possède pas de pip système ; uv gère son environnement. npm reste disponible
dans l'image navigateur pour ses commandes de validation ; ses dépendances sont
actualisées sans modifier les règles réseau du navigateur.
Les codecs GStreamer Bad inutilisés par Chromium sont retirés.

Le scan SSH conserve un inventaire brut et peut appliquer une VEX aux seules CVE
noyau examinées pour la version exacte de `linux-libc-dev`. La vérification de l'image
immuable prouve la présence d'en-têtes non exécutables et l'absence de noyau/modules.
La VEX expire ; les CVE classées restent visibles dans le rapport évalué et les logs.
Une autre version, une nouvelle CVE, une preuve absente ou une alerte perdue bloque.
Le contrôle ne classe pas les vulnérabilités du noyau de l'hôte. Voir la
[décision 0264](../../../project/decisions/0264-lts-runtime-security-assessment.md).

Activer dans les règles de la branche principale les statuts **Quality required** et
**Security required**. Ces deux jobs agrègent leurs dépendances et échouent aussi
quand un job requis a été annulé ou ignoré. Le dépôt fournit les jobs ; l'activation
de leur caractère obligatoire est un réglage GitHub distinct.

Préparer les sources avec `make docs-prepare`. Pour une qualification fonctionnelle complète,
l'utilisateur peut lancer `make validate` sur un instantané isolé du worktree.
`make validate-stability` ajoute trois répétitions E2E
par navigateur. Lire le rapport `artifacts/validation/*/summary.txt` et ses échecs ; toute
modification ultérieure invalide la validation. Les cibles `make security-check` et
`make tests-restore` peuvent aussi être exécutées séparément pour un contrôle ciblé.

## Contrôle avant publication

Après le dernier commit poussé sur `main`, attendre le workflow Security,
puis exécuter **avant de créer ou pousser le tag** :

```bash
make release-check RELEASE_REF=HEAD
```

Cette commande requiert Docker et jq. Elle utilise GitHub CLI (`gh`) avec un accès en
lecture aux Actions ; si `gh` est absent, curl interroge l’API publique en lecture seule.
Un dépôt privé exige un `gh` authentifié. `GH_REPO=propriétaire/dépôt` peut préciser le dépôt. Elle vérifie
la dernière exécution Security pour le commit exact, puis relance Trivy et
Semgrep sur son archive Git, indépendamment des fichiers non committés. Une CI absente,
échouée, annulée, ignorée ou encore en cours bloque ; un succès d’un autre commit ne
convient pas. Toute nouvelle modification doit être commitée, poussée et contrôlée.

Le workflow **Publish release** exige le même contrôle avant de créer la Release GitHub.
Il peut attendre Security jusqu’à quarante minutes, puis effectue le scan frais.
Ses erreurs apparaissent dans les annotations et le résumé Actions ; les journaux et
résultats CI sont conservés dans l’artefact `release-check`. Une erreur réseau ou une
indisponibilité du scanner bloque aussi. `make build-release` scanne également les
sources du commit avant de construire les images. Aucun de ces contrôles ne crée de tag.

Le scan des sources bloque les alertes HIGH/CRITICAL même sans correctif. Le scan des
images conserve aussi les alertes sans correctif et bloque celles qui restent actives.
Seules les conclusions VEX précises et vérifiées ci-dessus peuvent établir qu'une
alerte n'affecte pas l'artefact. Un résultat d'image ne remplace pas le contrôle des sources.

Une création manuelle dans l’interface GitHub contourne le workflow : utiliser **Publish
release**. Les protections de branches et de tags restent des réglages GitHub distincts.
Le contrôle n’établit pas l’absence de vulnérabilités encore inconnues. La
[décision de publication](../../../project/decisions/0263-security-only-release-gate.md)
décrit la cause du défaut de séquencement et le contrat retenu.

## Restauration répétable

`make tests-restore` utilise exclusivement `compose.test.yaml` avec un nom de
projet et des répertoires temporaires propres. Il ne charge ni ne restaure les volumes
de l'application. Il :

1. initialise le schéma réel par DbAdmin dans PostgreSQL éphémère ;
2. crée des fichiers témoins, une valeur chiffrée et une valeur signée avec des clés de test ;
3. sauvegarde toute la base avec `pg_dump -Fc`, archive fichiers et clés, vérifie les sommes SHA-256 ;
4. restaure avec `pg_restore --exit-on-error` dans une seconde base vide ;
5. vérifie les fichiers, le déchiffrement et la signature avec les clés restaurées ;
   relit aussi par l'API Documents le contenu courant, une ancienne version, le résumé
   manuel, les mots-clés et la pièce jointe, avec refus pour un utilisateur extérieur ;
6. supprime uniquement son projet Docker et ses temporaires.

Cet exercice vérifie la procédure et le format de sauvegarde ; il ne constitue pas
une restauration de vos sauvegardes réelles. Pour celles-ci, suivre la
[procédure d'administration](../admin/README.md) sur une
instance distincte, avec les mêmes clés, le dump et les volumes cohérents, puis
vérifier une connexion et un téléchargement de pièce jointe.

`UPGRADE_FROM=référence make tests-upgrade` et `UPGRADE_SOURCE=chemin make tests-upgrade`
construisent l’ancien backend avec son propre Dockerfile, ses dépendances verrouillées et
ses sources embarquées. La CI choisit le dernier tag sémantique présent parmi les ancêtres
du parent du candidat, plutôt que le simple commit précédent. Le même environnement historique sert à créer les données et à
vérifier le retour arrière ; il ne réutilise pas les dépendances du candidat. Une image
historique immuable fournie par `UPGRADE_PREVIOUS_IMAGE` reste réutilisée telle quelle.
`make tests-release-check` protège cette séparation, l’arrêt sur échec de construction et
la conservation des images fournies. La répétition complète utilise toujours une base et
des fichiers temporaires, sans intervenir sur l’instance applicative.

## Inventaire initial des images — 5 septembre 2026

Lors de cette revue historique, aucun correctif HIGH/CRITICAL alors disponible ne restait
inappliqué. Les distributions signalaient les alertes suivantes sans version corrigée ;
ces comptages ne décrivent pas les images actuelles et doivent être remesurés avant publication :

| Image | Occurrences paquet/alerte | Identifiants d'alerte distincts |
|---|---:|---:|
| Backend | 141 | 47 |
| Frontend | 0 | 0 |
| Navigateur | 2 | 1 |
| SSH | 200 | 103 |

Certaines alertes système sont classées critiques. Cet inventaire n'établit pas leur
exploitabilité dans Galaris ; elles restent à examiner et à corriger dès publication
amont. Les rapports JSON distinguent paquet, version, sévérité, statut et correctif.
Les comptages ne sont pas additionnables entre images qui partagent les mêmes paquets.
