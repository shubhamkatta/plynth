import { describe, expect, it, vi } from "vitest";
import { MemoryStore, PlynthClient } from "../src/index.js";
import type { Tokens } from "../src/index.js";

/**
 * Invite endpoints on the SDK (T-025).
 *
 * The four invite endpoints existed on the platform with no SDK methods, which
 * breaks the repo contract that new endpoints ship with SDK coverage. These
 * tests pin what spans two different auth surfaces:
 *
 * - preview/accept are UNAUTHENTICATED — the token in the body is the
 *   credential, and an invitee has no account yet.
 * - the prospect invite is PLATFORM-ADMIN, so it must route through the
 *   admin-token header rather than Authorization. Sending it over a user JWT
 *   would be a privilege escalation.
 * - a tenant invite adds a teammate; a prospect invite creates a whole new
 *   tenant. Calling the wrong one is a tenancy bug, so paths are asserted.
 */

const TOKENS: Tokens = {
  access_token: "a1",
  refresh_token: "r1",
  token_type: "bearer",
  expires_at: "2099-01-01T00:00:00Z",
};

const INVITE = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "new@example.test",
  kind: "tenant",
  expires_at: "2099-01-01T00:00:00Z",
  link: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Seen = { url: string; headers: Record<string, string>; body: unknown };

function capture(response: unknown, status = 200) {
  const seen: Seen[] = [];
  const fetchMock = vi.fn(
    async (url: string | URL | Request, init?: RequestInit) => {
      seen.push({
        url: typeof url === "string" ? url : url.toString(),
        headers: Object.fromEntries(new Headers(init?.headers).entries()),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      return jsonResponse(response, status);
    }
  );
  return { seen, fetchMock };
}

describe("invites", () => {
  it("posts a tenant invite to /users/invites with the user's Bearer", async () => {
    const { seen, fetchMock } = capture(INVITE, 201);
    const store = new MemoryStore();
    store.set(TOKENS);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "chatbot",
      tokenStore: store,
      fetch: fetchMock as unknown as typeof fetch,
    });

    const out = await c.users.createInvite({
      email: "new@example.test",
      role_codes: ["therapist"],
    });

    expect(out.email).toBe("new@example.test");
    expect(seen[0]?.url).toBe("https://api.test/api/v1/users/invites");
    expect(seen[0]?.headers["authorization"]).toBe("Bearer a1");
    expect(seen[0]?.body).toEqual({
      email: "new@example.test",
      role_codes: ["therapist"],
    });
  });

  it("sends a prospect invite over the admin token, never a Bearer", async () => {
    const prospect = { ...INVITE, kind: "prospect", link: "https://api.test/invite?token=t" };
    const { seen, fetchMock } = capture(prospect, 201);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      adminToken: "admin-secret",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const out = await c.products.createInvite("mayva-practice", {
      email: "prospect@example.test",
      send_email: false,
    });

    expect(out.link).toBe("https://api.test/invite?token=t");
    expect(seen[0]?.url).toBe(
      "https://api.test/api/v1/admin/products/mayva-practice/invites"
    );
    expect(seen[0]?.headers["x-platform-admin-token"]).toBe("admin-secret");
    expect(seen[0]?.headers["authorization"]).toBeUndefined();
    // send_email:false is how invites go out while SES is sandboxed — it must
    // survive serialization rather than being dropped as falsy.
    expect((seen[0]?.body as { send_email: boolean }).send_email).toBe(false);
  });

  it("previews an invite with no authentication", async () => {
    const preview = {
      email: "new@example.test",
      full_name: null,
      kind: "prospect",
      plan_code: "practice",
      product_name: "Mayva",
      expires_at: "2099-01-01T00:00:00Z",
    };
    const { seen, fetchMock } = capture(preview);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "chatbot",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const out = await c.auth.previewInvite({ token: "t".repeat(24) });

    expect(out.product_name).toBe("Mayva");
    expect(seen[0]?.headers["authorization"]).toBeUndefined();
  });

  it("accepts an invite and returns a token pair, so there is no second login", async () => {
    const pair = { ...TOKENS, access_token: "new-a", refresh_token: "new-r" };
    const { seen, fetchMock } = capture(pair, 201);
    const c = new PlynthClient({
      baseUrl: "https://api.test",
      productSlug: "chatbot",
      fetch: fetchMock as unknown as typeof fetch,
    });

    const out = await c.auth.acceptInvite({
      token: "t".repeat(24),
      password: "hunter2hunter2",
      full_name: "Pat",
    });

    expect(out.access_token).toBe("new-a");
    expect(seen[0]?.headers["authorization"]).toBeUndefined();
    // Idempotent: a double-submitted accept form must not create two accounts.
    expect(seen[0]?.headers["idempotency-key"]).toBeTruthy();
  });
});
