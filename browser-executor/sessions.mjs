import { BrowserRequestError } from "./lib.mjs";

/** Own capacity from admission through context cleanup, including pending creations. */
export class SessionPool extends Map {
  #occupied = 0;
  constructor(limit) {
    super();
    this.limit = limit;
  }

  get occupied() { return this.#occupied; }

  async create(factory, initialize, limit = this.limit) {
    if (this.#occupied >= limit) {
      throw new BrowserRequestError("capacity_reached", "Browser capacity has been reached.", 503);
    }
    this.#occupied += 1;
    let session;
    try {
      session = await factory();
      session.pending = 0;
      session.queue = Promise.resolve();
      session.closing = false;
      this.set(session.id, session);
      return await this.run(session, initialize);
    } catch (error) {
      if (session) await this.close(session.id);
      else this.#occupied -= 1;
      throw error;
    }
  }

  async run(session, operation) {
    if (session.closing || this.get(session.id) !== session) {
      throw new BrowserRequestError("session_not_found", "The browser session was not found.", 404);
    }
    session.pending += 1;
    const previous = session.queue;
    let release;
    session.queue = new Promise((resolve) => { release = resolve; });
    try {
      await previous;
      return await operation(session);
    } finally {
      session.touchedAt = Date.now();
      session.pending -= 1;
      release();
    }
  }

  async close(id) {
    const session = this.get(id);
    if (!session) return;
    if (session.closing) return session.closed;
    session.closing = true;
    session.closed = (async () => {
      await session.queue;
      try {
        await session.context.close();
      } finally {
        this.delete(id);
        this.#occupied -= 1;
      }
    })();
    return session.closed;
  }

  async sweep(now) {
    await Promise.all([...this.values()]
      .filter((session) => !session.pending && session.touchedAt + session.idleTtlMs < now)
      .map((session) => this.close(session.id)));
  }
}
