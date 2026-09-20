import assert from 'node:assert/strict'
import test from 'node:test'
import { browserResourceKind } from './resourceViewer.ts'
import { MAX_MODEL_BYTES, Model3dError, model3dFormat, validateGltfDocument } from './model3d.ts'
import { disposeModel, loadModel } from './model3dRuntime.ts'

// Three's FileLoader reports browser progress events even for embedded data URLs.
globalThis.ProgressEvent ??= class ProgressEvent extends Event {
  constructor(type, init = {}) { super(type); Object.assign(this, init) }
}

const obj = 'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
const stl = 'solid triangle\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid triangle'
const ply = 'ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n'
const buffer = Buffer.from(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]).buffer)
const gltf = {
  asset: { version: '2.0' }, scene: 0,
  scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
  meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
  accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: 'VEC3', min: [0, 0, 0], max: [1, 1, 0] }],
  bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: 36 }],
  buffers: [{ byteLength: 36, uri: `data:application/octet-stream;base64,${buffer.toString('base64')}` }],
}
function source(name, content, extras = {}) {
  return { key: name, name, mediaType: 'application/octet-stream', load: async () => new Blob([content]), ...extras }
}
const hasCode = code => error => error instanceof Model3dError && error.code === code

test('3D detection covers supported extensions and MIME aliases without treating CAD files as viewable', () => {
  for (const extension of ['glb', 'gltf', 'obj', 'stl', 'ply']) {
    assert.equal(browserResourceKind('application/octet-stream', `PART.${extension.toUpperCase()}`), 'model3d')
    assert.equal(model3dFormat('text/plain', `part.${extension}`), extension)
  }
  assert.equal(model3dFormat('model/gltf-binary; charset=binary', 'file'), 'glb')
  assert.equal(model3dFormat('model/obj', 'file'), 'obj')
  for (const name of ['part.step', 'house.ifc', 'model.obj.html', 'model.obj.exe', 'scene.blend']) {
    assert.equal(model3dFormat('application/octet-stream', name), null)
  }
  assert.equal(model3dFormat('application/vnd.ms-pki.stl', 'certificate'), null)
})

test('glTF rejects remote, relative, blob and active-content dependencies before any loader runs', () => {
  for (const uri of ['https://example.com/private.bin', '//example.com/a', '../a.bin', 'buffer.bin', 'blob:stolen', 'data:image/svg+xml;base64,PHN2Zz4=', 'javascript:alert(1)']) {
    assert.throws(() => validateGltfDocument({ buffers: [{ uri }] }), hasCode('dependencies'))
    assert.throws(() => validateGltfDocument({ images: [{ uri }] }), hasCode('dependencies'))
  }
  validateGltfDocument(gltf)
  assert.throws(() => validateGltfDocument({ buffers: [{ byteLength: MAX_MODEL_BYTES + 1 }] }), hasCode('tooLarge'))
  assert.throws(() => validateGltfDocument({ extensionsRequired: ['KHR_draco_mesh_compression'] }), hasCode('compression'))
})

for (const [name, content] of [['triangle.obj', obj], ['triangle.stl', stl], ['triangle.ply', ply], ['triangle.gltf', JSON.stringify(gltf)]]) {
  test(`loader produces finite centered geometry from ${name}`, async () => {
    const model = await loadModel(source(name, content), new AbortController().signal)
    try {
      const { Box3, Vector3 } = await import('three')
      const box = new Box3().setFromObject(model)
      assert.ok(box.getCenter(new Vector3()).length() < 0.0001)
      assert.equal(box.getSize(new Vector3()).x, 2)
    } finally { disposeModel(model) }
  })
}

test('binary GLB loads through the same validated parser', async () => {
  const document = { ...gltf, buffers: [{ byteLength: buffer.length }] }
  const json = Buffer.from(JSON.stringify(document))
  const padded = Buffer.alloc(Math.ceil(json.length / 4) * 4, 0x20)
  json.copy(padded)
  const glb = Buffer.alloc(12 + 8 + padded.length + 8 + buffer.length)
  glb.writeUInt32LE(0x46546c67, 0)
  glb.writeUInt32LE(2, 4)
  glb.writeUInt32LE(glb.length, 8)
  glb.writeUInt32LE(padded.length, 12)
  glb.writeUInt32LE(0x4e4f534a, 16)
  padded.copy(glb, 20)
  glb.writeUInt32LE(buffer.length, 20 + padded.length)
  glb.writeUInt32LE(0x004e4942, 24 + padded.length)
  buffer.copy(glb, 28 + padded.length)
  const model = await loadModel(source('triangle.glb', glb), new AbortController().signal)
  disposeModel(model)
})

test('oversized and cancelled previews never download the resource', async () => {
  let downloads = 0
  const resource = source('triangle.obj', obj, { size: MAX_MODEL_BYTES + 1, load: async () => { downloads++; return new Blob([obj]) } })
  await assert.rejects(loadModel(resource, new AbortController().signal), hasCode('tooLarge'))
  const cancelled = new AbortController()
  cancelled.abort()
  await assert.rejects(loadModel({ ...resource, size: 0 }, cancelled.signal), { name: 'AbortError' })
  assert.equal(downloads, 0)
})

test('a resource finishing after cancellation is not parsed', async () => {
  const controller = new AbortController()
  await assert.rejects(loadModel(source('bad.obj', '', {
    load: async () => { controller.abort(); return new Blob(['invalid']) },
  }), controller.signal), { name: 'AbortError' })
})

test('invalid and empty geometry fail with a readable preview error', async () => {
  for (const content of ['', '# no geometry', 'v NaN 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3']) {
    await assert.rejects(loadModel(source('invalid.obj', content), new AbortController().signal), hasCode('invalid'))
  }
})
