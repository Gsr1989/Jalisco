"""bot/handlers.py — FSM, comandos, callbacks y tarea en background del bot.
El orden de los handlers es el mismo que en el código original (aiogram usa el primero que coincide)."""
import asyncio
from datetime import datetime, timedelta

from aiogram import types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, ContentType, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import supabase, PRECIO_PERMISO, ZONA_MEXICO
from bot.core import bot, dp
from bot.folios import guardar_folio_con_reintento, _sb_insertar_borrador
from bot.timers import (
    timers_activos, pending_comprobantes,
    iniciar_timer_eliminacion, cancelar_timer_folio, obtener_folios_usuario,
)
from bot.pdf import _generar_pdf_unificado

# ============ FSM =============================================================

class PermisoForm(StatesGroup):
    marca  = State()
    linea  = State()
    anio   = State()
    serie  = State()
    motor  = State()
    color  = State()
    nombre = State()

# ============ BACKGROUND ======================================================

async def _generar_y_enviar_background(chat_id: int, datos: dict, user_id: int):
    try:
        fecha_ven   = datos["fecha_ven"]
        pdf_path    = await asyncio.to_thread(_generar_pdf_unificado, datos)
        folio_final = datos["folio"]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔑 Validar Admin", callback_data=f"validar_{folio_final}"),
            InlineKeyboardButton(text="⏹️ Detener Timer", callback_data=f"detener_{folio_final}")
        ]])
        await bot.send_document(
            chat_id, FSInputFile(pdf_path),
            caption=(f"📋 PERMISO DE CIRCULACIÓN - JALISCO\n"
                     f"Folio: {folio_final}\nVigencia: 30 días ({fecha_ven.strftime('%d/%m/%Y')})\n\n"
                     f"✅ Documento con 2 páginas unificadas\n⏰ TIMER ACTIVO (36 horas)"),
            reply_markup=keyboard)
        try:
            await asyncio.to_thread(_sb_insertar_borrador, datos, user_id)
        except Exception as e:
            print(f"[WARN] Error guardando borradores: {e}")
        await iniciar_timer_eliminacion(user_id, folio_final)
        await bot.send_message(user_id,
            "💰 INSTRUCCIONES DE PAGO\n\n"
            f"📄 Folio: {folio_final}\n💵 Monto: ${PRECIO_PERMISO}\n"
            "⏰ Tiempo límite: 36 horas\n\n"
            "🏦 TRANSFERENCIA:\n• Institución: SPIN BY OXXO\n"
            "• Titular: GUILLERMO S.R\n• Cuenta: 728969000048442454\n"
            f"• Concepto: Permiso {folio_final}\n\n"
            "🏪 OXXO:\n• Referencia: 2242170180214090\n• Titular: GUILLERMO S.R\n\n"
            "📸 Envía foto del comprobante para validar.\n"
            "⚠️ Sin pago en 36h el folio se elimina.\n\n"
            "📋 Para generar otro permiso use /banamex")
    except Exception as e:
        print(f"[ERROR] background folio {datos.get('folio','?')}: {e}")
        try:
            await bot.send_message(user_id,
                f"❌ Error al generar el documento: {e}\n\nUse /banamex para reintentar.")
        except Exception:
            pass

# ============ HANDLERS ========================================================

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏛️ SISTEMA DIGITAL DEL ESTADO DE JALISCO\n\n"
        f"💰 Costo: ${PRECIO_PERMISO}\n"
        "⏰ Tiempo límite: 36 horas\n\n"
        "⚠️ Su folio será eliminado si no paga dentro del tiempo límite")

@dp.message(Command("banamex"))
async def banamex_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    folios_activos = obtener_folios_usuario(message.from_user.id)
    if folios_activos:
        lineas = []
        for f in folios_activos:
            if f in timers_activos:
                mins = max(0, 2160 - int(
                    (datetime.now()-timers_activos[f]["start_time"]).total_seconds()/60))
                lineas.append(f"• {f}  ({mins//60}h {mins%60}min restantes)")
            else:
                lineas.append(f"• {f}  (sin timer)")
        botones = [[InlineKeyboardButton(text=f"⏹️ Detener {f}", callback_data=f"detener_{f}")]
                   for f in folios_activos]
        await message.answer(
            f"📋 FOLIOS JALISCO ACTIVOS ({len(folios_activos)}):\n\n" +
            "\n".join(lineas) + "\n\nPuedes detener el timer de cualquier folio:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=botones))
    await message.answer(
        f"🚗 NUEVO PERMISO - ESTADO DE JALISCO\n\n"
        f"💰 Costo: ${PRECIO_PERMISO}\n⏰ Plazo de pago: 36 horas\n\n"
        f"Primer paso: MARCA del vehículo:")
    await state.set_state(PermisoForm.marca)

@dp.message(PermisoForm.marca)
async def get_marca(message: types.Message, state: FSMContext):
    await state.update_data(marca=message.text.strip().upper())
    await message.answer("LÍNEA/MODELO del vehículo:")
    await state.set_state(PermisoForm.linea)

@dp.message(PermisoForm.linea)
async def get_linea(message: types.Message, state: FSMContext):
    await state.update_data(linea=message.text.strip().upper())
    await message.answer("AÑO del vehículo (4 dígitos):")
    await state.set_state(PermisoForm.anio)

@dp.message(PermisoForm.anio)
async def get_anio(message: types.Message, state: FSMContext):
    anio = message.text.strip()
    if not anio.isdigit() or len(anio) != 4:
        await message.answer("⚠️ Formato inválido. Use 4 dígitos (ej. 2021):"); return
    await state.update_data(anio=anio)
    await message.answer("NÚMERO DE SERIE:")
    await state.set_state(PermisoForm.serie)

@dp.message(PermisoForm.serie)
async def get_serie(message: types.Message, state: FSMContext):
    await state.update_data(serie=message.text.strip().upper())
    await message.answer("NÚMERO DE MOTOR:")
    await state.set_state(PermisoForm.motor)

@dp.message(PermisoForm.motor)
async def get_motor(message: types.Message, state: FSMContext):
    await state.update_data(motor=message.text.strip().upper())
    await message.answer("COLOR del vehículo:")
    await state.set_state(PermisoForm.color)

@dp.message(PermisoForm.color)
async def get_color(message: types.Message, state: FSMContext):
    await state.update_data(color=message.text.strip().upper())
    await message.answer("NOMBRE COMPLETO del propietario:")
    await state.set_state(PermisoForm.nombre)

@dp.message(PermisoForm.nombre)
async def get_nombre(message: types.Message, state: FSMContext):
    datos              = await state.get_data()
    datos["nombre"]    = message.text.strip().upper()
    hoy                = datetime.now(ZONA_MEXICO)
    datos["fecha_exp"] = hoy
    datos["fecha_ven"] = hoy + timedelta(days=30)
    await state.clear()
    ok = await guardar_folio_con_reintento(
        datos, message.from_user.id, message.from_user.username, "1")
    if not ok:
        await message.answer(
            "❌ No se pudo registrar el folio. Intenta de nuevo con /banamex\n\n"
            "📋 Para generar otro permiso use /banamex"); return
    await message.answer(
        f"🔄 Generando documentación...\n"
        f"<b>Folio:</b> {datos['folio']}\n<b>Titular:</b> {datos['nombre']}",
        parse_mode="HTML")
    asyncio.create_task(
        _generar_y_enviar_background(message.chat.id, datos, message.from_user.id))

# ============ CALLBACKS =======================================================

@dp.callback_query(lambda c: c.data and c.data.startswith("validar_"))
async def callback_validar_admin(callback: CallbackQuery):
    folio = callback.data.replace("validar_", "")
    if folio in timers_activos:
        uid = timers_activos[folio]["user_id"]
        cancelar_timer_folio(folio)
        try:
            now = datetime.now().isoformat()
            await asyncio.to_thread(lambda: (
                supabase.table("folios_registrados").update(
                    {"estado":"VALIDADO_ADMIN","fecha_comprobante":now}).eq("folio",folio).execute(),
                supabase.table("borradores_registros").update(
                    {"estado":"VALIDADO_ADMIN","fecha_comprobante":now}).eq("folio",folio).execute(),
            ))
        except Exception as e:
            print(f"Error actualizando BD folio {folio}: {e}")
        await callback.answer("✅ Folio validado por administración", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        try:
            await bot.send_message(uid,
                f"✅ PAGO VALIDADO POR ADMINISTRACIÓN - JALISCO\n"
                f"Folio: {folio}\nTu permiso está activo.\n\n"
                f"📋 Para generar otro permiso use /banamex")
        except Exception as e:
            print(f"Error notificando usuario: {e}")
    else:
        await callback.answer("❌ Folio no encontrado en timers activos", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith("detener_"))
async def callback_detener_timer(callback: CallbackQuery):
    folio = callback.data.replace("detener_", "")
    if folio in timers_activos:
        cancelar_timer_folio(folio)
        try:
            await asyncio.to_thread(lambda:
                supabase.table("folios_registrados").update(
                    {"estado":"TIMER_DETENIDO","fecha_detencion":datetime.now().isoformat()}
                ).eq("folio", folio).execute())
        except Exception as e:
            print(f"Error actualizando BD: {e}")
        await callback.answer("⏹️ Timer detenido exitosamente", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"⏹️ TIMER DETENIDO\n\nFolio: {folio}\n"
            f"El timer de eliminación ha sido detenido.\n\n"
            f"📋 Para generar otro permiso use /banamex")
    else:
        await callback.answer("❌ Timer ya no está activo", show_alert=True)

@dp.message(lambda m: m.text and m.text.strip().upper().startswith("SERO"))
async def codigo_admin(message: types.Message):
    texto = message.text.strip().upper()
    if len(texto) <= 4:
        await message.answer(
            "⚠️ Formato: SERO[folio]\nEjemplo: SERO980000000\n\n"
            "📋 Para generar otro permiso use /banamex"); return
    folio_admin = texto[4:]
    if folio_admin in timers_activos:
        uid = timers_activos[folio_admin]["user_id"]
        cancelar_timer_folio(folio_admin)
        try:
            now = datetime.now().isoformat()
            await asyncio.to_thread(lambda: (
                supabase.table("folios_registrados").update(
                    {"estado":"VALIDADO_ADMIN","fecha_comprobante":now}).eq("folio",folio_admin).execute(),
                supabase.table("borradores_registros").update(
                    {"estado":"VALIDADO_ADMIN","fecha_comprobante":now}).eq("folio",folio_admin).execute(),
            ))
        except Exception as e:
            print(f"Error actualizando BD folio {folio_admin}: {e}")
        await message.answer(
            f"✅ VALIDACIÓN OK\nFolio: {folio_admin}\nTimer cancelado.\n\n"
            f"📋 Para generar otro permiso use /banamex")
        try:
            await bot.send_message(uid,
                f"✅ PAGO VALIDADO POR ADMINISTRACIÓN - JALISCO\n"
                f"Folio: {folio_admin}\nTu permiso está activo.\n\n"
                f"📋 Para generar otro permiso use /banamex")
        except Exception as e:
            print(f"Error notificando usuario: {e}")
    else:
        await message.answer(
            f"❌ Folio {folio_admin} no encontrado en timers activos.\n\n"
            f"📋 Para generar otro permiso use /banamex")

@dp.message(lambda m: m.content_type == ContentType.PHOTO)
async def recibir_comprobante(message: types.Message):
    try:
        uid    = message.from_user.id
        folios = obtener_folios_usuario(uid)
        if not folios:
            await message.answer(
                "ℹ️ No hay trámites pendientes.\n\n📋 Para generar otro permiso use /banamex"); return
        if len(folios) > 1:
            lista = "\n".join(f"• {f}" for f in folios)
            pending_comprobantes[uid] = "waiting_folio"
            await message.answer(
                f"📄 Tienes varios folios activos:\n\n{lista}\n\n"
                f"Responde con el NÚMERO DE FOLIO para este comprobante.\n\n"
                f"📋 Para generar otro permiso use /banamex"); return
        folio = folios[0]; cancelar_timer_folio(folio)
        now = datetime.now().isoformat()
        await asyncio.to_thread(lambda: (
            supabase.table("folios_registrados").update(
                {"estado":"COMPROBANTE_ENVIADO","fecha_comprobante":now}).eq("folio",folio).execute(),
            supabase.table("borradores_registros").update(
                {"estado":"COMPROBANTE_ENVIADO","fecha_comprobante":now}).eq("folio",folio).execute(),
        ))
        await message.answer(
            f"✅ Comprobante recibido.\n📄 Folio: {folio}\n⏹️ Timer detenido.\n\n"
            f"📋 Para generar otro permiso use /banamex")
    except Exception as e:
        print(f"[ERROR] recibir_comprobante: {e}")
        await message.answer(
            "❌ Error procesando comprobante.\n\n📋 Para generar otro permiso use /banamex")

@dp.message(lambda m: m.from_user.id in pending_comprobantes
            and pending_comprobantes[m.from_user.id] == "waiting_folio")
async def especificar_folio_comprobante(message: types.Message):
    try:
        uid       = message.from_user.id
        folio_esp = message.text.strip().upper()
        if folio_esp not in obtener_folios_usuario(uid):
            await message.answer(
                "❌ Ese folio no está en tu lista activa.\n\n"
                "📋 Para generar otro permiso use /banamex"); return
        cancelar_timer_folio(folio_esp)
        del pending_comprobantes[uid]
        now = datetime.now().isoformat()
        await asyncio.to_thread(lambda: (
            supabase.table("folios_registrados").update(
                {"estado":"COMPROBANTE_ENVIADO","fecha_comprobante":now}).eq("folio",folio_esp).execute(),
            supabase.table("borradores_registros").update(
                {"estado":"COMPROBANTE_ENVIADO","fecha_comprobante":now}).eq("folio",folio_esp).execute(),
        ))
        await message.answer(
            f"✅ Comprobante asociado.\n📄 Folio: {folio_esp}\n⏹️ Timer detenido.\n\n"
            f"📋 Para generar otro permiso use /banamex")
    except Exception as e:
        print(f"[ERROR] especificar_folio: {e}")
        pending_comprobantes.pop(message.from_user.id, None)
        await message.answer("❌ Error.\n\n📋 Para generar otro permiso use /banamex")

@dp.message(Command("folios"))
async def ver_folios_activos(message: types.Message):
    folios = obtener_folios_usuario(message.from_user.id)
    if not folios:
        await message.answer(
            "ℹ️ No tienes folios pendientes.\n\n📋 Para generar otro permiso use /banamex"); return
    lista = []; botones = []
    for folio in folios:
        if folio in timers_activos:
            mins = max(0, 2160 - int(
                (datetime.now()-timers_activos[folio]["start_time"]).total_seconds()/60))
            lista.append(f"• {folio} ({mins//60}h {mins%60}min)")
        else:
            lista.append(f"• {folio} (sin timer)")
        botones.append([InlineKeyboardButton(
            text=f"⏹️ Detener {folio}", callback_data=f"detener_{folio}")])
    await message.answer(
        f"📋 FOLIOS JALISCO ACTIVOS ({len(folios)})\n\n" + "\n".join(lista) +
        "\n\n⏰ Timer 36h por folio.\n📸 Envía imagen para comprobante.\n\n"
        "📋 Para generar otro permiso use /banamex",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=botones))

@dp.message(lambda m: m.text and any(p in m.text.lower() for p in
    ['costo','precio','cuanto','cuánto','deposito','depósito','pago','valor','monto']))
async def responder_costo(message: types.Message):
    await message.answer(
        f"💰 El costo del permiso es ${PRECIO_PERMISO}.\n\n📋 Para generar otro permiso use /banamex")

@dp.message()
async def fallback(message: types.Message):
    await message.answer("🏛️ Sistema Digital Jalisco.")
