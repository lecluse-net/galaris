import { Spherical, Vector3 } from 'three'
import type { PerspectiveCamera } from 'three'
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js'

type NavigationKey = Pick<KeyboardEvent, 'key' | 'shiftKey' | 'ctrlKey' | 'metaKey' | 'altKey' | 'defaultPrevented' | 'preventDefault' | 'stopPropagation'>
type CameraControls = Pick<OrbitControls, 'target' | 'minDistance' | 'maxDistance' | 'update'>

/** Mouse and keyboard share the same camera, target and distance limits. */
export function model3dNavigation(
  camera: PerspectiveCamera,
  controls: CameraControls,
  reset: () => void,
  render: () => void,
): { zoom: (factor: number) => void; keydown: (event: NavigationKey) => void } {
  const update = (): void => { controls.update(); render() }
  const zoom = (factor: number): void => {
    if (!Number.isFinite(factor) || factor <= 0) return
    const offset = camera.position.clone().sub(controls.target)
    const distance = Math.min(controls.maxDistance, Math.max(controls.minDistance, offset.length() * factor))
    camera.position.copy(controls.target).add(offset.setLength(distance))
    update()
  }
  const arrows: Record<string, [number, number]> = {
    ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1],
  }
  return {
    zoom,
    keydown(event) {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return
      const direction = arrows[event.key]
      const zoomIn = event.key === '+' || event.key === '='
      const zoomOut = event.key === '-' || event.key === '_'
      if (!direction && !zoomIn && !zoomOut && event.key !== 'Home') return
      event.preventDefault()
      event.stopPropagation()
      if (event.key === 'Home') { reset(); return }
      if (zoomIn || zoomOut) { zoom(zoomIn ? 0.9 : 1 / 0.9); return }
      if (!direction) return
      const [horizontal, vertical] = direction
      const offset = camera.position.clone().sub(controls.target)
      if (event.shiftKey) {
        camera.updateMatrixWorld()
        const step = offset.length() * 0.04
        const movement = new Vector3().setFromMatrixColumn(camera.matrixWorld, 0).multiplyScalar(horizontal * step)
          .addScaledVector(new Vector3().setFromMatrixColumn(camera.matrixWorld, 1), vertical * step)
        camera.position.add(movement)
        controls.target.add(movement)
      } else {
        const spherical = new Spherical().setFromVector3(offset)
        spherical.theta += horizontal * Math.PI / 36
        spherical.phi -= vertical * Math.PI / 36
        spherical.makeSafe()
        camera.position.copy(controls.target).add(new Vector3().setFromSpherical(spherical))
      }
      update()
    },
  }
}
