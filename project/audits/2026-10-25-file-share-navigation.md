# Navigation File Share par harnais — décision du 25 octobre 2026

**Les conditions de poursuite de FUSE ne sont pas satisfaites.** Le répertoire est
moins coûteux, mais sa non-dégradation de réussite n'est pas établie. La piste est
arrêtée pour ce périmètre ; les outils MCP restent la référence. Cette conclusion
clôt l'expérience du plan initial, désormais retiré des travaux actifs.

## Protocole et preuves

Le vrai SDK Hermes **v0.22.4**, dans l'image amont épinglée par le dépôt, a exécuté
**`deepseek/deepseek-v4-flash-0731`**, exclusivement chez **DeepInfra via OpenRouter**.
Même modèle, température 0, raisonnement désactivé, outils natifs fichier/terminal
identiques et sessions neuves. Les fonctions MCP actuelles utilisent la vraie façade
File Share avec un transport externe synthétique. Seule la variante répertoire reçoit
les fichiers sur disque, en lecture seule. Les réponses attendues restent hors du harnais.

Le pilote indépendant réussit **4/4 exécutions**. La décision porte sur **12 autres
missions × 5 répétitions × 2 variantes = 120 exécutions**, sans exclusion après
observation des résultats. Ordre, seuils et budgets sont figés avant le premier run :
12 itérations SDK, 180 secondes par run, 2 048 tokens de sortie par requête,
8 millions de tokens pour la campagne.

Les **614 requêtes modèle** ont toutes rendu une comptabilité exploitable, avec le
même modèle et le même endpoint observés. Valeurs, types et URI sont vérifiés de
façon déterministe, avec les traces des accès exécutés. Les coûts des réponses
incorrectes sont inclus ; aucun coût Task reconstruit n'est utilisé.

Les preuves locales restent sous `artifacts/file-share-navigation/` : manifeste,
sources archivées, transcripts synthétiques, mesures par requête, scores et rapport.
Empreinte du corpus :
`deb2394eda2b2e1737c36eb1596e3cd1b77318b50ffe214b61a42d93b124b4d6`.
Les tentatives de calibration invalides restent séparées des 120 données de décision.

## Résultats

| Mesure | MCP | Répertoire |
|---|---:|---:|
| Missions réussies | 55/60 | 48/60 |
| Réussite | 91,67 % | 80,00 % |
| Coût fournisseur, échecs inclus | 0,139553 USD | 0,026569 USD |
| Coût par réussite vérifiée | 0,002537 USD | 0,000554 USD |
| Tokens d'entrée | 5 775 838 | 1 246 053 |
| Tokens de sortie | 40 607 | 12 193 |
| Appels d'outils du harnais | 466 | 145 |

Les intervalles appariés à 95 % rééchantillonnent les **12 missions**, en gardant leurs
répétitions ensemble : 10 000 tirages, graine figée. Les 60 runs d'une variante ne
deviennent pas 60 missions indépendantes.

- Écart de réussite répertoire − MCP : **−11,67 points**, intervalle
  **[−38,33 ; +16,67] points**. Il ne démontre pas une infériorité générale, mais
  n'exclut pas une perte supérieure à la marge de non-dégradation de 5 points.
- Baisse du coût par réussite : **78,18 %**, intervalle **[64,38 ; 87,43] %**.
  Le critère de coût franchit son seuil ; le critère de non-dégradation associé échoue.

| Mission | MCP | Répertoire |
|---|---:|---:|
| Découverte imbriquée | 5/5 | 5/5 |
| Noms Unicode | 5/5 | 5/5 |
| Titres proches | 5/5 | 5/5 |
| Lecture après la première page | 5/5 | 5/5 |
| Croisement | 5/5 | 5/5 |
| Énumération de 507 entrées | 0/5 | 5/5 |
| Snapshot Task récent | 5/5 | 5/5 |
| Pièce jointe Mail synthétique | 5/5 | 0/5 |
| Pièce jointe Messenger synthétique | 5/5 | 1/5 |
| Signature binaire | 5/5 | 5/5 |
| Fichier indisponible | 5/5 | 5/5 |
| Collection inaccessible | 5/5 | 2/5 |

Le MCP atteint son budget d'itérations pendant la pagination : le harnais garde des
pages de 100 et dépense aussi des appels en découverte, description et lecture de
résultats. L'API accepte déjà 500 entrées par page ; ce résultat ne prouve pas une
limite de capacité de la façade à 500 ressources.

Pour les pièces jointes, le répertoire retrouve généralement la bonne URI mais
confond une valeur du message parent avec le code du fichier demandé. Ses trois
autres échecs portent sur une référence non canonique de la collection inaccessible.
Aucun `complete:true` erroné n'est observé dans ces cas. Les contrôles d'identité
signalent aussi deux références incorrectes dans les réponses MCP de pagination.
Ces défauts restent publiés avec le résultat moyen.

## Limites et clôture

La fixture utilise un transport connecté synthétique. Ses snapshots Task et ses
arbres Mail/Messenger ne qualifient ni les providers natifs, ni IMAP, ni les ACL métier.
Le SDK est autonome : transitions Task et autorisation du runtime Galaris assemblé
ne sont pas comparées. Les helpers MCP et la recherche d'outils de cette version
Hermes participent aux coûts.

La latence du répertoire local est optimiste. Aucun FUSE distant, gros fichier,
seek vidéo ou cache de montage n'est qualifié. Les caches fournisseur sont observés
sans remise à zéro. Les durées sont conservées, mais l'activité concurrente de
développement ne permet pas d'en faire un benchmark de latence isolé. Les dates métier
sont explicites ; l'horloge système n'est pas virtualisée. Aucun autre modèle n'est qualifié.

Les 120 runs étaient achevés lorsqu'une édition du script shell encore exécuté a
interrompu l'étape de rapport. Le calcul a été effectué une seule fois depuis les
sources archivées, sans rejouer de run ni changer le score ou les seuils. Le lanceur
livré charge désormais son script en mémoire ; les conteneurs exécutent une copie
figée des sources, conservée dans chaque archive de campagne.

La revue du relais a également reproduit, avec un secret entièrement synthétique,
une conservation possible d'un préfixe de secret après troncature avant masquage.
Le masquage précède désormais la troncature et le test vérifie cette frontière.
Ces corrections de diagnostics et de lancement n'altèrent pas les 120 mesures archivées.

La vérification finale du lot passe 23 tests ciblés, dont la reproduction corrigée
du masquage, les continuations et les consommateurs MCP existants. Le typage passe.
Le lanceur figé termine ensuite un nouveau pilote de contrôle 4/4, distinct des
missions et du résultat de décision.
La préparation documentaire a validé le corpus et les contrats sur snapshot, mais
a refusé sa publication pendant des éditions concurrentes des sources. Le contrôle
d'architecture global a ensuite signalé les cartes devenues obsolètes. Ces contrôles
ne sont pas présentés comme une validation globale du checkout ; `make validate`
n'a pas été exécuté.

Le gain ponctuel de pagination ne satisfait pas les critères globaux. Il n'y a ni
seconde campagne de décision opportuniste, ni chantier FUSE, ni déploiement. L'outillage
et son [guide FR/EN](../../docs/fr/dev/file-share-navigation.md) restent disponibles
pour une expérience future explicitement distincte.
