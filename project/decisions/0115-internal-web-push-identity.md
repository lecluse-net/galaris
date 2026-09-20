# 0115 — Identité Web Push interne et réglages du Chat

Statut : Accepted

## Décision

Cette décision remplace l’exclusion de Web Push dans la décision 0113. Les quatre
variables `WEB_PUSH_*` quittent le `.env`. `ENCRYPTION_MASTER_KEY` et les `WEBRTC_*`
gardent strictement leurs valeurs, leur stockage et leur mécanisme de lecture.

DbAdmin génère une paire VAPID dans un unique paramètre interne chiffré
`WEB_PUSH_VAPID_KEYS` lorsque ce paramètre est absent, sans reprise du `.env`.
La paire reste stable aux synchronisations et aux redémarrages. Une valeur persistée
vide ou corrompue bloque le démarrage, sans rotation automatique.
Au premier passage depuis les anciennes variables, les appareils doivent désactiver
puis réactiver les notifications dans le Chat après rechargement de l’application.

La clé privée n’apparaît ni dans les préférences ni dans leur API, même pour un admin.
L’API Chat expose uniquement la clé publique nécessaire à l’abonnement. Les processus
backend partageant la base et la clé de chiffrement chargent la même identité.

Le contact VAPID (`mailto:` ou HTTPS) et le délai d’envoi (1 à 30 secondes) deviennent
des paramètres modifiables dans les préférences du Chat. Les valeurs initiales sont
`mailto:admin@localhost` et 3 secondes ; le `.env` n’est pas lu. Les changements s’appliquent
sans redémarrage ; un délai modifié concerne les nouvelles notifications en attente.

Le nettoyage du `.env` vérifie d’abord la validité de la paire persistée.
Les sauvegardes comprennent la base et la clé de chiffrement,
toujours conservée dans le `.env` ; aucune nouvelle clé opérateur n’est nécessaire.

## Validation

Les tests vérifient l’initialisation unique indépendante du `.env`, le chiffrement,
la conservation des abonnements, l’envoi avec la même clé, les refus d’accès aux clés
internes et la validation/persistance des réglages. Le nettoyage refuse de supprimer
les variables si la vérification échoue et préserve tous les autres octets du `.env`.
