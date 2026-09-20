/** Serialize lazy launch and idle shutdown without interrupting admitted sessions. */
export class BrowserLifecycle {
  #browser;
  #launching;
  #closing;
  #stopped = false;

  constructor(launch, onCrash) {
    this.launch = launch;
    this.onCrash = onCrash;
  }

  async get() {
    if (this.#closing) await this.#closing;
    if (this.#stopped) throw new Error('Browser executor is stopping');
    if (this.#browser) return this.#browser;
    if (!this.#launching) {
      this.#launching = this.launch().then(async browser => {
        if (this.#stopped) {
          await browser.close();
          throw new Error('Browser executor is stopping');
        }
        this.#browser = browser;
        browser.on('disconnected', () => {
          if (this.#browser === browser && !this.#stopped) this.onCrash();
        });
        return browser;
      }).finally(() => { this.#launching = undefined; });
    }
    return this.#launching;
  }

  closeIfIdle(busy) {
    // busy includes creations before a context exists, not only published sessions.
    if (busy || this.#launching || this.#closing || !this.#browser) return;
    const browser = this.#browser;
    this.#browser = undefined;
    this.#closing = browser.close().finally(() => { this.#closing = undefined; });
    return this.#closing;
  }

  async stop() {
    this.#stopped = true;
    await this.#launching?.catch(() => {});
    await this.#closing;
    const browser = this.#browser;
    this.#browser = undefined;
    await browser?.close();
  }
}
