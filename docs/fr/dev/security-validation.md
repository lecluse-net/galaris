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

Les images backend, frontend, navigateur et SSH sont construites avec leurs paquets
actualisés. `bash bin/security-check.sh image IMAGE` conserve l'inventaire complet
dans `artifacts/security/` et échoue si un correctif HIGH/CRITICAL reste disponible.
Les résultats sans correctif restent à examiner ; ils ne sont pas une certification
de sûreté. Les rapports CI sont conservés 30 jours.

Le backend exclut le `.venv` de l'hôte de son contexte de build. Le pip système,
inutile dans l'image de production qui utilise uv, est retiré. npm reste disponible
dans l'image navigateur pour ses commandes de validation ; ses dépendances sont
actualisées sans modifier les règles réseau du navigateur.

Activer dans les règles de la branche principale les statuts **Quality required** et
**Security required**. Ces deux jobs agrègent leurs dépendances et échouent aussi
quand un job requis a été annulé ou ignoré. Le dépôt fournit les jobs ; l'activation
de leur caractère obligatoire est un réglage GitHub distinct.

Avant livraison : `make tests`, `make typecheck`, `make architecture-check`,
`make tests-e2e ARGS='--repeat-each=3'`, `make tests-harness-manager`,
`make security-check` et `make tests-restore`.

## Restauration répétable

`make tests-restore` utilise exclusivement `compose.test.yaml` avec un nom de
projet et des répertoires temporaires propres. Il ne charge ni ne restaure les volumes
de l'application. Il :

1. initialise le schéma réel par DbAdmin dans PostgreSQL éphémère ;
2. crée des fichiers témoins, une valeur chiffrée et une valeur signée avec des clés de test ;
3. sauvegarde toute la base avec `pg_dump -Fc`, archive fichiers et clés, vérifie les sommes SHA-256 ;
4. restaure avec `pg_restore --exit-on-error` dans une seconde base vide ;
5. vérifie les fichiers, le déchiffrement et la signature avec les clés restaurées ;
6. supprime uniquement son projet Docker et ses temporaires.

Cet exercice vérifie la procédure et le format de sauvegarde ; il ne constitue pas
une restauration de vos sauvegardes réelles. Pour celles-ci, suivre la
[procédure d'administration](../admin/README.md) sur une
instance distincte, avec les mêmes clés, le dump et les volumes cohérents, puis
vérifier une connexion et un téléchargement de pièce jointe.

## Inventaire initial des images — 5 septembre 2026

Après mise à jour, aucun correctif HIGH/CRITICAL disponible n'est laissé inappliqué.
Les distributions signalent encore les alertes suivantes sans version corrigée :

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
