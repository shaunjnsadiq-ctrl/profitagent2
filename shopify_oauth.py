"""
ProfitAgent — Shopify OAuth Integration
"""

import os
import hmac
import hashlib
import urllib.parse
import httpx
from datetime import datetime

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY", "")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET", "")
SHOPIFY_SCOPES = "read_orders,read_products,read_inventory,read_analytics,read_customers"
BACKEND_URL = os.environ.get("BACKEND_URL", "https://profitagent2-production.up.railway.app")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ecom-profitagent.netlify.app")

REDIRECT_URI = f"{BACKEND_URL}/shopify/callback"


def get_install_url(shop_domain: str) -> str:
    shop = shop_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = shop.split(".")[0] + ".myshopify.com"

    params = {
        "client_id": SHOPIFY_API_KEY,
        "scope": SHOPIFY_SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": hashlib.sha256(f"{shop}{SHOPIFY_API_SECRET}profitagent".encode()).hexdigest()[:16],
        "grant_options[]": "per-user"
    }
    return f"https://{shop}/admin/oauth/authorize?" + urllib.parse.urlencode(params)


def verify_hmac(params: dict) -> bool:
    hmac_value = params.pop("hmac", None)
    if not hmac_value:
        return False
    sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode(),
        sorted_params.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(digest, hmac_value)


async def exchange_code_for_token(shop: str, code: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": SHOPIFY_API_KEY,
                "client_secret": SHOPIFY_API_SECRET,
                "code": code
            }
        )
        resp.raise_for_status()
        return resp.json().get("access_token")


async def get_shop_data(shop: str, access_token: str) -> dict:
    headers = {"X-Shopify-Access-Token": access_token}

    async with httpx.AsyncClient() as client:
        shop_resp = await client.get(
            f"https://{shop}/admin/api/2024-01/shop.json",
            headers=headers
        )
        shop_data = shop_resp.json().get("shop", {})

        from datetime import datetime, timedelta
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        orders_resp = await client.get(
            f"https://{shop}/admin/api/2024-01/orders.json",
            headers=headers,
            params={
                "status": "any",
                "created_at_min": since,
                "limit": 250,
                "fields": "id,total_price,line_items,created_at,financial_status"
            }
        )
        orders = orders_resp.json().get("orders", [])

        products_resp = await client.get(
            f"https://{shop}/admin/api/2024-01/products.json",
            headers=headers,
            params={"limit": 50, "fields": "id,title,variants"}
        )
        products = products_resp.json().get("products", [])

    total_revenue = sum(float(o.get("total_price", 0)) for o in orders)
    order_count = len(orders)
    aov = round(total_revenue / order_count, 2) if order_count > 0 else 0

    skus = []
    for p in products[:10]:
        for v in p.get("variants", [])[:1]:
            cost = float(v.get("cost", 0) or 0)
            price = float(v.get("price", 0) or 0)
            margin = round((price - cost) / price * 100, 1) if price > 0 and cost > 0 else 0
            if p.get("title"):
                skus.append({
                    "name": p["title"][:40],
                    "margin": margin,
                    "units": 0
                })

    return {
        "store": shop_data.get("name", shop),
        "rev": round(total_revenue, 2),
        "orders": order_count,
        "aov": aov,
        "skus": skus[:10],
        "shopify_connected": True,
        "shopify_domain": shop,
        "last_synced": datetime.utcnow().isoformat()
    }
