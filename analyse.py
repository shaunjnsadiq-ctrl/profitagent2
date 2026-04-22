from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from llm_router import run_analysis
from tools.analysis import run_tool, TOOL_DESCRIPTIONS

router = APIRouter()


# ── REQUEST / RESPONSE MODELS ─────────────────────────────────────────────────

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
    shopifyUrl: Optional[str] = None


class AnalyseRequest(BaseModel):
    question: str
    store_data: StoreData
    provider: str           # "openai" or "anthropic"
    api_key: str
    model: str              # e.g. "gpt-4o", "claude-sonnet-4-20250514"


class RunToolRequest(BaseModel):
    tool_name: str
    store_data: StoreData


# ── ROUTES ────────────────────────────────────────────────────────────────────

@router.post("/analyse")
async def analyse(req: AnalyseRequest):
    """
    Main endpoint. Takes a question + store data + LLM credentials.
    Runs the tool calling loop and returns a structured JSON report.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API key is required")
    if req.provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

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
        # Surface auth errors clearly
        if "401" in error_msg or "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Invalid API key. Please check your key in Settings.")
        if "rate_limit" in error_msg.lower() or "429" in error_msg:
            raise HTTPException(status_code=429, detail="Rate limit reached on your API key. Please wait a moment.")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {error_msg}")


@router.post("/run-tool")
async def run_single_tool(req: RunToolRequest):
    """Run a single analysis tool directly — useful for debugging."""
    store_dict = req.store_data.model_dump()
    result = run_tool(req.tool_name, store_dict)
    return {"status": "ok", "result": result}


@router.get("/tools")
async def list_tools():
    """Return the list of available analysis tools."""
    return {
        "tools": [
            {"name": t["name"], "description": t["description"]}
            for t in TOOL_DESCRIPTIONS
        ]
    }
