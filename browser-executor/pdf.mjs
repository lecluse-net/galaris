import { BrowserRequestError } from './lib.mjs';

export const PDF_HTML_MAX_BYTES = 12 * 1024 * 1024;
const PDF_MAX_BYTES = 16 * 1024 * 1024;

/** Print a disposable, offline page; no document JavaScript or session state is allowed. */
export async function renderStaticPdf(browser, html, { firstPageOnly = false } = {}) {
  if (typeof html !== 'string' || !html.trim() || Buffer.byteLength(html) > PDF_HTML_MAX_BYTES) {
    throw new BrowserRequestError('invalid_pdf_html', 'The document is empty or too large.', 413);
  }
  const context = await browser.newContext({
    javaScriptEnabled: false, offline: true, serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 794, height: 1123 },
  });
  const deadline = setTimeout(() => { void context.close().catch(() => {}); }, 30_000);
  try {
    await context.route('**/*', route => route.abort('blockedbyclient'));
    const page = await context.newPage();
    await page.setContent(html, { waitUntil: 'load', timeout: 20_000 });
    await page.evaluate(async () => {
      await Promise.all([...document.images].map(image => image.decode()));
      await document.fonts.ready;
    });
    const pdf = await page.pdf({
      format: 'A4', margin: { top: '10mm', right: '10mm', bottom: '10mm', left: '10mm' },
      preferCSSPageSize: true, printBackground: true, tagged: true, outline: true,
      pageRanges: firstPageOnly ? '1' : undefined,
    });
    if (pdf.length > PDF_MAX_BYTES) throw new BrowserRequestError('pdf_too_large', 'The PDF is too large.', 413);
    return pdf;
  } finally {
    clearTimeout(deadline);
    await context.close();
  }
}
