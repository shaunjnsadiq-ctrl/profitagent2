from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import sys, os, json, hashlib, base64
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="ProfitAgent Analytics Backend", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
sb = None

def get_sb():
    global sb
    if sb is None and SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            from supabase import create_client
            sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        except Exception as e:
            print(f"Supabase error: {e}")
    return sb

def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def make_token(email: str, uid: str) -> str:
    return hashlib.sha256(f"{email}{uid}profitagent".encode()).hexdigest()

class StoreData(BaseModel):
    store: Optional[str] = "My Store"
    rev: Optional[float] = 0
    orders: Optional[float] = 0
    aov: Optional[float] = 0
    google: Optional[float] = 0
    meta: Optional[float] = 0
    tiktok: Optional[float] = 0
    email: Optional[float] = 0
    skus: Optional[list] = []
    challenges: Optional[list] = []

class AnalyseRequest(BaseModel):
    question: str
    store_data: StoreData
    provider: str
    api_key: str
    model: str

class SignupRequest(BaseModel):
    name: str
    email: str
    store_name: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class SaveDataRequest(BaseModel):
    email: str
    token: str
    data: dict

class LoadDataRequest(BaseModel):
    email: str
    token: str

# ── HEALTH ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ProfitAgent Analytics Backend",
        "version": "2.0.0",
        "supabase": "connected" if get_sb() else "not configured"
    }

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/signup")
async def signup(req: SignupRequest):
    sb = get_sb()
    if not sb: raise HTTPException(503, "Database not configured")
    email = req.email.lower().strip()
    try:
        existing = sb.table("accounts").select("id").eq("email", email).execute()
        if existing.data: raise HTTPException(409, "An account with this email already exists. Please sign in.")
        result = sb.table("accounts").insert({
            "email": email,
            "password_hash": hash_pw(req.password),
            "name": req.name,
            "store_name": req.store_name,
            "plan": "beta",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        acc = result.data[0]
        return {"status": "ok", "user": {
            "id": acc["id"], "email": acc["email"], "name": acc["name"],
            "store_name": acc["store_name"], "plan": acc["plan"],
            "token": make_token(email, acc["id"])
        }}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Signup error: {e}")

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    sb = get_sb()
    if not sb: raise HTTPException(503, "Database not configured")
    email = req.email.lower().strip()
    try:
        result = sb.table("accounts").select("*").eq("email", email).eq("password_hash", hash_pw(req.password)).execute()
        if not result.data: raise HTTPException(401, "Incorrect email or password.")
        acc = result.data[0]
        sb.table("accounts").update({"last_login": datetime.utcnow().isoformat()}).eq("id", acc["id"]).execute()
        return {"status": "ok", "user": {
            "id": acc["id"], "email": acc["email"], "name": acc["name"],
            "store_name": acc["store_name"], "plan": acc["plan"],
            "token": make_token(email, acc["id"])
        }}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Login error: {e}")

# ── DATA ──────────────────────────────────────────────────────────────────────

@app.post("/api/data/save")
async def save_data(req: SaveDataRequest):
    sb = get_sb()
    if not sb: raise HTTPException(503, "Database not configured")
    email = req.email.lower().strip()
    try:
        acc_result = sb.table("accounts").select("id").eq("email", email).execute()
        if not acc_result.data: raise HTTPException(401, "Invalid session")
        acc_id = acc_result.data[0]["id"]
        if req.token != make_token(email, acc_id): raise HTTPException(401, "Invalid token")
        existing = sb.table("store_data").select("id").eq("email", email).execute()
        if existing.data:
            sb.table("store_data").update({"data": req.data, "updated_at": datetime.utcnow().isoformat()}).eq("email", email).execute()
        else:
            sb.table("store_data").insert({"account_id": acc_id, "email": email, "data": req.data}).execute()
        return {"status": "ok"}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Save error: {e}")

@app.post("/api/data/load")
async def load_data(req: LoadDataRequest):
    sb = get_sb()
    if not sb: raise HTTPException(503, "Database not configured")
    email = req.email.lower().strip()
    try:
        acc_result = sb.table("accounts").select("id").eq("email", email).execute()
        if not acc_result.data: raise HTTPException(401, "Invalid session")
        acc_id = acc_result.data[0]["id"]
        if req.token != make_token(email, acc_id): raise HTTPException(401, "Invalid token")
        result = sb.table("store_data").select("data").eq("email", email).execute()
        return {"status": "ok", "data": result.data[0]["data"] if result.data else {}}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Load error: {e}")

# ── ANALYSIS ──────────────────────────────────────────────────────────────────

@app.post("/api/analyse")
async def analyse(req: AnalyseRequest):
    if not req.question.strip(): raise HTTPException(400, "Question cannot be empty")
    if not req.api_key.strip(): raise HTTPException(400, "API key is required")
    if req.provider not in ("openai", "anthropic"): raise HTTPException(400, "Provider must be openai or anthropic")
    from analysis import TOOL_DESCRIPTIONS, run_tool
    from llm_router import run_analysis
    try:
        result = await run_analysis(
            question=req.question,
            store_data=req.store_data.model_dump(),
            provider=req.provider,
            api_key=req.api_key,
            model=req.model
        )
        return {"status": "ok", "result": result}
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "authentication" in error_msg.lower(): raise HTTPException(401, "Invalid API key.")
        if "429" in error_msg: raise HTTPException(429, "Rate limit reached.")
        raise HTTPException(500, f"Analysis failed: {error_msg}")

@app.get("/api/tools")
def list_tools():
    from analysis import TOOL_DESCRIPTIONS
    return {"tools": [{"name": t["name"], "description": t["description"]} for t in TOOL_DESCRIPTIONS]}

# ── PIXEL ─────────────────────────────────────────────────────────────────────

pixel_events = []

@app.get("/pixel/pa.js")
async def serve_pixel():
    pixel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pa.js")
    if os.path.exists(pixel_path):
        return FileResponse(pixel_path, media_type="application/javascript", headers={"Access-Control-Allow-Origin": "*"})
    return Response(content="// ProfitAgent pixel", media_type="application/javascript")

@app.post("/pixel/event")
async def receive_event(request: Request):
    try:
        event = json.loads(await request.body())
        event["received_at"] = datetime.utcnow().isoformat()
        pixel_events.append(event)
        if len(pixel_events) > 500: pixel_events.pop(0)
    except: pass
    return {"status": "ok"}

@app.get("/pixel/events")
async def get_events(store_id: str = None, limit: int = 50):
    events = pixel_events[-limit:]
    if store_id: events = [e for e in events if e.get("store_id") == store_id]
    return {"status": "ok", "count": len(events), "events": list(reversed(events))}

# ── SHOPIFY OAUTH ─────────────────────────────────────────────────────────────

@app.get("/")
async def root_shopify_handler(
    request: Request,
    shop: str = None,
    hmac: str = None,
    host: str = None,
    timestamp: str = None,
    code: str = None,
    state: str = None
):
    if shop and hmac:
        return await shopify_callback(
            request=request,
            shop=shop,
            code=code,
            state=state,
            hmac=hmac
        )
    return {"status": "ok", "service": "ProfitAgent", "version": "2.0.0"}


@app.get("/shopify/install")
async def shopify_install(shop: str):
    from shopify_oauth import get_install_url
    if not shop:
        raise HTTPException(400, "Shop parameter required")
    install_url = get_install_url(shop)
    return RedirectResponse(url=install_url)


@app.get("/shopify/callback")
async def shopify_callback(
    request: Request,
    shop: str = None,
    code: str = None,
    state: str = None,
    hmac: str = None
):
    from shopify_oauth import verify_hmac, exchange_code_for_token, get_shop_data

    if not shop or not code:
        raise HTTPException(400, "Missing shop or code parameter")

    params = dict(request.query_params)
    if not verify_hmac(params.copy()):
        raise HTTPException(403, "Invalid HMAC — request may be forged")

    try:
        access_token = await exchange_code_for_token(shop, code)

        db = get_sb()
        if db:
            existing = db.table("shopify_tokens").select("id").eq("shop_domain", shop).execute()
            if existing.data:
                db.table("shopify_tokens").update({
                    "access_token": access_token,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("shop_domain", shop).execute()
            else:
                db.table("shopify_tokens").insert({
                    "shop_domain": shop,
                    "access_token": access_token,
                    "scope": "read_orders,read_products,read_inventory,read_analytics",
                    "installed_at": datetime.utcnow().isoformat()
                }).execute()

            try:
                db.table("accounts").update({
                    "shopify_domain": shop
                }).is_("shopify_domain", "null").order("created_at", desc=True).limit(1).execute()
            except Exception:
                pass

        store_data = await get_shop_data(shop, access_token)
        encoded = base64.urlsafe_b64encode(json.dumps(store_data).encode()).decode()
        frontend = os.environ.get("FRONTEND_URL", "https://ecom-profitagent.netlify.app")
        return RedirectResponse(url=f"{frontend}/agent?shopify_data={encoded}&shop={shop}")

    except Exception as e:
        raise HTTPException(500, f"Shopify connection failed: {str(e)}")


@app.get("/shopify/sync/{shop_domain}")
async def shopify_sync(shop_domain: str, email: str = None):
    from shopify_oauth import get_shop_data
    db = get_sb()
    if not db:
        raise HTTPException(503, "Database not configured")
    result = db.table("shopify_tokens").select("access_token").eq("shop_domain", shop_domain).execute()
    if not result.data:
        raise HTTPException(404, "Store not connected. Please install ProfitAgent first.")
    access_token = result.data[0]["access_token"]
    store_data = await get_shop_data(shop_domain, access_token)
    return {"status": "ok", "data": store_data}


@app.get("/shopify/status/{shop_domain}")
async def shopify_status(shop_domain: str):
    db = get_sb()
    if not db:
        return {"connected": False}
    result = db.table("shopify_tokens").select("shop_domain,installed_at").eq("shop_domain", shop_domain).execute()
    if result.data:
        return {"connected": True, "shop": result.data[0]["shop_domain"], "since": result.data[0]["installed_at"]}
    return {"connected": False}


@app.get("/shopify/data")
async def shopify_data(email: str, token: str, days: int = 30):
    from shopify_oauth import get_shop_data

    db = get_sb()
    if not db:
        raise HTTPException(503, "Database not configured")

    acc_result = db.table("accounts").select("id, shopify_domain").eq("email", email.lower().strip()).execute()
    if not acc_result.data:
        raise HTTPException(401, "Invalid session")

    acc = acc_result.data[0]
    if token != make_token(email.lower().strip(), acc["id"]):
        raise HTTPException(401, "Invalid token")

    shop_domain = acc.get("shopify_domain")
    if not shop_domain:
        token_result = db.table("shopify_tokens").select("shop_domain").order("installed_at", desc=True).limit(1).execute()
        if not token_result.data:
            return {"connected": False, "message": "No Shopify store connected"}
        shop_domain = token_result.data[0]["shop_domain"]

    token_result = db.table("shopify_tokens").select("access_token").eq("shop_domain", shop_domain).execute()
    if not token_result.data:
        return {"connected": False, "message": "No Shopify store connected"}

    access_token = token_result.data[0]["access_token"]

    try:
        store_data = await get_shop_data(shop_domain, access_token, days=days)
        return {"status": "ok", "connected": True, "data": store_data}
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch Shopify data: {str(e)}")


# ── DAILY BRIEFING ────────────────────────────────────────────────────────────

@app.get("/briefing/today")
async def get_today_briefing(email: str, token: str):
    import json as _json
    from datetime import date, timedelta

    db = get_sb()
    if not db:
        raise HTTPException(503, "Database not configured")

    acc_result = db.table("accounts").select("id, shopify_domain").eq("email", email.lower().strip()).execute()
    if not acc_result.data:
        raise HTTPException(401, "Invalid session")
    acc = acc_result.data[0]
    if token != make_token(email.lower().strip(), acc["id"]):
        raise HTTPException(401, "Invalid token")

    shop_domain = acc.get("shopify_domain")
    if not shop_domain:
        return {"status": "no_store", "message": "No Shopify store connected"}

    today = date.today().isoformat()
    result = db.table("daily_briefings") \
        .select("*") \
        .eq("shop_domain", shop_domain) \
        .eq("date", today) \
        .execute()

    if not result.data:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = db.table("daily_briefings") \
            .select("*") \
            .eq("shop_domain", shop_domain) \
            .eq("date", yesterday) \
            .execute()
        if not result.data:
            return {"status": "no_briefing", "message": "Daily briefing not yet generated"}

    row = result.data[0]

    def parse(val):
        if isinstance(val, str):
            try: return _json.loads(val)
            except: return []
        return val or []

    return {
        "status": "ok",
        "date": row["date"],
        "summary": row.get("summary", ""),
        "profit_leaks": parse(row.get("profit_leaks")),
        "opportunities": parse(row.get("opportunities")),
        "daily_tasks": parse(row.get("daily_tasks")),
        "alerts": parse(row.get("alerts")),
        "metrics": parse(row.get("metrics")),
        "shop_domain": shop_domain,
    }


@app.post("/briefing/run-now")
async def run_briefing_now(email: str, token: str):
    """Run briefing inline — waits for completion and returns the result."""
    import json as _json
    from datetime import date

    db = get_sb()
    if not db:
        raise HTTPException(503, "Database not configured")

    acc_result = db.table("accounts").select("id, shopify_domain").eq("email", email.lower().strip()).execute()
    if not acc_result.data:
        raise HTTPException(401, "Invalid session")
    acc = acc_result.data[0]
    if token != make_token(email.lower().strip(), acc["id"]):
        raise HTTPException(401, "Invalid token")

    shop_domain = acc.get("shopify_domain")
    if not shop_domain:
        raise HTTPException(400, "No Shopify store connected")

    # Get Shopify access token
    token_result = db.table("shopify_tokens").select("access_token").eq("shop_domain", shop_domain).execute()
    if not token_result.data:
        raise HTTPException(404, "Shopify token not found")
    access_token = token_result.data[0]["access_token"]

    # Get Anthropic key — user's own first, master key as fallback
    anthropic_key = None
    try:
        key_result = db.table("accounts").select("anthropic_key").eq("id", acc["id"]).execute()
        if key_result.data:
            anthropic_key = key_result.data[0].get("anthropic_key")
    except Exception:
        pass
    if not anthropic_key:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        raise HTTPException(503, "No Anthropic API key configured")

    try:
        # 1. Fetch live Shopify data
        from shopify_oauth import get_shop_data
        store_data = await get_shop_data(shop_domain, access_token, days=30)

        # 2. Build Claude prompt
        currency = store_data.get("currency", "GBP")
        symbol = "£" if currency == "GBP" else "$"
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
- Top SKUs: {json.dumps(store_data.get('skus', [])[:5])}

Return ONLY valid JSON, no markdown fences, no preamble:
{{
  "summary": "2-3 sentence plain English briefing of the last 30 days and what needs attention today.",
  "profit_leaks": [
    {{"title": "Short title", "description": "What is leaking and why", "estimated_impact": "{symbol}X/month", "severity": "high|medium|low"}}
  ],
  "opportunities": [
    {{"title": "Short title", "description": "What to do and expected outcome", "estimated_uplift": "{symbol}X/month", "priority": 1}}
  ],
  "daily_tasks": [
    {{"task": "Specific task to do today", "reason": "Why this matters", "effort": "5min|15min|30min|1hr"}}
  ],
  "alerts": [
    {{"type": "warning|critical|info", "title": "Alert title", "detail": "What triggered this"}}
  ],
  "health_score": 75
}}
Include 2-4 profit leaks, 2-4 opportunities ranked by impact, 3 daily tasks.
Only include alerts genuinely triggered by the data.
If revenue is 0, focus on setup tasks and getting first orders."""

        # 3. Call Claude
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()

        # Strip markdown fences if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        briefing = _json.loads(raw.strip())

        # 4. Save to Supabase
        today = date.today().isoformat()
        db.table("daily_briefings").upsert({
            "shop_domain":   shop_domain,
            "account_id":    acc["id"],
            "date":          today,
            "summary":       briefing.get("summary", ""),
            "profit_leaks":  _json.dumps(briefing.get("profit_leaks", [])),
            "opportunities": _json.dumps(briefing.get("opportunities", [])),
            "daily_tasks":   _json.dumps(briefing.get("daily_tasks", [])),
            "alerts":        _json.dumps(briefing.get("alerts", [])),
            "metrics":       _json.dumps({"health_score": briefing.get("health_score", 0), **{k: store_data.get(k,0) for k in ["rev","orders","aov","rev_growth","refund_rate"]}}),
            "ai_provider":   "anthropic",
        }, on_conflict="shop_domain,date").execute()

        return {"status": "ok", "message": "Briefing generated successfully", "health_score": briefing.get("health_score"), "date": today}

    except Exception as e:
        raise HTTPException(500, f"Briefing failed: {str(e)}")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
