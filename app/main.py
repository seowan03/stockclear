from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS
from app.database import Base, engine, ensure_upload_files_user_id_column
from app.routers import ai, auth, history, inventory, kakao, upload

app = FastAPI(title="StockClear Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(kakao.router)
app.include_router(upload.router)
app.include_router(history.router)
app.include_router(inventory.router)
app.include_router(ai.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_upload_files_user_id_column()


@app.get("/")
def read_root():
    return FileResponse("static/upload.html")


app.mount("/js", StaticFiles(directory="js"), name="js")
app.mount("/", StaticFiles(directory="static"), name="static")
