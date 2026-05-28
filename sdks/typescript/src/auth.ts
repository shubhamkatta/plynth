import type { Tokens } from "./types.js";

export interface TokenStore {
  get(): Tokens | null | Promise<Tokens | null>;
  set(tokens: Tokens): void | Promise<void>;
  clear(): void | Promise<void>;
}

export class MemoryStore implements TokenStore {
  #tokens: Tokens | null = null;

  get(): Tokens | null {
    return this.#tokens;
  }

  set(tokens: Tokens): void {
    this.#tokens = tokens;
  }

  clear(): void {
    this.#tokens = null;
  }
}

/**
 * Browser-only opt-in store. Tokens in localStorage are vulnerable to XSS —
 * prefer an HttpOnly cookie set by your own backend if you have one.
 */
export class LocalStorageStore implements TokenStore {
  readonly #key: string;

  constructor(key = "plynth.tokens") {
    if (typeof localStorage === "undefined") {
      throw new Error("LocalStorageStore requires a browser environment");
    }
    this.#key = key;
  }

  get(): Tokens | null {
    const raw = localStorage.getItem(this.#key);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as Tokens;
    } catch {
      return null;
    }
  }

  set(tokens: Tokens): void {
    localStorage.setItem(this.#key, JSON.stringify(tokens));
  }

  clear(): void {
    localStorage.removeItem(this.#key);
  }
}
