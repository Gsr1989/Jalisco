"""bot/folios.py — Generación de folios (watermark Supabase), inserts, folios página 2 y folio representativo."""
import asyncio
import json
import re

from config import supabase

# ============ FOLIOS — WATERMARK EN SUPABASE =================================
FOLIO_PREFIJO_JAL = "JAL"

PREFIJOS_VALIDOS = {
    "1": 980000000,
    "2": 890000000,
    "3": 780000000,
}
_folio_cursors = {}
_folio_lock    = asyncio.Lock()

def _sb_leer_watermark_jal(prefijo_num: str) -> int | None:
    clave = f"{FOLIO_PREFIJO_JAL}_{prefijo_num}"
    try:
        r = supabase.table("folio_watermark").select("ultimo_asignado").eq("prefijo", clave).execute()
        if r.data:
            return r.data[0]["ultimo_asignado"]
        return None
    except Exception as e:
        print(f"[ERROR] leer_watermark JAL {prefijo_num}: {e}")
        return None

def _sb_guardar_watermark_jal(prefijo_num: str, numero: int):
    clave = f"{FOLIO_PREFIJO_JAL}_{prefijo_num}"
    try:
        supabase.table("folio_watermark").upsert({
            "prefijo":         clave,
            "ultimo_asignado": numero
        }).execute()
        print(f"[WATERMARK JAL] Guardado {clave}: {numero}")
    except Exception as e:
        print(f"[ERROR] guardar_watermark JAL {prefijo_num}: {e}")

def _leer_cursors_local():
    try:
        with open("folio_cursors.json") as f:
            return {k: int(v) for k, v in json.load(f).items()}
    except Exception:
        return {}

def _guardar_cursors_local(cursors: dict):
    try:
        with open("folio_cursors.json", "w") as f:
            json.dump(cursors, f)
    except Exception as e:
        print(f"[WARN] No se pudo persistir cursors: {e}")

def _leer_ultimo_folio_por_prefijo_db(prefijo_num: str) -> int:
    try:
        base = PREFIJOS_VALIDOS[prefijo_num]
        resp = (
            supabase.table("folios_registrados")
            .select("folio")
            .gte("folio", str(base))
            .lt("folio", str(base + 100000000))
            .order("folio", desc=True)
            .limit(1)
            .execute()
        )
        if resp.data:
            ultimo = int(resp.data[0]["folio"])
            print(f"[FOLIO][DB fallback] Último prefijo {prefijo_num}: {ultimo}")
            return ultimo
        return base - 1
    except Exception as e:
        print(f"[ERROR] Consultando folios prefijo {prefijo_num}: {e}")
        return PREFIJOS_VALIDOS[prefijo_num] - 1

async def inicializar_folio_cursors():
    global _folio_cursors
    cursors_local = _leer_cursors_local()
    for prefijo_num, base in PREFIJOS_VALIDOS.items():
        watermark = await asyncio.to_thread(_sb_leer_watermark_jal, prefijo_num)
        if watermark is not None:
            desde = watermark
            print(f"[FOLIO JAL] Prefijo {prefijo_num} desde watermark: {watermark}")
        else:
            desde = await asyncio.to_thread(_leer_ultimo_folio_por_prefijo_db, prefijo_num)
            await asyncio.to_thread(_sb_guardar_watermark_jal, prefijo_num, desde)
            print(f"[FOLIO JAL] Prefijo {prefijo_num} watermark creado desde DB: {desde}")
        local = cursors_local.get(prefijo_num)
        if local is not None and local > desde:
            desde = local
            print(f"[FOLIO JAL] Prefijo {prefijo_num} cursor local más alto: {local}")
        _folio_cursors[prefijo_num] = desde
    _guardar_cursors_local(_folio_cursors)

async def generar_folio_con_prefijo(prefijo_num: str) -> str:
    global _folio_cursors
    if prefijo_num not in PREFIJOS_VALIDOS:
        prefijo_num = "1"
    async with _folio_lock:
        base   = PREFIJOS_VALIDOS[prefijo_num]
        limite = base + 100000000
        _folio_cursors[prefijo_num] += 1
        if _folio_cursors[prefijo_num] >= limite:
            _folio_cursors[prefijo_num] = base
        numero = _folio_cursors[prefijo_num]
        await asyncio.to_thread(_sb_guardar_watermark_jal, prefijo_num, numero)
        _guardar_cursors_local(_folio_cursors)
        folio = f"{numero:09d}"
        print(f"[FOLIO JAL] Generado prefijo {prefijo_num}: {folio}")
        return folio

# ============ INSERT SUPABASE =================================================

def _sb_insertar_folio(datos: dict, user_id: int, username: str):
    supabase.table("folios_registrados").insert({
        "folio":             datos["folio"],
        "marca":             datos["marca"],
        "linea":             datos["linea"],
        "anio":              datos["anio"],
        "numero_serie":      datos["serie"],
        "numero_motor":      datos["motor"],
        "color":             datos["color"],
        "nombre":            datos["nombre"],
        "fecha_expedicion":  datos["fecha_exp"].date().isoformat(),
        "fecha_vencimiento": datos["fecha_ven"].date().isoformat(),
        "entidad":  "jalisco",
        "estado":   "PENDIENTE",
        "user_id":  user_id,
        "username": username or "Sin username",
    }).execute()

def _sb_insertar_borrador(datos: dict, user_id: int):
    supabase.table("borradores_registros").insert({
        "folio":             datos["folio"],
        "entidad":           "jalisco",
        "numero_serie":      datos["serie"],
        "marca":             datos["marca"],
        "linea":             datos["linea"],
        "numero_motor":      datos["motor"],
        "anio":              datos["anio"],
        "color":             datos["color"],
        "fecha_expedicion":  datos["fecha_exp"].isoformat(),
        "fecha_vencimiento": datos["fecha_ven"].isoformat(),
        "contribuyente":     datos["nombre"],
        "estado":            "PENDIENTE",
        "user_id":           user_id,
    }).execute()

async def guardar_folio_con_reintento(datos: dict, user_id: int, username: str, prefijo="1") -> bool:
    for intento in range(100_000_000):
        if "folio" not in datos or not re.fullmatch(r"\d{9}", str(datos.get("folio", ""))):
            datos["folio"] = await generar_folio_con_prefijo(prefijo)
        try:
            await asyncio.to_thread(_sb_insertar_folio, datos, user_id, username)
            print(f"[ÉXITO] ✅ Folio {datos['folio']} guardado (intento {intento+1})")
            return True
        except Exception as e:
            em = str(e).lower()
            if "duplicate" in em or "unique constraint" in em or "23505" in em:
                print(f"[DUPLICADO] {datos['folio']} existe, reintentando ({intento+1})")
                datos["folio"] = None
                await asyncio.sleep(0.1)
                continue
            print(f"[ERROR BD] {e}")
            return False
    return False

# ============ FOLIOS PÁGINA 2 =================================================

def _leer_folios_pagina2():
    try:
        with open("folios_pagina2.json") as f:
            return json.load(f)
    except Exception:
        return {
            "referencia_pago":   273312001734,
            "num_autorizacion":  370803,
            "folio_seguimiento": "GZUdr61oqv2",
            "linea_captura":     41340816,
        }

def _guardar_folios_pagina2(folios: dict):
    try:
        with open("folios_pagina2.json", "w") as f:
            json.dump(folios, f)
    except Exception as e:
        print(f"[WARN] No se pudo persistir folios página 2: {e}")

def _incrementar_sufijo_alfabetico(sufijo: str) -> str:
    chars = list(sufijo)
    for i in range(len(chars)-1, -1, -1):
        if chars[i] == 'z':
            chars[i] = 'a'
        else:
            chars[i] = chr(ord(chars[i]) + 1)
            break
    return ''.join(chars)

def _incrementar_alfanumerico(codigo: str) -> str:
    match = re.match(r'(\D*)(\d+)([a-z]+)(\d+)$', codigo)
    if match:
        prefijo = match.group(1)
        numero  = match.group(2)
        letras  = match.group(3)
        digito  = int(match.group(4)) + 1
        if digito > 9:
            digito = 0
            letras = _incrementar_sufijo_alfabetico(letras)
        return f"{prefijo}{numero}{letras}{digito}"
    return codigo[:-1] + str((int(codigo[-1]) + 1) % 10)

def generar_folios_pagina2() -> dict:
    folios = _leer_folios_pagina2()
    folios["referencia_pago"]   += 1
    folios["num_autorizacion"]  += 1
    folios["folio_seguimiento"]  = _incrementar_alfanumerico(folios["folio_seguimiento"])
    folios["linea_captura"]     += 1
    _guardar_folios_pagina2(folios)
    return folios

# ============ FOLIO REPRESENTATIVO — WATERMARK SUPABASE ======================

_REP_PREFIJO = "JAL_REP"
_REP_INICIO  = 21385
_rep_counter = {"actual": _REP_INICIO}
_rep_lock    = asyncio.Lock()

def _sb_leer_watermark_rep() -> int | None:
    try:
        r = supabase.table("folio_watermark") \
            .select("ultimo_asignado").eq("prefijo", _REP_PREFIJO).execute()
        if r.data:
            return r.data[0]["ultimo_asignado"]
        return None
    except Exception as e:
        print(f"[ERROR] leer_watermark REP: {e}")
        return None

def _sb_guardar_watermark_rep(numero: int):
    try:
        supabase.table("folio_watermark").upsert({
            "prefijo":         _REP_PREFIJO,
            "ultimo_asignado": numero
        }).execute()
        print(f"[WATERMARK REP] Guardado: {numero}")
    except Exception as e:
        print(f"[ERROR] guardar_watermark REP: {e}")

def _inicializar_folio_rep():
    watermark = _sb_leer_watermark_rep()
    if watermark is not None:
        _rep_counter["actual"] = watermark
        print(f"[FOLIO REP] Desde watermark Supabase: {watermark}")
        return
    try:
        with open("folio_representativo.txt") as f:
            val = int(f.read().strip())
        _rep_counter["actual"] = val
        _sb_guardar_watermark_rep(val)
        print(f"[FOLIO REP] Desde archivo local (primera vez): {val}")
    except FileNotFoundError:
        _rep_counter["actual"] = _REP_INICIO
        _sb_guardar_watermark_rep(_REP_INICIO)
        print(f"[FOLIO REP] Sin historial, empezando desde {_REP_INICIO}")

def obtener_folio_representativo() -> int:
    return _rep_counter["actual"]

def incrementar_folio_representativo(folio_actual: int) -> int:
    nuevo = folio_actual + 1
    _rep_counter["actual"] = nuevo
    _sb_guardar_watermark_rep(nuevo)
    try:
        with open("folio_representativo.txt", "w") as f:
            f.write(str(nuevo))
    except Exception as e:
        print(f"[WARN] No se pudo guardar folio_representativo.txt: {e}")
    return nuevo
