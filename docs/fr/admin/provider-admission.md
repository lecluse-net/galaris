<p align="right"><strong>Français</strong> · <a href="../../en/admin/provider-admission.md">English</a></p>

# Réguler les appels aux fournisseurs IA

Dans **Configurer → Fournisseurs & modèles → Fournisseurs**, ouvrez la configuration
d'un fournisseur et réglez **Appels simultanés maximum**. Cette limite est commune à
tous ses modèles, profils, agents et utilisateurs. Elle porte sur les appels physiques
tracés par Galaris, pas sur le nombre de tâches ou de conversations ouvertes.

## Choisir une limite

| Valeur | Effet |
|---|---|
| `0` | Aucun plafond de concurrence imposé par Galaris ; les limites du fournisseur restent applicables. |
| `1` | Un seul appel physique à la fois pour cette connexion. |
| `N` positif | Au plus N appels simultanés, avec une capacité protégée pour les conversations. |

Le défaut est **10** pour une connexion du catalogue hors Ollama et **1** pour
une connexion personnalisée ou Ollama. Une valeur enregistrée, y compris zéro, reste conservée
lors des modifications et mises à jour. Le champ accepte uniquement un entier positif
ou nul. Une connexion distincte possède sa propre limite ; deux configurations du même
compte distant ne partagent donc pas un plafond Galaris.

Enregistrez et rouvrez la configuration pour vérifier la valeur. Les règles habituelles
d'enregistrement automatique des fournisseurs continuent de s'appliquer ; voir le
[parcours de configuration](../user/navigation.md).

## Comprendre l'attente et les priorités

Quand la limite est atteinte, les demandes attendent avant leur départ vers le fournisseur.
Les conversations vocales sont prioritaires, puis les conversations textuelles, puis les
autres travaux. Le vieillissement des attentes et la rotation entre contextes limitent
la monopolisation de la file. Une priorité ne préempte pas un appel déjà engagé.

À partir de trois places, une place voix et une place texte sont protégées. Avec deux
places, les travaux de fond utilisent au plus une place. Avec une seule place, le
prochain départ suit l'ordre d'admission ; un appel lent peut toujours retarder une
conversation. Augmenter la limite ne garantit pas un meilleur débit si le fournisseur
ou la machine sont déjà saturés.

Un appel en streaming conserve sa place jusqu'à sa finalisation. L'attente d'un outil,
d'une réponse humaine ou du prochain tour ne réserve pas toute la capacité du fournisseur.
Une baisse de limite laisse finir les appels en cours ; une hausse ou zéro peut libérer
les demandes en attente. Les autres fournisseurs continuent de travailler indépendamment.

## Suivre, interrompre et reprendre

Consultez **Superviser → Activité → Activité LLM** et le détail de l'inférence pour
distinguer l'attente du temps d'exécution. L'attente seule n'utilise pas de tokens modèle.
Le délai physique commence au départ de l'appel ; une échéance globale explicite de
l'inférence inclut aussi file, pauses et reprises.

Les commandes de pause et d'arrêt retirent les admissions qui ne doivent plus partir.
Une reprise reste soumise aux droits, à l'activation du fournisseur et à la politique
de l'inférence durable. Pour un effet déjà engagé, l'absence de réponse ne prouve pas
son annulation distante et n'autorise pas un rejeu automatique.

Le **profil secondaire** d'un agent répond à une autre situation : il fournit un secours
lorsque le fournisseur principal échoue selon les conditions prévues. Il ne sert pas à
contourner une simple attente de capacité. Configurez les mêmes usages dans les deux
profils ; voir le [guide utilisateur](../user/README.md).

## Périmètre et vérifications

Le coordinateur actuel appartient à `app.llm.provider_scheduler` et suppose le backend
mono-worker fourni. Plusieurs backends indépendants nécessiteraient une coordination
distribuée. Les sessions audio persistantes qui ne sont pas tracées comme `LLMCall`
ne sont pas comptées comme des appels physiques Chat/Responses. La découverte des modèles,
les lectures de crédits et les authentifications ne sont pas des générations.

Les [tests du scheduler](../../../back/app/llm/tests/test_provider_scheduler.py) vérifient
concurrence, priorités, capacité protégée, annulation, changement à chaud et indépendance
des fournisseurs. Le [contrat accepté](../../../project/decisions/0181-provider-llm-admission.md)
précise les autres parcours et limites de qualification. Les
[paramètres fournisseur](../dev/provider-parameters.md) et les
[lecteurs de consommation](../dev/provider-quotas.md) restent des contrats distincts.
