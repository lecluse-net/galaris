import assert from 'node:assert/strict'
import test from 'node:test'
import { PerspectiveCamera, Vector3 } from 'three'
import { model3dNavigation } from './model3dNavigation.ts'

function fixture() {
  const camera = new PerspectiveCamera(40, 1, 0.01, 100)
  camera.position.set(3, 2, 3)
  const controls = { target: new Vector3(), minDistance: 0.1, maxDistance: 40, update() { camera.lookAt(this.target); camera.updateMatrixWorld() } }
  const reset = () => { camera.position.set(3, 2, 3); controls.target.set(0, 0, 0); controls.update() }
  reset()
  let renders = 0
  const navigation = model3dNavigation(camera, controls, reset, () => { renders++ })
  return { camera, controls, navigation, renders: () => renders }
}
function key(value, modifiers = {}) {
  return { key: value, ctrlKey: false, altKey: false, metaKey: false, shiftKey: false, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true }, stopPropagation() {}, ...modifiers }
}

test('arrow rotation preserves the orbit center and camera distance', () => {
  const { camera, controls, navigation } = fixture()
  const initial = camera.position.clone()
  navigation.keydown(key('ArrowRight'))
  assert.ok(camera.position.distanceTo(initial) > 0.1)
  assert.ok(Math.abs(camera.position.length() - initial.length()) < 1e-9)
  assert.equal(controls.target.length(), 0)
  navigation.keydown(key('ArrowLeft'))
  assert.ok(camera.position.distanceTo(initial) < 1e-9)
  for (let i = 0; i < 100; i++) navigation.keydown(key('ArrowUp'))
  assert.ok(camera.position.toArray().every(Number.isFinite))
  assert.ok(Math.abs(camera.position.length() - initial.length()) < 1e-9)
})

test('Shift + arrows translates camera and target together without changing the viewing direction', () => {
  const { camera, controls, navigation } = fixture()
  const offset = camera.position.clone().sub(controls.target)
  const before = camera.position.clone()
  navigation.keydown(key('ArrowRight', { shiftKey: true }))
  assert.ok(controls.target.length() > 0)
  assert.ok(camera.position.clone().sub(before).distanceTo(controls.target) < 1e-9)
  assert.ok(camera.position.clone().sub(controls.target).distanceTo(offset) < 1e-9)
})

test('keyboard and toolbar zoom respect the same near/far bounds', () => {
  const { camera, controls, navigation } = fixture()
  const before = camera.position.length()
  navigation.keydown(key('+'))
  assert.ok(camera.position.length() < before)
  for (let i = 0; i < 100; i++) navigation.keydown(key('-'))
  assert.ok(Math.abs(camera.position.length() - controls.maxDistance) < 1e-9)
  navigation.zoom(1e-12)
  assert.ok(Math.abs(camera.position.length() - controls.minDistance) < 1e-9)
  navigation.zoom(Infinity)
  assert.ok(camera.position.toArray().every(Number.isFinite))
})

test('Home restores both camera and target after rotation, pan and zoom', () => {
  const { camera, controls, navigation } = fixture()
  navigation.keydown(key('ArrowRight'))
  navigation.keydown(key('ArrowDown', { shiftKey: true }))
  navigation.keydown(key('+'))
  navigation.keydown(key('Home'))
  assert.deepEqual(camera.position.toArray(), [3, 2, 3])
  assert.equal(controls.target.length(), 0)
})

test('browser shortcuts, Tab, Escape and consumed events are left untouched', () => {
  const { navigation, renders } = fixture()
  for (const event of [key('Tab'), key('Escape'), key('+', { ctrlKey: true }), key('ArrowLeft', { altKey: true }), key('Home', { metaKey: true })]) {
    navigation.keydown(event)
    assert.equal(event.defaultPrevented, false)
  }
  navigation.keydown(key('ArrowLeft', { defaultPrevented: true }))
  assert.equal(renders(), 0)
  const arrow = key('ArrowRight')
  navigation.keydown(arrow)
  assert.equal(arrow.defaultPrevented, true)
})
