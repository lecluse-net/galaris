import { Node } from '@tiptap/core'
import { chartAttribute, chartCaption, chartSelector, encodeEditorialChart, readChartFigure, type EditorialChart } from './editorialChart'
import { renderChartFigure } from './editorialChartDisplay'

export const EditorialChartNode = Node.create({
  name: 'editorialChart', group: 'block', atom: true, draggable: true, priority: 1160,
  addAttributes: () => ({ chart: { default: null } }),
  parseHTML: () => [{ tag: chartSelector, getAttrs: element => {
    const chart = readChartFigure(element)
    return chart ? { chart } : false
  } }],
  renderHTML: ({ node }) => {
    const chart = node.attrs.chart as EditorialChart
    return ['figure', { [chartAttribute]: encodeEditorialChart(chart) }, ['figcaption', {}, chartCaption(chart)]]
  },
  addNodeView: () => ({ node }) => {
    const chart = node.attrs.chart as EditorialChart
    const dom = document.createElement('figure')
    const caption = document.createElement('figcaption')
    caption.textContent = chartCaption(chart)
    dom.append(caption)
    dom.contentEditable = 'false'
    void renderChartFigure(dom, chart).catch(() => { /* Leave the text fallback visible. */ })
    return { dom }
  },
})
