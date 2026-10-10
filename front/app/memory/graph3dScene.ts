import {
  Box3, BufferAttribute, Color, DynamicDrawUsage, Frustum, InstancedBufferAttribute,
  InstancedBufferGeometry, Matrix4, Mesh, MOUSE, PerspectiveCamera, Quaternion,
  Scene, ShaderMaterial, Vector2, Vector3, WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { GraphPoint3d } from './graph3dLayout'
import { fitGraph3d } from './graph3dCamera'
import { Graph3dGlyphs } from './graph3dGlyphs'
import { markerVertexShader, markerFragmentShader, linkVertexShader, linkFragmentShader } from './graph3dShaders'

export interface Graph3dMarker {
  id: string
  title: string
  point: GraphPoint3d
  color: string
  symbol: string
  borderColor: string
  selectedBorderColor: string
  borderWidth: number
  size: number
  shape: number
  opacity: number
  priority: number
  grouped: number
}
export interface Graph3dLink {
  source: string; target: string; type: string; color: string; suggested: boolean
  width: number; opacity: number; curvature: number; overviewStyle: { width: number; opacity: number }
}
export interface Graph3dCamera { position: [number, number, number]; target: [number, number, number] }
export interface Graph3dProjection { id: string; x: number; y: number; depth: number; size: number; near: boolean }
export interface Graph3dPreview { url: string; aspect: number; nativeSize: number }
interface SpatialCell {
  key: string
  bounds: Box3
  markers: Graph3dMarker[]
  displayed: Graph3dMarker[]
  groups: Graph3dMarker[][]
}
interface OrbitGesture {
  x: number
  y: number
  pivot: Vector3
  position: Vector3
  target: Vector3
  right: Vector3
  phi: number
}
interface MarkerPaint {
  fill: [number, number, number]
  border: [number, number, number, number]
  selectedBorder: [number, number, number, number]
}
interface LinkPaint {
  source: GraphPoint3d
  target: GraphPoint3d
  curvature: number
  width: number
  attributes: Record<string, number[]>
  chunks: number
  visibleMask: number
}

/** Owns one WebGL context; no per-node Mesh, Vue component or raycast. Scene
 * marker buffers follow data; link buffers also follow adaptive subdivision.
 * Camera frames compact visible instances and
 * use a screen grid for picking. Labels and authorized previews are bounded. */
export class MemoryGraphScene {
  private readonly renderer: WebGLRenderer
  private readonly scene = new Scene()
  private readonly camera = new PerspectiveCamera(45, 1, 0.001, 100_000)
  private readonly controls: OrbitControls
  private readonly geometry = new InstancedBufferGeometry()
  private readonly material: ShaderMaterial
  private readonly mesh: Mesh
  private readonly glyphs = new Graph3dGlyphs(() => this.schedule())
  private readonly linkGeometry = new InstancedBufferGeometry()
  private readonly linkMaterial = new ShaderMaterial({ vertexShader: linkVertexShader, fragmentShader: linkFragmentShader,
    transparent: true, depthWrite: false, uniforms: { originHigh: { value: new Vector3() }, originLow: { value: new Vector3() },
      viewport: { value: new Vector2(1, 1) }, cameraNear: { value: 0.001 }, detailed: { value: 0 } } })
  private readonly links: Mesh
  private linkOverview = true
  private readonly overlay: HTMLDivElement
  private readonly center = new Vector3()
  private readonly boundsCenter = new Vector3()
  private readonly fitDirection = new Vector3()
  private fitPoints: GraphPoint3d[] = []
  private fitDirty = true
  private readonly projected = new Vector3()
  private readonly colors = new Color()
  private readonly markerPaints = new WeakMap<Graph3dMarker, MarkerPaint>()
  private readonly frustum = new Frustum()
  private readonly clipMatrix = new Matrix4()
  private cells: SpatialCell[] = []
  private foldedCells = new Set<string>()
  private readonly openedCells = new Set<string>()
  private readonly proxyCells = new Map<string, string>()
  private displayById = new Map<string, Graph3dMarker>()
  private sourceLinks: Graph3dLink[] = []
  private linkPaints: LinkPaint[] = []
  private linkBuffersDirty = true
  private visibleLinks = 0
  private frontierDirty = true
  private spatialGrouped = 0
  private readonly buckets = new Map<string, Graph3dProjection[]>()
  private readonly elements = new Map<string, HTMLDivElement>()
  private readonly images = new Map<string, HTMLImageElement>()
  private readonly imageBounds = new Map<string, { w: number; h: number }>()
  private markers: Graph3dMarker[] = []
  private byId = new Map<string, Graph3dMarker>()
  private projections = new Map<string, Graph3dProjection>()
  private capacity = 0
  private linkCapacity = 0
  private width = 1
  private height = 1
  private fitDistance = 1
  private frame: number | null = null
  private disposed = false
  private suspended = false
  private cameraChanged = true
  private paints = 0
  private pointer: { pointerId: number; x: number; y: number; lastX: number; lastY: number;
    nodeId: string | null; moved: boolean; orbit: OrbitGesture | null } | null = null
  private readonly touchPointers = new Map<number, { x: number; y: number }>()
  private navigationDepth: number | null = null
  private navigating = false
  private overview = true
  private selected: string | null = null
  private previews = new Map<string, Graph3dPreview>()
  private ink = '#222222'
  private onCamera: () => void
  private readonly onSelect: (id: string) => void
  private readonly onFailure: () => void
  private readonly groupTitle: (count: number) => string

  constructor(private readonly host: HTMLElement, callbacks: {
    camera: () => void; select: (id: string) => void; failure: () => void; groupTitle: (count: number) => string
  }) {
    this.onCamera = callbacks.camera
    this.onSelect = callbacks.select
    this.onFailure = callbacks.failure
    this.groupTitle = callbacks.groupTitle
    this.renderer = new WebGLRenderer({ antialias: false, alpha: false, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, window.innerWidth < 1024 ? 1.5 : 2))
    this.renderer.domElement.setAttribute('aria-hidden', 'true')
    host.append(this.renderer.domElement)
    this.geometry.setAttribute('position', new BufferAttribute(new Float32Array([
      -0.5, -0.5, 0, 0.5, -0.5, 0, 0.5, 0.5, 0, -0.5, 0.5, 0,
    ]), 3))
    this.geometry.setIndex([0, 1, 2, 0, 2, 3])
    this.material = new ShaderMaterial({ vertexShader: markerVertexShader, fragmentShader: markerFragmentShader, transparent: true, depthWrite: false,
      uniforms: { viewport: { value: new Vector2(1, 1) }, glyphAtlas: { value: this.glyphs.texture } } })
    this.mesh = new Mesh(this.geometry, this.material)
    this.mesh.frustumCulled = false
    this.mesh.renderOrder = 1
    this.scene.add(this.mesh)
    // Each instance is a four-segment chunk of a curve. Long projected links
    // use more chunks, while short links keep a single lightweight instance.
    const stations: number[] = [], indices: number[] = []
    for (let i = 0; i <= 4; i++) stations.push(i / 4, -0.5, 0, i / 4, 0.5, 0)
    for (let i = 0; i < 4; i++) {
      const a = i * 2, b = (i + 1) * 2
      indices.push(a, b, b + 1, a, b + 1, a + 1)
    }
    this.linkGeometry.setAttribute('position', new BufferAttribute(new Float32Array(stations), 3))
    this.linkGeometry.setIndex(indices)
    this.linkGeometry.instanceCount = 0
    this.links = new Mesh(this.linkGeometry, this.linkMaterial)
    this.links.frustumCulled = false
    this.scene.add(this.links)
    this.overlay = document.createElement('div')
    this.overlay.className = 'memory-graph-3d-overlay'
    Object.assign(this.overlay.style, { position: 'absolute', inset: '0', overflow: 'hidden', pointerEvents: 'none' })
    host.append(this.overlay)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = false
    this.controls.enableRotate = true
    // Navigation moves camera and target together, so it can pass the pivot.
    this.controls.enableZoom = false
    this.controls.minDistance = 0
    this.controls.maxDistance = Infinity
    this.controls.addEventListener('change', this.changed)
    this.renderer.domElement.addEventListener('pointerdown', this.pointerDown, true)
    this.renderer.domElement.addEventListener('pointermove', this.pointerMove, true)
    this.renderer.domElement.addEventListener('pointerup', this.pointerUp, true)
    this.renderer.domElement.addEventListener('pointercancel', this.pointerCancel, true)
    this.renderer.domElement.addEventListener('lostpointercapture', this.pointerCancel, true)
    this.renderer.domElement.addEventListener('wheel', this.wheel, { capture: true, passive: false })
    this.renderer.domElement.addEventListener('webglcontextlost', this.contextLost)
    host.addEventListener('keydown', this.keydown)
    this.resize()
  }

  get zoom(): number {
    if (this.controls.target.distanceTo(this.center) < 0.001
      && Math.abs(this.camera.position.distanceTo(this.center) - this.fitDistance) < this.fitDistance / 100_000) return 1
    return Math.max(1, this.fitDistance / Math.max(this.camera.near, this.navigationDepth ?? this.camera.position.distanceTo(this.controls.target)))
  }
  get view(): Graph3dCamera {
    return { position: this.camera.position.toArray(), target: this.controls.target.toArray() }
  }
  get visible(): ReadonlyMap<string, Graph3dProjection> { return this.projections }
  get groupedCount(): number { return this.spatialGrouped }
  spacingAt(id: string, distance: number): number {
    const point = this.projections.get(id)
    return point ? distance * this.height / (2 * Math.tan(this.camera.fov * Math.PI / 360) * Math.max(this.camera.near, -point.depth)) : 0
  }

  setData(markers: Graph3dMarker[], links: Graph3dLink[], bounds: Iterable<GraphPoint3d>, fit: boolean): void {
    this.cameraChanged = true
    this.markers = [...markers].sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id))
    this.byId = new Map(markers.map(marker => [marker.id, marker]))
    this.sourceLinks = links
    this.frontierDirty = true
    if (!markers.length) {
      this.pointer = null; this.touchPointers.clear(); this.navigationDepth = null
      this.geometry.instanceCount = 0
      this.projections.clear(); this.buckets.clear(); this.imageBounds.clear()
      this.overlay.replaceChildren(); this.elements.clear(); this.images.clear()
      this.renderer.clear()
    }
    const cells = new Map<string, SpatialCell>()
    for (const marker of this.markers) {
      const p = marker.point, key = `${Math.floor(p.x / 500)},${Math.floor(p.y / 500)},${Math.floor(p.z / 500)}`
      let cell = cells.get(key)
      if (!cell) { cell = { key, bounds: new Box3(), markers: [], displayed: [], groups: [] }; cells.set(key, cell) }
      cell.markers.push(marker)
      cell.bounds.expandByPoint(this.projected.set(p.x, p.y, p.z))
    }
    this.cells = [...cells.values()]
    for (const cell of this.cells) {
      const groups = new Map<string, Graph3dMarker[]>()
      for (const marker of cell.markers) if (marker.priority < 10 && !marker.grouped) {
        const key = `${marker.color}:${marker.shape}`
        if (!groups.has(key)) groups.set(key, [])
        groups.get(key)!.push(marker)
      }
      cell.groups = [...groups.values()].filter(group => group.length >= 8)
    }
    if (markers.length > this.capacity) {
      this.capacity = 2 ** Math.ceil(Math.log2(Math.max(16, markers.length)))
      for (const [name, components] of [['center', 3], ['tint', 3], ['appearance', 3], ['border', 4], ['glyph', 2], ['borderWidth', 1]] as const) {
        this.geometry.setAttribute(name, new InstancedBufferAttribute(new Float32Array(this.capacity * components), components).setUsage(DynamicDrawUsage))
      }
    }
    this.fitPoints = [...bounds]
    this.fitDirty = true
    const direction = fit ? new Vector3(0, 0.15, 1).normalize() : this.camera.position.clone().sub(this.controls.target).normalize()
    this.updateFit(direction)
    if (fit || this.overview) this.frameFit(direction)
    else this.schedule()
  }

  setTheme(background: string, ink: string): void {
    this.ink = ink
    this.renderer.setClearColor(background)
    this.schedule()
  }
  setSelected(id: string | null): void { this.selected = id; this.schedule() }
  setPreviews(previews: Map<string, Graph3dPreview>): void { this.previews = previews; this.schedule() }
  setSymbols(symbols: ReadonlyMap<string, string>): void {
    let changed = false
    for (const [id, symbol] of symbols) {
      const marker = this.byId.get(id)
      if (marker && marker.symbol !== symbol) { marker.symbol = symbol; changed = true }
    }
    if (changed) { this.frontierDirty = true; this.schedule() }
  }
  restore(view: Graph3dCamera): void {
    this.overview = false
    this.camera.position.fromArray(view.position); this.controls.target.fromArray(view.target)
    const direction = this.camera.position.clone().sub(this.controls.target).normalize()
    this.updateFit(direction)
    // Stored overview cameras from the previous spherical fit can be farther
    // away than the new maximum. Keep free-navigation poses, update overviews.
    if ((this.controls.target.distanceTo(this.center) < 0.001 || this.controls.target.distanceTo(this.boundsCenter) < 0.001)
      && this.camera.position.clone().sub(this.center).dot(direction) >= this.fitDistance * (1 - 1e-5)) {
      this.frameFit(direction)
      return
    }
    this.controls.update(); this.schedule()
  }
  fit(): void {
    this.frameFit(new Vector3(0, 0.15, 1).normalize())
  }
  private updateFit(direction: Vector3): void {
    if (direction.lengthSq() < 1e-12) direction.set(0, 0.15, 1).normalize()
    if (!this.fitDirty && direction.distanceToSquared(this.fitDirection) < 1e-12) return
    const result = fitGraph3d(this.fitPoints, this.width, this.height, direction)
    this.center.set(result.center.x, result.center.y, result.center.z)
    this.boundsCenter.set(result.boundsCenter.x, result.boundsCenter.y, result.boundsCenter.z)
    this.fitDistance = result.distance
    this.fitDirection.copy(direction)
    this.fitDirty = false
    this.camera.near = this.fitDistance / 100_000_000
    this.camera.far = this.fitDistance * 8
    this.camera.updateProjectionMatrix()
  }
  private frameFit(direction: Vector3): void {
    this.updateFit(direction)
    this.overview = true
    this.openedCells.clear()
    this.controls.target.copy(this.center)
    this.camera.position.copy(this.center).addScaledVector(direction, this.fitDistance)
    this.controls.update(); this.schedule()
  }
  focus(id: string): void {
    const marker = this.byId.get(id) ?? this.displayById.get(id)
    if (!marker) return
    this.overview = false
    const offset = this.camera.position.clone().sub(this.controls.target)
    this.controls.target.set(marker.point.x, marker.point.y, marker.point.z)
    this.camera.position.copy(this.controls.target).add(offset.setLength(Math.min(offset.length(), 900, this.fitDistance / 3)))
    this.controls.update(); this.schedule()
  }
  zoomBy(factor: number, pointer?: { x: number; y: number }): void {
    if (!Number.isFinite(factor) || factor <= 0 || factor === 1) return
    if (this.overview && factor < 1) return
    this.overview = false
    const forward = this.controls.target.clone().sub(this.camera.position).normalize()
    let direction = forward, distance = this.navigationDepth ?? this.fitDistance / 10
    if (pointer) {
      const rect = this.host.getBoundingClientRect()
      const tangent = Math.tan(this.camera.fov * Math.PI / 360)
      // Build the ray in camera space, without subtracting large world positions.
      // Translating both camera and target along it preserves the point under the
      // cursor and the viewing direction, even while passing through its plane.
      direction = new Vector3((2 * (pointer.x - rect.left) / this.width - 1) * tangent * this.camera.aspect,
        (1 - 2 * (pointer.y - rect.top) / this.height) * tangent, -1).applyQuaternion(this.camera.quaternion).normalize()
      const id = this.pick(pointer.x, pointer.y)
      if (id) distance = Math.max(this.camera.near, -this.projections.get(id)!.depth)
    }
    const floor = this.fitDistance / 1000
    // The minimum step crosses a nearby object's plane rather than approaching
    // it forever. In empty space, navigation continues at a usable world speed.
    const axialTravel = factor > 1 ? Math.max(floor, distance * (1 - 1 / factor)) : Math.min(-floor, distance * (1 - 1 / factor))
    const travel = axialTravel / direction.dot(forward)
    this.camera.position.addScaledVector(direction, travel)
    this.controls.target.addScaledVector(direction, travel)
    if (factor < 1) {
      const back = forward.clone().negate()
      this.updateFit(back)
      if (this.camera.position.clone().sub(this.center).dot(back) >= this.fitDistance) {
        this.frameFit(back)
        return
      }
    }
    this.navigating = true
    try { this.controls.update() } finally { this.navigating = false }
    this.schedule()
  }
  resize(): void {
    const fitting = this.overview
    const rect = this.host.getBoundingClientRect()
    this.width = Math.max(1, rect.width); this.height = Math.max(1, rect.height)
    this.camera.aspect = this.width / this.height
    this.fitDirty = true
    const direction = this.camera.position.clone().sub(this.controls.target).normalize()
    this.updateFit(direction)
    this.renderer.setSize(this.width, this.height)
    this.material.uniforms.viewport!.value.set(this.width, this.height)
    this.linkMaterial.uniforms.viewport!.value.set(this.width, this.height)
    if (fitting && this.markers.length) this.frameFit(direction)
    this.schedule()
  }
  suspend(value: boolean): void {
    this.suspended = value
    this.controls.enabled = !value
    if (value) { this.pointer = null; this.touchPointers.clear() }
    if (value && this.frame !== null) { cancelAnimationFrame(this.frame); this.frame = null }
    if (!value) this.schedule()
  }
  private changed = (): void => {
    this.cameraChanged = true
    // Panning the fitted overview stays centered. Free navigation beyond the
    // graph must not be mistaken for an overview just because it is far away.
    if (this.overview && !this.navigating && !(this.pointer?.moved && this.pointer.orbit)) {
      this.openedCells.clear()
      const shift = this.center.clone().sub(this.controls.target)
      this.controls.target.copy(this.center); this.camera.position.add(shift)
    }
    this.schedule()
  }
  private schedule(): void {
    if (this.disposed || this.suspended || this.frame !== null) return
    this.frame = requestAnimationFrame(() => {
      this.frame = null
      this.paint()
      if (this.cameraChanged) { this.cameraChanged = false; this.onCamera() }
    })
  }

  private paint(): void {
    this.camera.updateMatrixWorld()
    this.clipMatrix.copy(this.camera.projectionMatrix)
    this.clipMatrix.elements[0]! *= this.width / (this.width + 80)
    this.clipMatrix.elements[5]! *= this.height / (this.height + 80)
    this.frustum.setFromProjectionMatrix(this.clipMatrix.multiply(this.camera.matrixWorldInverse))
    this.updateFrontier()
    this.projections.clear(); this.buckets.clear()
    const centers = this.geometry.getAttribute('center') as InstancedBufferAttribute | undefined
    const tints = this.geometry.getAttribute('tint') as InstancedBufferAttribute | undefined
    const appearances = this.geometry.getAttribute('appearance') as InstancedBufferAttribute | undefined
    const borders = this.geometry.getAttribute('border') as InstancedBufferAttribute | undefined
    const glyphs = this.geometry.getAttribute('glyph') as InstancedBufferAttribute | undefined
    const borderWidths = this.geometry.getAttribute('borderWidth') as InstancedBufferAttribute | undefined
    let count = 0, represented = 0, closestDepth = Infinity
    const origin = this.camera.position
    this.linkMaterial.uniforms.originHigh!.value.set(Math.fround(origin.x), Math.fround(origin.y), Math.fround(origin.z))
    this.linkMaterial.uniforms.originLow!.value.set(origin.x - Math.fround(origin.x), origin.y - Math.fround(origin.y), origin.z - Math.fround(origin.z))
    for (const cell of this.cells) {
      if (!this.frustum.intersectsBox(cell.bounds)) continue
      for (const marker of cell.displayed) {
        const p = marker.point
        this.projected.set(p.x, p.y, p.z).project(this.camera)
        if (this.projected.z < -1 || this.projected.z > 1) continue
        const x = (this.projected.x + 1) * this.width / 2, y = (1 - this.projected.y) * this.height / 2
        if (x < -40 || x > this.width + 40 || y < -40 || y > this.height + 40) continue
        // Local depth determines the two sizes; orbiting does not grow all nodes.
        const matrix = this.camera.matrixWorldInverse.elements
        const depth = matrix[2]! * p.x + matrix[6]! * p.y + matrix[10]! * p.z + matrix[14]!
        closestDepth = Math.min(closestDepth, -depth)
        const near = this.fitDistance / Math.max(this.camera.near, -depth) >= 1.8
        const size = Math.min(marker.grouped ? 56 : 48, marker.size) * (near ? 1.1 : 0.56)
        const projection = { id: marker.id, x, y, depth, size, near }
        this.projections.set(marker.id, projection)
        const key = `${Math.floor(x / 80)},${Math.floor(y / 80)}`
        if (!this.buckets.has(key)) this.buckets.set(key, [])
        this.buckets.get(key)!.push(projection)
        centers?.setXYZ(count, p.x - origin.x, p.y - origin.y, p.z - origin.z)
        const paint = this.markerPaint(marker)
        tints?.setXYZ(count, ...paint.fill)
        const selected = marker.id === this.selected
        const shape = marker.symbol === 'circle' ? 0 : marker.symbol === 'diamond' ? 1 : marker.symbol === 'roundRect' ? 2 : 3
        appearances?.setXYZ(count, selected ? size * 1.12 : size, shape, selected ? 1 : marker.opacity)
        borders?.setXYZW(count, ...(selected ? paint.selectedBorder : paint.border))
        borderWidths?.setX(count, selected && marker.borderWidth > 0 ? 4 : marker.borderWidth)
        const glyph = shape === 3 ? this.glyphs.get(marker.symbol) : null
        glyphs?.setXY(count, glyph?.index ?? 0, glyph?.colored ?? 0)
        count++
        represented += 1 + (this.proxyCells.has(marker.id) ? marker.grouped : 0)
      }
    }
    this.geometry.instanceCount = count
    this.navigationDepth = Number.isFinite(closestDepth) ? Math.max(this.camera.near, closestDepth) : null
    for (const attribute of [centers, tints, appearances, borders, glyphs, borderWidths]) if (attribute) {
      attribute.clearUpdateRanges(); attribute.addUpdateRange(0, count * attribute.itemSize); attribute.needsUpdate = true
    }
    if (this.zoom <= 1.2) this.linkOverview = true
    else if (this.zoom >= 1.5) this.linkOverview = false
    this.linkMaterial.uniforms.detailed!.value = Number(!this.linkOverview)
    this.linkMaterial.uniforms.cameraNear!.value = this.camera.near
    this.paintLinks()
    this.paintOverlay()
    this.renderer.render(this.scene, this.camera)
    // Aggregate renderer evidence only, available to the existing browser harness.
    this.host.dataset.graph3dNodes = String(count)
    this.host.dataset.graph3dLinks = String(this.visibleLinks)
    this.host.dataset.graph3dLinkSegments = String(this.linkGeometry.instanceCount * 4)
    this.host.dataset.graph3dDrawCalls = String(this.renderer.info.render.calls)
    this.host.dataset.graph3dZoom = String(this.zoom)
    this.host.dataset.graph3dFrames = String(++this.paints)
    this.host.dataset.graph3dGrouped = String(this.spatialGrouped)
    this.host.dataset.graph3dRepresented = String(represented)
    this.host.dataset.graph3dSourceLinks = String(this.sourceLinks.length)
  }

  private markerPaint(marker: Graph3dMarker): MarkerPaint {
    const cached = this.markerPaints.get(marker)
    if (cached) return cached
    const border = (value: string): [number, number, number, number] => {
      const rgba = /^rgba\(([^)]+)\)$/.exec(value)?.[1]?.split(',')
      this.colors.set(rgba ? `rgb(${rgba.slice(0, 3).join(',')})` : value)
      return [this.colors.r, this.colors.g, this.colors.b, rgba ? Number(rgba[3]) : 1]
    }
    this.colors.set(marker.color)
    const paint: MarkerPaint = { fill: [this.colors.r, this.colors.g, this.colors.b],
      border: border(marker.borderColor), selectedBorder: border(marker.selectedBorderColor) }
    this.markerPaints.set(marker, paint)
    return paint
  }

  private updateFrontier(): void {
    const folded = new Set<string>()
    const matrix = this.camera.matrixWorldInverse.elements
    for (const cell of this.cells) {
      if (!cell.groups.length || this.openedCells.has(cell.key) || this.selected !== null && cell.markers.some(marker => marker.id === this.selected)) continue
      const center = cell.bounds.getCenter(this.projected)
      const depth = -(matrix[2]! * center.x + matrix[6]! * center.y + matrix[10]! * center.z + matrix[14]!)
      if (depth <= this.camera.near) continue
      const width = Math.max(cell.bounds.max.x - cell.bounds.min.x, cell.bounds.max.y - cell.bounds.min.y,
        cell.bounds.max.z - cell.bounds.min.z)
      const pixels = width * this.height / (2 * Math.tan(this.camera.fov * Math.PI / 360) * depth)
      const detailThreshold = Math.max(72, Math.sqrt(Math.max(...cell.groups.map(group => group.length))) * 32)
      if (pixels < detailThreshold * (this.foldedCells.has(cell.key) ? 1.35 : 1)) folded.add(cell.key)
    }
    if (!this.frontierDirty && folded.size === this.foldedCells.size && [...folded].every(key => this.foldedCells.has(key))) return
    this.frontierDirty = false
    this.cameraChanged = true
    this.foldedCells = folded
    this.displayById = new Map(this.byId)
    this.proxyCells.clear()
    this.spatialGrouped = 0
    const representatives = new Map<string, string>()
    for (const cell of this.cells) {
      cell.displayed = [...cell.markers]
      if (!folded.has(cell.key)) continue
      const hidden = new Set<string>()
      for (const group of cell.groups) {
        const first = group[0]!, id = `@cell:${cell.key}:${first.shape}:${first.color}`
        const point = { x: 0, y: 0, z: 0 }
        for (const member of group) {
          hidden.add(member.id); representatives.set(member.id, id)
          point.x += member.point.x; point.y += member.point.y; point.z += member.point.z
        }
        point.x /= group.length; point.y /= group.length; point.z /= group.length
        const marker = { ...first, id, point, title: this.groupTitle(group.length), grouped: group.length - 1, priority: 30, size: 48 }
        this.displayById.set(id, marker); this.proxyCells.set(id, cell.key)
        cell.displayed.push(marker)
        this.spatialGrouped += group.length - 1
      }
      cell.displayed = cell.displayed.filter(marker => !hidden.has(marker.id))
    }
    this.rebuildLinks(representatives)
  }

  private rebuildLinks(representatives: ReadonlyMap<string, string>): void {
    this.linkPaints = []
    this.linkBuffersDirty = true
    const pairs = new Set<string>()
    for (const edge of this.sourceLinks) {
      const source = this.displayById.get(representatives.get(edge.source) ?? edge.source)
      const target = this.displayById.get(representatives.get(edge.target) ?? edge.target)
      if (!source || !target || source === target) continue
      // Aggregate only equal type/direction/status. Internal links remain in
      // sourceLinks and reappear when their spatial cell unfolds.
      const key = JSON.stringify([source.id, target.id, edge.type, edge.suggested])
      if (pairs.has(key)) continue
      pairs.add(key)
      this.colors.set(edge.color)
      const start = [source.point.x, source.point.y, source.point.z]
      const end = [target.point.x, target.point.y, target.point.z]
      this.linkPaints.push({ source: source.point, target: target.point, curvature: edge.curvature,
        width: Math.max(edge.width, edge.overviewStyle.width), chunks: 0, visibleMask: 0,
        attributes: { startHigh: start.map(Math.fround), startLow: start.map(value => value - Math.fround(value)),
          endHigh: end.map(Math.fround), endLow: end.map(value => value - Math.fround(value)),
          tint: [this.colors.r, this.colors.g, this.colors.b], suggestion: [Number(edge.suggested)], curvature: [edge.curvature],
          appearance: [edge.overviewStyle.width, edge.width, edge.overviewStyle.opacity, edge.opacity] } })
    }
  }

  private paintLinks(): void {
    let count = 0
    this.visibleLinks = 0
    const matrix = this.camera.matrixWorldInverse.elements, origin = this.camera.position
    const near = this.camera.near
    const scale = this.height / (2 * Math.tan(this.camera.fov * Math.PI / 360))
    const limit = Math.max(this.width, this.height) * 2
    for (const link of this.linkPaints) {
      const sx = link.source.x - origin.x, sy = link.source.y - origin.y, sz = link.source.z - origin.z
      const tx = link.target.x - origin.x, ty = link.target.y - origin.y, tz = link.target.z - origin.z
      let ax = matrix[0]! * sx + matrix[4]! * sy + matrix[8]! * sz
      let ay = matrix[1]! * sx + matrix[5]! * sy + matrix[9]! * sz
      let az = matrix[2]! * sx + matrix[6]! * sy + matrix[10]! * sz
      let bx = matrix[0]! * tx + matrix[4]! * ty + matrix[8]! * tz
      let by = matrix[1]! * tx + matrix[5]! * ty + matrix[9]! * tz
      let bz = matrix[2]! * tx + matrix[6]! * ty + matrix[10]! * tz
      let chunks = 0, visibleMask = 0
      if (az < -near || bz < -near) {
        // Match the shader's near-plane clipping before estimating screen size.
        if (az > -near) {
          const fraction = (-near - az) / (bz - az)
          ax += (bx - ax) * fraction; ay += (by - ay) * fraction; az = -near
        } else if (bz > -near) {
          const fraction = (-near - bz) / (az - bz)
          bx += (ax - bx) * fraction; by += (ay - by) * fraction; bz = -near
        }
        ax *= scale / -az; ay *= scale / -az
        bx *= scale / -bz; by *= scale / -bz
        const length = Math.max(Math.hypot(bx - ax, by - ay), 0.0001)
        const bend = Math.max(-limit, Math.min(limit, link.curvature * length))
        // The entire quadratic lies within its control-point bounds. Cull only
        // when that envelope cannot touch the viewport (including its stroke).
        const cx = (ax + bx) / 2 - (by - ay) / length * bend
        const cy = (ay + by) / 2 + (bx - ax) / length * bend
        const halfWidth = this.width / 2 + link.width + 1, halfHeight = this.height / 2 + link.width + 1
        if (Math.max(ax, bx, cx) >= -halfWidth && Math.min(ax, bx, cx) <= halfWidth
          && Math.max(ay, by, cy) >= -halfHeight && Math.min(ay, by, cy) <= halfHeight) {
          // The quadratic's chord error is abs(bend) / (2 * segments^2).
          // Target subpixel error (0.75 CSS px), rather than oversampling long,
          // nearly straight links. Four-segment steps and hysteresis limit churn.
          const needed = Math.min(64, Math.max(4, Math.sqrt(Math.abs(bend) / 1.5)))
          chunks = Math.ceil(needed / 4)
          if (chunks < link.chunks && needed > (link.chunks - 1) * 4 - 1) chunks = link.chunks
          // A long relation crossing the camera can have enormous projected
          // endpoints. Submit only chunks whose curve envelope touches the
          // viewport, rather than drawing all of its offscreen subdivisions.
          const dx = bx - ax, dy = by - ay
          const nx = -dy / length, ny = dx / length
          for (let chunk = 0; chunk < chunks; chunk++) {
            const start = chunk / chunks, end = (chunk + 1) / chunks
            const startBend = 2 * bend * start * (1 - start), endBend = 2 * bend * end * (1 - end)
            const startX = ax + dx * start + nx * startBend, startY = ay + dy * start + ny * startBend
            const endX = ax + dx * end + nx * endBend, endY = ay + dy * end + ny * endBend
            const controlX = startX + (dx + nx * 2 * bend * (1 - 2 * start)) / (2 * chunks)
            const controlY = startY + (dy + ny * 2 * bend * (1 - 2 * start)) / (2 * chunks)
            if (Math.max(startX, endX, controlX) < -halfWidth || Math.min(startX, endX, controlX) > halfWidth
              || Math.max(startY, endY, controlY) < -halfHeight || Math.min(startY, endY, controlY) > halfHeight) continue
            visibleMask |= 1 << chunk
            count++
          }
        }
      }
      if (chunks !== link.chunks) { link.chunks = chunks; this.linkBuffersDirty = true }
      if (visibleMask !== link.visibleMask) { link.visibleMask = visibleMask; this.linkBuffersDirty = true }
      if (visibleMask) this.visibleLinks++
    }
    if (!this.linkBuffersDirty) return
    if (count > this.linkCapacity) {
      // Reuse GPU buffers across regrouping; release the old allocation before
      // growing it, since replacing attributes alone does not free GPU memory.
      this.linkGeometry.dispose()
      this.linkCapacity = 2 ** Math.ceil(Math.log2(Math.max(16, count)))
      for (const [name, components] of [['startHigh', 3], ['startLow', 3], ['endHigh', 3], ['endLow', 3], ['tint', 3], ['suggestion', 1], ['appearance', 4], ['curvature', 1], ['curveRange', 2]] as const) {
        this.linkGeometry.setAttribute(name, new InstancedBufferAttribute(new Float32Array(this.linkCapacity * components), components).setUsage(DynamicDrawUsage))
      }
    }
    for (const [name, attribute] of Object.entries(this.linkGeometry.attributes)) {
      if (!(attribute instanceof InstancedBufferAttribute)) continue
      let index = 0
      for (const link of this.linkPaints) {
        const values = link.attributes[name]
        for (let chunk = 0; chunk < link.chunks; chunk++) {
          if (!(link.visibleMask & (1 << chunk))) continue
          if (name === 'curveRange') attribute.setXY(index, chunk / link.chunks, 1 / link.chunks)
          else attribute.array.set(values!, index * attribute.itemSize)
          index++
        }
      }
      attribute.clearUpdateRanges(); attribute.addUpdateRange(0, count * attribute.itemSize); attribute.needsUpdate = true
    }
    this.linkGeometry.instanceCount = count
    this.linkBuffersDirty = false
  }

  private activate(id: string): void {
    const cell = this.proxyCells.get(id)
    if (cell) {
      this.openedCells.add(cell)
      this.focus(id)
    } else this.onSelect(id)
  }

  private paintOverlay(): void {
    this.imageBounds.clear()
    const aliveLabels = new Set<string>(), aliveImages = new Set<string>()
    const occupied: { x: number; y: number; w: number; h: number }[] = []
    const intersects = (x: number, y: number, w: number, h: number): boolean => occupied.some(rect =>
      Math.abs(rect.x - x) < (rect.w + w) / 2 + 4 && Math.abs(rect.y - y) < (rect.h + h) / 2 + 4)
    const ordered = [...this.projections.values()].filter(point => {
      const marker = this.displayById.get(point.id)!
      return point.near || this.previews.has(point.id) || marker.priority >= 10 || marker.grouped || point.id === this.selected
    }).sort((a, b) =>
      (a.id === this.selected ? -100 : -this.displayById.get(a.id)!.priority)
      - (b.id === this.selected ? -100 : -this.displayById.get(b.id)!.priority))
    for (const point of ordered) {
      const marker = this.displayById.get(point.id)!
      const preview = this.previews.get(marker.id)
      let imageSize = 0
      if (preview && point.near) {
        let clearance = preview.nativeSize
        for (let bx = Math.floor((point.x - 332) / 80); bx <= Math.floor((point.x + 332) / 80); bx++) {
          for (let by = Math.floor((point.y - 332) / 80); by <= Math.floor((point.y + 332) / 80); by++) {
            for (const neighbor of this.buckets.get(`${bx},${by}`) ?? []) if (neighbor.id !== point.id) {
              clearance = Math.min(clearance, Math.max(0,
                Math.max(Math.abs(neighbor.x - point.x), Math.abs(neighbor.y - point.y)) - neighbor.size / 2 - 12))
            }
          }
        }
        const localZoom = this.fitDistance / Math.max(this.camera.near, -point.depth)
        imageSize = Math.min(preview.nativeSize, 56 * Math.max(1, localZoom / 3), clearance)
        const w = preview.aspect >= 1 ? imageSize : imageSize * preview.aspect
        const h = preview.aspect >= 1 ? imageSize / preview.aspect : imageSize
        if (imageSize >= 24 && !intersects(point.x, point.y, w, h)) {
          let img = this.images.get(marker.id)
          if (!img) {
            img = document.createElement('img'); img.alt = ''; img.draggable = false
            Object.assign(img.style, { position: 'absolute', transform: 'translate(-50%, -50%)', objectFit: 'contain' })
            this.images.set(marker.id, img); this.overlay.append(img)
          }
          if (img.getAttribute('src') !== preview.url) img.src = preview.url
          Object.assign(img.style, { left: `${point.x}px`, top: `${point.y}px`, width: `${w}px`, height: `${h}px` })
          occupied.push({ x: point.x, y: point.y, w, h }); aliveImages.add(marker.id)
          this.imageBounds.set(marker.id, { w, h })
        } else imageSize = 0
      }
      if (aliveLabels.size >= (this.zoom < 1.8 ? 12 : 80)) continue
      if (!point.near && marker.priority < 10 && !marker.grouped && marker.id !== this.selected) continue
      const title = marker.title
      const w = Math.min(180, title.length * 7 + 8), h = 20
      const y = point.y + Math.max(point.size, imageSize) / 2 + h / 2 + 4
      if (point.x - w / 2 < 0 || point.x + w / 2 > this.width || y + h / 2 > this.height || intersects(point.x, y, w, h)) continue
      let label = this.elements.get(marker.id)
      if (!label) {
        label = document.createElement('div')
        Object.assign(label.style, { position: 'absolute', transform: 'translate(-50%, -50%)', font: '12px sans-serif',
          whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden', borderRadius: '3px', padding: '2px 4px' })
        this.elements.set(marker.id, label); this.overlay.append(label)
      }
      label.textContent = title
      Object.assign(label.style, { left: `${point.x}px`, top: `${y}px`, maxWidth: `${w}px`, color: this.ink })
      occupied.push({ x: point.x, y, w, h }); aliveLabels.add(marker.id)
    }
    for (const [id, label] of this.elements) if (!aliveLabels.has(id)) { label.remove(); this.elements.delete(id) }
    for (const [id, img] of this.images) if (!aliveImages.has(id)) { img.remove(); this.images.delete(id) }
  }

  private pointerDown = (event: PointerEvent): void => {
    if (this.disposed || this.suspended) return
    this.host.focus({ preventScroll: true })
    if (event.pointerType === 'touch') this.touchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (this.pointer) { this.pointer.moved = true; return }
    if (!event.isPrimary || event.button !== 0) return
    const nodeId = this.pick(event.clientX, event.clientY)
    const marker = nodeId ? this.displayById.get(nodeId) : null
    const pivot = marker ? new Vector3(marker.point.x, marker.point.y, marker.point.z) : this.controls.target.clone()
    // The capture listener chooses the native gesture before OrbitControls
    // handles this press. Keep that choice until release, independent of hover.
    if (event.pointerType === 'mouse') {
      this.controls.mouseButtons.LEFT = nodeId || event.ctrlKey || event.metaKey || event.shiftKey ? MOUSE.ROTATE : MOUSE.PAN
    }
    this.pointer = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, lastX: event.clientX, lastY: event.clientY,
      nodeId, moved: false, orbit: marker && event.pointerType === 'mouse' && !event.ctrlKey && !event.metaKey && !event.shiftKey
        ? this.orbitGesture(pivot, event.clientX, event.clientY) : null }
  }
  private pointerMove = (event: PointerEvent): void => {
    if (event.pointerType === 'touch' && this.touchPointers.has(event.pointerId)) {
      const previous = this.pinchDistance()
      this.touchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
      const next = this.pinchDistance()
      if (previous > 0 && next > 0) this.zoomBy(next / previous)
    }
    const pointer = this.pointer
    if (!pointer || pointer.pointerId !== event.pointerId) return
    pointer.lastX = event.clientX; pointer.lastY = event.clientY
    const threshold = event.pointerType === 'touch' ? 5 : 0
    if (Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > threshold) pointer.moved = true
    // A deliberate left drag leaves the centered overview before native panning
    // updates the camera; otherwise the change handler would undo its movement.
    if (event.pointerType === 'mouse' && pointer.moved && (event.buttons & 1)) this.overview = false
    if (pointer.orbit && pointer.moved && (event.buttons & 1)) {
      // Orbit the camera and its viewing target as one rigid frame around the
      // picked pivot. The pivot is not the viewing target: its screen position
      // stays unchanged, including at the first pixel of the gesture.
      event.preventDefault(); event.stopImmediatePropagation()
      this.overview = false
      const gesture = pointer.orbit, speed = 2 * Math.PI * this.controls.rotateSpeed / this.height
      const yaw = new Quaternion().setFromAxisAngle(this.camera.up, -(event.clientX - gesture.x) * speed)
      const phi = Math.max(0.000001, Math.min(Math.PI - 0.000001, gesture.phi - (event.clientY - gesture.y) * speed))
      const rotation = new Quaternion().setFromAxisAngle(gesture.right.clone().applyQuaternion(yaw), phi - gesture.phi).multiply(yaw)
      this.camera.position.copy(gesture.position).sub(gesture.pivot).applyQuaternion(rotation).add(gesture.pivot)
      this.controls.target.copy(gesture.target).sub(gesture.pivot).applyQuaternion(rotation).add(gesture.pivot)
      this.controls.update()
      this.schedule()
    }
  }
  private orbitGesture(pivot: Vector3, x: number, y: number): OrbitGesture {
    const direction = this.camera.position.clone().sub(this.controls.target).normalize()
    return { x, y, pivot, position: this.camera.position.clone(), target: this.controls.target.clone(),
      right: new Vector3(1, 0, 0).applyQuaternion(this.camera.quaternion),
      phi: Math.acos(Math.max(-1, Math.min(1, direction.dot(this.camera.up)))) }
  }
  private pinchDistance(): number {
    if (this.touchPointers.size !== 2) return 0
    const [first, second] = [...this.touchPointers.values()]
    return Math.hypot(first!.x - second!.x, first!.y - second!.y)
  }
  private pointerUp = (event: PointerEvent): void => {
    this.touchPointers.delete(event.pointerId)
    const pointer = this.pointer
    if (!pointer || pointer.pointerId !== event.pointerId) return
    this.pointer = null
    const threshold = event.pointerType === 'touch' ? 5 : 0
    if (pointer.moved || event.button !== 0 || Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > threshold) return
    if (pointer.nodeId && this.pick(event.clientX, event.clientY) === pointer.nodeId) this.activate(pointer.nodeId)
  }
  private pointerCancel = (event: PointerEvent): void => {
    this.touchPointers.delete(event.pointerId)
    if (this.pointer?.pointerId === event.pointerId) this.pointer = null
  }
  private wheel = (event: WheelEvent): void => {
    if (this.disposed || this.suspended || event.deltaY === 0) return
    if (this.pointer) this.pointer.moved = true
    event.preventDefault(); event.stopImmediatePropagation()
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.height : 1
    this.zoomBy(2 ** Math.max(-1, Math.min(1, -event.deltaY * unit * 0.0016)), { x: event.clientX, y: event.clientY })
    if (this.pointer?.orbit) this.pointer.orbit = this.orbitGesture(this.pointer.orbit.pivot, this.pointer.lastX, this.pointer.lastY)
  }
  private pick(clientX: number, clientY: number): string | null {
    const rect = this.host.getBoundingClientRect(), x = clientX - rect.left, y = clientY - rect.top
    let nearest: Graph3dProjection | null = null, distance = Infinity
    for (let bx = Math.floor((x - 160) / 80); bx <= Math.floor((x + 160) / 80); bx++) {
      for (let by = Math.floor((y - 160) / 80); by <= Math.floor((y + 160) / 80); by++) {
        for (const point of this.buckets.get(`${bx},${by}`) ?? []) {
          const d = Math.hypot(point.x - x, point.y - y)
          const preview = this.imageBounds.get(point.id)
          const hit = preview ? Math.abs(x - point.x) <= preview.w / 2 && Math.abs(y - point.y) <= preview.h / 2 : d <= Math.max(8, point.size / 2)
          if (hit && (d < distance || d === distance && point.depth > (nearest?.depth ?? -Infinity))) {
            nearest = point; distance = d
          }
        }
      }
    }
    return nearest?.id ?? null
  }
  private keydown = (event: KeyboardEvent): void => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return
    if (event.key === 'Home') { event.preventDefault(); this.fit() }
    else if (event.key === '+' || event.key === '=') { event.preventDefault(); this.zoomBy(1.25) }
    else if (event.key === '-' || event.key === '_') { event.preventDefault(); this.zoomBy(0.8) }
    else if (event.key === 'Enter') {
      const id = this.selected ?? this.projections.keys().next().value
      if (id) { event.preventDefault(); this.activate(id) }
    } else if (event.key.startsWith('Arrow')) {
      event.preventDefault()
      const ids = [...this.projections.keys()]
      if (!ids.length) return
      const index = this.selected ? ids.indexOf(this.selected) : -1
      const step = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1
      this.selected = ids[(index + step + ids.length) % ids.length]!
      this.host.setAttribute('aria-description', this.displayById.get(this.selected)?.title ?? '')
      this.schedule()
    }
  }
  private contextLost = (event: Event): void => { event.preventDefault(); this.onFailure() }
  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    if (this.frame !== null) cancelAnimationFrame(this.frame)
    this.controls.removeEventListener('change', this.changed)
    this.controls.dispose()
    this.renderer.domElement.removeEventListener('pointerdown', this.pointerDown, true)
    this.renderer.domElement.removeEventListener('pointermove', this.pointerMove, true)
    this.renderer.domElement.removeEventListener('pointerup', this.pointerUp, true)
    this.renderer.domElement.removeEventListener('pointercancel', this.pointerCancel, true)
    this.renderer.domElement.removeEventListener('lostpointercapture', this.pointerCancel, true)
    this.renderer.domElement.removeEventListener('wheel', this.wheel, true)
    this.renderer.domElement.removeEventListener('webglcontextlost', this.contextLost)
    this.host.removeEventListener('keydown', this.keydown)
    this.geometry.dispose(); this.material.dispose(); this.linkGeometry.dispose(); this.linkMaterial.dispose(); this.glyphs.dispose()
    this.renderer.dispose(); this.renderer.forceContextLoss()
    this.renderer.domElement.remove(); this.overlay.remove()
    this.markers = []; this.byId.clear(); this.projections.clear(); this.buckets.clear(); this.previews.clear()
    this.cells = []; this.fitPoints = []
    this.displayById.clear(); this.proxyCells.clear(); this.openedCells.clear(); this.foldedCells.clear(); this.sourceLinks = []; this.linkPaints = []
    this.elements.clear(); this.images.clear()
    this.imageBounds.clear()
    this.pointer = null; this.touchPointers.clear()
    this.onCamera = () => undefined
  }
}
