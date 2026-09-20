# 0018 — Durcissement des comptes et observabilité centralisée

- Statut : Accepted
- Date : 2026-07-30

## Contexte

Une limitation globale par adresse IP ne protège pas un compte contre les essais distribués et
devient contournable si un proxy relaie un en-tête client non assaini. Le mot de passe seul ne
permet pas non plus à un administrateur auto-hébergé de réduire l’impact d’une fuite
d’identifiants. Enfin, des journaux uniquement locaux et des exceptions absorbées silencieusement
rendent les incidents difficiles à relier entre HTTP, base de données et exécution agentique.

## Décision

La politique de compte impose 12 caractères et persiste les échecs d’authentification. Après un
seuil configurable, le verrouillage est exponentiel et borné. La vérification et la mise à jour
s’effectuent sous verrou SQL ; le chemin d’un compte inconnu exécute aussi une vérification bcrypt.

Chaque utilisateur peut activer un TOTP. Le secret est chiffré par la clé maîtresse Galaris, le
dernier compteur accepté empêche le rejeu et les codes de secours sont stockés sous forme de
condensats à usage unique. La configuration et la désactivation exigent une session authentifiée.
Le proxy frontal remplace `X-Forwarded-For` par l’adresse observée avant de l’envoyer au backend.

Logfire est la couche de corrélation centrale. Elle reçoit, lorsqu’un jeton est configuré, les
traces FastAPI, HTTPX, SQLAlchemy et Pydantic AI, les métriques système et les logs Loguru. Les
corps, en-têtes et contenus IA ne sont pas capturés. Les tests ne produisent aucune télémétrie
externe. Une exception large ne peut plus être absorbée silencieusement dans le code de
production : les replis attendus sont bornés à des exceptions précises ou journalisés.

## Conséquences

- Atlas ajoute les colonnes de verrouillage et MFA avec des valeurs par défaut serveur sûres pour
  les comptes existants.
- Les codes de secours doivent être conservés par l’utilisateur lors de leur unique affichage.
- Une installation sans `LOGFIRE_TOKEN` continue de fonctionner sans service externe.
- Les données d’observabilité restent des métadonnées techniques ; les contenus privés exigeraient
  une décision distincte et un consentement explicite.
