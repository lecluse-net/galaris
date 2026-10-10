import { test } from 'node:test'
import assert from 'node:assert/strict'
import { PerspectiveCamera, Vector3 } from 'three'
import { fitGraph3d } from './graph3dCamera.ts'

test('3D overview fits wide, tall and deep graphs, fills the viewport and centers their projected bounds', () => {
  const graphs = [
    [{ x: -4000, y: -250, z: 0 }, { x: 4000, y: 250, z: 0 }],
    [{ x: -250, y: -4000, z: 0 }, { x: 250, y: 4000, z: 0 }],
    [{ x: -1100, y: -700, z: -900 }, { x: 700, y: 450, z: 500 }, { x: 1600, y: -300, z: -500 }],
  ]
  for (const [width, height] of [[1440, 900], [390, 800]]) {
    for (const direction of [new Vector3(0, 0.15, 1).normalize(), new Vector3(0.7, 0.4, 1).normalize()]) {
      for (const graph of graphs) {
        const points = graph.map(point => ({ x: point.x + 1e7, y: point.y - 2e7, z: point.z + 3e7 }))
        const fit = fitGraph3d(points, width, height, direction)
        const camera = new PerspectiveCamera(45, width / height, 0.0001, 1e8)
        const target = new Vector3(fit.center.x, fit.center.y, fit.center.z)
        camera.position.copy(target).addScaledVector(direction, fit.distance)
        camera.lookAt(target); camera.updateMatrixWorld()
        const pixels = points.map(point => {
          const p = new Vector3(point.x, point.y, point.z).project(camera)
          assert(p.z >= -1 && p.z <= 1, 'every node stays in front of the camera')
          return { x: (p.x + 1) * width / 2, y: (1 - p.y) * height / 2 }
        })
        const minX = Math.min(...pixels.map(p => p.x)), maxX = Math.max(...pixels.map(p => p.x))
        const minY = Math.min(...pixels.map(p => p.y)), maxY = Math.max(...pixels.map(p => p.y))
        assert(minX >= 35 && maxX <= width - 35 && minY >= 35 && maxY <= height - 35, 'node glyphs remain fully visible')
        assert(Math.max((maxX - minX) / width, (maxY - minY) / height) > 0.75, 'the graph uses the available viewport')
        assert(Math.abs((minX + maxX) / 2 - width / 2) < 0.1, 'horizontal centering survives unequal depths')
        assert(Math.abs((minY + maxY) / 2 - height / 2) < 0.1, 'vertical centering survives unequal depths')
      }
    }
  }
})

test('empty and single-node overviews have a finite camera pose', () => {
  for (const points of [[], [{ x: -20, y: 80, z: 300 }]]) {
    const fit = fitGraph3d(points, 390, 800, { x: 0, y: 0, z: 0 })
    assert(Number.isFinite(fit.distance) && fit.distance > 0)
    assert(Object.values(fit.center).every(Number.isFinite))
  }
})
