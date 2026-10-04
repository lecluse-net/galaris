import assert from 'node:assert/strict';
import test from 'node:test';
import { chromium } from 'playwright';
import { renderModelThumbnail } from './model-thumbnail.mjs';

const triangle = 'v -1 -1 0\nv 1 -1 0\nv 0 1 0\nf 1 2 3\n';

function modelFixtures() {
  const vertices = Buffer.alloc(36);
  [-1, -1, 0, 1, -1, 0, 0, 1, 0].forEach((value, index) => vertices.writeFloatLE(value, index * 4));
  const gltf = {
    asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
    buffers: [{ byteLength: vertices.length }], bufferViews: [{ buffer: 0, byteLength: vertices.length }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: 'VEC3', min: [-1, -1, 0], max: [1, 1, 0] }],
  };
  const json = Buffer.from(JSON.stringify(gltf));
  const padded = Buffer.alloc(Math.ceil(json.length / 4) * 4, 32);
  json.copy(padded);
  const glb = Buffer.alloc(28 + padded.length + vertices.length);
  glb.writeUInt32LE(0x46546c67, 0); glb.writeUInt32LE(2, 4); glb.writeUInt32LE(glb.length, 8);
  glb.writeUInt32LE(padded.length, 12); glb.writeUInt32LE(0x4e4f534a, 16); padded.copy(glb, 20);
  glb.writeUInt32LE(vertices.length, 20 + padded.length); glb.writeUInt32LE(0x004e4942, 24 + padded.length);
  vertices.copy(glb, 28 + padded.length);
  gltf.buffers[0].uri = `data:application/octet-stream;base64,${vertices.toString('base64')}`;
  return [
    ['triangle.obj', Buffer.from(triangle)],
    ['triangle.stl', Buffer.from('solid triangle\nfacet normal 0 0 1\nouter loop\nvertex -1 -1 0\nvertex 1 -1 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid triangle\n')],
    ['triangle.ply', Buffer.from('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n-1 -1 0\n1 -1 0\n0 1 0\n3 0 1 2\n')],
    ['triangle.gltf', Buffer.from(JSON.stringify(gltf))],
    ['triangle.glb', glb],
  ];
}

test('offline model capture renders geometry and disposes successful and failed contexts', { timeout: 60_000 }, async () => {
  const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    for (const [name, content] of modelFixtures()) {
      const png = await renderModelThumbnail(browser, { name, data: content.toString('base64') });
      assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
      assert.ok(png.length > 1000, `${name}: rendered geometry differs from a solid background`);
      assert.equal(browser.contexts().length, 0);
    }
    await assert.rejects(renderModelThumbnail(browser, { name: 'invalid.obj', data: Buffer.from('broken').toString('base64') }));
    const external = { asset: { version: '2.0' }, buffers: [{ uri: 'https://example.org/private.bin', byteLength: 12 }] };
    await assert.rejects(renderModelThumbnail(browser, { name: 'private.gltf', data: Buffer.from(JSON.stringify(external)).toString('base64') }), /External dependencies/);
    assert.equal(browser.contexts().length, 0);
  } finally { await browser.close(); }
});
