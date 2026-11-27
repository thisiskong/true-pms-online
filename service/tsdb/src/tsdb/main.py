"""FastAPI application. Run: uvicorn tsdb.main:app --port 8080 --workers 4"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.meta import router as meta_router
from .api.routes import router
from .config import get_settings
from .store import close_store, open_store


@asynccontextmanager
async def lifespan(_: FastAPI):
  await open_store(get_settings())
  try:
    yield
  finally:
    await close_store()


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title="tsdb", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(meta_router)
