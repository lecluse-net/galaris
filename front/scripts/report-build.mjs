// Measure the entry's eager dependency graph separately from optional chunks.
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const directory = resolve(process.argv[2] ?? 'dist')
const manifest = JSON.parse(await readFile(resolve(directory, '.vite/manifest.json'), 'utf8'))
const visited = new Set()
const eager = new Set()
function visit(key) {
  if (visited.has(key)) return
  visited.add(key)
  const entry = manifest[key]
  eager.add(entry.file)
  for (const css of entry.css ?? []) eager.add(css)
  for (const dependency of entry.imports ?? []) visit(dependency)
}
for (const [key, entry] of Object.entries(manifest)) if (entry.isEntry) visit(key)
async function sizes(files) {
  const rows = await Promise.all([...files].map(async file => {
    const data = await readFile(resolve(directory, file))
    return { file, bytes: data.length, gzip_bytes: gzipSync(data).length }
  }))
  return {
    files: rows.length,
    bytes: rows.reduce((sum, row) => sum + row.bytes, 0),
    gzip_bytes: rows.reduce((sum, row) => sum + row.gzip_bytes, 0),
  }
}
const all = new Set(Object.values(manifest).flatMap(entry => [entry.file, ...(entry.css ?? [])]))
console.log(JSON.stringify({
  metric: 'frontend_build_bytes',
  eager: await sizes(eager), all: await sizes(all),
  note: 'Static imports and CSS; excludes dynamic imports, fonts, API traffic and PWA precache downloads. Gzip is measured per file.',
}, null, 2))
