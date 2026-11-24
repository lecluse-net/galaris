import { chartCaption, chartSelector, readChartFigure, type EditorialChart } from './editorialChart'
import { svgImage } from './editorialSvg'

export async function renderChartFigure(figure: Element, chart: EditorialChart): Promise<void> {
  const { renderEditorialChart } = await import('./editorialChartRendering')
  const image = svgImage(figure.ownerDocument, renderEditorialChart(chart, chartCaption(chart)))
  if (!image) throw new Error('Unable to display document chart')
  figure.replaceChildren(image)
}

export async function renderChartFigures(root: ParentNode): Promise<void> {
  await Promise.all([...root.querySelectorAll(chartSelector)].map(async figure => {
    const chart = readChartFigure(figure)
    if (chart) await renderChartFigure(figure, chart)
  }))
}
