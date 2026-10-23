"""
main.py — Punto de entrada único (un solo servicio en Render).

  • FastAPI  → webhook de Telegram (/webhook), /health y /status
  • Flask    → toda la web (login, admin, usuarios, consulta pública) montada en "/"

Arranque:  uvicorn main:app --host 0.0.0.0 --port $PORT      (o:  python main.py)
"""
import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from aiogram import types

try:
    from a2wsgi import WSGIMiddleware
except ImportError:  # fallback si no está instalado a2wsgi
    from fastapi.middleware.wsgi import WSGIMiddleware

from config import BASE_URL
from bot.core import bot, dp
from bot import handlers  # noqa: F401  (registra los handlers en dp)
from bot.folios import inicializar_folio_cursors, _inicializar_folio_rep, _folio_cursors, _rep_counter
from bot.pdf import _cargar_plantillas, PDF417_DISPONIBLE
from bot.timers import timers_activos
from web.app import app as flask_app

VERSION = "19.0"

# ============ FASTAPI =========================================================

_keep_task = None

async def keep_alive():
    while True:
        await asyncio.sleep(600)
        print("[HEARTBEAT] Sistema Jalisco activo")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _keep_task
    try:
        await inicializar_folio_cursors()
        await asyncio.to_thread(_inicializar_folio_rep)
        _cargar_plantillas()
        await bot.delete_webhook(drop_pending_updates=True)
        if BASE_URL:
            wh = f"{BASE_URL}/webhook"
            await bot.set_webhook(wh, allowed_updates=["message","callback_query"])
            print(f"[WEBHOOK] Configurado: {wh}")
            _keep_task = asyncio.create_task(keep_alive())
        else:
            print("[POLLING] Sin webhook")
        print(f"[SISTEMA] Jalisco v{VERSION} iniciado — "
              f"PDF417 {'✅' if PDF417_DISPONIBLE else '⚠️ fallback QR'} — "
              f"Folio rep: {_rep_counter['actual']}")
        yield
    except Exception as e:
        print(f"[ERROR CRÍTICO] {e}"); yield
    finally:
        if _keep_task:
            _keep_task.cancel()
            with suppress(asyncio.CancelledError): await _keep_task
        await bot.session.close()

app = FastAPI(lifespan=lifespan, title="Sistema Jalisco Digital", version=VERSION)

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data   = await request.json()
        update = types.Update(**data)
        await dp.feed_webhook_update(bot, update)
        return {"ok": True}
    except Exception as e:
        print(f"[ERROR] webhook: {e}")
        return {"ok": False, "error": str(e)}

# OJO: el health pasó de "/" a "/health" porque "/" ahora es el login de la web.
@app.get("/health")
async def health():
    return {
        "ok":                True,
        "version":           VERSION,
        "entidad":           "Jalisco",
        "pdf417_disponible": PDF417_DISPONIBLE,
        "active_timers":     len(timers_activos),
        "cursors_actuales":  _folio_cursors,
        "folio_rep_actual":  _rep_counter["actual"],
        "cambios_v19.0":     ["Web Flask montada dentro del bot — un solo servicio",
                              "Código dividido en módulos bot/ y web/"]
    }

@app.get("/status")
async def status_detail():
    from datetime import datetime
    from config import ZONA_MEXICO
    return {
        "sistema":             f"Jalisco Digital v{VERSION}",
        "pdf417_disponible":   PDF417_DISPONIBLE,
        "total_timers":        len(timers_activos),
        "folios_activos":      list(timers_activos.keys()),
        "cursors_por_prefijo": _folio_cursors,
        "folio_rep_actual":    _rep_counter["actual"],
        "timestamp":           datetime.now(ZONA_MEXICO).isoformat(),
    }

# ============ WEB FLASK montada en "/" (SIEMPRE al final, después de las rutas FastAPI) ====
app.mount("/", WSGIMiddleware(flask_app))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"[ARRANQUE] Jalisco v{VERSION} — puerto {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
