import { writeFileSync, mkdirSync } from 'node:fs'
import { solaire } from '../core/util/solaire.ts'
import { folderArtwork as panels } from '../core/util/folderArtwork.ts'

const root = new URL('../public/folder-icons/gnome/', import.meta.url)
for (const [name, palette] of Object.entries(solaire)) {
  mkdirSync(new URL(name + '/', root), { recursive: true })
  for (const [state, paths] of Object.entries(panels)) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <!-- Galaris folder artwork, GPL-2.0; generated from the Solaire palette. -->
  <path fill="${palette.accent}" d="${paths.back}"/>
  <path fill="${palette.dark}" opacity="0.18" d="${paths.back}"/>
  <path fill="${palette.light}" d="${paths.lip}"/>
  <path fill="${palette.accent}" d="${paths.front}"/>
  <path fill="${palette.dark}" opacity="0.14" d="${paths.edge}"/>
</svg>
`
    writeFileSync(new URL(`${name}/${state}.svg`, root), svg)
  }
}
