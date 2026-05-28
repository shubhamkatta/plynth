"""Async usage example.

    python examples/async_usage.py
"""

from __future__ import annotations

import asyncio
import os

from plynth_sdk import AsyncPlynthClient, MemoryStore, PlynthApiError


async def main() -> None:
    async with AsyncPlynthClient(
        base_url=os.environ.get("PLYNTH_BASE_URL", "http://localhost:8000"),
        product_slug=os.environ.get("PLYNTH_PRODUCT_SLUG", "chatbot"),
        token_store=MemoryStore(),
    ) as client:
        await client.auth.login({
            "email": os.environ["PLYNTH_EMAIL"],
            "password": os.environ["PLYNTH_PASSWORD"],
        })
        me = await client.auth.me()
        print(f"signed in as {me['email']}, perms: {len(me['permissions'])}")

        try:
            wallet = await client.credits.consume({
                "feature_key": "credits.ai_completion",
                "amount": "1",
            })
            print(f"balance after: {wallet['balance']}")
        except PlynthApiError as exc:
            if exc.code == "insufficient_credits":
                print("need upsell — wallet too low")
            else:
                raise


if __name__ == "__main__":
    asyncio.run(main())
