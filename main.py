from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.analyse import router as analyse_router
from routes.health import router as health_router

app = FastAPI(title="ProfitAgent Analytics Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your Netlify domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(analyse_router, prefix="/api")


# ── PIXEL ROUTES ──────────────────────────────────────────────────────────────

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse
import os, json
from datetime import datetime

# In-memory event store (resets on redeploy — fine for demo)
pixel_events = []

@app.get("/pixel/pa.js")
async def serve_pixel():
    """Serve the pixel JavaScript file."""
    pixel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pa.js")
    if os.path.exists(pixel_path):
        return FileResponse(pixel_path, media_type="application/javascript",
                          headers={"Access-Control-Allow-Origin": "*",
                                   "Cache-Control": "public, max-age=3600"})
    # Fallback inline pixel
    js = """(function(){
  var s=document.querySelector('script[data-store]');
  var storeId=s?s.getAttribute('data-store'):'unknown';
  window.ProfitAgentPixel={storeId:storeId,track:function(e,p){
    var payload={store_id:storeId,event:e,properties:p||{},timestamp:new Date().toISOString()};
    if(navigator.sendBeacon){navigator.sendBeacon('""" + "/pixel/event" + """',new Blob([JSON.stringify(payload)],{type:'application/json'}));}
    else{fetch('""" + "/pixel/event" + """',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).catch(function(){});}
  }};
  window.pa=function(e,p){window.ProfitAgentPixel.track(e,p);};
  window.ProfitAgentPixel.track('pixel_loaded',{store_id:storeId});
})();"""
    from fastapi.responses import Response
    return Response(content=js, media_type="application/javascript",
                   headers={"Access-Control-Allow-Origin": "*"})

@app.post("/pixel/event")
async def receive_event(request: Request):
    """Receive pixel events from any store."""
    try:
        body = await request.body()
        event = json.loads(body)
        event["received_at"] = datetime.utcnow().isoformat()
        pixel_events.append(event)
        # Keep last 500 events only
        if len(pixel_events) > 500:
            pixel_events.pop(0)
        return {"status": "ok", "event": event.get("event")}
    except Exception as e:
        return {"status": "ok"}  # Never reject — pixel fires are best-effort

@app.get("/pixel/events")
async def get_events(store_id: str = None, limit: int = 50):
    """View recent pixel events — useful for debugging."""
    events = pixel_events[-limit:]
    if store_id:
        events = [e for e in events if e.get("store_id") == store_id]
    return {"status": "ok", "count": len(events), "events": list(reversed(events))}

@app.get("/pixel/demo")
async def pixel_demo():
    """Serve the pixel demo store page."""
    demo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pixel_demo.html")
    if os.path.exists(demo_path):
        return FileResponse(demo_path, media_type="text/html")
    return HTMLResponse("<h1>Demo page not found</h1>")

@app.get("/pixel/stats/{store_id}")
async def pixel_stats(store_id: str):
    """Basic stats for a store's pixel events."""
    store_events = [e for e in pixel_events if e.get("store_id") == store_id]
    event_counts = {}
    for e in store_events:
        name = e.get("event", "unknown")
        event_counts[name] = event_counts.get(name, 0) + 1
    return {
        "status": "ok",
        "store_id": store_id,
        "total_events": len(store_events),
        "event_breakdown": event_counts,
        "pixel_status": "firing" if store_events else "no events yet"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
