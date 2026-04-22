from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="ProfitAgent Analytics Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/health")
def health():
    return {"status": "ok", "service": "ProfitAgent Analytics Backend"}

@app.post("/api/analyse")
async def analyse(req: AnalyseRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API key is required")
    if req.provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be openai or anthropic")
    from analysis import TOOL_DESCRIPTIONS, run_tool
    from llm_router import run_analysis
    store_dict = req.store_data.model_dump()
    try:
        result = await run_analysis(
            question=req.question,
            store_data=store_dict,
            provider=req.provider,
            api_key=req.api_key,
            model=req.model
        )
        return {"status": "ok", "result": result}
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "authentication" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Invalid API key.")
        if "429" in error_msg or "rate_limit" in error_msg.lower():
            raise HTTPException(status_code=429, detail="Rate limit reached.")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {error_msg}")

@app.get("/api/tools")
def list_tools():
    from analysis import TOOL_DESCRIPTIONS
    return {"tools": [{"name": t["name"], "description": t["description"]} for t in TOOL_DESCRIPTIONS]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
