import { layoutGraph3d, type Graph3dLayoutRequest } from './graph3dLayout'

self.onmessage = (event: MessageEvent<Graph3dLayoutRequest>): void => {
  self.postMessage(layoutGraph3d(event.data))
}
