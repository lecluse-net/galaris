import type { DocumentApp } from '@/app/document/documentApps'
import { applicationSnapshotScript } from '@/app/document/documentAppSnapshot'
import threeSource from 'virtual:galaris-document-three'
import { applyDocumentContrast, solaire } from '@/core/util'

// The outer frame owns frame-src: blob:. It also blocks self-navigation of the
// untrusted inner frame, a channel that connect-src alone does not restrict.
const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src blob:; worker-src 'none'; form-action 'none'; base-uri 'none'"
const quoted = (value: unknown): string => JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026')

function hasAuthoredJavaScript(app: DocumentApp): boolean {
  if (app.javascript?.trim()) return true
  const doc = new DOMParser().parseFromString('<body>' + (app.html ?? ''), 'text/html')
  return Boolean(doc.querySelector('script')) || [...doc.querySelectorAll('*')].some(element =>
    [...element.attributes].some(attribute => attribute.name.startsWith('on')
      || /^\s*javascript:/i.test(attribute.value.replace(/[\t\r\n]/g, ''))),
  )
}

export function appSandboxDocument(app: DocumentApp, dark = false, notifyFocus = false): string {
  // CSS, SVG and native disclosures need isolation, but no 3D engine. Keep the
  // existing library available to all authored scripts, including inline handlers.
  const libraries = hasAuthoredJavaScript(app) ? '<script>' + threeSource.replace(/<\/script/gi, '<\\/script') + '</script>' : ''
  const sdk = `
    (() => {
      // CSP connect-src does not cover WebRTC in every engine. No alternate realm
      // (worker, child frame or popup) is permitted by this sandbox.
      for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'mozRTCPeerConnection', 'RTCIceGatherer', 'RTCIceTransport', 'RTCDtlsTransport']) {
        Object.defineProperty(window, name, {value: undefined, writable: false, configurable: false});
      }
      // Navigating to an executable blob would create a fresh realm before the outer
      // frame's load handler can stop it. Keep blob URLs for passive media only.
      const blobType = Function.prototype.call.bind(Object.getOwnPropertyDescriptor(Blob.prototype, 'type').get);
      const passiveType = Set.prototype.has.bind(new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/webm', 'video/mp4', 'video/webm', 'video/ogg']));
      const createBlobUrl = URL.createObjectURL.bind(URL);
      const passiveBlobUrl = value => {
        if (!passiveType(blobType(value))) throw new DOMException('Only passive media blob URLs are allowed', 'SecurityError');
        return createBlobUrl(value);
      };
      for (const constructor of new Set([URL, window.webkitURL].filter(Boolean))) {
        Object.defineProperty(constructor, 'createObjectURL', {value: passiveBlobUrl, writable: false, configurable: false});
      }
      ${applicationSnapshotScript}
      if (${quoted(notifyFocus)}) for (const type of ['pointerdown', 'focusin']) addEventListener(type, event => {
        if (event.isTrusted) parent.postMessage({type: 'galaris-app-focus'}, '*');
      }, true);
      const applyDocumentContrast = (${applyDocumentContrast.toString()});
      function updateTheme(dark) {
        document.documentElement.dataset.galarisTheme = dark ? 'dark' : 'light';
        applyDocumentContrast(document, dark ? 'rgb(39, 39, 39)' : 'rgb(255, 255, 255)');
      }
      addEventListener('message', event => {
        if (event.source === parent && event.data?.type === 'galaris-host-theme' && typeof event.data.dark === 'boolean') updateTheme(event.data.dark);
      });
      // Keep the displayed WebGL frame available to the existing static snapshot
      // path, without re-running authored animation or Dataset mutations at export.
      const canvasContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(kind, options) {
        if (kind === 'webgl' || kind === 'webgl2' || kind === 'experimental-webgl') options = {...options, preserveDrawingBuffer: true};
        return canvasContext.call(this, kind, options);
      };
      addEventListener('message', event => {
        if (event.source !== parent || event.data !== 'galaris-app-snapshot' || !event.ports[0]) return;
        const reply = event.ports[0];
        captureRenderedDocument().then(html => reply.postMessage({html}), () => reply.postMessage({error: 'Snapshot unavailable'})).finally(() => reply.close());
      });
      let port, sequence = 0;
      const pending = new Map();
      let ready;
      const connected = new Promise(resolve => ready = resolve);
      addEventListener('message', event => {
        if (event.source !== parent || event.data !== 'galaris-app-connect' || !event.ports[0] || port) return;
        port = event.ports[0];
        port.onmessage = ({data}) => {
          const entry = pending.get(data.id);
          if (!entry) return;
          pending.delete(data.id); clearTimeout(entry.timer);
          if (data.error) entry.reject(Object.assign(new Error(data.error), {code: data.code}));
          else entry.resolve(data.result);
        };
        ready();
      });
      async function request(alias, operation, value, expected_revision) {
        await connected;
        if (pending.size >= 8) throw new Error('Too many pending Dataset operations');
        return new Promise((resolve, reject) => {
          const id = String(++sequence);
          const timer = setTimeout(() => { pending.delete(id); reject(new Error('Dataset request timed out; read before retrying')); }, 20000);
          pending.set(id, {resolve, reject, timer});
          port.postMessage({id, alias, operation, value, expected_revision});
        });
      }
      Object.defineProperty(window, 'galaris', {value: Object.freeze({datasets: Object.freeze({
        read: alias => request(alias, 'read'),
        replace: (alias, value, expectedRevision) => request(alias, 'replace', value, expectedRevision),
        append: (alias, value, expectedRevision) => request(alias, 'append', value, expectedRevision)
      })})});
      parent.postMessage('galaris-app-ready', '*');
      addEventListener('DOMContentLoaded', () => {
        const refreshContrast = () => applyDocumentContrast(document, document.documentElement.dataset.galarisTheme === 'dark' ? 'rgb(39, 39, 39)' : 'rgb(255, 255, 255)');
        refreshContrast();
        let timer;
        const observer = new MutationObserver(records => {
          if (timer || records.every(record => record.target.nodeType === 1 && record.target.closest('style[data-galaris-contrast]'))) return;
          timer = setTimeout(() => { timer = undefined; refreshContrast(); }, 250);
        });
        observer.observe(document.body, {subtree:true, childList:true, attributes:true, attributeFilter:['style','class']});
        observer.observe(document.head, {subtree:true, childList:true, characterData:true});
        addEventListener('pagehide', () => { observer.disconnect(); clearTimeout(timer); });
        const report = () => parent.postMessage({type: 'galaris-app-height', height: document.body.scrollHeight}, '*');
        new ResizeObserver(report).observe(document.body); report();
      });
    })();`
  const inner = '<!doctype html><html data-galaris-theme="' + (dark ? 'dark' : 'light') + '"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'
    + policy.replace('frame-src blob:', "frame-src 'none'") + '"><meta name="referrer" content="no-referrer">'
    + '<script>' + sdk + '</script>' + libraries + '<style>html{font-family:system-ui,sans-serif;color-scheme:light;color:' + solaire.gray.dark + '}html[data-galaris-theme="dark"]{color-scheme:dark;color:' + solaire.gray.light + '}body{margin:0;display:flow-root}'
    + (app.css ?? '').replace(/<\/style/gi, '<\\/style') + '</style></head><body>' + (app.html ?? '')
    + '<script>' + (app.javascript ?? '').replace(/<\/script/gi, '<\\/script') + '</script></body></html>'
  return '<!doctype html><html style="color-scheme:' + (dark ? 'dark' : 'light') + '"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'
    + policy + '"><meta name="referrer" content="no-referrer"><style>html,body,iframe{margin:0;width:100%;height:100%;border:0;background:transparent}iframe{color-scheme:inherit}</style></head><body>'
    + '<iframe sandbox="allow-scripts allow-forms" referrerpolicy="no-referrer" title="Application"></iframe><script>'
    + `const frame = document.querySelector('iframe');
       let port, ready = false, connected = false;
       let dark = ${quoted(dark)};
       let loaded = false;
       addEventListener('securitypolicyviolation', event => {
         if (event.effectiveDirective === 'frame-src') parent.postMessage('galaris-app-navigated', '*');
       });
       frame.addEventListener('load', () => {
         if (loaded) parent.postMessage('galaris-app-navigated', '*');
         loaded = true;
       });
       function connect() {
         if (!port || !ready || connected) return;
         connected = true;
         frame.contentWindow.postMessage('galaris-app-connect', '*', [port]);
       }
       addEventListener('message', event => {
         if (event.source === parent && event.data?.type === 'galaris-host-theme' && typeof event.data.dark === 'boolean') { dark = event.data.dark; document.documentElement.style.colorScheme = dark ? 'dark' : 'light'; if (ready) frame.contentWindow.postMessage({type:'galaris-host-theme', dark}, '*'); }
         if (event.source === parent && event.data === 'galaris-app-snapshot' && event.ports[0]) frame.contentWindow.postMessage(event.data, '*', [event.ports[0]]);
         if (event.source === parent && event.data === 'galaris-host-connect' && !port) { port = event.ports[0]; connect(); }
         if (event.source === frame.contentWindow && event.data === 'galaris-app-ready') { ready = true; frame.contentWindow.postMessage({type:'galaris-host-theme', dark}, '*'); connect(); }
         if (event.source === frame.contentWindow && event.data?.type === 'galaris-app-height') parent.postMessage(event.data, '*');
         if (event.source === frame.contentWindow && event.data?.type === 'galaris-app-focus') parent.postMessage({type: 'galaris-app-focus'}, '*');
       });
       frame.src = URL.createObjectURL(new Blob([${quoted(inner)}], {type: 'text/html'}));`
    + '</script></body></html>'
}
