**Bilan de Galaris — 30 derniers commits, 11 septembre 2026**

La qualité s'est améliorée, surtout sur les workflows durables, la cohérence documentaire et la pertinence des tests. La maturité de livraison reste inférieure à la maturité des mécanismes internes : le dernier commit ne passe pas tous les contrôles exécutés pendant ce bilan. Une incompatibilité du limiteur HTTP est également reproduite. Je recommande une phase de consolidation avant une nouvelle extension importante du périmètre.

**Périmètre et méthode**

Comparaison de `7f0e977dfad55eccf83b23cdf19df428a1d7442d` (`HEAD~30`) à `9c59a87aaacb49f0e1c73c773aa6e03662c26ed1` (`HEAD`). Les 30 commits vont du 6 au 11 septembre 2026. La revue croise historique, différences de code, contrats, tests, configuration CI et preuves des audits précédents. Les lectures détaillées se concentrent sur les chemins sensibles et les changements structurants ; il ne s'agit pas d'une revue ligne par ligne des 1 107 fichiers modifiés.

Les exécutions nouvelles portent sur une copie `git archive HEAD` sous `/tmp/galaris-audit-30commits-tI2eB4`, avec ses dépendances verrouillées et une base PostgreSQL éphémère. Les secrets de cette copie sont générés pour les tests. Les changements non commités sur les équipes, les dialogues, Messenger, Chat et leurs autorisations sont exclus du verdict sur les commits. Aucun correctif applicatif, commit ou déploiement n'a été effectué par cet audit.

Les preuves historiques sont explicitement distinguées des vérifications nouvelles. Les configurations de production, protections de branche distantes, comptes externes, sauvegardes réelles et performances de l'installation ne sont pas certifiées. La version antérieure n'a pas été soumise à nouveau à toutes les suites : la tendance repose sur les différences de mécanismes et les preuves disponibles, pas sur un taux de bugs comparatif mesuré.

**Évolution mesurable du périmètre et de la dette**

| Indicateur | Avant les 30 commits | Dernier commit | Lecture |
|---|---:|---:|---|
| Modules backend déclarés | 65 | 70 | Plus de capacités à maintenir |
| Modules frontend déclarés | 33 | 34 | Extension maîtrisée en nombre de modules |
| Handlers HTTP/WebSocket détectés | 488 | 523 | +35 surfaces à autoriser et tester |
| Tables SQLAlchemy détectées | 94 | 108 | +14 tables et davantage de transitions de données |
| Outils MCP natifs détectés | 123 | 128 | Surface agentique élargie |
| Dépendances backend recensées | 475 | 513 | Complexité totale en hausse |
| Imports privés admis dans la baseline backend | 294 | 283 | 11 exceptions supprimées, aucune nouvelle dans ce diff |
| Paires backend bidirectionnelles | 28 | 25 | Amélioration structurelle réelle |
| Taille de la composante cyclique backend | 18 domaines | 17 domaines | Un grand cycle subsiste |

Sources : cartographies versionnées aux deux références et différences de `back/architecture-baseline.json`. La cartographie JSON de HEAD comporte une erreur de classement d'un fichier frontend, détaillée plus bas ; elle ne change pas les compteurs backend ci-dessus. Le diff global représente 115 951 insertions et 17 310 suppressions, mais contient beaucoup de documentation, d'assets et de données de tests : ce volume n'est pas une mesure de complexité du code.

**Ce qui s'est amélioré**

| Domaine | Progrès vérifiés dans les sources | Appréciation |
|---|---|---|
| Task / Process / multimédia | Budgets d'admission durables, checkpoints versionnés, protection des publications, traitement des issues distantes ambiguës, reprises et callbacks idempotents | Progrès majeur de fiabilité |
| Base de données | Meilleure conservation des données pendant expansion/contraction, gestion des annulations, traitement explicite des contraintes impossibles à resserrer immédiatement | Meilleure robustesse des mises à jour |
| Ressources et performance | Transferts bornés, pression mémoire mieux contrôlée, navigateur lancé à la demande et libéré au repos, polling suspendu hors visibilité | Amélioration ciblée ; capacité globale non mesurée ici |
| Documents | Contrat HTML commun, protection contre les anciens clients, migrations conservant les sources, révisions et conflits explicites, partage humain/agent/équipe | Forte amélioration de cohérence fonctionnelle |
| Lab | Séparation exécution/jugement, campagnes persistées, répétitions, reprise, revue humaine et conservation des sorties candidates | Meilleur outil pour mesurer la qualité IA |
| Tests | Remplacement d'assertions de fragments source par des comportements Vue réels et des scénarios DB ; couverture des refus, reprises et doublons | Amélioration méthodologique nette |
| Architecture | Réduction des imports privés et des cycles ; façades et ports mieux respectés | Bonne direction, dette encore importante |
| Interface | Palette Solaire, icônes et navigation communes, éditeur et partage mutualisés, Lab simplifié | Cohérence visuelle et fonctionnelle renforcée |

Les principaux commits de consolidation sont `2a434b48`, `b8a8b8df` et `45ae467f`. `15881f3c` traite les ressources au repos. `8646ec07` et `a8781a16` améliorent les garanties des tests. `80f3eed9` et `08a315fc` portent les évolutions structurantes Documents et Lab.

La baisse de mémoire navigateur de 141,7 à 93,19 Mio après retour au repos est une mesure historique documentée, réalisée sur un scénario local précis. Elle représente environ 34 % pour cet exécuteur dans ce scénario, pas pour toute l'application. Voir [la mesure et ses limites](2026-09-07-resource-usage.md).

Le bilan de tests du 10 septembre mentionne 79,35 % de couverture avec branches sur une sélection critique. Ce n'est ni la couverture de toute l'application ni une mesure refaite ici. Le nombre de tests Node a baissé en partie parce que des assertions de source ont été remplacées par des scénarios de composants ; cette baisse ne constitue pas en elle-même une régression. Voir [la revue fonctionnelle](2026-09-10-functional-tests.md) et [la sélection de couverture](../../back/coverage-critical.ini).

**Constats nouveaux et priorités immédiates**

**A1 — Priorité haute : la limite HTTP par défaut ne couvre pas les routes incluses via APIRouter.**

`back/core/rate_limit.py` configure `default_limits=["100/minute"]`. `back/core/api.py` installe bien `SlowAPIMiddleware`. Avec les dépendances exactes du commit, FastAPI 0.141.1 et SlowAPI 0.1.10, une sonde ASGI en mémoire donne les résultats suivants après avoir abaissé le seuil à deux requêtes pour le test :

| Montage | Quatre réponses successives |
|---|---|
| Route directement déclarée sur FastAPI, limite par défaut | 200, 200, 429, 429 |
| Route incluse via APIRouter, limite par défaut | 200, 200, 200, 200 |
| Route incluse via APIRouter, décorateur de limite explicite | 200, 200, 429, 429 |

Les modules utilisent des routeurs inclus : la protection globale annoncée n'est donc pas fiable pour cette architecture. Les décorateurs explicites des routes de connexion conservent leur effet dans la sonde. Le verrouillage progressif des comptes reste également un mécanisme distinct. Ce constat n'est pas un contournement démontré des ACL ni une attaque de charge contre l'installation.

Les deux versions étaient déjà présentes avant les 30 commits : c'est une faiblesse résiduelle découverte pendant la revue, pas une régression attribuable à cette période. Le [signalement amont SlowAPI #281](https://github.com/laurentS/slowapi/issues/281) décrit le même montage défaillant. La preuve principale reste la reproduction locale avec les versions du dépôt.

Action : rétablir une limitation compatible avec les routeurs réels, avec des tests HTTP dépassant le quota et vérifiant la réponse 429. Couvrir les routes explicites, les routes modulaires, l'identité client derrière le proxy et le retour à un état normal. Le limiteur est désactivé en `APP_ENV=test` : les suites ordinaires ne prouvent donc pas cette garantie. Pour une évolution vers plusieurs workers, définir aussi le partage du compteur, actuellement sans stockage partagé configuré dans ce module.

**A2 — Priorité haute pour la livraison : le dernier commit ne passe pas la suite backend complète.**

Résultat : **3 538 réussis, 2 échoués, 1 ignoré, 8 avertissements**, en 168,21 secondes. Les deux échecs sont reproduits seuls dans une nouvelle base isolée : ils ne dépendent pas de l'ordre de la suite complète.

- `app/llm/tests/test_personal_speech.py::test_http_preferences_and_audio_use_the_authenticated_user_without_document_privileges` : le même client HTTP se connecte successivement comme administrateur puis comme utilisateur. La nouvelle connexion révoque la famille de session précédente ; le test réutilise ensuite le JWT administrateur révoqué pour créer le deuxième compte et obtient 401. Le test doit isoler les sessions des personnes. Il ne faut pas assouplir la révocation pour satisfaire cette attente.
- `app/messenger/tests/test_service_incoming.py::test_mail_sender_is_admitted_directly_as_task_without_automatic_delivery` : attente en texte brut alors que l'objectif est désormais du HTML (`<p>…</p>`). L'admission est bien observée ; l'assertion de représentation n'a pas suivi le contrat HTML. Une correction de cette attente existe déjà dans le worktree utilisateur et n'appartient pas au HEAD audité.

Ces échecs ne démontrent pas deux pannes de production. Ils démontrent que l'intégration exacte du commit ne bénéficie pas d'une validation complètement verte. Les rapports historiques décrivant un worktree plus large ne peuvent pas tenir lieu de validation de HEAD.

**A3 — Priorité moyenne : le contrôle de cartographie échoue sur HEAD.**

Les deux JSON FR/EN classent `front/app/topic/components/TopicParticipants.vue` dans les fichiers d'une dépendance de Task, au lieu de la dépendance de Topic correspondante. Une reconstruction en mémoire déplace exactement cette entrée. Les documents Markdown ne sont pas signalés comme périmés. Le contrôleur de frontières d'architecture passe indépendamment.

Action : régénérer avec `make project-context`, puis exécuter le contrôle sur le commit destiné à être livré. Ce n'est pas une panne utilisateur, mais le job statique CI est configuré pour refuser cet écart.

**A4 — Priorité haute pour la livraison : des tests d'upload ciblent une commande absente de l'interface.**

La suite complète de composants termine avec **183 scénarios réussis et 5 échoués**, sans retry, en 9 minutes. Les cinq scénarios de `front/browser-tests/document-upload.spec.mjs` attendent le bouton « Upload into document », puis l'événement de sélection de fichier. Ils dépassent chacun leur délai de 30 secondes. La capture du composant et `editorToolbarGroups()` confirment que `documentUploadFile` n'est plus inclus dans les commandes affichées, bien que sa fabrique existe encore.

Les parcours de pièces jointes et le glisser-déposer restent présents : le test de dépôt au bon emplacement et les scénarios de pièces jointes du même passage réussissent. Il ne faut donc pas conclure à une impossibilité générale de téléverser des fichiers. Le défaut certain est le désalignement entre interface et tests. Clarifier le parcours public attendu, puis reprendre les garanties d'ordre d'insertion, d'annulation et de refus des réponses tardives sur ce parcours. Ne pas réintroduire automatiquement une ancienne commande pour rendre les tests verts et ne pas supprimer leurs garanties sans reprise.

**Risques résiduels à traiter après les blocages immédiats**

**Sécurité des contenus exécutables.** La lecture HTML éditoriale et le lecteur d'aperçu HTML autonome sont deux chemins différents. L'éditeur/lecteur riche conserve les scripts archivés comme code inerte, ce qui est une bonne protection. En revanche, `_HTML_PREVIEW_CSP` dans `back/app/chat/router.py` autorise les scripts, `unsafe-eval`, les connexions réseau larges, formulaires et popups. L'absence de `allow-same-origin` apporte une isolation utile, mais ne rend pas le document hors ligne. Les [permissions de sandbox documentées par MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe) doivent être évaluées séparément de l'accès réseau.

Je recommande un profil d'aperçu restrictif par défaut et une activation explicite des capacités réseau nécessaires, ou une origine dédiée aux aperçus actifs. Ajouter des tests navigateur contrôlant l'accès au parent, les requêtes sortantes, les popups et l'expiration des tickets. Les tickets actuels durent une heure et sont résolus comme capacités non nominatives ; leur copie reste consultable jusqu'à expiration. C'est un choix de sécurité à rendre explicite, pas la preuve qu'un tiers peut deviner les tickets.

**Autorité des utilisateurs et des agents.** Le partage documentaire progresse nettement : humains sans agent, équipes vivantes, droits lecture/écriture, remplacement atomique et versions attendues ont des scénarios dédiés. Il faut maintenant qualifier la politique d'autorisation sur l'ensemble du trajet utilisateur → agent → tâche → ressource → transport. Le chantier non commité sur les dialogues et les équipes va dans cette direction, mais n'est pas compté comme livré. Une matrice commune doit prouver les mêmes refus par HTTP, MCP, websocket, appel vocal et événement de bridge, y compris après révocation pendant une session ouverte.

Pour l'injection d'instructions dans des mails, fichiers ou résultats d'outils, les garanties décisives restent les contrôles d'autorité et de destination côté serveur. Prévoir des scénarios adversariaux dans lesquels un contenu externe demande un envoi non autorisé ou une lecture hors périmètre. C'est cohérent avec les recommandations [OWASP sur l'injection indirecte](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) et [les permissions excessives des agents](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/). Aucun scénario réel de compromission par injection n'a été exécuté dans ce bilan.

**Coût et saturation.** Les budgets Task sont un progrès, mais leur propre contrat indique qu'ils bornent l'admission et non la facture fournisseur. Les plafonds sont optionnels et valent zéro par défaut ; une phase déjà lancée peut dépasser l'estimation. Le Lab possède un `max_cost` facultatif contrôlé entre travaux. Définir des plafonds opératoires explicites par utilisateur/équipe, des réservations à l'admission et une visibilité sur l'encours, puis compléter par les limites disponibles côté fournisseurs. Définir précisément le dépassement encore possible. Voir `back/app/task/budget.py`, `back/core/params/runtime_settings.py` et `back/app/lab/run_claims.py`.

**Exploitation réelle.** Les exercices de restauration, de mise à niveau et de charge constituent une base sérieuse. Les objectifs versionnés indiquent néanmoins eux-mêmes que la cohérence d'une sauvegarde à chaud n'est pas qualifiée et que l'objectif de restauration de 15 minutes vise une petite installation, sans inclure détection et transfert distant. La présence de règles d'alerte dans Git ne prouve pas leur activation. Refaire une restauration depuis une vraie sauvegarde sur une instance séparée, chronométrer l'ensemble et déclencher les alertes pour vérifier leur réception. Voir [les objectifs opérationnels](../../docs/fr/dev/operational-objectives.json).

**Dépendances et images.** Les workflows de sécurité, scans de secrets, SAST, audits de dépendances et qualification d'images existent. Les inventaires historiques conservent néanmoins des alertes système sans correctif disponible. Une absence de correctif n'est pas une absence de risque. Ce bilan n'a pas refait les scans de vulnérabilités : aucun chiffre historique ne doit être présenté comme l'état actuel des images. Requalifier les images réellement promues et vérifier que `Quality required` et `Security required` sont obligatoires dans les règles de branche.

**Maintenabilité et cohérence.** Les 283 imports privés et le cycle de 17 domaines restent une dette substantielle. Plusieurs services sont très grands : Memory autour de 3 845 lignes, le service d'évaluation des mécanismes Lab autour de 2 690, le service de ressources autour de 2 330 ; la page Goals atteint 2 829 lignes. Ces tailles ne sont pas des défauts à elles seules, mais augmentent la difficulté d'isoler les effets d'une modification. Extraire progressivement les responsabilités qui changent ensemble : contrôle d'accès, partage, stockage, publication et politique d'exécution. Conserver les tests métier pendant ces extractions et réduire la baseline à chaque suppression effective de dépendance.

La palette et les composants communs réduisent les variations visuelles. La prochaine étape de cohérence doit surtout viser les comportements : mêmes messages et possibilités de récupération en cas de refus, conflit, interruption, attente ou erreur ; mêmes principes de navigation ; conservation des brouillons ; commandes utilisables au clavier et sur mobile. Une campagne d'accessibilité et un budget de poids JavaScript/temps d'ouverture sur un mobile modeste apporteraient davantage qu'un nouveau lot d'ajustements d'icônes.

Le build exécuté pendant cet audit produit notamment un fragment `util` de **1 765,51 kB minifiés, 482,34 kB gzip**, et un précache PWA de **8 929,38 KiB pour 318 entrées**. Le build signale plusieurs fragments dépassant 500 kB. Ces chiffres ne représentent ni le téléchargement compressé total de la première page ni une latence mesurée. Ils justifient de vérifier le chargement différé de l'éditeur, du rendu 3D et des autres fonctionnalités lourdes, puis de mesurer ouverture, mémoire et mises à jour PWA sur mobile. Aucun score d'accessibilité ni chronométrage utilisateur frontend n'a été réalisé ici.

**Qualité des agents IA.** Le Lab offre désormais les briques nécessaires pour comparer proprement : entrées et paramètres figés, sorties persistées, jugements indépendants, répétitions et revue humaine. Cela améliore la capacité à mesurer, mais ne démontre pas encore une meilleure qualité des modèles en conditions réelles. Constituer un petit corpus métier de référence séparant développement, validation et cas réservés ; évaluer réussite finale, outil choisi, destinataire, ressource livrée, coût, latence et respect des droits. Garder une adjudication humaine sur les cas ambigus et éviter de confondre note du juge IA et preuve d'un effet réalisé.

**Ordre de travail recommandé**

| Priorité | Travail concret | Preuve de fin |
|---|---|---|
| Avant la prochaine livraison | Corriger la limitation HTTP et stabiliser les tests/contrôles rouges du commit | Sonde de quota intégrée, suite et contrôles du commit exact verts |
| Avant la prochaine livraison | Qualifier les changements d'autorisations en cours et l'upgrade HTML | Refus inter-utilisateurs cohérents et répétition d'upgrade sur données peuplées |
| Prochaine itération | Durcir les aperçus actifs et tester les chemins d'abus des outils | Tests de réseau/sandbox et d'autorité sur scénarios adversariaux |
| Prochaine itération | Activer et éprouver alertes, budgets et restauration réels | Réception d'alerte vérifiée, plafonds documentés, exercice complet mesuré |
| En continu | Réduire le couplage et découper les changements structurants | Baseline en baisse, commits indépendamment validables |
| En continu | Utiliser le Lab pour des décisions produit mesurées | Résultats sur cas réservés, succès métier/coût/latence et revue humaine |

Je ne recommande pas une réécriture générale. Le socle est suffisamment structuré pour consolider progressivement. Le meilleur rendement vient maintenant de la validation des parcours complets, du contrôle des frontières de confiance et de la qualification de ce qui est réellement livré.

**Journal des vérifications nouvelles**

| Vérification | Résultat |
|---|---|
| Suite backend complète, copie de HEAD | 3 538 réussis, 2 échoués, 1 ignoré, 8 avertissements |
| Deux scénarios backend relancés seuls | Les deux échecs reproduits |
| Pyright strict, image builder du commit | 0 erreur, 0 avertissement, 0 information |
| Contrats d'architecture, script sur copie de HEAD | Conformes |
| Cartographie générée, mode vérification | Deux JSON périmés ; une entrée de fichier à déplacer dans chaque langue |
| Sonde SlowAPI/FastAPI, image exacte et réseau désactivé | Contournement de la limite par défaut via APIRouter reproduit ; limite explicite opérante |
| Lint backend, Ruff | Conforme |
| Build frontend de production, typage Vue/TypeScript et lint inclus | Réussi ; avertissement sur la taille de plusieurs fragments JavaScript |
| Tests unitaires frontend | 214 réussis |
| Catalogues de traduction frontend | 5 035 paires anglais/français et 5 035 messages chinois contrôlés |
| Composants réels Chromium | 183 réussis, 5 échoués, sans retry, en 9 minutes ; échecs d'upload détaillés en A4 |
| Vérification finale du diff | Aucune erreur d'espacement ; seul ce rapport est ajouté par l'audit |

Les premières tentatives ont aussi rencontré des problèmes d'environnement de qualification : secret de navigateur vide dans `.env.example`, droits du répertoire temporaire de résultats créé par Docker, moteur Node de Pyright absent du conteneur sans réseau. Ils ont été résolus dans les temporaires avant les résultats ci-dessus ; ils ne sont pas comptés comme défauts applicatifs.

Les E2E complets avec backend, les essais de restauration/upgrade, la charge volumique optionnelle, les mutations et les scans de sécurité n'ont pas été relancés lors de ce bilan. Les scénarios Chromium ci-dessus montent les vrais composants avec des frontières HTTP simulées ; ils ne remplacent pas les E2E d'assemblage ni une validation Firefox/WebKit. `make architecture-check` pris dans son ensemble ne serait pas vert à HEAD, puisque sa dépendance de vérification de cartographie échoue, même si le contrôleur de frontières et les tests d'architecture inclus dans la suite backend passent.

Journaux locaux : `/tmp/galaris-audit-backend.log`, `/tmp/galaris-audit-recheck.log`, `/tmp/galaris-audit-pyright.log`, `/tmp/galaris-audit-map.log`, `/tmp/galaris-audit-architecture.log`, `/tmp/galaris-audit-components.log`, `/tmp/galaris-audit-front-build.log`. Les traces de composants se trouvent dans le répertoire `artifacts/front-components/` de la copie temporaire. Ces fichiers locaux ne constituent pas une archive de release durable.
