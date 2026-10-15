// Shared local-file renderer. The HTTP shell owns the rendering CSP; only
// the inner file frame has an opaque origin. The app keeps its own policy.
(() => {
  const sandbox = 'allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads allow-presentation'
  const payloadElement = document.getElementById('resource-payload')
  const frame = document.createElement('iframe')
  // Only these fixed shells keep the application origin. The actual file
  // always runs in the inner frame without allow-same-origin.
  frame.setAttribute('sandbox', payloadElement ? sandbox + ' allow-same-origin' : sandbox)
  frame.referrerPolicy = 'no-referrer'
  if (payloadElement) {
    const payload = JSON.parse(payloadElement.textContent)
    frame.title = payload.name
    frame.addEventListener('load', () => {
      frame.contentWindow.postMessage({ type: 'galaris.resource.render', ...payload }, '*')
    }, { once: true })
    frame.src = new URL('./resource-viewer.html', document.currentScript.src).href
    document.body.append(frame)
  } else {
    window.addEventListener('message', function receive(event) {
      if (event.source !== window.parent || event.data?.type !== 'galaris.resource.render'
          || typeof event.data.content !== 'string' || typeof event.data.name !== 'string') return
      window.removeEventListener('message', receive)
      frame.title = event.data.name
      frame.srcdoc = event.data.content
      document.body.append(frame)
    })
  }
})()
