# 0117 — Distribution et mises à jour du Harness Manager

Statut : accepté — 2026-09-17.

Le manager reste un service hôte indépendant. Sa version numérique fixe X.Y.Z est définie
dans son `pyproject.toml`, consommée par son API et par la distribution Galaris. Toute
livraison modifiant son code distribué doit incrémenter cette version et actualiser `uv.lock`.
L'interface compare cette version à celle annoncée par le service sans confondre divergence
de version et panne de connexion. Un manager plus récent ne doit pas être rétrogradé.

Le backend embarque une liste fermée de sources via un contexte Docker dédié, sans `.env`,
instances, dépendances locales ou fichiers non distribués. Il produit un ZIP déterministe
du code et, sur demande avec PARAMS_EDIT, un ZIP d'installation contenant aussi le `.env`
préparé avec la clé enregistrée. Les réponses sont no-store ; les lectures ordinaires et
les mises à jour automatiques ne distribuent aucun secret. Le README inclus est autonome.

`make update` dans le manager utilise l'adresse `GALARIS_UPDATE_URL` exportée par l'IHM et
la clé partagée. Les endpoints machine exigent un token Fernet dédié de moins de 60 secondes,
indépendamment des sessions utilisateur. Le manifeste est authentifié avec cette même clé,
lie version, taille et SHA-256, et expire après cinq minutes. Le client refuse les redirections,
les archives altérées, les chemins non prévus, les liens symboliques et les downgrades.

La mise à jour prend un verrou local, sauvegarde les seuls fichiers de code, conserve `.env`
et les instances, puis synchronise les dépendances verrouillées. Elle relance uniquement un
manager déjà actif dans son mode initial et vérifie sa version. Un échec déclenche une tentative
de restauration ; un échec de restauration laisse une sauvegarde et un message explicite.
Les opérations de gestion doivent être évitées pendant la courte interruption. Aucun conteneur
de harnais n'est reconstruit et aucun déploiement Galaris ne lance cette commande à distance.

Une version ancienne sans updater nécessite une première extraction du ZIP de code seul,
service arrêté, puis installation et relance. Sa configuration est conservée et l'adresse
de mise à jour doit être ajoutée pour les versions suivantes.

Garanties vérifiées : contrats HTTP et droits, contenu et modes des ZIP, secret uniquement dans
l'export autorisé, authentification et intégrité, versions divergentes, refus d'archives
non conformes, conservation de la configuration et des instances, restauration après échec,
absence de downgrade et exclusion des mises à jour concurrentes, téléchargement depuis l'IHM.
