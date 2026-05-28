/**
 * Node 20+ usage example.
 *   tsx examples/node.ts
 */
import { PlynthClient, MemoryStore, PlynthApiError } from "../src/index.js";

const client = new PlynthClient({
  baseUrl: process.env["PLYNTH_BASE_URL"] ?? "http://localhost:8000",
  productSlug: process.env["PLYNTH_PRODUCT_SLUG"] ?? "chatbot",
  tokenStore: new MemoryStore(),
});

async function main() {
  await client.auth.login({
    email: process.env["PLYNTH_EMAIL"]!,
    password: process.env["PLYNTH_PASSWORD"]!,
  });

  const me = await client.auth.me();
  console.log(`signed in as ${me.email}, perms: ${me.permissions.length}`);

  try {
    const wallet = await client.credits.consume({
      feature_key: "credits.ai_completion",
      amount: "1",
    });
    console.log(`balance after: ${wallet.balance}`);
  } catch (err) {
    if (err instanceof PlynthApiError && err.code === "insufficient_credits") {
      console.log("need upsell — wallet too low");
    } else throw err;
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
