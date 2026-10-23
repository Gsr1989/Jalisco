"""web/folios.py — Folios de la web, timer de pago (2h) y folios de página 2 / representativo (versión web)."""
import re
import time
from datetime import datetime, timedelta

from config import supabase, ENTIDAD
from web.utils import logger, parse_date_any

# ===================== FOLIOS JALISCO =====================
PREFIJO_JALISCO = 900000000
LIMITE_MAXIMO   = 999999999

def generar_folio_automatico_jalisco():
    logger.info("[FOLIO] Iniciando generación automática")
    todos = supabase.table("folios_registrados")\
        .select("folio").eq("entidad", ENTIDAD).execute().data or []
    logger.info(f"[FOLIO] Total folios en BD: {len(todos)}")

    folios_jalisco = []
    for f in todos:
        try:
            num = int(f['folio'])
            if PREFIJO_JALISCO <= num <= LIMITE_MAXIMO:
                folios_jalisco.append(num)
        except:
            pass

    if not folios_jalisco:
        siguiente = PREFIJO_JALISCO
    else:
        siguiente = max(folios_jalisco) + 1

    for intento in range(10000000):
        candidato = siguiente + intento
        if candidato > LIMITE_MAXIMO:
            raise Exception(f"Límite máximo alcanzado ({LIMITE_MAXIMO})")
        folio_str = f"{candidato:09d}"
        if candidato not in folios_jalisco:
            logger.info(f"[FOLIO] ✅ {folio_str} (intento {intento+1})")
            return folio_str

    raise Exception("Sin folio disponible tras 10,000,000 intentos")


def guardar_folio_con_reintento(datos, username):
    if not datos.get("folio") or not re.fullmatch(r"\d{9}", str(datos.get("folio", ""))):
        try:
            datos["folio"] = generar_folio_automatico_jalisco()
        except Exception as e:
            logger.error(f"[ERROR] Folio: {e}")
            return False

    folio_inicial = int(datos["folio"])
    fexp_date = parse_date_any(datos["fecha_exp"])
    fven_date = parse_date_any(datos["fecha_ven"])

    for intento in range(10000000):
        folio_actual = folio_inicial + intento
        if folio_actual < PREFIJO_JALISCO or folio_actual > LIMITE_MAXIMO:
            return False

        folio_str = f"{folio_actual:09d}"
        try:
            supabase.table("folios_registrados").insert({
                "folio":             folio_str,
                "marca":             datos["marca"],
                "linea":             datos["linea"],
                "anio":              datos["anio"],
                "numero_serie":      datos["serie"],
                "numero_motor":      datos["motor"],
                "color":             datos.get("color", "BLANCO"),
                "nombre":            datos.get("nombre", "SIN NOMBRE"),
                "fecha_expedicion":  fexp_date.isoformat(),
                "fecha_vencimiento": fven_date.isoformat(),
                "entidad":           ENTIDAD,
                "estado":            "ACTIVO",
                "creado_por":        username
            }).execute()
            datos["folio"] = folio_str
            logger.info(f"[DB] ✅ {folio_str} (intento {intento+1})")
            return True
        except Exception as e:
            em = str(e).lower()
            if "duplicate" in em or "unique" in em or "23505" in em:
                continue
            logger.error(f"[ERROR BD] {e}")
            return False

    return False

# ===================== TIMER DE PAGO =====================
def get_timer_info(usuario: dict):
    if usuario.get("pagado"):
        return None
    creado_en = usuario.get("created_at")
    if not creado_en:
        return None
    try:
        if isinstance(creado_en, str):
            creado_en = datetime.fromisoformat(
                creado_en.replace("Z", "+00:00")).replace(tzinfo=None)
        restante = 7200 - (datetime.utcnow() - creado_en).total_seconds()
        return {
            "limite_iso":         (creado_en + timedelta(hours=2)).isoformat(),
            "segundos_restantes": max(0, int(restante)),
            "vencido":            restante <= 0
        }
    except Exception as e:
        logger.error(f"[TIMER] {e}")
        return None

# ===================== FOLIOS PÁGINA 2 =====================
def generar_folios_pagina2() -> dict:
    ts = int(time.time())
    return {
        "referencia_pago":   273312001734 + ts % 1000000,
        "num_autorizacion":  370803 + ts % 100000,
        "folio_seguimiento": f"GZ{ts % 1000}xy{ts % 10}",
        "linea_captura":     41340816 + ts % 1000000
    }

def obtener_folio_representativo():
    return 21385 + int(time.time()) % 100000
