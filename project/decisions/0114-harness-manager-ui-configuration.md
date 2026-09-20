# 0114 — Configuration du Harness Manager depuis les préférences

Statut : accepté — 2026-09-17.

Le raccordement au manager ne nécessite aucune donnée avant l’accès à PostgreSQL. Ses URL
et sa clé partagée deviennent donc des Params communs aux quatre harnais externes, avec
validation, chiffrement du secret et application sans redémarrage. Cette décision remplace
la configuration du client par environnement décrite dans les décisions 0038 et 0063.

DbAdmin importe les trois anciennes variables uniquement pour les lignes absentes, sans
écraser un choix déjà enregistré. Le réseau reste défini dans le Compose commun (0064).
Le nom d’hôte de l’API de retour est accepté par le middleware de confiance à chaque requête.

L’écran existant de diagnostic reçoit un formulaire, une génération de clé pour installation
neuve et un export explicite du `.env` du manager. Lecture : PARAMS_ACCESS ou PARAMS_EDIT ;
écriture, génération et export : PARAMS_EDIT. Les réponses contenant un secret sont no-store.
Une lecture ordinaire ne retourne jamais la clé. L’enregistrement du groupe est atomique.

Le service hôte conserve son bootstrap indépendant, son fichier `.env` et son installation
systemd. L’export ne pousse aucun fichier et n’exécute aucune commande distante. Les réglages
du générateur sont des options de préparation locales à l’écran, pas une configuration active
du service. Pour une installation existante, préserver la clé, BASE_DIR et les autres options.

Les diagnostics vérifient le manager, sans prétendre vérifier l’accès des conteneurs à MCP.
Un déploiement distant doit toujours router Galaris vers les noms des conteneurs runtime et
les runtimes vers l’API Galaris. Un changement d’URL API exige la synchronisation des harnais
existants ; une rotation de clé exige de coordonner le service et les clients.

Garanties : tests HTTP/DB de persistance, chiffrement, droits et export dotenv ; migration
idempotente ; tests des quatre consommateurs ; tests navigateur d’édition, réouverture,
export, erreurs et réponses tardives.
