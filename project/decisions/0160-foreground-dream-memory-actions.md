# 0160 — Actions Dream explicites dans les nœuds mémoire

Statut : accepté. Date : 2026-10-06.

La modale d'un nœud propose les opérations Dream compatibles avec sa source :
description, analyse documentaire, miniature, findings et structure. Une demande humaine
s'exécute immédiatement avec un délai borné par le budget Dream existant, indépendamment
des réglages et pauses du scheduler opportuniste. Les modèles et limites de taille restent
ceux des traitements existants. La régénération explicite des miniatures des fichiers,
pièces jointes et documents HTML relance le rendu et remplace atomiquement le cache partagé.
Un échec conserve la miniature précédente. Les documents utilisent le snapshot imprimable
de leur révision enregistrée, avec les pièces jointes intégrées ; une révision périmée est refusée.
La vérification des souvenirs force la détection des suggestions, sans appliquer les
résolutions automatiques ni modifier les politiques persistées.

L'API exige `MEMORY_EDIT` ou `MEMORY_ADMIN`, le périmètre de gestion de l'agent et la
propriété de la ressource. Un accès en lecture ne permet pas de remplacer une description.
Memory contrôle les pièces jointes et structures ; File Share contrôle les ressources
externes derrière son port Dream. Les temporaires sont bornés et supprimés après usage.

Chaque demande écrit un reçu `manual.memory.<action>`, avec coût et résultat, sans modifier
un ancien reçu terminal ni le soumettre aux reprises du scheduler automatique. Les appels
simultanés sur un même nœud sont refusés tant que son reçu possède un lease actif. Un échec
ou une interruption laisse un reçu en erreur ; l'utilisateur peut relancer l'action.

Une régénération est explicite et historisée. Les révisions, propriétaires, sources et
octets sont revérifiés avant application ; une acquisition ou édition concurrente prévaut.
Les notes personnelles du catalogue restent prioritaires sur son résumé généré. L'interface
préserve les brouillons, bloque l'édition pendant l'action et ignore les réponses d'un
nœud fermé ou remplacé. Les tests utilisent des sources synthétiques et remplacent les
modèles externes, tout en conservant les workflows Memory et PostgreSQL réels.
