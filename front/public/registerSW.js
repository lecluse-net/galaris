// Compatibility bootstrap for HTML still served by an older service worker.
// Current builds register through virtual:pwa-register instead.
if ('serviceWorker' in navigator) {
  let controlled = !!navigator.serviceWorker.controller
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (controlled) window.location.reload()
    controlled = true
  })
  navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' }).catch(() => {
    // A later navigation retries if the deployment is temporarily unavailable.
  })
}
