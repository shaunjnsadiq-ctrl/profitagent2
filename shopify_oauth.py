"""
ProfitAgent — Shopify OAuth Integration
Full order data, revenue, AOV, SKU performance and margin analysis.
"""

import os
import hmac
import hashlib
import urllib.parse
import httpx
from datetime import datetime, timedelta

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY", "")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET", "")
SHOPIFY_SCOPES = "read_orders,read_products,read_inventory,read_analytics,read_customers"
BACKEND_URL = os.environ.get("BACKEND_URL", "https://profitagent2-production.up.railway.app")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ecom-profitagent.netlify.app")
REDIRECT_URI = f"{BACKEND_URL}/shopify/callback"
API_VERSION = "2024-01"


def get_install_url(shop_domain: str) -> str:
    shop = shop_domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
    if not shop.endswith(".myshopify.com"):
        shop = shop.split(".")[0] + ".myshopify.com"
    params = {
        "client_id": SHOPIFY_API_KEY,
        "scope": SHOPIFY_SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": hashlib.sha256(f"{shop}{SHOPIFY_API_SECRET}profitagent".encode()).hexdigest()[:16],
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


async def fetch_all_orders(shop: str, headers: dict, since: str) -> list:
    """Fetch all orders using pagination — handles stores with 250+ orders."""
    all_orders = []
    url = f"https://{shop}/admin/api/{API_VERSION}/orders.json"
    params = {
        "status": "any",
        "financial_status": "paid",
        "created_at_min": since,
        "limit": 250,
        "fields": "id,total_price,subtotal_price,total_discounts,line_items,created_at,financial_status,cancel_reason"
    }

    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                break
            data = resp.json()
            orders = data.get("orders", [])
            all_orders.extend(orders)

            # Handle pagination via Link header
            link_header = resp.headers.get("Link", "")
            if 'rel="next"' in link_header:
                # Extract next URL
                parts = link_header.split(",")
                next_url = None
                for part in parts:
                    if 'rel="next"' in part:
                        next_url = part.split(";")[0].strip().strip("<>")
                        break
                url = next_url
                params = {}  # params are already in the next URL
            else:
                url = None

    return all_orders


async def get_shop_data(shop: str, access_token: str, days: int = 30) -> dict:
    """
    Pull comprehensive store data from Shopify API.
    Returns revenue, orders, AOV, SKU performance, top products,
    refund rate and daily revenue trend.
    """
    auth_headers = {"X-Shopify-Access-Token": access_token}
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    since_prev = (datetime.utcnow() - timedelta(days=days * 2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:

        # ── Shop info ──────────────────────────────────────────────────────
        shop_resp = await client.get(
            f"https://{shop}/admin/api/{API_VERSION}/shop.json",
            headers=auth_headers
        )
        shop_info = shop_resp.json().get("shop", {})

        # ── Products with cost data ────────────────────────────────────────
        products_resp = await client.get(
            f"https://{shop}/admin/api/{API_VERSION}/products.json",
            headers=auth_headers,
            params={"limit": 250, "fields": "id,title,variants,product_type,status"}
        )
        products = products_resp.json().get("products", [])

        # ── Refunds for the period ─────────────────────────────────────────
        refunds_resp = await client.get(
            f"https://{shop}/admin/api/{API_VERSION}/orders.json",
            headers=auth_headers,
            params={
                "status": "any",
                "financial_status": "refunded,partially_refunded",
                "created_at_min": since,
                "limit": 250,
                "fields": "id,total_price,refunds"
            }
        )
        refunded_orders = refunds_resp.json().get("orders", [])

    # ── Fetch all paid orders with pagination ──────────────────────────────
    orders = await fetch_all_orders(shop, auth_headers, since)
    prev_orders = await fetch_all_orders(shop, auth_headers, since_prev)
    # prev_orders only covers the previous period (not overlapping)
    prev_orders = [o for o in prev_orders if o.get("created_at", "") < since]

    # ── Revenue calculations ───────────────────────────────────────────────
    total_revenue = sum(float(o.get("total_price", 0)) for o in orders)
    prev_revenue = sum(float(o.get("total_price", 0)) for o in prev_orders)
    order_count = len(orders)
    prev_order_count = len(prev_orders)
    aov = round(total_revenue / order_count, 2) if order_count > 0 else 0
    prev_aov = round(prev_revenue / prev_order_count, 2) if prev_order_count > 0 else 0

    # Revenue growth %
    rev_growth = round(((total_revenue - prev_revenue) / prev_revenue) * 100, 1) if prev_revenue > 0 else 0
    order_growth = round(((order_count - prev_order_count) / prev_order_count) * 100, 1) if prev_order_count > 0 else 0

    # ── Total discounts given ──────────────────────────────────────────────
    total_discounts = sum(float(o.get("total_discounts", 0)) for o in orders)

    # ── Refund rate ────────────────────────────────────────────────────────
    refund_count = len(refunded_orders)
    refund_rate = round((refund_count / order_count) * 100, 1) if order_count > 0 else 0

    # ── SKU performance from line items ───────────────────────────────────
    sku_stats = {}
    for order in orders:
        for item in order.get("line_items", []):
            sku = item.get("sku") or item.get("title", "Unknown")[:30]
            if not sku:
                continue
            if sku not in sku_stats:
                sku_stats[sku] = {
                    "name": item.get("title", sku)[:40],
                    "units": 0,
                    "revenue": 0.0,
                    "price": float(item.get("price", 0))
                }
            qty = int(item.get("quantity", 1))
            sku_stats[sku]["units"] += qty
            sku_stats[sku]["revenue"] += float(item.get("price", 0)) * qty

    # Match cost data from products
    product_cost_map = {}
    for p in products:
        for v in p.get("variants", []):
            sku = v.get("sku", "")
            cost = float(v.get("cost", 0) or 0)
            price = float(v.get("price", 0) or 0)
            if sku:
                product_cost_map[sku] = {"cost": cost, "price": price}

    # Build SKU list with margin
    skus = []
    for sku, stats in sku_stats.items():
        cost_data = product_cost_map.get(sku, {})
        cost = cost_data.get("cost", 0)
        price = stats["price"]
        margin = round(((price - cost) / price) * 100, 1) if price > 0 and cost > 0 else None
        skus.append({
            "name": stats["name"],
            "sku": sku,
            "units": stats["units"],
            "revenue": round(stats["revenue"], 2),
            "margin": margin,
            "price": price
        })

    # Sort by revenue descending, take top 10
    skus = sorted(skus, key=lambda x: x["revenue"], reverse=True)[:10]

    # ── Daily revenue trend (last 14 days) ────────────────────────────────
    daily = {}
    for i in range(14):
        day = (datetime.utcnow() - timedelta(days=13 - i)).strftime("%Y-%m-%d")
        daily[day] = 0.0

    for order in orders:
        day = order.get("created_at", "")[:10]
        if day in daily:
            daily[day] += float(order.get("total_price", 0))

    daily_trend = [{"date": d, "revenue": round(v, 2)} for d, v in daily.items()]

    # ── Top products by units sold ─────────────────────────────────────────
    top_products = sorted(skus, key=lambda x: x["units"], reverse=True)[:5]

    # ── Build final payload ────────────────────────────────────────────────
    return {
        # Core metrics
        "store": shop_info.get("name", shop),
        "shop_domain": shop,
        "currency": shop_info.get("currency", "GBP"),
        "rev": round(total_revenue, 2),
        "orders": order_count,
        "aov": aov,

        # Growth vs previous period
        "rev_growth": rev_growth,
        "order_growth": order_growth,
        "prev_rev": round(prev_revenue, 2),
        "prev_orders": prev_order_count,
        "prev_aov": prev_aov,

        # Additional metrics
        "total_discounts": round(total_discounts, 2),
        "refund_rate": refund_rate,
        "refund_count": refund_count,

        # Ad spend placeholders (to be connected via Meta/Google APIs)
        "google": 0,
        "meta": 0,
        "tiktok": 0,
        "email": 0,

        # Product data
        "skus": skus,
        "top_products": top_products,
        "product_count": len(products),

        # Trend data
        "daily_trend": daily_trend,
        "period_days": days,

        # Meta
        "shopify_connected": True,
        "last_synced": datetime.utcnow().isoformat(),
    }
