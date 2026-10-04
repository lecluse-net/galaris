import { getInstanceByDom, registerPostUpdate, type ECharts, type List } from 'echarts/core'

const dataByChart = new WeakMap<ECharts, List>()

// The public extension lifecycle exposes the live data used by the native force
// layout. Retain a read-only reference instead of accessing private chart APIs.
registerPostUpdate((model, api) => {
  const chart = getInstanceByDom(api.getDom())
  if (!chart) return
  const series = model.getSeriesByIndex(0)
  if (series?.subType === 'graph') dataByChart.set(chart, series.getData())
  else dataByChart.delete(chart)
})

export function graphViewportData(chart: ECharts): List | undefined {
  return dataByChart.get(chart)
}
