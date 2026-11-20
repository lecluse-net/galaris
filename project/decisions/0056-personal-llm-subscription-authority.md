# 0056 — Autorité utilisateur des abonnements LLM personnels

- Statut : Accepted
- Date : 2026-08-28

## Contexte

Le fournisseur `openai-codex` connecte un abonnement ChatGPT personnel par OAuth. Une Task ou un
appel LLM peut toutefois provenir d’un utilisateur Galaris, d’un participant Messenger, d’un
enfant agentique ou d’un worker différé comme Dream, Goal, Lab ou Process. Le seul compte qui
administre la connexion n’est donc pas une preuve suffisante de l’auteur réel du travail.

## Décision

Une connexion ChatGPT désigne obligatoirement son titulaire par `llm_providers.user_id`. Avant
tout transport d’inférence, `app.llm` résout l’autorité depuis les preuves durables du travail :
requester figé du Message, round, Task et sa lignée, ProcessRun, exécution Lab, ou contexte
Galaris authentifié. Le requester effectivement retenu est conservé dans la trace `LLMCall`.

L’identité Galaris d’un message conversationnel est figée à son ingestion. Modifier ensuite
l’association Messenger dans « Mon profil » n’autorise pas rétroactivement l’historique. Une
origine Messenger sans attribution explicite est toujours refusée, même si l’instance ne compte
qu’un utilisateur. La relève Mail et les tâches de sa lignée excluent l’abonnement personnel, à
partir du message canonique. L’adresse de l’en-tête identifie le contact observé. Pour une inférence
prévue sur l’abonnement, Galaris emploie le modèle correspondant dans le profil secondaire configuré
et expose la décision dans le suivi de la tâche. L’usage d’un abonnement dans une application tierce
relève des [conditions Sign in with ChatGPT](https://openai.com/policies/sign-in-with-chatgpt-terms/).
Un Goal fige de la même manière l’utilisateur lié à son référent Messenger lorsqu’il est créé ou
lorsque ce référent est remplacé, puis transmet cette autorité à chacun de ses cycles. Pour un
Goal antérieur à cette colonne, la première exécution suivant la mise à niveau fige une seule fois
l’association canonique alors en vigueur.

Quand exactement un utilisateur Galaris actif existe et qu’il est le titulaire configuré, un
travail interne ou autonome sans auteur explicite peut lui être attribué. Ce repli ne s’applique
jamais à Messenger. Dès qu’au moins deux utilisateurs sont actifs, toute utilisation de
l’abonnement exige une attribution durable explicite et concordante.

Les fournisseurs facturés par API ne sont pas concernés par cette politique. Les agents partagés
ou accessibles à des tiers doivent utiliser un fournisseur OpenAI API.

## Conséquences

- Tasks, Codex, autres harnais, Dream, Goal, Lab et Process traversent la même garde centrale.
- Les enfants de Task héritent du requester de leur lignée et les workers restaurent l’autorité
  depuis leurs enregistrements durables après un redémarrage.
- Le formulaire ChatGPT affiche le titulaire, le mode mono/multi-utilisateur et un avertissement
  explicite avant la connexion OAuth.
- Une attribution absente ou contradictoire échoue avant tout appel réseau au fournisseur.
