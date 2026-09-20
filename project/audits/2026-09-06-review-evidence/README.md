# Preuves du contre-audit du 6 septembre 2026

Source : `3062cf45f56f0dd97b49e42e0e5ef59c2b7d1d92`.

Ces sondes **constatent des défauts** : leurs assertions passent lorsque le comportement audité
est présent. Après correction, elles doivent être remplacées par des tests de non-régression
exigeant le comportement souhaité. Elles restent hors des suites automatiques du produit.

## Résultats conservés

- `backend_probes.py` : six contre-exemples exécutés via `make tests`, avec la configuration
  PostgreSQL éphémère et les fixtures réelles du dépôt. Résultat : six succès de reproduction.
- `frontend_probe.mjs` : trois séquences sur les véritables modules TypeScript, Vue et Pinia,
  avec transports HTTP et plateforme simulés. Aucun appel à l’API réelle.
- `manager_probe.py` : répertoire temporaire canari ; substitution d’un parent après construction
  de la réponse. Lecture hors instance et longueur de réponse incohérente reproduites.
- `browser_probe.mjs` : démarre un serveur navigateur séparé, tue uniquement son enfant Chromium,
  constate que Node reste vivant sans listener HTTP, puis détruit les processus de la sonde.
- `typescript-diagnostics.txt` : contrôle explicite du code réel, après suppression de la sonde
  négative ; **180 diagnostics dans 44 fichiers**, code de sortie 2.
- `typescript-negative-control.txt` : sortie réussie de `npm run type-check` malgré une erreur
  volontaire dans `front/app/_audit_typecheck_probe.ts` pendant ce contrôle. Ce fichier temporaire
  a été supprimé. Son contenu était :

  ```ts
  export const __galarisAuditTypeProbe: number = 'audit-intentional-type-error'
  ```

- `inventory.py` et `inventory.json` : inventaire par domaine et plus grandes unités. Lignes
  physiques, commentaires/traductions inclus ; dépendances et répertoires générés exclus.

## Rejouer sans utiliser les données de développement

Depuis la racine du dépôt, les sondes backend ont besoin du `conftest.py` backend. Copier
temporairement la sonde sous `back/tests`, en refusant d’écraser un fichier existant :

```bash
(
  probe=back/tests/_audit_review_probes.py
  test ! -e "$probe" || exit 2
  trap 'rm -f "$probe"' EXIT
  cp project/audits/2026-09-06-review-evidence/backend_probes.py "$probe"
  make tests ARGS='tests/_audit_review_probes.py -s -q'
)
```

Le frontend nécessite les dépendances du projet. Dans le conteneur frontend déjà installé,
exécuter la sonde via stdin : les imports relatifs sont résolus depuis `/app`.

```bash
docker exec -i -w /app galaris-front node --input-type=module \
  < project/audits/2026-09-06-review-evidence/frontend_probe.mjs
docker exec -w /app galaris-front npm exec vue-tsc -- --noEmit -p tsconfig.app.json
```

La sonde de fichiers s’exécute dans un nouveau conteneur sans réseau, avec le dépôt en lecture
seule. Elle utilise les dépendances de l’image backend locale ; aucun entrypoint applicatif
n’est lancé et le répertoire manipulé est temporaire dans ce conteneur.

```bash
docker run --rm --network none --entrypoint python -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/repo:ro" galaris-backend \
  /repo/project/audits/2026-09-06-review-evidence/manager_probe.py
```

La panne Chromium doit exclusivement être exécutée dans son conteneur jetable :

```bash
docker run --rm --init --network none --entrypoint node \
  -v "$PWD/browser-executor:/opt/galaris-browser/source:ro" \
  -v "$PWD/project/audits/2026-09-06-review-evidence/browser_probe.mjs:/opt/galaris-browser/probe.mjs:ro" \
  galaris-browser-executor /opt/galaris-browser/probe.mjs
```

Les noms d’images et du conteneur frontend ci-dessus sont ceux de l’environnement audité.
Les logs complets des suites restent sous `/tmp/galaris-new-audit-*.log` pendant cette session.
Le rapport principal conserve leurs résultats et limites ; ces logs temporaires ne sont pas une
preuve durable d’une exécution ultérieure ou d’une autre révision.
