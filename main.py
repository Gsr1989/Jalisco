import os
import hmac

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from a2wsgi import WSGIMiddleware

# IMPORTAR PAGINA FLASK
from pagina import app as flask_app

# IMPORTAR BOT TELEGRAM
from bot import app as bot_app
from bot import bot, dp


# ==========================================
# INICIALIZACION
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    # Iniciar recursos del bot
    async with bot_app.router.lifespan_context(bot_app):
        print("[SISTEMA] Bot iniciado")
        yield

    print("[SISTEMA] Cerrando servidor")


# ==========================================
# SERVIDOR PRINCIPAL
# ==========================================

app = FastAPI(
    title="Servidor Unificado",
    lifespan=lifespan
)


# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/health")
async def health():

    return {
        "ok": True,
        "servidor": "Flask + Telegram"
    }


# ==========================================
# WEBHOOK TELEGRAM
# ==========================================

@app.post("/webhook")
async def webhook(request: Request):

    secreto = os.environ.get(
        "TELEGRAM_WEBHOOK_SECRET", ""
    )

    recibido = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )

    if not secreto or not hmac.compare_digest(
        secreto, recibido
    ):
        raise HTTPException(
            status_code=403,
            detail="No autorizado"
        )

    datos = await request.json()

    from aiogram import types

    update = types.Update(**datos)

    await dp.feed_webhook_update(
        bot,
        update
    )

    return {"ok": True}


# ==========================================
# PAGINA WEB FLASK
# ==========================================

app.mount(
    "/",
    WSGIMiddleware(flask_app)
)
