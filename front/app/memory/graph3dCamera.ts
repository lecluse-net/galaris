import type { GraphPoint3d } from './graph3dLayout'

/** Fit the actual perspective footprint, rather than a sphere which wastes
 * horizontal space on wide screens. The target also centers the projected
 * bounds when nodes have unequal depths. Only framing operations call this. */
export function fitGraph3d(points: readonly GraphPoint3d[], width: number, height: number, direction: GraphPoint3d): {
  center: GraphPoint3d; boundsCenter: GraphPoint3d; distance: number
} {
  const length = Math.hypot(direction.x, direction.y, direction.z)
  const back = length ? { x: direction.x / length, y: direction.y / length, z: direction.z / length } : { x: 0, y: 0, z: 1 }
  const horizontal = Math.hypot(back.x, back.z)
  const right = horizontal > 1e-8 ? { x: back.z / horizontal, y: 0, z: -back.x / horizontal } : { x: 1, y: 0, z: 0 }
  const up = { x: back.y * right.z - back.z * right.y,
    y: back.z * right.x - back.x * right.z, z: back.x * right.y - back.y * right.x }
  let minX = Infinity, minY = Infinity, minZ = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const point of points) {
    minX = Math.min(minX, point.x); maxX = Math.max(maxX, point.x)
    minY = Math.min(minY, point.y); maxY = Math.max(maxY, point.y)
    minZ = Math.min(minZ, point.z); maxZ = Math.max(maxZ, point.z)
  }
  const boundsCenter = points.length ? { x: (minX + maxX) / 2, y: (minY + maxY) / 2, z: (minZ + maxZ) / 2 } : { x: 0, y: 0, z: 0 }
  const padding = Math.min(Math.min(width, height) * 0.2, 36 + Math.min(width, height) * 0.02)
  const tangent = Math.tan(Math.PI / 8)
  const tanX = tangent * Math.max(1, width - padding * 2) / Math.max(1, height)
  const tanY = tangent * Math.max(1, height - padding * 2) / Math.max(1, height)
  const projected = points.map(point => {
    const x = point.x - boundsCenter.x, y = point.y - boundsCenter.y, z = point.z - boundsCenter.z
    return { x: x * right.x + y * right.y + z * right.z,
      y: x * up.x + y * up.y + z * up.z, z: x * back.x + y * back.y + z * back.z }
  })
  if (!projected.length) return { center: boundsCenter, boundsCenter, distance: 80 }
  let lowerX = -Infinity, upperX = Infinity, lowerY = -Infinity, upperY = Infinity, nearest = -Infinity
  for (const point of projected) {
    lowerX = Math.max(lowerX, point.x + tanX * point.z); upperX = Math.min(upperX, point.x - tanX * point.z)
    lowerY = Math.max(lowerY, point.y + tanY * point.z); upperY = Math.min(upperY, point.y - tanY * point.z)
    nearest = Math.max(nearest, point.z)
  }
  const distance = Math.max(80, nearest + 1, (lowerX - upperX) / (2 * tanX), (lowerY - upperY) / (2 * tanY))
  const balance = (axis: 'x' | 'y', lower: number, upper: number, tan: number): number => {
    let low = lower - distance * tan, high = upper + distance * tan
    for (let iteration = 0; iteration < 20; iteration++) {
      const offset = (low + high) / 2
      let min = Infinity, max = -Infinity
      for (const point of projected) {
        const value = (point[axis] - offset) / (distance - point.z)
        min = Math.min(min, value); max = Math.max(max, value)
      }
      if (min + max > 0) low = offset
      else high = offset
    }
    return (low + high) / 2
  }
  const x = balance('x', lowerX, upperX, tanX), y = balance('y', lowerY, upperY, tanY)
  return { distance, boundsCenter, center: { x: boundsCenter.x + right.x * x + up.x * y,
    y: boundsCenter.y + right.y * x + up.y * y, z: boundsCenter.z + right.z * x + up.z * y } }
}
