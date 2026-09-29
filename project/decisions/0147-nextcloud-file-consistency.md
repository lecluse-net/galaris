# 0147 — Cohérence des fichiers Nextcloud

Statut : accepté. Date : 2026-09-29.

## Garantie et consommateurs

Les fichiers partagés entre un PC et les agents conservent leurs noms et leur contenu lors
des opérations `file_*`. Une création ne remplace jamais un fichier apparu simultanément ;
une édition ne remplace pas silencieusement une version modifiée pendant son exécution.
Les consommateurs sont la façade MCP, les copies entre providers, les outils multimédias et
les connexions combinant Nextcloud Files et Talk. Leur résolution de connexion et leurs ACL
restent inchangées. Aucun accès à une installation de production n’est nécessaire aux tests.

## Décision

Des protocoles optionnels ajoutent la pagination et les mutations conditionnelles au contrat
de transport existant. Les autres providers conservent leur comportement. Nextcloud utilise
`If-None-Match: *` pour créer et `If-Match` avec un ETag fort pour remplacer. Les agents peuvent
transmettre `expected_etag` issu de leur lecture ; une édition ou un append protège également
sa propre lecture, sans exiger ce paramètre. Une absence d’ETag bloque la mutation protégée.
Un déplacement entre providers ne supprime la source Nextcloud que si sa version est inchangée.

La pagination parcourt chaque collection par `Depth: 1`. Un curseur conserve une pile bornée
et une empreinte des entrées de chaque dossier en cours. Un changement invalide le parcours
au lieu de masquer des omissions. La recherche avance ce même parcours et expose les fichiers
ignorés en mode texte. Les limites de taille, de profondeur et de durée produisent des erreurs
explicites ; elles ne doivent pas être présentées comme un inventaire exhaustif.

Les noms décodés sont encodés au moment de produire une URI, avant de repasser par son parseur.
La suppression et le déplacement génériques des collections Nextcloud sont refusés. Le succès
d’un partage exige une enveloppe OCS valide et un lien exploitable ; une issue réseau ambiguë
n’autorise aucun rejeu automatique.

## Vérification

Les scénarios de `back/bridge/nextcloud/tests/test_file_share.py` exercent la vraie façade et
le vrai client contre un serveur HTTP synthétique, y compris les préconditions, conflits,
noms réservés, pages et échecs réseau. Les anciennes suites validaient surtout la résolution
des clients et des doubles de stockage ; elles ne simulaient pas ces comportements WebDAV.
Le catalogue des tests fonctionnels référence désormais cette frontière HTTP. Cette preuve
ne remplace pas une qualification sur la version Nextcloud et le reverse proxy déployés.
