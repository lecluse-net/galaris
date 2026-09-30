# ADR 0146 — Consommation et crédits des fournisseurs

- Statut : Accepted
- Date : 2026-09-29

## Décision

Les fournisseurs déclarent un lecteur de consommation dans le registre public `app.llm`.
Le catalogue expose `supports_quota` depuis ce registre ; l’interface compose le même
panneau pour les connexions configurées, indépendamment de leur code ou de leur mode
d’authentification. Un nouveau service se raccorde par son bridge, sans liste parallèle
dans le frontend. L’ajout d’un lecteur seul ne nécessite pas de changement de schéma SQL.

Le contrat conserve les fenêtres ChatGPT et ajoute les montants consommés, leur plafond,
le solde disponible, l’unité et la portée compte/clé API. Un pourcentage calculé depuis
des montants nécessite un plafond positif et une consommation connue ; les pourcentages
ChatGPT restent ceux du fournisseur. Une absence reste inconnue ; zéro reste
une valeur explicite. Un dépassement conserve son pourcentage et son solde négatif,
mais la barre graphique est bornée. Aucun plafond n’est reconstruit depuis le solde
actuel ou depuis les seuls appels Galaris.

Les bridges lisent les réponses externes et les traduisent vers ce contrat. Le lecteur
reçoit une connexion détachée et sa clé déchiffrée côté serveur ; la réponse HTTP ne
contient ni clé ni projection brute du compte. Les droits d’administration fournisseur
et les règles de propriété ChatGPT existantes restent appliqués. La consultation ne
réalise aucune génération et ne modifie ni le fournisseur ni ses budgets.

OpenRouter peut déclarer une clé de gestion facultative, distincte de la clé d’inférence.
Il expose uniquement le montant restant en USD : le budget encore disponible pour la clé
API ou le solde du compte obtenu par `total_credits - total_usage`. Les achats cumulés ne
constituent pas un plafond ; ni consommation totale, ni plafond, ni pourcentage ne sont
exposés pour créer une jauge. Un montant absent reste inconnu ; zéro et les soldes négatifs
restent explicites.
`LLMProvider.management_api_key` conserve uniquement la valeur chiffrée par le service
Fernet existant. Les réponses exposent `management_api_key_configured`, jamais le secret.
Une écriture sans ce champ conserve la clé ; une nouvelle valeur la remplace ; `null` la
supprime. Seuls les profils déclarant cette capacité acceptent une clé de gestion.
La connexion détachée ordinaire ne la transporte pas : seul le service de consultation
des crédits la déchiffre et la passe au lecteur. Le bridge l’utilise exclusivement pour
`/credits`, sans remplacer la clé des modèles ni retomber silencieusement sur un budget
de clé si la consultation du compte échoue. Le formulaire explique sa portée administrative
et lie la page officielle de création. Les erreurs de sauvegarde ne journalisent pas le
payload Axios contenant les identifiants.

## Fournisseurs initiaux et limites

| Fournisseur | Source et portée |
|---|---|
| ChatGPT/Codex | Fenêtres du compte connecté et solde supplémentaire `credits.balance` en crédits, sans jauge pour ce solde ; authentification et propriétaire existants |
| ElevenLabs | `/v1/user/subscription` ; crédits du compte et prochain renouvellement |
| Mammouth AI | `/key/info` ; consommation de clé et plafond lorsqu’il est fourni ; distinct des quotas de l’application |
| OpenRouter | `/api/v1/key` ; montant restant pour la clé sans clé de gestion ; `/credits` avec la clé de gestion facultative pour le solde du compte ; aucun plafond ni pourcentage |
| DeepSeek | `/user/balance` ; solde monétaire par devise sans plafond inventé |
| SunoAPI.org | `/api/v1/generate/credit` ; crédits du compte tiers, distinct de Suno officiel |
| Fireworks AI | Solde prépayé non intégré : aucune route publique identifiée ; aucun panneau de solde ou de consommation |

Correction du 2026-09-30 : l’intégration Fireworks de `monthly-spend-usd` est retirée.
Ce quota fournit une autorisation de dépenses mensuelle, pas un solde prépayé. La différence
plafond moins dépenses ne répond pas au besoin de connaître l’argent disponible. Les tests
initiaux vérifiaient le calcul sans protéger cette distinction ; un plafond synthétique
d’un million reproduit l’affichage trompeur. Le catalogue ne déclare plus de lecteur
Fireworks ; aucun panneau de solde ou de consommation ni lien dédié n’est affiché dans sa
configuration. Un ancien indicateur `supports_quota` ne réactive pas
la jauge. Une vérification en développement confirme que la route du portail de solde
refuse la clé API (401), tandis que le quota de dépenses accepte cette clé. Aucun
identifiant ou montant du compte réel n’est conservé ici.
L’[audit des fournisseurs](../../docs/fr/dev/provider-quotas.md) sépare les intégrations
présentes des possibilités documentées qui nécessitent d’autres clés ou services.

Mammouth documente la route publique mais pas son schéma dans OpenAPI. Le parseur des
champs `info.spend`, `info.max_budget` et `info.budget_reset_at` est validé avec des données
synthétiques ; aucune clé réelle n’était disponible pour confirmer ce format. Une réponse
sans ces champs demeure vide et ne devient pas une jauge à zéro.

## Vérification

Les tests communs traversent le catalogue, la connexion chiffrée et le endpoint autorisé,
en remplaçant seulement HTTP externe. Les scénarios Chromium couvrent unités, absence de
plafond, dépassement, erreur/reprise, changement de connexion et renouvellement des
identifiants. La couverture ChatGPT existante conserve les refus d’accès et le rafraîchissement
OAuth. Les réponses tardives sont abandonnées lors d’un changement de contexte.
