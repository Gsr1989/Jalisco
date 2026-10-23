from contextlib import asynccontextmanager

from fastapi import FastAPI
from a2wsgi import WSGIMiddleware

# PAGINA FLASK
from pagina import app as flask_app

# BOT TELEGRAM
from bot import app as telegram_app


# ====================================
# INICIAR AMBAS APLICACIONES
# ====================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    async with telegram_app.router.lifespan_context(
        telegram_app
    ):
        print("BOT TELEGRAM INICIADO")
        print("PAGINA FLASK DISPONIBLE")

        yield

    print("SERVIDOR FINALIZADO")


# ====================================
# SERVIDOR PRINCIPAL
# ====================================

app = FastAPI(
    title="Servidor Unificado",
    lifespan=lifespan
)


# ====================================
# COMPROBAR ESTADO
# ====================================

@app.get("/health")
async def health():

    return {
        "ok": True,
        "flask": "integrado",
        "telegram": "integrado"
    }


# ====================================
# BOT TELEGRAM
# ====================================

app.mount(
    "/telegram",
    telegram_app
)


# ====================================
# PAGINA FLASK
# ====================================

app.mount(
    "/",
    WSGIMiddleware(flask_app)
)
