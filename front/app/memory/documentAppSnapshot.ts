// Runs inside the opaque document frame. Only a static copy leaves that frame.
export const applicationSnapshotScript = String.raw`
async function captureRenderedDocument() {
  await document.fonts.ready;
  await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
  return new Promise((resolve, reject) => requestAnimationFrame(() => {
    try {
      let count = 0;
      function copy(source) {
        if (++count > 10000) throw new Error('Document rendering too large');
        if (source.nodeType === Node.TEXT_NODE) return source.cloneNode();
        if (!(source instanceof Element) || ['SCRIPT','STYLE','LINK','META','BASE','NOSCRIPT','IFRAME','OBJECT','EMBED'].includes(source.tagName)) return null;
        let target;
        if (source instanceof HTMLCanvasElement || source instanceof HTMLVideoElement) {
          target = source.cloneNode(false);
          let canvas = source;
          if (source instanceof HTMLVideoElement) {
            canvas = document.createElement('canvas'); canvas.width = source.videoWidth; canvas.height = source.videoHeight;
            canvas.getContext('2d').drawImage(source, 0, 0);
          }
          target.setAttribute('data-document-raster', canvas.toDataURL('image/png'));
        } else {
          target = source.cloneNode(false);
          for (const attribute of [...target.attributes]) {
            if (/^on/i.test(attribute.name) || ['srcdoc','autofocus','contenteditable'].includes(attribute.name)) target.removeAttribute(attribute.name);
          }
          for (const child of source.childNodes) { const node = copy(child); if (node) target.append(node); }
        }
        if (source instanceof HTMLInputElement) {
          target.setAttribute('value', source.type === 'password' ? '' : source.value);
          target.toggleAttribute('checked', source.checked);
        }
        if (source instanceof HTMLTextAreaElement) target.textContent = source.value;
        if (source instanceof HTMLOptionElement) target.toggleAttribute('selected', source.selected);
        if (source instanceof HTMLDetailsElement) target.toggleAttribute('open', source.open);
        if (source instanceof HTMLImageElement && /^(blob:)/.test(source.currentSrc || source.src)) {
          const canvas = document.createElement('canvas'); canvas.width = source.naturalWidth; canvas.height = source.naturalHeight;
          canvas.getContext('2d').drawImage(source, 0, 0); target.src = canvas.toDataURL('image/png'); target.removeAttribute('srcset');
        }
        return target;
      }
      const body = copy(document.body);
      // Keep authored layout rules, including media queries and percentage widths.
      // Computed pixel dimensions belong to the editor viewport, not the printed page.
      const head = document.createElement('head');
      for (const sheet of [...document.styleSheets, ...document.adoptedStyleSheets]) {
        if (sheet.disabled) continue;
        const style = document.createElement('style');
        style.textContent = [...sheet.cssRules].map(rule => rule.cssText).join('\n');
        if (sheet.media.mediaText) style.media = sheet.media.mediaText;
        head.append(style);
      }
      const root = document.documentElement.cloneNode(false);
      root.append(head, body);
      const html = root.outerHTML;
      if (html.length > 12000000) throw new Error('Document rendering too large');
      resolve(html);
    } catch (error) { reject(error); }
  }));
}`
