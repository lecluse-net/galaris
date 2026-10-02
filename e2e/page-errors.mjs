// WebKit emits a native XHR page error when a full navigation cancels a request.
// Exclude it only with matching requestfailed evidence; real CORS/JS errors remain.
export function collectPageErrors(page, { waitForRequest = () => true } = {}) {
  const errors = []
  const cancellations = []
  const pending = new Set()
  let replacingDocument = false
  page.on('request', request => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
      // Requests from the departing document can start during navigation and
      // disappear without a requestfinished/requestfailed event.
      replacingDocument = true
      pending.clear()
    } else if (!replacingDocument && new URL(request.url()).pathname.startsWith('/api/') && waitForRequest(request)) pending.add(request)
  })
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) replacingDocument = false
  })
  page.on('requestfinished', request => pending.delete(request))
  page.on('requestfailed', request => {
    pending.delete(request)
    if (/Load request cancelled|net::ERR_ABORTED/i.test(request.failure()?.errorText ?? '')) {
      cancellations.push({ url: request.url(), at: Date.now() })
    }
  })
  page.on('pageerror', error => {
    // Playwright can split WebKit's native error name at the URL's colon.
    const pattern = /^XMLHttpRequest cannot load (https?):\s*\/+([^\s]+) due to access control checks\./
    const match = pattern.exec(error.stack ?? '') ?? pattern.exec(`${error.name}: ${error.message}`)
    const url = match ? `${match[1]}://${match[2]}` : undefined
    errors.push({ message: error.message, url, at: Date.now() })
  })
  const observed = () => errors.filter(error => !error.url || !cancellations.some(cancelled =>
      cancelled.url === error.url && Math.abs(cancelled.at - error.at) < 250,
    )).map(error => error.message)
  // Wait for finite API responses before deliberately replacing their document.
  // Socket.IO long polling is excluded; no arbitrary idle delay is required.
  observed.settle = async () => {
    do {
      const requests = new Set(pending)
      if (requests.size) await new Promise(resolve => {
        const finished = request => {
          requests.delete(request)
          if (!requests.size) {
            page.off('requestfinished', finished)
            page.off('requestfailed', finished)
            resolve()
          }
        }
        page.on('requestfinished', finished)
        page.on('requestfailed', finished)
        for (const request of requests) if (!pending.has(request)) finished(request)
      })
      await page.evaluate(() => Promise.resolve())
    } while (pending.size)
  }
  return observed
}
