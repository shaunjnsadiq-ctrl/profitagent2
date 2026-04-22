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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
