import { writeFileSync, mkdirSync } from 'node:fs'
import { solaire } from '../core/util/solaire.ts'
import { folderSvgContent } from '../core/util/folderArtwork.ts'

const root = new URL('../public/folder-icons/solaire/', import.meta.url)
for (const [name, palette] of Object.entries({ default: undefined, ...solaire })) {
  mkdirSync(new URL(name + '/', root), { recursive: true })
  for (const size of [16, 24, 32, 64]) {
    for (const state of ['folder', 'folder-open']) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <!-- Adapted from Modern-Office-Day-Icons, DrMcC0y, GPL-3.0. -->
  ${folderSvgContent(palette, state === 'folder-open', `folder-${name}-${size}`, size)}
</svg>
`
      const suffix = size === 24 ? '' : `-${size}`
      writeFileSync(new URL(`${name}/${state}${suffix}.svg`, root), svg)
    }
  }
}
