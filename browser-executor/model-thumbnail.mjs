import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { BrowserRequestError } from './lib.mjs';

export const MODEL_MAX_BYTES = 32_000_000;
const origin = 'https://model-preview.invalid';
const formats = {
  'model/gltf-binary': 'glb', 'model/gltf+json': 'gltf', 'model/obj': 'obj',
  'application/x-wavefront-obj': 'obj', 'model/stl': 'stl', 'application/sla': 'stl',
  'model/x.stl': 'stl', 'application/x-stl': 'stl', 'model/ply': 'ply',
  'application/ply': 'ply', 'application/x-ply': 'ply',
};

/** Only library modules are served locally; model dependencies never reach a network. */
export async function renderModelThumbnail(browser, { name, media_type: mime, data }) {
  const format = formats[mime] ?? /\.(glb|gltf|obj|stl|ply)$/i.exec(String(name))?.[1]?.toLowerCase();
  if (!format || typeof data !== 'string' || data.length > Math.ceil(MODEL_MAX_BYTES / 3) * 4
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(data)) {
    throw new BrowserRequestError('invalid_model', 'Invalid or oversized model.', 413);
  }
  const bytes = Buffer.from(data, 'base64');
  if (!bytes.length || bytes.length > MODEL_MAX_BYTES) throw new BrowserRequestError('invalid_model', 'Invalid model.', 413);
  const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false, viewport: { width: 320, height: 220 }, deviceScaleFactor: 1 });
  const deadline = setTimeout(() => { void context.close().catch(() => {}); }, 30_000);
  try {
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const allowed = url.origin === origin && /^\/(?:build|examples\/jsm)\/[\w/.-]+\.js$/.test(url.pathname)
        && !url.pathname.split('/').includes('..');
      if (!allowed) return route.abort('blockedbyclient');
      try {
        const path = fileURLToPath(new URL(`..${url.pathname}`, import.meta.resolve('three')));
        await route.fulfill({ contentType: 'text/javascript', body: await readFile(path), headers: { 'Access-Control-Allow-Origin': '*' } });
      } catch { await route.abort('blockedbyclient'); }
    });
    const page = await context.newPage();
    await page.setContent(`<html><head><script type="importmap">{"imports":{"three":"${origin}/build/three.module.js"}}</script></head><body style="margin:0"><canvas></canvas></body></html>`);
    // The only executed code is our renderer. Source bytes are passed as data.
    await page.evaluate(async ({ format, data, origin, maxBytes }) => {
      const THREE = await import(`${origin}/build/three.module.js`);
      const bytes = Uint8Array.from(atob(data), character => character.charCodeAt(0));
      const text = () => new TextDecoder().decode(bytes);
      let root;
      if (format === 'glb' || format === 'gltf') {
        const view = new DataView(bytes.buffer);
        let document;
        if (format === 'glb') {
          if (bytes.length < 20 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2
            || view.getUint32(8, true) !== bytes.length || view.getUint32(16, true) !== 0x4e4f534a
            || view.getUint32(12, true) > bytes.length - 20) throw new Error('Invalid GLB');
          document = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + view.getUint32(12, true))));
        } else document = JSON.parse(text());
        for (const key of ['buffers', 'images']) {
          if (document[key] !== undefined && !Array.isArray(document[key])) throw new Error('Invalid dependencies');
          let total = 0;
          for (const entry of document[key] ?? []) {
            if (!entry || typeof entry !== 'object') throw new Error('Invalid dependency');
            if (entry.uri !== undefined && (typeof entry.uri !== 'string'
              || !/^data:(?:application\/octet-stream|application\/gltf-buffer|image\/(?:png|jpeg|webp));base64,/i.test(entry.uri))) throw new Error('External dependencies');
            if (entry.byteLength !== undefined) {
              if (!Number.isSafeInteger(entry.byteLength) || entry.byteLength < 0) throw new Error('Invalid buffer');
              total += entry.byteLength;
            }
          }
          if (total > maxBytes) throw new Error('Oversized buffers');
        }
        if ((document.extensionsRequired ?? []).some(extension => ['KHR_draco_mesh_compression', 'KHR_texture_basisu'].includes(extension))) throw new Error('Unsupported compression');
        const { GLTFLoader } = await import(`${origin}/examples/jsm/loaders/GLTFLoader.js`);
        const { MeshoptDecoder } = await import(`${origin}/examples/jsm/libs/meshopt_decoder.module.js`);
        const loader = new GLTFLoader();
        loader.setMeshoptDecoder(MeshoptDecoder);
        loader.manager.setURLModifier(url => {
          if (!url.startsWith('data:') && !url.startsWith('blob:')) throw new Error('External dependencies');
          return url;
        });
        root = (await loader.parseAsync(bytes.buffer, '')).scene;
      } else if (format === 'obj') {
        const { OBJLoader } = await import(`${origin}/examples/jsm/loaders/OBJLoader.js`);
        root = new OBJLoader().parse(text());
      } else {
        const { [format === 'stl' ? 'STLLoader' : 'PLYLoader']: Loader } = await import(`${origin}/examples/jsm/loaders/${format === 'stl' ? 'STLLoader' : 'PLYLoader'}.js`);
        const geometry = new Loader().parse(bytes.buffer);
        root = format === 'ply' && !geometry.index
          ? new THREE.Points(geometry, new THREE.PointsMaterial({ color: 0x808080, size: 0.015 }))
          : new THREE.Mesh(geometry);
      }
      let vertices = 0;
      root.traverse(object => {
        if (!object.geometry) return;
        const position = object.geometry.getAttribute('position');
        if (!position) throw new Error('Invalid geometry');
        vertices += position.count;
        if (vertices > 2_000_000) throw new Error('Oversized geometry');
        for (const value of position.array) if (!Number.isFinite(value)) throw new Error('Invalid vertex');
        if (format !== 'glb' && format !== 'gltf' && object.isMesh) {
          if (!object.geometry.hasAttribute('normal')) object.geometry.computeVertexNormals();
          const vertexColors = object.geometry.hasAttribute('color');
          object.material = new THREE.MeshStandardMaterial({ color: vertexColors ? 0xffffff : 0x808080, vertexColors, side: THREE.DoubleSide, roughness: 0.65 });
        }
      });
      if (!vertices) throw new Error('Empty geometry');
      const box = new THREE.Box3().setFromObject(root), size = box.getSize(new THREE.Vector3());
      const extent = Math.max(size.x, size.y, size.z);
      if (!Number.isFinite(extent) || extent <= 0) throw new Error('Invalid bounds');
      const model = new THREE.Group(); model.add(root);
      model.scale.setScalar(2 / extent);
      model.position.copy(box.getCenter(new THREE.Vector3())).multiplyScalar(-2 / extent);
      const renderer = new THREE.WebGLRenderer({ canvas: document.querySelector('canvas'), antialias: true });
      renderer.setSize(320, 220, false);
      const scene = new THREE.Scene(); scene.background = new THREE.Color(0xf5f5f5);
      const light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(3, 5, 4);
      scene.add(model, new THREE.HemisphereLight(0xffffff, 0x808080, 3), light);
      const camera = new THREE.PerspectiveCamera(40, 320 / 220, 0.01, 100);
      camera.position.set(1, 0.7, 1).normalize().multiplyScalar(1.8 / Math.sin(Math.PI / 9));
      camera.lookAt(0, 0, 0); renderer.render(scene, camera);
    }, { format, data, origin, maxBytes: MODEL_MAX_BYTES });
    return await page.locator('canvas').screenshot({ type: 'png', timeout: 5_000 });
  } finally {
    clearTimeout(deadline);
    await context.close();
  }
}
