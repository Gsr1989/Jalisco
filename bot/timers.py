"""bot/timers.py — Timers de 36h (SOLO EN RAM), recordatorios y eliminación automática de folios.

Los timers viven únicamente en memoria: si Render reinicia, se pierden (a propósito).
Nada de timers se guarda en Supabase. Requiere un solo worker (bot y panel comparten proceso).
"""
import asyncio
from datetime import datetime

from config import supabase, PRECIO_PERMISO
from bot.core import bot

timers_activos       = {}   # folio -> {"task","user_id","start_time","nombre"}
user_folios          = {}   # user_id -> [folios]
pending_comprobantes = {}

# ============ EXPIRACIÓN ======================================================

def _leer_estado_folio(folio: str):
    """Devuelve el estado del folio en BD, None si no existe. Lanza excepción si falla la red."""
    r = supabase.table("folios_registrados").select("estado").eq("folio", folio).limit(1).execute()
    if r.data:
        return r.data[0].get("estado")
    return None

async def eliminar_folio_automatico(folio: str):
    """Al vencer las 36h: borra el folio SOLO si en BD sigue PENDIENTE.
    Si ya fue validado / se detuvo el timer / mandó comprobante, NO se toca."""
    try:
        user_id = timers_activos.get(folio, {}).get("user_id")

        estado = "?"
        for intento in range(3):
            try:
                estado = await asyncio.to_thread(_leer_estado_folio, folio)
                break
            except Exception as e:
                print(f"[TIMER] Error leyendo estado {folio} (intento {intento+1}/3): {e}")
                await asyncio.sleep(3)
        else:
            # No se pudo confirmar el estado: JAMÁS borrar a ciegas
            print(f"[TIMER] No se pudo verificar {folio}; NO se elimina")
            limpiar_timer_folio(folio)
            return

        if estado != "PENDIENTE":
            print(f"[TIMER] Folio {folio} estado={estado}; no se elimina")
            limpiar_timer_folio(folio)
            return

        await asyncio.to_thread(lambda: (
            supabase.table("folios_registrados").delete().eq("folio", folio).execute(),
            supabase.table("borradores_registros").delete().eq("folio", folio).execute(),
        ))
        if user_id:
            await bot.send_message(user_id,
                f"⏰ TIEMPO AGOTADO - ESTADO DE JALISCO\n\n"
                f"El folio {folio} ha sido eliminado por no completar el pago en 36 horas.\n\n"
                f"📋 Para generar otro permiso use /banamex")
        limpiar_timer_folio(folio)
    except Exception as e:
        print(f"Error eliminando folio {folio}: {e}")
        limpiar_timer_folio(folio)

async def enviar_recordatorio(folio: str, minutos_restantes: int):
    try:
        if folio not in timers_activos: return
        user_id = timers_activos[folio]["user_id"]
        await bot.send_message(user_id,
            f"⚡ RECORDATORIO DE PAGO - JALISCO\n\n"
            f"Folio: {folio}\n"
            f"Tiempo restante: {minutos_restantes} minutos\n"
            f"Monto: ${PRECIO_PERMISO}\n\n"
            f"📸 Envíe su comprobante de pago (imagen).\n\n"
            f"📋 Para generar otro permiso use /banamex")
    except Exception as e:
        print(f"Error enviando recordatorio para folio {folio}: {e}")

# ============ TIMER (RAM) =====================================================

async def iniciar_timer_eliminacion(user_id: int, folio: str, nombre: str = ""):
    async def timer_task():
        print(f"[TIMER] Iniciado folio {folio}, usuario {user_id} (36h)")
        await asyncio.sleep(34.5 * 3600)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 90)
        await asyncio.sleep(30 * 60)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 60)
        await asyncio.sleep(30 * 60)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 30)
        await asyncio.sleep(20 * 60)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 10)
        await asyncio.sleep(10 * 60)
        if folio in timers_activos:
            print(f"[TIMER] Expirado folio {folio} - revisando estado")
            await eliminar_folio_automatico(folio)

    task = asyncio.create_task(timer_task())
    timers_activos[folio] = {"task": task, "user_id": user_id,
                             "start_time": datetime.now(), "nombre": nombre or ""}
    user_folios.setdefault(user_id, []).append(folio)
    print(f"[SISTEMA] Timer 36h iniciado folio {folio}, total: {len(timers_activos)}")

def cancelar_timer_folio(folio: str):
    if folio in timers_activos:
        _cancelar_task_seguro(timers_activos[folio]["task"])
        user_id = timers_activos[folio]["user_id"]
        del timers_activos[folio]
        if user_id in user_folios and folio in user_folios[user_id]:
            user_folios[user_id].remove(folio)
            if not user_folios[user_id]: del user_folios[user_id]
        print(f"[SISTEMA] Timer cancelado folio {folio}")

def limpiar_timer_folio(folio: str):
    if folio in timers_activos:
        user_id = timers_activos[folio]["user_id"]
        del timers_activos[folio]
        if user_id in user_folios and folio in user_folios[user_id]:
            user_folios[user_id].remove(folio)
            if not user_folios[user_id]: del user_folios[user_id]

def obtener_folios_usuario(user_id: int) -> list:
    return user_folios.get(user_id, [])

# ============ CANCELAR TODOS ==================================================

def _cancelar_task_seguro(task):
    """Cancela la tarea aunque se llame desde otro hilo (el panel Flask corre en un hilo aparte)."""
    try:
        loop = task.get_loop()
        loop.call_soon_threadsafe(task.cancel)
    except Exception:
        try: task.cancel()
        except Exception: pass

def cancelar_todos_usuario(user_id: int) -> list:
    """Cancela TODOS los timers de un usuario de Telegram. Devuelve la lista de folios cancelados."""
    folios = list(user_folios.get(user_id, []))
    cancelados = []
    for folio in folios:
        info = timers_activos.pop(folio, None)
        if info:
            _cancelar_task_seguro(info["task"])
            cancelados.append(folio)
    user_folios.pop(user_id, None)
    print(f"[SISTEMA] cancelar_todos_usuario {user_id}: {len(cancelados)} timers")
    return cancelados

def cancelar_todos() -> list:
    """Cancela TODOS los timers del bot sin importar el usuario. Devuelve los folios cancelados.
    Los timers que se creen después de esto siguen vivos con normalidad."""
    cancelados = []
    for folio in list(timers_activos.keys()):
        info = timers_activos.pop(folio, None)
        if info:
            _cancelar_task_seguro(info["task"])
            cancelados.append(folio)
    user_folios.clear()
    print(f"[SISTEMA] cancelar_todos: {len(cancelados)} timers")
    return cancelados
