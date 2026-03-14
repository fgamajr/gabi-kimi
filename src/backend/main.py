from fastapi import FastAPI
from src.backend.core.config import settings
from src.backend.data.db import MongoDB

app = FastAPI(title="GABI DOU API")

@app.on_event("startup")
async def startup_db_client():
    MongoDB.connect()

@app.on_event("shutdown")
async def shutdown_db_client():
    if MongoDB.client:
        MongoDB.client.close()

@app.get("/")
async def root():
    return {"message": "GABI DOU API is running"}
