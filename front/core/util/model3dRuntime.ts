import {
  Box3, Color, DirectionalLight, DoubleSide, Group, HemisphereLight, Material,
  Line, Mesh, MeshStandardMaterial, Object3D, PerspectiveCamera, Points, PointsMaterial,
  Scene, Texture, Vector3, WebGLRenderer,
} from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js'
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import {
  MAX_MODEL_BYTES, MAX_MODEL_VERTICES, Model3dError, model3dFormat, validateGltfDocument,
} from './model3d.ts'
import type { Model3dSource } from './model3d.ts'
import { model3dNavigation } from './model3dNavigation.ts'

export interface Model3dView {
  reset: () => void
  zoom: (factor: number) => void
  resize: (width: number, height: number) => void
  snapshot: () => Promise<Blob>
  dispose: () => void
}

// glTF scenes may share geometry and textures. Own all loaded scenes until the preview closes.
const additionalScenes = new WeakMap<Object3D, Object3D[]>()

export function disposeModel(root: Object3D): void {
  const materials = new Set<Material>()
  const textures = new Set<Texture>()
  const visited = new Set<Object3D>()
  const collect = (current: Object3D): void => current.traverse(object => {
    if (visited.has(object)) return
    visited.add(object)
    for (const scene of additionalScenes.get(object) ?? []) collect(scene)
    additionalScenes.delete(object)
    if (object instanceof Mesh || object instanceof Points || object instanceof Line) {
      object.geometry.dispose()
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        materials.add(material)
      }
    }
  })
  collect(root)
  for (const material of materials) {
    for (const value of Object.values(material)) if (value instanceof Texture) textures.add(value)
    material.dispose()
  }
  for (const texture of textures) {
    const image: unknown = texture.source.data
    if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap) image.close()
    texture.dispose()
  }
}

function gltfDocument(data: ArrayBuffer): unknown {
  const bytes = new Uint8Array(data)
  const view = new DataView(data)
  if (bytes.length >= 4 && view.getUint32(0, true) === 0x46546c67) {
    if (bytes.length < 20 || view.getUint32(4, true) !== 2 || view.getUint32(8, true) !== bytes.length
      || view.getUint32(16, true) !== 0x4e4f534a) throw new Model3dError('invalid')
    const length = view.getUint32(12, true)
    if (length > bytes.length - 20) throw new Model3dError('invalid')
    return JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + length))) as unknown
  }
  return JSON.parse(new TextDecoder().decode(bytes)) as unknown
}

export async function loadModel(source: Model3dSource, signal: AbortSignal): Promise<Object3D> {
  signal.throwIfAborted()
  if ((source.size ?? 0) > MAX_MODEL_BYTES) throw new Model3dError('tooLarge')
  const format = model3dFormat(source.mediaType, source.name)
  if (!format) throw new Model3dError('invalid')
  const blob = await source.load()
  signal.throwIfAborted()
  if (!blob.size || blob.size > MAX_MODEL_BYTES) throw new Model3dError(blob.size ? 'tooLarge' : 'invalid')
  const data = await blob.arrayBuffer()
  signal.throwIfAborted()
  let root: Object3D
  if (format === 'glb' || format === 'gltf') {
    validateGltfDocument(gltfDocument(data))
    const loader = new GLTFLoader()
    loader.setMeshoptDecoder(MeshoptDecoder)
    // The document is self-contained. Only embedded buffers/images and loader-created blobs can load.
    loader.manager.setURLModifier(url => {
      if (!url.startsWith('data:') && !url.startsWith('blob:')) throw new Model3dError('dependencies')
      return url
    })
    const gltf = await loader.parseAsync(data, '')
    root = new Group()
    root.add(gltf.scene)
    additionalScenes.set(root, gltf.scenes.filter(scene => scene !== gltf.scene))
  } else if (format === 'obj') {
    root = new OBJLoader().parse(new TextDecoder().decode(data))
    // OBJ geometry can be viewed without guessing where a companion MTL or texture is stored.
    root.traverse(object => {
      if (!(object instanceof Mesh)) return
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose()
      const vertexColors = object.geometry.hasAttribute('color')
      object.material = new MeshStandardMaterial({ color: vertexColors ? 0xffffff : 0x7ba9db, vertexColors, side: DoubleSide, roughness: 0.65 })
    })
  } else {
    const geometry = format === 'stl' ? new STLLoader().parse(data) : new PLYLoader().parse(data)
    const vertexColors = geometry.hasAttribute('color')
    if (format === 'ply' && !geometry.index) {
      root = new Points(geometry, new PointsMaterial({ color: vertexColors ? 0xffffff : 0x7ba9db, vertexColors, size: 0.015 }))
    } else {
      if (!geometry.hasAttribute('normal')) geometry.computeVertexNormals()
      root = new Mesh(geometry, new MeshStandardMaterial({ color: vertexColors ? 0xffffff : 0x7ba9db, vertexColors, side: DoubleSide, roughness: 0.65 }))
    }
  }
  try {
    signal.throwIfAborted()
    let vertices = 0
    root.traverse(object => {
      if (object instanceof Mesh || object instanceof Points) {
        const position = object.geometry.getAttribute('position')
        vertices += position?.count ?? 0
        if (vertices > MAX_MODEL_VERTICES) throw new Model3dError('tooLarge')
        if (!position) throw new Model3dError('invalid')
        for (let index = 0; index < position.array.length; index++) {
          if (!Number.isFinite(position.array[index])) throw new Model3dError('invalid')
        }
      }
    })
    if (!vertices) throw new Model3dError('invalid')
    const box = new Box3().setFromObject(root)
    const size = box.getSize(new Vector3())
    const extent = Math.max(size.x, size.y, size.z)
    if (!Number.isFinite(extent) || extent <= 0) throw new Model3dError('invalid')
    const center = box.getCenter(new Vector3())
    const normalized = new Group()
    normalized.add(root)
    normalized.scale.setScalar(2 / extent)
    normalized.position.copy(center).multiplyScalar(-2 / extent)
    return normalized
  } catch (error) {
    disposeModel(root)
    throw error
  }
}

/** Render on interaction/resize only; thumbnails release their GPU context immediately. */
export function createModelView(canvas: HTMLCanvasElement, model: Object3D, interactive: boolean): Model3dView {
  let renderer: WebGLRenderer
  try {
    renderer = new WebGLRenderer({ canvas, antialias: true })
  } catch {
    disposeModel(model)
    throw new Model3dError('webgl')
  }
  renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 2))
  const scene = new Scene()
  scene.background = new Color(0xe9eef5)
  scene.add(model, new HemisphereLight(0xffffff, 0x65758b, 3))
  const light = new DirectionalLight(0xffffff, 3)
  light.position.set(3, 5, 4)
  scene.add(light)
  const camera = new PerspectiveCamera(40, 1, 0.01, 100)
  const controls = new OrbitControls(camera, canvas)
  controls.enabled = interactive
  controls.minDistance = 0.1
  controls.maxDistance = 40
  const render = (): void => renderer.render(scene, camera)
  controls.addEventListener('change', render)
  const reset = (): void => {
    const distance = 1.8 / Math.sin(Math.atan(Math.tan(Math.PI / 9) * Math.min(1, camera.aspect)))
    camera.position.set(1, 0.7, 1).normalize().multiplyScalar(distance)
    controls.target.set(0, 0, 0)
    controls.update()
    render()
  }
  reset()
  const navigation = model3dNavigation(camera, controls, reset, render)
  if (interactive) canvas.addEventListener('keydown', navigation.keydown)
  return {
    reset,
    zoom: navigation.zoom,
    resize(width, height) {
      if (width < 1 || height < 1) return
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      render()
    },
    snapshot() {
      render()
      return new Promise((resolve, reject) => canvas.toBlob(blob => {
        if (blob) resolve(blob)
        else reject(new Model3dError('webgl'))
      }, 'image/png'))
    },
    dispose() {
      canvas.removeEventListener('keydown', navigation.keydown)
      controls.dispose()
      disposeModel(model)
      renderer.dispose()
      renderer.forceContextLoss()
    },
  }
}

let thumbnailQueue: Promise<unknown> = Promise.resolve()

export function createModelThumbnail(source: Model3dSource, signal: AbortSignal): Promise<Blob> {
  const job = thumbnailQueue.then(async () => {
    const model = await loadModel(source, signal)
    const canvas = document.createElement('canvas')
    const view = createModelView(canvas, model, false)
    try {
      view.resize(320, 220)
      view.reset()
      return await view.snapshot()
    } finally {
      view.dispose()
    }
  })
  thumbnailQueue = job.catch(() => undefined)
  return job
}
