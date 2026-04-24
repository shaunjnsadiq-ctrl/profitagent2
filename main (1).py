from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional
import sys, os, json, hashlib
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

@app.get("/health")
def health():
    return {"status": "ok", "service": "ProfitAgent Analytics Backend", "version": "2.0.0", "supabase": "connected" if get_sb() else "not configured"}

@app.post("/api/auth/signup")
async def signup(req: SignupRequest):
    sb = get_sb()
    if not sb: raise HTTPException(503, "Database not configured")
    email = req.email.lower().strip()
    try:
        existing = sb.table("accounts").select("id").eq("email", email).execute()
        if existing.data: raise HTTPException(409, "An account with this email already exists. Please sign in.")
        result = sb.table("accounts").insert({"email": email, "password_hash": hash_pw(req.password), "name": req.name, "store_name": req.store_name, "plan": "beta", "created_at": datetime.utcnow().isoformat()}).execute()
        acc = result.data[0]
        return {"status": "ok", "user": {"id": acc["id"], "email": acc["email"], "name": acc["name"], "store_name": acc["store_name"], "plan": acc["plan"], "token": make_token(email, acc["id"])}}
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
        return {"status": "ok", "user": {"id": acc["id"], "email": acc["email"], "name": acc["name"], "store_name": acc["store_name"], "plan": acc["plan"], "token": make_token(email, acc["id"])}}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Login error: {e}")

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

@app.post("/api/analyse")
async def analyse(req: AnalyseRequest):
    if not req.question.strip(): raise HTTPException(400, "Question cannot be empty")
    if not req.api_key.strip(): raise HTTPException(400, "API key is required")
    if req.provider not in ("openai", "anthropic"): raise HTTPException(400, "Provider must be openai or anthropic")
    from analysis import TOOL_DESCRIPTIONS, run_tool
    from llm_router import run_analysis
    try:
        result = await run_analysis(question=req.question, store_data=req.store_data.model_dump(), provider=req.provider, api_key=req.api_key, model=req.model)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
