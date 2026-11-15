import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

// Keep upstream credits for bundled renderer code as well as native/runtime modules.
const lock = JSON.parse(await readFile('package-lock.json', 'utf8'))
const notices = ['Galaris desktop — third-party notices', 'License texts for installed build and runtime dependencies. Electron also ships its Chromium notices.']
for (const directory of Object.keys(lock.packages).filter(name => name.startsWith('node_modules/')).sort()) {
  let entries
  try { entries = await readdir(directory, { withFileTypes: true }) } catch (error) {
    if (error.code === 'ENOENT') continue // Optional dependencies for other platforms.
    throw error
  }
  const metadata = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'))
  notices.push(`\n${'='.repeat(72)}\n${metadata.name} ${metadata.version}\nLicense: ${metadata.license ?? 'See upstream package'}\n`)
  for (const entry of entries.filter(item => item.isFile() && /^(licen[cs]e|copying|notice)(\.|$)/i.test(item.name))) {
    notices.push(`${entry.name}\n${await readFile(path.join(directory, entry.name), 'utf8')}`)
  }
}
await mkdir('dist', { recursive: true })
await writeFile('dist/THIRD-PARTY-NOTICES.txt', `${notices.join('\n')}\n`)
