import { init, use } from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TitleComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { chartAttribute, encodeEditorialChart, type EditorialChart } from './editorialChart'
import { isStandaloneSvg } from './editorialSvg'
import { solaire } from './solaire'

use([SVGRenderer, BarChart, LineChart, PieChart, GridComponent, TitleComponent])

const colors = [solaire.blue, solaire.green, solaire.orange, solaire.iris, solaire.red, solaire.cyan,
  solaire.fuchsia, solaire.yellow, solaire.violet, solaire.salmon, solaire.gray].map(color => color.accent)
const ink = '#292C30'

export function renderEditorialChart(data: EditorialChart, fallbackTitle: string): string {
  const chart = init(null, undefined, { renderer: 'svg', ssr: true, width: 640, height: 360 })
  try {
    const pie = data.type === 'pie'
    chart.setOption({
      animation: false,
      backgroundColor: '#FFFFFF',
      color: colors,
      textStyle: { fontFamily: 'sans-serif', fontSize: 16, color: ink },
      title: { text: data.title, left: 'center', top: 12,
        textStyle: { width: 600, overflow: 'truncate', fontSize: 20, color: ink } },
      ...(pie ? {
        series: [{ type: 'pie', center: ['50%', data.title ? '55%' : '50%'], radius: '52%',
          stillShowZeroSum: false, data: data.rows.map(({ label, value }) => ({ name: label, value })),
          label: { color: ink, width: 150, fontSize: 18, overflow: 'truncate', formatter: '{b}\n{c} ({d}%)' } }],
      } : {
        grid: { left: 98, right: 32, top: data.title ? 64 : 24, bottom: 70 },
        xAxis: { type: 'category', data: data.rows.map(row => row.label),
          axisLabel: { color: ink, fontSize: 18, width: Math.min(130, 480 / data.rows.length), overflow: 'truncate' } },
        yAxis: { type: 'value', axisLabel: { color: ink, fontSize: 18 }, splitLine: { lineStyle: { color: solaire.gray.light } } },
        series: [{ type: data.type, data: data.rows.map(row => row.value), barMaxWidth: 80,
          symbolSize: 8, lineStyle: { width: 3 } }],
      }),
    })
    const template = document.createElement('template')
    template.innerHTML = chart.renderToSVGString()
    const svg = template.content.firstElementChild
    if (!svg) throw new Error('Chart SVG unavailable')
    svg.querySelectorAll('style').forEach(style => style.remove())
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title')
    title.textContent = data.title || fallbackTitle
    svg.prepend(title)
    svg.setAttribute('role', 'img')
    svg.setAttribute(chartAttribute, encodeEditorialChart(data))
    if (!isStandaloneSvg(svg)) throw new Error('Chart SVG is not standalone')
    return svg.outerHTML
  } finally {
    chart.dispose()
  }
}
