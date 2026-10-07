from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS
from app.database import init_db

from app.routers import ai, auth, history, inquiries, inventory, kakao, upload
from app.security import no_store_api_responses

app = FastAPI(title="StockClear Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.middleware("http")(no_store_api_responses)

app.include_router(auth.router)
app.include_router(kakao.router)
app.include_router(upload.router)
app.include_router(history.router)
app.include_router(inquiries.router)
app.include_router(inventory.router)
app.include_router(ai.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def read_root():
    return FileResponse("static/mainpage.html")


@app.get("/Sellpage.html")
def read_sell_page():
    return RedirectResponse("/sellpage/Sellpage.html")


app.mount("/js", StaticFiles(directory="js"), name="js")
app.mount("/css", StaticFiles(directory="css"), name="css")
app.mount("/", StaticFiles(directory="static"), name="static")
