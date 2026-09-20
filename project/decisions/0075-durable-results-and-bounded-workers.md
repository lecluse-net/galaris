# 0075 — Résultats durables, workers bornés et réparation explicite

- Statut : accepté
- Date : 2026-09-06

## Contexte

Un timeout d'observation ne prouve pas l'échec d'une exécution distante. Un résultat
non consommé et une livraison incertaine restent utiles à la reprise, même anciens.
Une file globale séquentielle peut retarder des moteurs indépendants.

## Décision

Les jobs d'admission et d'observation Process sont séparés par moteur. Chaque branche
concurrente possède sa session SQL ; les services réutilisent la session contextuelle.
Quatre branches au maximum sont admises par lot et l'admission alterne les agents.
Le bail de soumission dépend du délai du moteur. Les erreurs d'observation passent
le Process en `unknown` avec backoff, sans inventer de résultat terminal.

Chaque consommateur enregistre au bootstrap un filtre SQL de protection de la
rétention. Les résultats attendus par une Task, les notifications non résolues et les
octets multimédia non livrés restent protégés avant sélection du lot. Les traces LLM
protègent la composante causale des Tasks actives, sans retenir les tâches sans lien.

Les checkpoints multimédia et les snapshots de lancement Process sont versionnés.
Un snapshot historique sans version est lu comme v1 ; une version future ou une forme
invalide échoue sur le seul job avant tout effet externe, sans bloquer le reste de la file.
L'identité des sorties est immuable ;
une contrainte unique et un UPSERT arbitrent les réceptions concurrentes. Un reçu
incertain est réparé par un administrateur du périmètre après expiration du bail :
soit rattachement d'un fichier dont le SHA-256 est vérifié, soit absence explicitement
attestée autorisant une nouvelle livraison. Aucune réparation ne régénère le média.

Les opérations binaires nécessitant un buffer réservent une enveloppe commune en
octets, avec limite d'opérations et d'identité. Cette admission n'est pas une limite
RSS du processus ni une garantie de facturation du fournisseur. Les transferts
comptent les octets décodés avant écriture et retirent les temporaires incomplets.
Le décodeur vocal produit au plus 50 trames par lot. La sortie Talk admet 100 trames
de 20 ms puis attend le consommateur ; une génération invalide les fragments d'avant
une interruption, y compris ceux d'un producteur bloqué.

Les transports de fichiers propres à un Tool sont enregistrés par leur bridge via
`app.file_share.interface`. La façade vérifie la connexion avant de construire le transport ;
elle ne sélectionne plus directement une classe privée du bridge Mail.

## Conséquences et validation

Les dégradations restent locales. Une incertitude sans preuve peut conserver des
données longtemps : l'aperçu de rétention et la réparation sont des outils opérateur,
jamais une autorisation implicite de supprimer ou de répéter un effet externe.

Les tests utilisent des transactions PostgreSQL indépendantes, une interruption après
commit de lot, des réponses UI inversées, un crash Chromium réel et des images de
production sans montage du code. Le test mixte inclut maintenant deux pairs WebRTC
locaux réels et de l'encodage binaire. La qualification d'un fournisseur distant ou d'un
réseau TURN de production reste propre à l'installation.
