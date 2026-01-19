from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, abort
from datetime import datetime, timedelta
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

from werkzeug.middleware.proxy_fix import ProxyFix

# ===================== CONFIGURACIÓN FLASK =====================
app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

# ✅ FIX PROXY (Render) - CRÍTICO para evitar error 400
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ✅ Configuración de cookies para HTTPS (Render)
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024  # 16 MB máximo
)

# ✅ Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ===================== SUPABASE CONFIG =====================
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SUPABASE_BUCKET_PDFS = "pdfs"  # bucket público

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
PREFIJO_JALISCO = 900000000  # Empieza en 900000000
LIMITE_MAXIMO = 999999999     # Máximo: 999999999

def generar_folio_automatico_jalisco():
    """
    Genera folio automático para Jalisco
    Formato: 900000000, 900000001, 900000002... hasta 999999999
    Intenta 100,000 veces hasta encontrar uno disponible
    """
    try:
        # Buscar el último folio de Jalisco
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
            siguiente = ultimo + 1
            logger.info(f"[FOLIO JALISCO] Último en DB: {ultimo}, siguiente: {siguiente}")
        else:
            siguiente = PREFIJO_JALISCO
            logger.info(f"[FOLIO JALISCO] No hay folios, empezando en: {siguiente}")

        # Intentar hasta 100,000 veces encontrar folio disponible
        for intento in range(100000):
            folio_candidato = siguiente + intento

            # Verificar que no se pase del límite
            if folio_candidato > LIMITE_MAXIMO:
                raise Exception(f"Se alcanzó el límite de folios ({LIMITE_MAXIMO})")

            folio_str = f"{folio_candidato:09d}"

            # Verificar si existe en BD
            existe = supabase.table("folios_registrados")\
                .select("folio")\
                .eq("folio", folio_str)\
                .execute().data

            if not existe:
                logger.info(f"[FOLIO JALISCO] ✅ Generado: {folio_str} (intento {intento + 1})")
                return folio_str

        raise Exception("No se pudo generar folio después de 100,000 intentos")

    except Exception as e:
        logger.error(f"[ERROR] Generando folio Jalisco: {e}")
        raise

def guardar_folio_con_reintento(datos, username):
    """
    Guarda folio en DB con anti-duplicados
    Si el folio existe, intenta con el siguiente
    """
    max_intentos = 100000

    # Si no trae folio o es inválido, generar automático
    if "folio" not in datos or not datos.get("folio") or not re.fullmatch(r"\d{9}", str(datos.get("folio", ""))):
        try:
            datos["folio"] = generar_folio_automatico_jalisco()
        except Exception as e:
            logger.error(f"[ERROR] No se pudo generar folio: {e}")
            return False

    folio_inicial = int(datos["folio"])

    for intento in range(max_intentos):
        folio_actual = folio_inicial + intento

        # Verificar rango válido
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
                "fecha_expedicion": datos["fecha_exp"].date().isoformat(),
                "fecha_vencimiento": datos["fecha_ven"].date().isoformat(),
                "entidad": ENTIDAD,
                "estado": "ACTIVO",
                "creado_por": username  # ✅ NUEVO: tracking de usuario
            }).execute()

            datos["folio"] = folio_str
            logger.info(f"[ÉXITO] ✅ Folio {folio_str} guardado (intento {intento + 1})")
            return True

        except Exception as e:
            em = str(e).lower()
            if "duplicate" in em or "unique constraint" in em or "23505" in em:
                logger.warning(f"[DUPLICADO] {folio_str} existe, probando {folio_actual + 1}...")
                continue

            logger.error(f"[ERROR BD] {e}")
            return False

    logger.error(f"[ERROR FATAL] No se encontró folio disponible tras {max_intentos} intentos")
    return False

# ===================== FOLIOS PÁGINA 2 =====================
def generar_folios_pagina2() -> dict:
    """Genera folios ficticios para la página 2 del recibo"""
    timestamp = int(time.time())
    return {
        "referencia_pago": 273312001734 + timestamp % 1000000,
        "num_autorizacion": 370803 + timestamp % 100000,
        "folio_seguimiento": f"GZ{timestamp % 1000}xy{timestamp % 10}",
        "linea_captura": 41340816 + timestamp % 1000000
    }

def obtener_folio_representativo():
    """Genera folio representativo para mostrar en el PDF"""
    return 21385 + int(time.time()) % 100000

# ===================== SUPABASE STORAGE =====================
def subir_pdf_a_supabase(ruta_pdf_local: str, folio: str, entidad: str = ENTIDAD):
    """Sube el PDF a Storage: bucket 'pdfs' -> jalisco/<folio>.pdf"""
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
    """
    Hilo en segundo plano:
    - sube a storage
    - guarda pdf_path en folios_registrados
    """
    try:
        storage_path = subir_pdf_a_supabase(ruta_pdf_local, folio, entidad=entidad)
        if storage_path:
            supabase.table("folios_registrados")\
                .update({"pdf_path": storage_path})\
                .eq("folio", folio)\
                .execute()
            logger.info(f"[STORAGE] ✅ Path guardado en DB: {storage_path}")
    except Exception as e:
        logger.error(f"[STORAGE BG] ❌ Error: {e}")

def url_publica_pdf(storage_path: str):
    """Obtiene URL pública del PDF en Storage"""
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
    """Genera código QR con URL de consulta"""
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
        logger.info(f"[QR] ✅ Generado para {folio} -> {url_directa}")
        return img_qr, url_directa
    except Exception as e:
        logger.error(f"[ERROR QR] {e}")
        return None, None

def generar_codigo_ine(contenido, ruta_salida):
    """Genera código de barras PDF417 (estilo INE)"""
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
        logger.info(f"[PDF417] ✅ Código generado: {ruta_salida}")
    except Exception as e:
        logger.error(f"[ERROR PDF417] {e}")
        img_fallback = Image.new('RGB', (200, 50), color=(220, 220, 220))
        img_fallback.save(ruta_salida)

def generar_pdf_unificado(datos: dict) -> str:
    """Genera PDF completo de 2 páginas con todos los datos de Jalisco"""
    fol = datos["folio"]
    fecha_exp = datos["fecha_exp"]
    fecha_ven = datos["fecha_ven"]

    zona_mexico = ZoneInfo("America/Mexico_City")
    ahora_cdmx = datetime.now(zona_mexico)

    out = os.path.join(OUTPUT_DIR, f"{fol}.pdf")

    try:
        # ===================== PÁGINA 1: JALISCO =====================
        doc1 = fitz.open(PLANTILLA_PDF)
        pg1 = doc1[0]

        # Insertar datos del vehículo
        for campo in ["marca", "linea", "anio", "serie", "nombre", "color"]:
            if campo in coords_jalisco and campo in datos:
                x, y, s, col = coords_jalisco[campo]
                pg1.insert_text((x, y), datos.get(campo, ""), fontsize=s, color=col, fontname="hebo")

        # Fecha de vencimiento
        pg1.insert_text(coords_jalisco["fecha_ven"][:2], fecha_ven.strftime("%d/%m/%Y"),
                       fontsize=coords_jalisco["fecha_ven"][2], color=coords_jalisco["fecha_ven"][3])

        # Folio principal
        pg1.insert_text((860, 364), fol, fontsize=14, color=(0, 0, 0), fontname="hebo")

        # Fecha actual
        fecha_actual_str = fecha_exp.strftime("%d/%m/%Y")
        pg1.insert_text((475, 830), fecha_actual_str, fontsize=32, color=(0, 0, 0), fontname="hebo")

        # Folio representativo
        fol_rep = obtener_folio_representativo()
        folio_grande = f"4A-DVM/{fol_rep}"
        pg1.insert_text((240, 830), folio_grande, fontsize=32, color=(0, 0, 0), fontname="hebo")
        pg1.insert_text((480, 182), folio_grande, fontsize=63, color=(0, 0, 0), fontname="hebo")

        # Timestamp
        fecha_str = ahora_cdmx.strftime("%d/%m/%Y")
        hora_str = ahora_cdmx.strftime("%H:%M:%S")
        folio_chico = f"DVM-{fol_rep}   {fecha_str}  {hora_str}"
        pg1.insert_text((915, 760), folio_chico, fontsize=14, color=(0, 0, 0), fontname="hebo")

        # Código de barras simple
        pg1.insert_text((935, 600), f"*{fol}*", fontsize=30, color=(0, 0, 0), fontname="Courier")

        # Código PDF417 (estilo INE)
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

        pg1.insert_image(fitz.Rect(932.65, 807, 1141.395, 852.127),
                        filename=ine_img_path, keep_proportion=False, overlay=True)

        pg1.insert_text((915, 775), "EXPEDICION: VENTANILLA DIGITAL", fontsize=12, color=(0, 0, 0), fontname="hebo")

        # QR dinámico en coordenadas de Jalisco
        img_qr, _ = generar_qr_dinamico(fol)
        if img_qr:
            buf = BytesIO()
            img_qr.save(buf, format="PNG")
            buf.seek(0)
            qr_pix = fitz.Pixmap(buf.read())
            x_qr = coords_qr_dinamico["x"]
            y_qr = coords_qr_dinamico["y"]
            ancho_qr = coords_qr_dinamico["ancho"]
            alto_qr = coords_qr_dinamico["alto"]
            pg1.insert_image(
                fitz.Rect(x_qr, y_qr, x_qr + ancho_qr, y_qr + alto_qr),
                pixmap=qr_pix,
                overlay=True
            )

        # ===================== PÁGINA 2: JALISCO =====================
        doc2 = fitz.open(PLANTILLA_BUENO)
        pg2 = doc2[0]

        # Fecha y hora
        fecha_hora_str = fecha_exp.strftime("%d/%m/%Y %H:%M")
        pg2.insert_text((380, 195), fecha_hora_str, fontsize=10, fontname="helv", color=(0, 0, 0))
        pg2.insert_text((380, 290), datos['serie'], fontsize=10, fontname="helv", color=(0, 0, 0))

        # Folios ficticios página 2
        folios_pag2 = generar_folios_pagina2()

        pg2.insert_text(coords_pagina2["referencia_pago"][:2], str(folios_pag2["referencia_pago"]),
                       fontsize=coords_pagina2["referencia_pago"][2], color=coords_pagina2["referencia_pago"][3])

        pg2.insert_text(coords_pagina2["num_autorizacion"][:2], str(folios_pag2["num_autorizacion"]),
                       fontsize=coords_pagina2["num_autorizacion"][2], color=coords_pagina2["num_autorizacion"][3])

        pg2.insert_text(coords_pagina2["total_pagado"][:2], f"${PRECIO_FIJO_PAGINA2}.00 MN",
                       fontsize=coords_pagina2["total_pagado"][2], color=coords_pagina2["total_pagado"][3])

        pg2.insert_text(coords_pagina2["folio_seguimiento"][:2], folios_pag2["folio_seguimiento"],
                       fontsize=coords_pagina2["folio_seguimiento"][2], color=coords_pagina2["folio_seguimiento"][3])

        pg2.insert_text(coords_pagina2["linea_captura"][:2], str(folios_pag2["linea_captura"]),
                       fontsize=coords_pagina2["linea_captura"][2], color=coords_pagina2["linea_captura"][3])

        # Combinar ambas páginas
        doc_final = fitz.open()
        doc_final.insert_pdf(doc1)
        doc_final.insert_pdf(doc2)
        doc_final.save(out)

        doc_final.close()
        doc1.close()
        doc2.close()

        logger.info(f"[PDF JALISCO] ✅ Generado: {out}")

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
    """Redirige al login"""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login para usuarios normales y admin"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Admin especial
        if username == 'Serg890105tm3' and password == 'Serg890105tm3':
            session['admin'] = True
            session['username'] = 'Serg890105tm3'
            return redirect(url_for('admin'))

        # Usuarios normales
        resp = supabase.table("verificaciondigitalcdmx")\
            .select("*")\
            .eq("username", username)\
            .eq("password", password)\
            .execute()

        if resp.data:
            session['user_id'] = resp.data[0]['id']
            session['username'] = resp.data[0]['username']
            session['admin'] = False
            return redirect(url_for('registro_usuario'))

        flash('Usuario o contraseña incorrectos', 'error')
        return render_template('login.html')
    
    return render_template('login.html')

@app.route('/admin')
def admin():
    """Panel de administración"""
    if not session.get('admin'):
        return redirect(url_for('login'))
    return render_template('panel.html')

@app.route('/crear_usuario', methods=['GET', 'POST'])
def crear_usuario():
    """Crear nuevos usuarios con folios asignados"""
    if not session.get('admin'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        folios = int(request.form['folios'])
        
        existe = supabase.table("verificaciondigitalcdmx")\
            .select("id")\
            .eq("username", username)\
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
    """Generar permiso vehicular (usuarios normales)"""
    if 'username' not in session or not session['username']:
        flash("Sesión no válida. Inicia sesión de nuevo.", "error")
        return redirect(url_for('login'))

    # Bloquear si es admin
    if session.get('admin'):
        return redirect(url_for('admin'))

    # Obtener info del usuario
    user_data = supabase.table("verificaciondigitalcdmx")\
        .select("*")\
        .eq("username", session['username'])\
        .execute()

    if not user_data.data:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for('login'))

    usuario = user_data.data[0]
    folios_asignados = usuario['folios_asignac']
    folios_usados = usuario['folios_usados']
    folios_disponibles = folios_asignados - folios_usados

    folios_info = {
        'folios_asignac': folios_asignados,
        'folios_usados': folios_usados
    }

    if request.method == 'POST':
        # Verificar folios disponibles
        if folios_disponibles <= 0:
            flash("⚠️ Ya no tienes folios disponibles. Contacta al administrador.", "error")
            return render_template('registro_usuario.html', folios_info=folios_info)

        # Obtener datos del formulario
        marca = request.form['marca'].strip().upper()
        linea = request.form['linea'].strip().upper()
        anio = request.form['anio'].strip()
        numero_serie = request.form['serie'].strip().upper()
        numero_motor = request.form['motor'].strip().upper()
        color = request.form.get('color', 'N/A').strip().upper()
        nombre = request.form.get('nombre', 'N/A').strip().upper()

        # Fechas
        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
        vigencia = int(request.form.get('vigencia', 30))
        venc = ahora + timedelta(days=vigencia)

        datos = {
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

        try:
            # 1) Guardar en DB con folio automático y anti-duplicados
            ok = guardar_folio_con_reintento(datos, session['username'])
            if not ok:
                flash("❌ No se pudo registrar el folio. Intenta de nuevo.", "error")
                return render_template('registro_usuario.html', folios_info=folios_info)

            folio_final = datos["folio"]

            # 2) Generar PDF local (rápido)
            pdf_path_local = generar_pdf_unificado(datos)

            # 3) Incrementar folios usados
            supabase.table("verificaciondigitalcdmx")\
                .update({"folios_usados": folios_usados + 1})\
                .eq("username", session['username'])\
                .execute()

            # 4) Subir PDF en segundo plano (NO BLOQUEA)
            t = threading.Thread(
                target=subir_pdf_bg_y_guardar_path,
                args=(pdf_path_local, folio_final, ENTIDAD),
                daemon=True
            )
            t.start()

            flash(f'✅ Permiso generado. Folio: {folio_final}. Te quedan {folios_disponibles - 1} folios.', 'success')
            return render_template('exitoso.html',
                                 folio=folio_final,
                                 serie=numero_serie,
                                 fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

        except Exception as e:
            logger.error(f"[ERROR] Generando permiso: {e}")
            flash(f"Error al generar el permiso: {e}", 'error')
            return render_template('registro_usuario.html', folios_info=folios_info)

    return render_template('registro_usuario.html', folios_info=folios_info)

@app.route('/mis_permisos')
def mis_permisos():
    """✅ NUEVO: Historial de permisos del usuario"""
    if not session.get('username') or session.get('admin'):
        flash('Acceso denegado.', 'error')
        return redirect(url_for('login'))
    
    # Buscar todos los folios generados por este usuario
    permisos = supabase.table("folios_registrados")\
        .select("*")\
        .eq("creado_por", session['username'])\
        .order("fecha_expedicion", desc=True)\
        .execute().data
    
    # Procesar datos
    hoy = datetime.now()
    for p in permisos:
        try:
            fe = datetime.fromisoformat(p['fecha_expedicion'])
            fv = datetime.fromisoformat(p['fecha_vencimiento'])
            p['fecha_formateada'] = fe.strftime('%d/%m/%Y')
            p['hora_formateada'] = fe.strftime('%H:%M:%S')
            p['estado'] = "VIGENTE" if hoy <= fv else "VENCIDO"
        except:
            p['fecha_formateada'] = 'Error'
            p['hora_formateada'] = 'Error'
            p['estado'] = 'ERROR'
    
    # Obtener stats del usuario
    usr_data = supabase.table("verificaciondigitalcdmx")\
        .select("folios_asignac, folios_usados")\
        .eq("username", session['username']).execute().data[0]
    
    return render_template('mis_permisos.html', 
                         permisos=permisos,
                         total_generados=len(permisos),
                         folios_asignados=usr_data['folios_asignac'],
                         folios_usados=usr_data['folios_usados'])

@app.route('/registro_admin', methods=['GET', 'POST'])
def registro_admin():
    """Generar permiso como administrador (sin límite de folios)"""
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        folio_manual = request.form.get('folio', '').strip().upper()
        marca = request.form['marca'].strip().upper()
        linea = request.form['linea'].strip().upper()
        anio = request.form['anio'].strip()
        numero_serie = request.form['serie'].strip().upper()
        numero_motor = request.form['motor'].strip().upper()
        color = request.form.get('color', 'N/A').strip().upper()
        nombre = request.form.get('nombre', 'N/A').strip().upper()

        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
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

        try:
            ok = guardar_folio_con_reintento(datos, "ADMIN")
            if not ok:
                flash("❌ No se pudo registrar el folio.", "error")
                return redirect(url_for('registro_admin'))

            folio_final = datos["folio"]
            pdf_path_local = generar_pdf_unificado(datos)

            # Subir en segundo plano
            t = threading.Thread(
                target=subir_pdf_bg_y_guardar_path,
                args=(pdf_path_local, folio_final, ENTIDAD),
                daemon=True
            )
            t.start()

            flash('Permiso generado correctamente.', 'success')
            return render_template('exitoso.html',
                                 folio=folio_final,
                                 serie=numero_serie,
                                 fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

        except Exception as e:
            logger.error(f"[ERROR] Admin generando: {e}")
            flash(f"Error: {e}", 'error')
            return redirect(url_for('registro_admin'))

    return render_template('registro_admin.html')

@app.route('/consulta_folio', methods=['GET', 'POST'])
def consulta_folio():
    """Consultar folio desde formulario"""
    resultado = None
    if request.method == 'POST':
        folio = request.form['folio'].strip().upper()
        registros = supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data
        
        if not registros:
            resultado = {"estado": "NO SE ENCUENTRA REGISTRADO", "color": "rojo", "folio": folio}
        else:
            r = registros[0]
            fexp = datetime.fromisoformat(r['fecha_expedicion'])
            fven = datetime.fromisoformat(r['fecha_vencimiento'])
            estado = "VIGENTE" if datetime.now() <= fven else "VENCIDO"
            color = "verde" if estado == "VIGENTE" else "cafe"
            resultado = {
                "estado": estado,
                "color": color,
                "folio": folio,
                "fecha_expedicion": fexp.strftime('%d/%m/%Y'),
                "fecha_vencimiento": fven.strftime('%d/%m/%Y'),
                "marca": r['marca'],
                "linea": r['linea'],
                "año": r['anio'],
                "numero_serie": r['numero_serie'],
                "numero_motor": r['numero_motor'],
                "entidad": r.get('entidad', ENTIDAD)
            }
        return render_template('resultado_consulta.html', resultado=resultado)
    
    return render_template('consulta_folio.html')

@app.route('/consulta/<folio>')
def consulta_folio_directo(folio):
    """Consulta pública de folio vía URL (desde QR)"""
    row = supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data

    if not row:
        return render_template("resultado_consulta.html", resultado={
            "estado": "NO SE ENCUENTRA REGISTRADO",
            "color": "rojo",
            "folio": folio
        })

    r = row[0]
    fe = datetime.fromisoformat(r['fecha_expedicion'])
    fv = datetime.fromisoformat(r['fecha_vencimiento'])
    estado = "VIGENTE" if datetime.now() <= fv else "VENCIDO"
    color = "verde" if estado == "VIGENTE" else "cafe"

    resultado = {
        "estado": estado,
        "color": color,
        "folio": folio,
        "fecha_expedicion": fe.strftime("%d/%m/%Y"),
        "fecha_vencimiento": fv.strftime("%d/%m/%Y"),
        "marca": r['marca'],
        "linea": r['linea'],
        "año": r['anio'],
        "numero_serie": r['numero_serie'],
        "numero_motor": r['numero_motor'],
        "entidad": r.get('entidad', ENTIDAD)
    }

    return render_template("resultado_consulta.html", resultado=resultado)

@app.route('/descargar_recibo/<folio>')
def descargar_recibo(folio):
    """
    Descargar PDF:
    - Si existe en Storage, redirige a URL pública
    - Si no, sirve desde local
    """
    try:
        row = supabase.table("folios_registrados")\
            .select("pdf_path")\
            .eq("folio", folio)\
            .limit(1)\
            .execute().data

        if row and row[0].get("pdf_path"):
            storage_path = row[0]["pdf_path"]
            public_url = url_publica_pdf(storage_path)
            if public_url:
                return redirect(public_url)
    except Exception as e:
        logger.error(f"[DESCARGA] Error DB/Storage: {e}")

    # Fallback a archivo local
    ruta_pdf = f"{OUTPUT_DIR}/{folio}.pdf"
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
    """Cerrar sesión"""
    session.clear()
    return redirect(url_for('login'))

# ===================== EJECUTAR APP =====================
if __name__ == '__main__':
    # Verificar que existan las plantillas
    if not os.path.exists(PLANTILLA_PDF):
        logger.warning(f"⚠️ No se encuentra: {PLANTILLA_PDF}")
    if not os.path.exists(PLANTILLA_BUENO):
        logger.warning(f"⚠️ No se encuentra: {PLANTILLA_BUENO}")
    
    # En producción (Render) NO usar debug=True
    app.run(host='0.0.0.0', port=5000, debug=False)
