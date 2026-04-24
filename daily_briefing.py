"""
ProfitAgent — Daily AI Briefing Job
Runs at 2am UTC every day via Railway cron.
Pulls live Shopify data for every connected store,
runs Claude analysis, saves results to Supabase.

Railway cron command: python daily_briefing.py
Railway cron schedule: 0 2 * * *
"""

import os
import json
import asyncio
import httpx
from datetime import datetime, date

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
MASTER_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BACKEND_URL          = os.environ.get("BACKEND_URL", "https://profitagent2-production.up.railway.app")
API_VERSION          = "2024-01"
CLAUDE_MODEL         = "claude-sonnet-4-20250514"


def get_sb():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


async def get_anthropic_key_for_account(sb, account_id: str) -> str:
    """Try account's own key first, fall back to master key."""
    if account_id:
        try:
            result = sb.table("accounts").select("anthropic_key").eq("id", account_id).execute()
            if result.data and result.data[0].get("anthropic_key"):
                return result.data[0]["anthropic_key"]
        except Exception:
            pass
    return MASTER_ANTHROPIC_KEY


async def fetch_shopify_data(shop_domain: str, access_token: str) -> dict:
    """Pull live store data from Shopify."""
    from shopify_oauth import get_shop_data
    return await get_shop_data(shop_domain, access_token, days=30)


async def run_claude_analysis(store_data: dict, api_key: str) -> dict:
    """
    Run Claude analysis on store data.
    Returns structured briefing with summary, profit leaks,
    opportunities, daily tasks and alerts.
    """
    currency = store_data.get("currency", "GBP")
    symbol   = "£" if currency == "GBP" else "$"

    prompt = f"""You are ProfitAgent, an ecommerce profit intelligence system.
Analyse this store's data and return a JSON briefing. Today is {date.today().isoformat()}.

STORE DATA:
- Store: {store_data.get('store', 'Unknown')}
- Revenue (last 30 days): {symbol}{store_data.get('rev', 0):,.2f}
- Orders: {store_data.get('orders', 0)}
- AOV: {symbol}{store_data.get('aov', 0):,.2f}
- Revenue growth vs prior period: {store_data.get('rev_growth', 0)}%
- Order growth: {store_data.get('order_growth', 0)}%
- Refund rate: {store_data.get('refund_rate', 0)}%
- Total discounts given: {symbol}{store_data.get('total_discounts', 0):,.2f}
- Google Ads spend: {symbol}{store_data.get('google', 0):,.2f}
- Meta Ads spend: {symbol}{store_data.get('meta', 0):,.2f}
- TikTok Ads spend: {symbol}{store_data.get('tiktok', 0):,.2f}
- Email/SMS spend: {symbol}{store_data.get('email', 0):,.2f}
- Product count: {store_data.get('product_count', 0)}
- Top SKUs by revenue: {json.dumps(store_data.get('skus', [])[:5], indent=2)}
- Daily revenue trend (last 14 days): {json.dumps(store_data.get('daily_trend', []), indent=2)}

Return ONLY valid JSON, no markdown, no preamble. Use this exact structure:

{{
  "summary": "2-3 sentence plain English briefing of what happened in the last 30 days and what needs attention today.",
  "profit_leaks": [
    {{
      "title": "Short title of the leak",
      "description": "What is leaking and why",
      "estimated_impact": "£X/month or X% of revenue",
      "severity": "high|medium|low"
    }}
  ],
  "opportunities": [
    {{
      "title": "Short opportunity title",
      "description": "What to do and expected outcome",
      "estimated_uplift": "£X/month or X%",
      "priority": 1
    }}
  ],
  "daily_tasks": [
    {{
      "task": "Specific actionable task to do today",
      "reason": "Why this matters right now",
      "effort": "5min|15min|30min|1hr"
    }}
  ],
  "alerts": [
    {{
      "type": "warning|critical|info",
      "title": "Alert title",
      "detail": "What triggered this alert and what to do"
    }}
  ],
  "health_score": 75
}}

Rules:
- profit_leaks: identify 2-4 specific leaks based on the data (high refunds, discount overuse, low-margin SKUs, poor ROAS, etc.)
- opportunities: rank 2-4 by estimated £ impact, most valuable first (priority 1 = highest)
- daily_tasks: give 3 specific tasks for today, most important first
- alerts: only fire alerts that are genuinely triggered by the data (e.g. refund rate > 5%, ROAS < 2x, revenue decline > 10%)
- health_score: 0-100 overall store health based on ROAS, margins, growth, refunds
- If revenue is 0 (new store / no orders), adjust output accordingly — focus on setup tasks
- All monetary values in {currency}
"""

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["content"][0]["text"].strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)


async def process_store(sb, shop_domain: str, access_token: str, account_id: str):
    """Run the full briefing pipeline for one store."""
    print(f"[{datetime.utcnow().isoformat()}] Processing {shop_domain}...")

    try:
        # 1. Fetch live Shopify data
        store_data = await fetch_shopify_data(shop_domain, access_token)
        print(f"  ✓ Shopify data fetched — rev={store_data.get('rev')}, orders={store_data.get('orders')}")

        # 2. Get the API key (own key or master fallback)
        api_key = await get_anthropic_key_for_account(sb, account_id)
        if not api_key:
            print(f"  ✗ No Anthropic API key available for {shop_domain}, skipping")
            return

        # 3. Run Claude analysis
        briefing = await run_claude_analysis(store_data, api_key)
        print(f"  ✓ Claude analysis complete — health score: {briefing.get('health_score')}")

        # 4. Save to Supabase (upsert by shop_domain + date)
        today = date.today().isoformat()
        record = {
            "shop_domain":  shop_domain,
            "account_id":   account_id,
            "date":         today,
            "summary":      briefing.get("summary", ""),
            "profit_leaks": json.dumps(briefing.get("profit_leaks", [])),
            "opportunities": json.dumps(briefing.get("opportunities", [])),
            "daily_tasks":  json.dumps(briefing.get("daily_tasks", [])),
            "alerts":       json.dumps(briefing.get("alerts", [])),
            "metrics":      json.dumps({
                "health_score": briefing.get("health_score", 0),
                "rev":          store_data.get("rev", 0),
                "orders":       store_data.get("orders", 0),
                "aov":          store_data.get("aov", 0),
                "rev_growth":   store_data.get("rev_growth", 0),
                "refund_rate":  store_data.get("refund_rate", 0),
            }),
            "ai_provider": "anthropic",
        }

        sb.table("daily_briefings").upsert(
            record,
            on_conflict="shop_domain,date"
        ).execute()

        print(f"  ✓ Saved briefing for {shop_domain} ({today})")

    except Exception as e:
        print(f"  ✗ Failed for {shop_domain}: {e}")


async def run_daily_briefings():
    """Main entry point — process all connected stores."""
    print(f"\n{'='*50}")
    print(f"ProfitAgent Daily Briefing — {datetime.utcnow().isoformat()}")
    print(f"{'='*50}\n")

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: Missing Supabase credentials")
        return

    sb = get_sb()

    # Fetch all connected stores
    tokens_result = sb.table("shopify_tokens").select("shop_domain, access_token").execute()
    tokens = tokens_result.data or []
    print(f"Found {len(tokens)} connected store(s)\n")

    if not tokens:
        print("No stores connected. Exiting.")
        return

    # Match stores to accounts
    for token_row in tokens:
        shop_domain  = token_row["shop_domain"]
        access_token = token_row["access_token"]

        # Find the account linked to this shop
        acc_result = sb.table("accounts").select("id").eq("shopify_domain", shop_domain).execute()
        account_id = acc_result.data[0]["id"] if acc_result.data else None

        await process_store(sb, shop_domain, access_token, account_id)
        # Small delay between stores to avoid rate limits
        await asyncio.sleep(2)

    print(f"\n{'='*50}")
    print(f"Daily briefing complete — {datetime.utcnow().isoformat()}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    asyncio.run(run_daily_briefings())
