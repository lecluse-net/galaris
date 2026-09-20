# Preuves de la revue après commit

État source : `b8a8b8df` (7 septembre 2026). Voir le
[rapport](../2026-09-07-postcommit-quality-review.md).

Ces sondes **reproduisent des défauts**. Leurs assertions constatent le comportement actuel ;
elles ne définissent pas le comportement à conserver. Elles restent hors des suites produit.
Aucun fournisseur réel, compte externe ou secret applicatif n'est utilisé par ces sondes.

- `backend_probes.py` : **8 cas reproduits**, PostgreSQL éphémère, fichiers temporaires,
  transactions indépendantes pour le Lab et fournisseur multimédia simulé. La sonde de budget
  reprend les réservations réelles mais réduit seulement le délai d'attente à 20 ms.
  La sonde du superviseur injecte un démarrage qui attend indéfiniment ; elle ne prétend pas
  qu'un composant réel était bloqué lors de l'audit. La sonde Atlas utilise un mot de passe
  inventé et vérifie qu'il reste décodable, sans l'écrire dans les journaux.
- `frontend_probes.mjs` : **2 cas reproduits** sur les vrais modules TypeScript, Pinia et Vue,
  avec transports simulés : sélection Process remplacée et abonnement WebSocket différé.
- `inventory.py` / `inventory.json` : inventaire statique de tous les fichiers `.py`, `.ts`,
  `.vue`, `.mjs`, `.sh` sous les sept racines de code et tests. Les nombres de lignes incluent
  commentaires et traductions ; ils ne mesurent ni complexité ni couverture. Dépendances,
  caches et cartes générées sont exclus. L'inventaire a précédé l'ajout temporaire des sondes.

## Rejouer

Backend, depuis la racine du dépôt, sans écraser un fichier existant :

```bash
(
  probe=back/tests/_audit_postcommit_probes.py
  test ! -e "$probe" || exit 2
  trap 'rm -f "$probe"' EXIT
  cp project/audits/2026-09-07-postcommit-evidence/backend_probes.py "$probe"
  make tests ARGS='tests/_audit_postcommit_probes.py -q'
)
```

Frontend, dans le conteneur installé de cet environnement ; aucune requête HTTP réelle :

```bash
docker exec -i -w /app galaris-front node --input-type=module \
  < project/audits/2026-09-07-postcommit-evidence/frontend_probes.mjs
```

Les journaux temporaires sont `/tmp/galaris-postcommit-audit-tests.log`,
`/tmp/galaris-postcommit-audit-quality.log`, `/tmp/galaris-postcommit-sidecars.log`,
`/tmp/galaris-postcommit-e2e.log`, `/tmp/galaris-postcommit-probes-final.log` et
`/tmp/galaris-postcommit-frontend.log`. Le rapport conserve les résultats ; ces chemins
temporaires ne sont pas une archive de release.
