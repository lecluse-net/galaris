import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { basename, dirname, resolve } from 'node:path'
import { build } from 'esbuild'
import { compileScript, compileStyle, parse } from 'vue/compiler-sfc'
import * as vue from 'vue'

const source = import.meta.dirname
const output = process.argv[2]
if (!output) throw new Error('Usage: node build.mjs OUTPUT_DIRECTORY')

const manifest = JSON.parse(await readFile(resolve(source, 'bundle.json'), 'utf8'))
const { code } = manifest
const styles = new Map()
const hostImports = {
  vue: `export const { ${Object.keys(vue).filter(name => /^[A-Za-z_$][\w$]*$/.test(name)).join(', ')} } = host.vue`,
  'vue-i18n': 'export const { useI18n } = host',
  quasar: 'export const { QBanner, QBtn, QBtnToggle, QSpace, QSpinner } = host.quasar',
  '@/core/util/facade': 'export const { saveBlobAsResource, solaire } = host',
  '@/app/document': 'export const { DocumentToolbar } = host',
}
const result = await build({
  stdin: {
    contents: `import editor from './DrawingEditor.vue'; import preview from './DrawingPreview.vue';
      import { snapshot } from './snapshot.ts'; export const drawing = { editor, preview, snapshot };`,
    resolveDir: source,
  },
  platform: 'browser', bundle: true, format: 'iife', globalName: 'DrawingBundle', write: false,
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  plugins: [{
    name: 'sample-drawing-components',
    setup(builder) {
      builder.onResolve({ filter: /^(vue|vue-i18n|quasar|@\/core\/util\/facade|@\/app\/document)$/ }, args => ({ path: args.path, namespace: 'host' }))
      builder.onLoad({ filter: /.*/, namespace: 'host' }, args => ({ contents: hostImports[args.path] }))
      builder.onLoad({ filter: /\.vue$/ }, async args => {
        const raw = await readFile(args.path, 'utf8')
        const id = `data-v-${createHash('sha256').update(raw).digest('hex').slice(0, 12)}`
        const filename = basename(args.path)
        const { descriptor, errors } = parse(raw, { filename })
        if (errors.length) throw new Error(String(errors[0]))
        const recipe = compileScript(descriptor, { id, inlineTemplate: true, genDefaultAs: 'component', isProd: true })
        styles.set(filename, descriptor.styles.map(style => {
          const result = compileStyle({ filename, source: style.content, id, scoped: style.scoped })
          if (result.errors.length) throw new Error(String(result.errors[0]))
          return result.code
        }).join('\n'))
        return {
          contents: `${recipe.content}\ncomponent.__scopeId = ${JSON.stringify(id)}; export default component;`,
          loader: 'ts', resolveDir: dirname(args.path),
        }
      })
    },
  }],
})
const css = Array.from(styles.keys()).sort().map(filename => styles.get(filename)).join('\n')
const module = `export function createFormat(host) {
  if (!host.DocumentToolbar) throw new Error('Drawing requires the Galaris DocumentToolbar SDK component.');
${result.outputFiles[0].text}
  const stylesheet = document.createElement('style');
  stylesheet.textContent = ${JSON.stringify(css)};
  document.head.append(stylesheet);
  return DrawingBundle.drawing;
}\n`
const codec = await readFile(resolve(source, '__init__.py'), 'utf8')
await mkdir(resolve(output, 'backend'), { recursive: true })
await mkdir(resolve(output, 'frontend'), { recursive: true })
await writeFile(resolve(output, 'manifest.json'), JSON.stringify(manifest))
await writeFile(resolve(output, `backend/${code}.py`), `${codec}
from app.plugin.contracts import PluginRuntimeContext

def plugin_format(_context: PluginRuntimeContext) -> DocumentFormatDefinition:
    from dataclasses import replace
    return replace(definition(), code="${code}", provider="${code}")
`)
await writeFile(resolve(output, `frontend/${code}.mjs`), module)
