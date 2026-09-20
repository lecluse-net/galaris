/** Shared, transport-independent contract for 3D resource previews. */
export type Model3dFormat = 'glb' | 'gltf' | 'obj' | 'stl' | 'ply'

export interface Model3dSource {
  /** Include the authorization scope and resource revision in this key. */
  key: string
  name: string
  mediaType: string
  size?: number | null
  load: () => Promise<Blob>
}

const mimeFormats: Record<string, Model3dFormat> = {
  'model/gltf-binary': 'glb',
  'model/gltf+json': 'gltf',
  'model/obj': 'obj',
  'application/x-wavefront-obj': 'obj',
  'model/stl': 'stl',
  'application/sla': 'stl',
  'model/x.stl': 'stl',
  'application/x-stl': 'stl',
  'model/ply': 'ply',
  'application/ply': 'ply',
  'application/x-ply': 'ply',
}

export function model3dFormat(mediaType: string, name = ''): Model3dFormat | null {
  const mime = mediaType.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  const known = mimeFormats[mime]
  if (known) return known
  const extension = /\.(glb|gltf|obj|stl|ply)$/i.exec(name.trim())?.[1]?.toLowerCase()
  return (extension as Model3dFormat | undefined) ?? null
}

export const MAX_MODEL_BYTES = 32_000_000
export const MAX_MODEL_VERTICES = 2_000_000

export class Model3dError extends Error {
  readonly code: 'invalid' | 'tooLarge' | 'dependencies' | 'compression' | 'webgl'
  constructor(code: Model3dError['code']) {
    super(code)
    this.code = code
  }
}

/** Reject dependencies before invoking a loader: an attachment must never fetch arbitrary URLs. */
export function validateGltfDocument(document: unknown): void {
  if (!document || typeof document !== 'object' || Array.isArray(document)) throw new Model3dError('invalid')
  const value = document as Record<string, unknown>
  for (const key of ['buffers', 'images']) {
    const entries = value[key]
    if (entries === undefined) continue
    if (!Array.isArray(entries)) throw new Model3dError('invalid')
    let bytes = 0
    for (const entry of entries) {
      if (!entry || typeof entry !== 'object') throw new Model3dError('invalid')
      const { uri, byteLength } = entry as Record<string, unknown>
      if (uri !== undefined && (typeof uri !== 'string' || !/^data:(?:application\/octet-stream|application\/gltf-buffer|image\/(?:png|jpeg|webp));base64,/i.test(uri))) {
        throw new Model3dError('dependencies')
      }
      if (byteLength !== undefined) {
        if (typeof byteLength !== 'number' || !Number.isSafeInteger(byteLength) || byteLength < 0) throw new Model3dError('invalid')
        bytes += byteLength
      }
    }
    if (bytes > MAX_MODEL_BYTES) throw new Model3dError('tooLarge')
  }
  const required = value.extensionsRequired
  if (Array.isArray(required) && required.some(extension => (
    extension === 'KHR_draco_mesh_compression' || extension === 'KHR_texture_basisu'
  ))) throw new Model3dError('compression')
}
