# 0104 — Documents comme pivot de l'information rédigée

Statut : accepté — 17 septembre 2026.

La règle de conservation des désactivations de Memory et File Sharing est remplacée par
[0105 — Services système obligatoires](0105-mandatory-system-tools.md).

## Décision

Les documents Galaris sont le support canonique des rapports, articles, analyses, plans,
notes et brouillons durables requis par le résultat demandé. Leur URI stable
`document://` relie recherche, rédaction, revue, collaboration et transmission. Enrichir le
même document et y conserver les références sources plutôt que maintenir des copies Markdown
ou HTML concurrentes. Les conversations portent les échanges et les renvois au document.

Précision du 18 septembre 2026 : cette préférence de support n'impose pas de créer un document
pour chaque Task. Créer ou enrichir un document lorsque le contenu rédigé doit être conservé,
révisé ou partagé ; privilégier le document pertinent existant. Les réponses autonomes et
confirmations restent dans la conversation, l'état opérationnel dans la ressource métier.
Ne pas ajouter un document pour attester une action, ni le substituer au type de ressource
demandé lorsqu'une opération manque.

Memory et File Sharing sont connectés et actifs par défaut. Une désactivation explicite reste
préservée par la synchronisation ; le catalogue autorisé du run détermine les opérations à
annoncer. Une panne temporaire ne vaut pas désactivation. Cette priorité est une consigne de
rédaction, pas une nouvelle frontière d'autorisation des ressources.

La création utilise `file_create(path="document://", name=..., content=...)` avec un fragment
HTML éditorial UTF-8. Les modifications conservent le contrat de révision existant. Le partage
utilise `memory_sharing` puis `document_share` avec le destinataire et la version de droits
retournés. Un lien ou `document_show` n'accorde aucun accès ; un envoi externe reste distinct.

Les formats explicitement demandés, le code et les pages interactives peuvent rester des
fichiers. Les échanges courts restent conversationnels, les faits durables concis restent
des mémoires, les pièces jointes et artefacts techniques gardent leur propre contrat.
Aucune conversion des anciens fichiers, réactivation forcée ou modification d'ACL n'est induite.

## Application et vérification

Le catalogue injecté aux exécuteurs, le prompt par défaut du planificateur, le skill système
Galaris et les skills de développement portent ce principe. Les prompts personnalisés du
planificateur conservent leur priorité et doivent être alignés par leur administrateur.

`test_agent_registry.py` vérifie les consignes selon les fonctions autorisées ;
`test_mandatory_tools.py` vérifie l'activation initiale et la conservation d'une désactivation ;
`test_storage.py` vérifie que le skill système est lu depuis le package livré. Ces tests
ne garantissent pas l'obéissance de chaque modèle ; le choix effectif d'un document reste
un comportement agentique à observer.
