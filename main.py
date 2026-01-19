from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, abort
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from supabase import create_client, Client
import fitz
import os
import qrcode
import pdf417gen
from PIL import Image
from io import BytesIO
import time
import re
import threading
import logging
import sys

from werkzeug.middleware.proxy_fix import ProxyFix

# ===================== LOGGING AGRESIVO =====================
sys.dont_write_bytecode = True

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ===================== ZONA HORARIA (CDMX) =====================
TZ_CDMX = ZoneInfo("America/Mexico_City")

def now_cdmx() -> datetime:
    return datetime.now(TZ_CDMX)

def today_cdmx() -> date:
    return now_cdmx().date()

def parse_date_any(value) -> date:
    if not value:
        raise ValueError("Fecha vacía")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ_CDMX)
        else:
            value = value.astimezone(TZ_CDMX)
        return value.date()

    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_CDMX)
    else:
        dt = dt.astimezone(TZ_CDMX)
    return dt.date()

# ===================== CONFIGURACIÓN FLASK =====================
app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=2,
    x_proto=2,
    x_host=2,
    x_prefix=1
)

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    MAX_CONTENT_LENGTH=32 * 1024 * 1024,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24)
)

@app.before_request
def log_request_info():
    logger.debug('=' * 80)
    logger.debug(f'REQUEST: {request.method} {request.url}')
    logger.debug(f'Remote: {request.remote_addr}')
    logger.debug(f'Form keys: {list(request.form.keys()) if request.form else "No form"}')
    logger.debug('=' * 80)

@app.after_request
def log_response_info(response):
    logger.debug(f'RESPONSE: {response.status}')
    return response

# ===================== SUPABASE CONFIG =====================
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SUPABASE_BUCKET_PDFS = "pdfs"

# ===================== CONFIG GENERAL =====================
OUTPUT_DIR = "documentos"
PLANTILLA_PDF = "jalisco1.pdf"
PLANTILLA_BUENO = "jalisco.pdf"
URL_CONSULTA_BASE = "https://serviciodigital-jaliscogobmx.onrender.com"
ENTIDAD = "jalisco"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===================== COORDENADAS PDF JALISCO =====================
coords_jalisco = {
    "folio": (800, 360, 14, (0, 0, 0)),
    "marca": (340, 332, 14, (0, 0, 0)),
    "serie": (920, 332, 14, (0, 0, 0)),
    "linea": (340, 360, 14, (0, 0, 0)),
    "anio": (340, 389, 14, (0, 0, 0)),
    "color": (340, 418, 14, (0, 0, 0)),
    "nombre": (340, 304, 14, (0, 0, 0)),
    "fecha_exp": (120, 350, 14, (0, 0, 0)),
    "fecha_exp_completa": (120, 370, 14, (0, 0, 0)),
    "fecha_ven": (285, 570, 90, (0, 0, 0))
}

coords_pagina2 = {
    "referencia_pago": (380, 123, 10, (0, 0, 0)),
    "num_autorizacion": (380, 147, 10, (0, 0, 0)),
    "total_pagado": (380, 170, 10, (0, 0, 0)),
    "folio_seguimiento": (380, 243, 10, (0, 0, 0)),
    "linea_captura": (380, 265, 10, (0, 0, 0))
}

coords_qr_dinamico = {"x": 966, "y": 603, "ancho": 140, "alto": 140}
PRECIO_FIJO_PAGINA2 = 1080

# ===================== FOLIOS JALISCO: 900000000 al infinito =====================
PREFIJO_JALISCO = 900000000
LIMITE_MAXIMO = 999999999

def generar_folio_automatico_jalisco():
    try:
        # ✅ FILTRAR SOLO FOLIOS DE JALISCO (9 dígitos >= 900000000)
        resp = supabase.table("folios_registrados")\
            .select("folio")\
            .eq("entidad", ENTIDAD)\
            .gte("folio", str(PREFIJO_JALISCO))\
            .lte("folio", str(LIMITE_MAXIMO))\
            .order("folio", desc=True)\
            .limit(1)\
            .execute()

        if resp.data and len(resp.data) > 0:
            ultimo = int(resp.data[0]["folio"])
            # ✅ VALIDAR QUE EL ÚLTIMO ESTÉ EN RANGO
            if ultimo >= PREFIJO_JALISCO and ultimo <= LIMITE_MAXIMO:
                siguiente = ultimo + 1
                logger.info(f"[FOLIO] Ultimo={ultimo} siguiente={siguiente}")
            else:
                # Si está fuera de rango, empezar desde el inicio
                siguiente = PREFIJO_JALISCO
                logger.warning(f"[FOLIO] Ultimo folio {ultimo} fuera de rango, reiniciando desde {siguiente}")
        else:
            siguiente = PREFIJO_JALISCO
            logger.info(f"[FOLIO] Sin folios de Jalisco, inicio={siguiente}")

        # ✅ VALIDAR QUE EL SIGUIENTE ESTÉ EN RANGO
        if siguiente < PREFIJO_JALISCO or siguiente > LIMITE_MAXIMO:
            logger.error(f"[FOLIO] Siguiente {siguiente} fuera de rango, usando inicio")
            siguiente = PREFIJO_JALISCO

        for intento in range(100000):
            folio_candidato = siguiente + intento
            
            # ✅ VALIDAR LÍMITE
            if folio_candidato > LIMITE_MAXIMO:
                raise Exception(f"Límite alcanzado ({LIMITE_MAXIMO})")

            folio_str = f"{folio_candidato:09d}"

            existe = supabase.table("folios_registrados")\
                .select("folio")\
                .eq("folio", folio_str)\
                .limit(1)\
                .execute().data

            if not existe:
                logger.info(f"[FOLIO] ✅ {folio_str} (intento {intento+1})")
                return folio_str

        raise Exception("No se pudo generar folio después de 100,000 intentos")
    except Exception as e:
        logger.error(f"[ERROR] generar_folio_automatico_jalisco: {e}")
        raise

def guardar_folio_con_reintento(datos, username):
    max_intentos = 100000

    if not datos.get("folio") or not re.fullmatch(r"\d{9}", str(datos.get("folio", ""))):
        try:
            datos["folio"] = generar_folio_automatico_jalisco()
        except Exception as e:
            logger.error(f"[ERROR] No se pudo generar folio: {e}")
            return False

    folio_inicial = int(datos["folio"])
    fexp_date = parse_date_any(datos["fecha_exp"])
    fven_date = parse_date_any(datos["fecha_ven"])

    for intento in range(max_intentos):
        folio_actual = folio_inicial + intento

        if folio_actual < PREFIJO_JALISCO or folio_actual > LIMITE_MAXIMO:
            logger.error(f"[ERROR] Folio {folio_actual} fuera de rango")
            return False

        folio_str = f"{folio_actual:09d}"

        try:
            supabase.table("folios_registrados").insert({
                "folio": folio_str,
                "marca": datos["marca"],
                "linea": datos["linea"],
                "anio": datos["anio"],
                "numero_serie": datos["serie"],
                "numero_motor": datos["motor"],
                "color": datos["color"],
                "nombre": datos["nombre"],
                "fecha_expedicion": fexp_date.isoformat(),
                "fecha_vencimiento": fven_date.isoformat(),
                "entidad": ENTIDAD,
                "estado": "ACTIVO",
                "creado_por": username
            }).execute()

            datos["folio"] = folio_str
            logger.info(f"[DB] ✅ Folio {folio_str} guardado (intento {intento+1})")
            return True

        except Exception as e:
            em = str(e).lower()
            if "duplicate" in em or "unique constraint" in em or "23505" in em:
                logger.warning(f"[DUP] {folio_str} existe, probando siguiente...")
                continue

            logger.error(f"[ERROR BD] {e}")
            return False

    logger.error(f"[ERROR] No se encontró folio disponible tras {max_intentos} intentos")
    return False

# ===================== FOLIOS PÁGINA 2 =====================
def generar_folios_pagina2() -> dict:
    timestamp = int(time.time())
    return {
        "referencia_pago": 273312001734 + timestamp % 1000000,
        "num_autorizacion": 370803 + timestamp % 100000,
        "folio_seguimiento": f"GZ{timestamp % 1000}xy{timestamp % 10}",
        "linea_captura": 41340816 + timestamp % 1000000
    }

def obtener_folio_representativo():
    return 21385 + int(time.time()) % 100000

# ===================== SUPABASE STORAGE =====================
def subir_pdf_a_supabase(ruta_pdf_local: str, folio: str, entidad: str = ENTIDAD):
    try:
        ruta_storage = f"{entidad}/{folio}.pdf"
        with open(ruta_pdf_local, "rb") as f:
            contenido = f.read()

        supabase.storage.from_(SUPABASE_BUCKET_PDFS).upload(
            ruta_storage,
            contenido,
            {"content-type": "application/pdf", "upsert": True}
        )

        logger.info(f"[STORAGE] ✅ Subido: {ruta_storage}")
        return ruta_storage
    except Exception as e:
        logger.error(f"[STORAGE] ❌ Error subiendo: {e}")
        return None

def subir_pdf_bg_y_guardar_path(ruta_pdf_local: str, folio: str, entidad: str = ENTIDAD):
    try:
        storage_path = subir_pdf_a_supabase(ruta_pdf_local, folio, entidad=entidad)
        if storage_path:
            supabase.table("folios_registrados")\
                .update({"pdf_path": storage_path})\
                .eq("folio", folio)\
                .execute()
            logger.info(f"[STORAGE] ✅ Path guardado: {storage_path}")
    except Exception as e:
        logger.error(f"[STORAGE BG] ❌ Error: {e}")

def url_publica_pdf(storage_path: str):
    try:
        res = supabase.storage.from_(SUPABASE_BUCKET_PDFS).get_public_url(storage_path)
        if isinstance(res, dict):
            return res.get("publicURL") or res.get("publicUrl") or res.get("public_url") or res.get("url")
        return res
    except Exception as e:
        logger.error(f"[STORAGE] ❌ Error get_public_url: {e}")
        return None

# ===================== GENERACIÓN PDF JALISCO =====================
def generar_qr_dinamico(folio):
    try:
        url_directa = f"{URL_CONSULTA_BASE}/consulta/{folio}"
        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1
        )
        qr.add_data(url_directa)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color=(220, 220, 220)).convert("RGB")
        logger.info(f"[QR] ✅ {folio} -> {url_directa}")
        return img_qr, url_directa
    except Exception as e:
        logger.error(f"[ERROR QR] {e}")
        return None, None

def generar_codigo_ine(contenido, ruta_salida):
    try:
        codes = pdf417gen.encode(contenido, columns=6, security_level=5)
        image = pdf417gen.render_image(codes)

        if image.mode != 'RGB':
            image = image.convert('RGB')

        ancho, alto = image.size
        img_gris = Image.new('RGB', (ancho, alto), color=(220, 220, 220))
        pixels = image.load()
        pixels_gris = img_gris.load()

        for y in range(alto):
            for x in range(ancho):
                pixel = pixels[x, y]
                if isinstance(pixel, tuple):
                    if sum(pixel[:3]) < 384:
                        pixels_gris[x, y] = (0, 0, 0)
                else:
                    if pixel < 128:
                        pixels_gris[x, y] = (0, 0, 0)

        img_gris.save(ruta_salida)
        logger.info(f"[PDF417] ✅ {ruta_salida}")
    except Exception as e:
        logger.error(f"[ERROR PDF417] {e}")
        img_fallback = Image.new('RGB', (200, 50), color=(220, 220, 220))
        img_fallback.save(ruta_salida)

def generar_pdf_unificado(datos: dict) -> str:
    fol = datos["folio"]
    fecha_exp_dt: datetime = datos["fecha_exp"]
    fecha_ven_dt: datetime = datos["fecha_ven"]

    if fecha_exp_dt.tzinfo is None:
        fecha_exp_dt = fecha_exp_dt.replace(tzinfo=TZ_CDMX)
    else:
        fecha_exp_dt = fecha_exp_dt.astimezone(TZ_CDMX)

    if fecha_ven_dt.tzinfo is None:
        fecha_ven_dt = fecha_ven_dt.replace(tzinfo=TZ_CDMX)
    else:
        fecha_ven_dt = fecha_ven_dt.astimezone(TZ_CDMX)

    ahora_dt = now_cdmx()
    out = os.path.join(OUTPUT_DIR, f"{fol}.pdf")

    try:
        doc1 = fitz.open(PLANTILLA_PDF)
        pg1 = doc1[0]

        for campo in ["marca", "linea", "anio", "serie", "nombre", "color"]:
            if campo in coords_jalisco:
                x, y, s, col = coords_jalisco[campo]
                pg1.insert_text((x, y), str(datos.get(campo, "")), fontsize=s, color=col, fontname="hebo")

        pg1.insert_text(
            coords_jalisco["fecha_ven"][:2],
            fecha_ven_dt.strftime("%d/%m/%Y"),
            fontsize=coords_jalisco["fecha_ven"][2],
            color=coords_jalisco["fecha_ven"][3]
        )

        pg1.insert_text((860, 364), fol, fontsize=14, color=(0, 0, 0), fontname="hebo")
        pg1.insert_text((475, 830), fecha_exp_dt.strftime("%d/%m/%Y"), fontsize=32, color=(0, 0, 0), fontname="hebo")

        fol_rep = obtener_folio_representativo()
        folio_grande = f"4A-DVM/{fol_rep}"
        pg1.insert_text((240, 830), folio_grande, fontsize=32, color=(0, 0, 0), fontname="hebo")
        pg1.insert_text((480, 182), folio_grande, fontsize=63, color=(0, 0, 0), fontname="hebo")

        folio_chico = f"DVM-{fol_rep}   {ahora_dt.strftime('%d/%m/%Y')}  {ahora_dt.strftime('%H:%M:%S')}"
        pg1.insert_text((915, 760), folio_chico, fontsize=14, color=(0, 0, 0), fontname="hebo")

        pg1.insert_text((935, 600), f"*{fol}*", fontsize=30, color=(0, 0, 0), fontname="Courier")

        contenido_ine = f"""FOLIO:  {fol}
MARCA:  {datos.get('marca', '')}
SUBMARCA:  {datos.get('linea', '')}
AÑO:  {datos.get('anio', '')}
SERIE:  {datos.get('serie', '')}
MOTOR:  {datos.get('motor', '')}
COLOR:  {datos.get('color', '')}
NOMBRE:  {datos.get('nombre', '')}"""

        ine_img_path = os.path.join(OUTPUT_DIR, f"{fol}_inecode.png")
        generar_codigo_ine(contenido_ine, ine_img_path)

        pg1.insert_image(
            fitz.Rect(932.65, 807, 1141.395, 852.127),
            filename=ine_img_path,
            keep_proportion=False,
            overlay=True
        )

        pg1.insert_text((915, 775), "EXPEDICION: VENTANILLA DIGITAL", fontsize=12, color=(0, 0, 0), fontname="hebo")

        img_qr, _ = generar_qr_dinamico(fol)
        if img_qr:
            buf = BytesIO()
            img_qr.save(buf, format="PNG")
            buf.seek(0)
            qr_pix = fitz.Pixmap(buf.read())

            x_qr = coords_qr_dinamico["x"]
            y_qr = coords_qr_dinamico["y"]
            w = coords_qr_dinamico["ancho"]
            h = coords_qr_dinamico["alto"]

            pg1.insert_image(fitz.Rect(x_qr, y_qr, x_qr + w, y_qr + h), pixmap=qr_pix, overlay=True)

        doc2 = fitz.open(PLANTILLA_BUENO)
        pg2 = doc2[0]

        pg2.insert_text((380, 195), fecha_exp_dt.strftime("%d/%m/%Y %H:%M"), fontsize=10, fontname="helv", color=(0, 0, 0))
        pg2.insert_text((380, 290), str(datos.get('serie', '')), fontsize=10, fontname="helv", color=(0, 0, 0))

        folios_pag2 = generar_folios_pagina2()

        pg2.insert_text(coords_pagina2["referencia_pago"][:2], str(folios_pag2["referencia_pago"]),
                        fontsize=coords_pagina2["referencia_pago"][2], color=coords_pagina2["referencia_pago"][3])

        pg2.insert_text(coords_pagina2["num_autorizacion"][:2], str(folios_pag2["num_autorizacion"]),
                        fontsize=coords_pagina2["num_autorizacion"][2], color=coords_pagina2["num_autorizacion"][3])

        pg2.insert_text(coords_pagina2["total_pagado"][:2], f"${PRECIO_FIJO_PAGINA2}.00 MN",
                        fontsize=coords_pagina2["total_pagado"][2], color=coords_pagina2["total_pagado"][3])

        pg2.insert_text(coords_pagina2["folio_seguimiento"][:2], str(folios_pag2["folio_seguimiento"]),
                        fontsize=coords_pagina2["folio_seguimiento"][2], color=coords_pagina2["folio_seguimiento"][3])

        pg2.insert_text(coords_pagina2["linea_captura"][:2], str(folios_pag2["linea_captura"]),
                        fontsize=coords_pagina2["linea_captura"][2], color=coords_pagina2["linea_captura"][3])

        doc_final = fitz.open()
        doc_final.insert_pdf(doc1)
        doc_final.insert_pdf(doc2)
        doc_final.save(out)

        doc_final.close()
        doc1.close()
        doc2.close()

        logger.info(f"[PDF] ✅ {out}")

    except Exception as e:
        logger.error(f"[ERROR PDF] {e}")
        doc_fallback = fitz.open()
        page = doc_fallback.new_page()
        page.insert_text((50, 50), f"ERROR - Folio: {fol}", fontsize=12)
        doc_fallback.save(out)
        doc_fallback.close()

    return out

# ===================== RUTAS FLASK =====================
@app.route('/')
def inicio():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username == 'Serg890105tm3' and password == 'Serg890105tm3':
            session['admin'] = True
            session['username'] = 'Serg890105tm3'
            logger.info("[LOGIN] Admin login exitoso")
            return redirect(url_for('admin'))

        resp = supabase.table("verificaciondigitalcdmx")\
            .select("*")\
            .eq("username", username)\
            .eq("password", password)\
            .execute()

        if resp.data:
            session['user_id'] = resp.data[0].get('id')
            session['username'] = resp.data[0]['username']
            session['admin'] = False
            logger.info(f"[LOGIN] Usuario {username} login exitoso")
            return redirect(url_for('registro_usuario'))

        logger.warning(f"[LOGIN] Login fallido para {username}")
        flash('Usuario o contraseña incorrectos', 'error')

    return render_template('login.html')

@app.route('/admin')
def admin():
    if not session.get('admin'):
        return redirect(url_for('login'))
    return render_template('panel.html')

@app.route('/crear_usuario', methods=['GET', 'POST'])
def crear_usuario():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        folios = int(request.form['folios'])

        existe = supabase.table("verificaciondigitalcdmx")\
            .select("id")\
            .eq("username", username)\
            .limit(1)\
            .execute()

        if existe.data:
            flash('Error: el nombre de usuario ya existe.', 'error')
        else:
            supabase.table("verificaciondigitalcdmx").insert({
                "username": username,
                "password": password,
                "folios_asignac": folios,
                "folios_usados": 0
            }).execute()
            flash('Usuario creado exitosamente.', 'success')

    return render_template('crear_usuario.html')

@app.route('/registro_usuario', methods=['GET', 'POST'])
def registro_usuario():
    try:
        if not session.get('username'):
            logger.error("[REGISTRO] Sin username en session")
            flash("Sesión no válida. Inicia sesión de nuevo.", "error")
            return redirect(url_for('login'))

        if session.get('admin'):
            logger.info("[REGISTRO] Admin redirigido")
            return redirect(url_for('admin'))

        logger.info(f"[REGISTRO] Usuario: {session['username']}")

        user_data = supabase.table("verificaciondigitalcdmx")\
            .select("*")\
            .eq("username", session['username'])\
            .limit(1)\
            .execute()

        if not user_data.data:
            logger.error(f"[REGISTRO] Usuario {session['username']} no encontrado en DB")
            flash("Usuario no encontrado.", "error")
            return redirect(url_for('login'))

        usuario = user_data.data[0]
        folios_asignados = int(usuario.get('folios_asignac', 0))
        folios_usados = int(usuario.get('folios_usados', 0))
        folios_disponibles = folios_asignados - folios_usados

        folios_info = {"folios_asignac": folios_asignados, "folios_usados": folios_usados}

        if request.method == 'POST':
            logger.info(f"[REGISTRO] ===== POST RECIBIDO =====")
            logger.info(f"[REGISTRO] Usuario: {session['username']}")
            logger.info(f"[REGISTRO] ===== FORM DATA COMPLETO =====")
            for key, value in request.form.items():
                logger.info(f"[REGISTRO] {key} = [{value}]")
            logger.info(f"[REGISTRO] ==================================")
            
            if folios_disponibles <= 0:
                logger.warning(f"[REGISTRO] Sin folios disponibles")
                flash("⚠️ Ya no tienes folios disponibles. Contacta al administrador.", "error")
                return render_template('registro_usuario.html', folios_info=folios_info)

            try:
                marca = request.form.get('marca', '').strip().upper()
                linea = request.form.get('linea', '').strip().upper()
                anio = request.form.get('anio', '').strip()
                numero_serie = request.form.get('serie', '').strip().upper()
                numero_motor = request.form.get('motor', '').strip().upper()
                color = request.form.get('color', '').strip().upper() or 'BLANCO'
                nombre = request.form.get('nombre', '').strip().upper() or 'SIN NOMBRE'
                
                logger.info(f"[REGISTRO] ===== DATOS EXTRAÍDOS =====")
                logger.info(f"[REGISTRO] marca=[{marca}] len={len(marca)}")
                logger.info(f"[REGISTRO] linea=[{linea}] len={len(linea)}")
                logger.info(f"[REGISTRO] anio=[{anio}] len={len(anio)}")
                logger.info(f"[REGISTRO] serie=[{numero_serie}] len={len(numero_serie)}")
                logger.info(f"[REGISTRO] motor=[{numero_motor}] len={len(numero_motor)}")
                logger.info(f"[REGISTRO] color=[{color}]")
                logger.info(f"[REGISTRO] nombre=[{nombre}]")
                logger.info(f"[REGISTRO] ==================================")
                
                # Validación específica
                campos_faltantes = []
                if not marca:
                    campos_faltantes.append("Marca")
                if not linea:
                    campos_faltantes.append("Línea/Submarca")
                if not anio:
                    campos_faltantes.append("Año")
                if not numero_serie:
                    campos_faltantes.append("Número de Serie")
                if not numero_motor:
                    campos_faltantes.append("Número de Motor")
                
                if campos_faltantes:
                    logger.error(f"[REGISTRO] Campos faltantes: {campos_faltantes}")
                    flash(f"❌ Faltan los siguientes campos: {', '.join(campos_faltantes)}", "error")
                    return render_template('registro_usuario.html', folios_info=folios_info)
                
            except Exception as e:
                logger.error(f"[REGISTRO] Error extrayendo form data: {e}", exc_info=True)
                flash(f"❌ Error en los datos del formulario: {e}", "error")
                return render_template('registro_usuario.html', folios_info=folios_info)

            folio_manual = request.form.get('folio', '').strip()
            if folio_manual and not re.fullmatch(r"\d{9}", folio_manual):
                logger.error(f"[REGISTRO] Folio inválido: {folio_manual}")
                flash("❌ El folio debe tener exactamente 9 dígitos.", "error")
                return render_template('registro_usuario.html', folios_info=folios_info)

            ahora = now_cdmx()
            vigencia = int(request.form.get('vigencia', 30))
            venc = ahora + timedelta(days=vigencia)

            datos = {
                "folio": folio_manual if folio_manual else None,
                "marca": marca,
                "linea": linea,
                "anio": anio,
                "serie": numero_serie,
                "motor": numero_motor,
                "color": color,
                "nombre": nombre,
                "fecha_exp": ahora,
                "fecha_ven": venc
            }

            logger.info(f"[REGISTRO] Iniciando guardado en BD")

            try:
                ok = guardar_folio_con_reintento(datos, session['username'])
                if not ok:
                    logger.error("[REGISTRO] guardar_folio_con_reintento falló")
                    flash("❌ No se pudo registrar el folio. Intenta de nuevo.", "error")
                    return render_template('registro_usuario.html', folios_info=folios_info)

                folio_final = datos["folio"]
                logger.info(f"[REGISTRO] ✅ Folio guardado en BD: {folio_final}")

                logger.info(f"[REGISTRO] Generando PDF")
                pdf_path_local = generar_pdf_unificado(datos)
                logger.info(f"[REGISTRO] ✅ PDF generado: {pdf_path_local}")

                logger.info(f"[REGISTRO] Actualizando folios_usados")
                supabase.table("verificaciondigitalcdmx")\
                    .update({"folios_usados": folios_usados + 1})\
                    .eq("username", session['username'])\
                    .execute()

                logger.info(f"[REGISTRO] Iniciando thread de subida a Supabase")
                t = threading.Thread(
                    target=subir_pdf_bg_y_guardar_path,
                    args=(pdf_path_local, folio_final, ENTIDAD),
                    daemon=True
                )
                t.start()

                logger.info(f"[REGISTRO] ✅✅✅ PERMISO GENERADO EXITOSAMENTE: {folio_final}")
                flash(f'✅ Permiso generado. Folio: {folio_final}. Te quedan {folios_disponibles - 1} folios.', 'success')
                
                return render_template(
                    'exitoso.html',
                    folio=folio_final,
                    serie=numero_serie,
                    fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M')
                )

            except Exception as e:
                logger.error(f"[REGISTRO] ❌ Error generando permiso: {e}", exc_info=True)
                flash(f"Error al generar el permiso: {e}", 'error')
                return render_template('registro_usuario.html', folios_info=folios_info)

        logger.info(f"[REGISTRO] GET request")
        return render_template('registro_usuario.html', folios_info=folios_info)
        
    except Exception as e:
        logger.error(f"[REGISTRO] ❌ Error CRÍTICO: {e}", exc_info=True)
        flash(f"Error del sistema: {e}", 'error')
        return redirect(url_for('login'))

@app.route('/mis_permisos')
def mis_permisos():
    if not session.get('username') or session.get('admin'):
        flash('Acceso denegado.', 'error')
        return redirect(url_for('login'))

    permisos = supabase.table("folios_registrados")\
        .select("*")\
        .eq("creado_por", session['username'])\
        .order("fecha_expedicion", desc=True)\
        .execute().data or []

    hoy = today_cdmx()

    for p in permisos:
        try:
            fe = parse_date_any(p.get('fecha_expedicion'))
            fv = parse_date_any(p.get('fecha_vencimiento'))

            p['fecha_formateada'] = fe.strftime('%d/%m/%Y')
            p['hora_formateada'] = "00:00:00"
            p['estado'] = "VIGENTE" if hoy <= fv else "VENCIDO"
        except Exception:
            p['fecha_formateada'] = 'Error'
            p['hora_formateada'] = 'Error'
            p['estado'] = 'ERROR'

    usr_data = supabase.table("verificaciondigitalcdmx")\
        .select("folios_asignac, folios_usados")\
        .eq("username", session['username'])\
        .limit(1)\
        .execute().data

    usr_row = usr_data[0] if usr_data else {"folios_asignac": 0, "folios_usados": 0}

    return render_template(
        'mis_permisos.html',
        permisos=permisos,
        total_generados=len(permisos),
        folios_asignados=int(usr_row.get('folios_asignac', 0)),
        folios_usados=int(usr_row.get('folios_usados', 0))
    )

@app.route('/registro_admin', methods=['GET', 'POST'])
def registro_admin():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            logger.info(f"[ADMIN] ===== POST RECIBIDO =====")
            logger.info(f"[ADMIN] ===== FORM DATA COMPLETO =====")
            for key, value in request.form.items():
                logger.info(f"[ADMIN] {key} = [{value}]")
            logger.info(f"[ADMIN] ==================================")
            
            folio_manual = request.form.get('folio', '').strip()
            if folio_manual and not re.fullmatch(r"\d{9}", folio_manual):
                flash("❌ El folio debe tener exactamente 9 dígitos.", "error")
                return redirect(url_for('registro_admin'))

            marca = request.form.get('marca', '').strip().upper()
            linea = request.form.get('linea', '').strip().upper()
            anio = request.form.get('anio', '').strip()
            numero_serie = request.form.get('serie', '').strip().upper()
            numero_motor = request.form.get('motor', '').strip().upper()
            color = request.form.get('color', '').strip().upper() or 'BLANCO'
            nombre = request.form.get('nombre', '').strip().upper() or 'SIN NOMBRE'

            # Validación específica
            campos_faltantes = []
            if not marca:
                campos_faltantes.append("Marca")
            if not linea:
                campos_faltantes.append("Línea/Submarca")
            if not anio:
                campos_faltantes.append("Año")
            if not numero_serie:
                campos_faltantes.append("Número de Serie")
            if not numero_motor:
                campos_faltantes.append("Número de Motor")
            
            if campos_faltantes:
                logger.error(f"[ADMIN] Campos faltantes: {campos_faltantes}")
                flash(f"❌ Faltan los siguientes campos: {', '.join(campos_faltantes)}", "error")
                return redirect(url_for('registro_admin'))

            ahora = now_cdmx()
            vigencia = int(request.form.get('vigencia', 30))
            venc = ahora + timedelta(days=vigencia)

            datos = {
                "folio": folio_manual if folio_manual else None,
                "marca": marca,
                "linea": linea,
                "anio": anio,
                "serie": numero_serie,
                "motor": numero_motor,
                "color": color,
                "nombre": nombre,
                "fecha_exp": ahora,
                "fecha_ven": venc
            }

            ok = guardar_folio_con_reintento(datos, "ADMIN")
            if not ok:
                flash("❌ No se pudo registrar el folio.", "error")
                return redirect(url_for('registro_admin'))

            folio_final = datos["folio"]
            pdf_path_local = generar_pdf_unificado(datos)

            t = threading.Thread(
                target=subir_pdf_bg_y_guardar_path,
                args=(pdf_path_local, folio_final, ENTIDAD),
                daemon=True
            )
            t.start()

            logger.info(f"[ADMIN] ✅ Permiso generado: {folio_final}")
            flash('Permiso generado correctamente.', 'success')
            return render_template(
                'exitoso.html',
                folio=folio_final,
                serie=numero_serie,
                fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M')
            )

        except Exception as e:
            logger.error(f"[ADMIN] ❌ Error: {e}", exc_info=True)
            flash(f"Error: {e}", 'error')
            return redirect(url_for('registro_admin'))

    return render_template('registro_admin.html')

@app.route('/consulta_folio', methods=['GET', 'POST'])
def consulta_folio():
    resultado = None

    if request.method == 'POST':
        folio = request.form['folio'].strip()
        registros = supabase.table("folios_registrados")\
            .select("*")\
            .eq("folio", folio)\
            .limit(1)\
            .execute().data

        if not registros:
            resultado = {"estado": "NO SE ENCUENTRA REGISTRADO", "color": "rojo", "folio": folio}
        else:
            r = registros[0]
            fexp = parse_date_any(r.get('fecha_expedicion'))
            fven = parse_date_any(r.get('fecha_vencimiento'))

            hoy = today_cdmx()
            estado = "VIGENTE" if hoy <= fven else "VENCIDO"
            color = "verde" if estado == "VIGENTE" else "cafe"

            resultado = {
                "estado": estado,
                "color": color,
                "folio": folio,
                "fecha_expedicion": fexp.strftime('%d/%m/%Y'),
                "fecha_vencimiento": fven.strftime('%d/%m/%Y'),
                "marca": r.get('marca', ''),
                "linea": r.get('linea', ''),
                "año": r.get('anio', ''),
                "numero_serie": r.get('numero_serie', ''),
                "numero_motor": r.get('numero_motor', ''),
                "entidad": r.get('entidad', ENTIDAD)
            }

        return render_template('resultado_consulta.html', resultado=resultado)

    return render_template('consulta_folio.html')

@app.route('/consulta/<folio>')
def consulta_folio_directo(folio):
    row = supabase.table("folios_registrados")\
        .select("*")\
        .eq("folio", folio)\
        .limit(1)\
        .execute().data

    if not row:
        return render_template("resultado_consulta.html", resultado={
            "estado": "NO SE ENCUENTRA REGISTRADO",
            "color": "rojo",
            "folio": folio
        })

    r = row[0]
    fe = parse_date_any(r.get('fecha_expedicion'))
    fv = parse_date_any(r.get('fecha_vencimiento'))

    hoy = today_cdmx()
    estado = "VIGENTE" if hoy <= fv else "VENCIDO"
    color = "verde" if estado == "VIGENTE" else "cafe"

    resultado = {
        "estado": estado,
        "color": color,
        "folio": folio,
        "fecha_expedicion": fe.strftime("%d/%m/%Y"),
        "fecha_vencimiento": fv.strftime("%d/%m/%Y"),
        "marca": r.get('marca', ''),
        "linea": r.get('linea', ''),
        "año": r.get('anio', ''),
        "numero_serie": r.get('numero_serie', ''),
        "numero_motor": r.get('numero_motor', ''),
        "entidad": r.get('entidad', ENTIDAD)
    }

    return render_template("resultado_consulta.html", resultado=resultado)

@app.route('/descargar_recibo/<folio>')
def descargar_recibo(folio):
    try:
        row = supabase.table("folios_registrados")\
            .select("pdf_path")\
            .eq("folio", folio)\
            .limit(1)\
            .execute().data

        if row and row[0].get("pdf_path"):
            public_url = url_publica_pdf(row[0]["pdf_path"])
            if public_url:
                return redirect(public_url)
    except Exception as e:
        logger.error(f"[DESCARGA] Error: {e}")

    ruta_pdf = os.path.join(OUTPUT_DIR, f"{folio}.pdf")
    if not os.path.exists(ruta_pdf):
        abort(404)

    return send_file(
        ruta_pdf,
        as_attachment=True,
        download_name=f"{folio}_jalisco.pdf",
        mimetype='application/pdf'
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ===================== EJECUTAR APP =====================
if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("🚀 INICIANDO SERVIDOR JALISCO")
    logger.info(f"Output dir: {OUTPUT_DIR}")
    logger.info(f"Plantilla PDF: {PLANTILLA_PDF} (existe: {os.path.exists(PLANTILLA_PDF)})")
    logger.info(f"Plantilla Bueno: {PLANTILLA_BUENO} (existe: {os.path.exists(PLANTILLA_BUENO)})")
    logger.info("=" * 80)
    
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
