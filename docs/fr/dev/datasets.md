<p align="right"><strong>Français</strong> · <a href="../../en/dev/datasets.md">English</a></p>

# Jeux de données et contrats de données

`app.dataset` possède le codec commun, les jeux de données et leurs opérations JSON.
La façade publique est `app.dataset.facade` ; les imports
`app.process.values` exposent le codec avec les restrictions de compatibilité de Process.

Le codec de variables représente chaque valeur avec son type :

```json
{
  "approved": {"type": "bool", "value": false},
  "report": {"type": "File", "value": "file://00000000-0000-4000-8000-000000000001"},
  "note": {"type": "string", "value": null}
}
```

Les types sont `int`, `float`, `string`, `bool`, `Agent`, `User`, `File`, `Document`,
`Dataset`, `array` et `object`. Les conteneurs imbriquent des valeurs typées.
Les entiers sont exacts et transportables en JavaScript ; les nombres non finis,
les clés JSON dupliquées et les charges dépassant les limites sont refusés.
Le typage vérifie la forme d'une référence ; sa résolution vérifie séparément les droits.

Les jeux de données acceptent toutes les racines JSON, sans schéma associé. Leur contenu
et celui des révisions sont conservés exactement. Le codec typé reste disponible pour les
variables des processus ; leur définition et leur validation appartiennent à Process.
Les applications documentaires utilisent le pont Dataset avec les droits du lecteur et
son consentement personnel. Les écritures libres et les restaurations vérifient le JSON,
les droits et la révision, sans imposer de structure métier.
Les écritures utilisent `expected_revision` ; le partage utilise `expected_lock_version`.
Le provider `data://` enregistré dans File Sharing utilise les mêmes services.

La migration DbAdmin `app.dataset.legacy_documents` conserve les sources et crée
des alias vérifiés. Les anciens accès Memory délèguent au nouveau domaine.
Le pont HTML conserve le consentement personnel par révision documentaire et le
budget SQL partagé de 30 écritures / 4 Mo par minute et par utilisateur/jeu de données.

Le partage reprend `DocumentSharingLevelUpdate` et le même catalogue de destinataires que
Memory. `PUT /datasets/{id}/sharing-level` remplace atomiquement le niveau et les grants,
sous verrou et `expected_lock_version`, sans réécrire le JSON ni ses révisions. Le composant
frontend commun `SharingPanel` gère lecture/écriture et héritage des groupes. Un éditeur
ne devient pas propriétaire ; les ressources en lecture seule ne peuvent pas être repartagées.

`GET /datasets/{id}/usages` pagine les catégories `documents`, `processes` et `agents`.
Le point de composition enregistre les fournisseurs publics de Memory, Process et LLM ;
Dataset n'importe pas leurs modèles. Les requêtes portent sur les contenus documentaires
natifs courants, les références de runs et snapshots, et les traces d'outils conservées.
Les permissions du module source et ses ACL s'appliquent avant comptage et pagination.
Ce relevé décrit des références observées et ne constitue pas un graphe exhaustif de dépendances.
La suppression reste logique, sous verrou et version attendue ; le moteur conserve la
propriété du cycle de vie de ses datasets.

## Projection historique et conditions de retrait

Dataset est l'unique autorité de contenu, historique et droits. Une création native
`data://` ne crée pas de Document Memory. Seul un alias de migration vérifié reçoit
une projection `DatasetDocumentProjection`, définie dans `app.memory.contracts` :
métadonnées, version, empreinte et grants, sans contenu ni historique. La suppression
retire la projection des lecteurs courants, en conservant les sources et l'alias comme
preuves de migration. La lecture de cet état passe par une requête async explicite.

Les anciens appels Memory restent des adaptateurs vers Dataset pour les éditeurs,
applications HTML, pièces jointes et Process encore raccordés. Les nouveaux consommateurs
utilisent `app.dataset.facade` ou File Sharing avec `data://`.

Le retrait de la projection exige que ces consommateurs aient migré, que les clés étrangères
Process ne ciblent plus le Document historique, et que les parcours de contenu, révisions,
partage/révocation, PJ, consentements et budgets passent sur les URI canoniques. Les alias
vérifiés restent un contrat de lecture des anciennes références, indépendant de la projection.
Leur conservation et celle des preuves ne doivent pas être confondues avec le maintien d'un
second chemin d'écriture. Aucun retrait de ligne source n'est prévu par cette consolidation.
