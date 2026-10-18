import { build } from 'esbuild'
import type { Plugin } from 'vite'

/** Bundle pinned, local libraries into the opaque runtime; documents need no CDN. */
export function documentRuntimeLibraries(): Plugin {
  const id = '\0galaris:document-three'
  let bundled: Promise<string> | undefined
  return {
    name: 'galaris-document-libraries',
    resolveId: source => source === 'virtual:galaris-document-three' ? id : undefined,
    async load(source) {
      if (source !== id) return
      bundled ??= build({ stdin: { contents: "export * from 'three'; export { OrbitControls } from 'three/addons/controls/OrbitControls.js'; export { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';", resolveDir: process.cwd(), loader: 'js' }, bundle: true, write: false, format: 'iife', globalName: 'THREE', minify: true }).then(result => result.outputFiles[0]!.text)
      return 'export default ' + JSON.stringify(await bundled)
    },
  }
}
