from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, abort, jsonify
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
import logging
import sys

from werkzeug.middleware.proxy_fix import ProxyFix

# ===================== LOGGING =====================
sys.dont_write_bytecode = True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ===================== ZONA HORARIA =====================
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

# ===================== FLASK CONFIG =====================
app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=2, x_host=2, x_prefix=1)

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    MAX_CONTENT_LENGTH=32 * 1024 * 1024,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24)
)

# ===================== SUPABASE CONFIG =====================
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===================== CONFIG GENERAL =====================
OUTPUT_DIR      = "documentos"
PLANTILLA_PDF   = "jalisco1.pdf"
PLANTILLA_BUENO = "jalisco.pdf"
URL_CONSULTA_BASE = "https://serviciodigital-jaliscogobmx.onrender.com"
ENTIDAD         = "jalisco"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===================== COORDENADAS PDF =====================
coords_jalisco = {
    "marca":    (340, 332, 14, (0, 0, 0)),
    "serie":    (920, 332, 14, (0, 0, 0)),
    "linea":    (340, 360, 14, (0, 0, 0)),
    "anio":     (340, 389, 14, (0, 0, 0)),
    "color":    (340, 418, 14, (0, 0, 0)),
    "nombre":   (340, 304, 14, (0, 0, 0)),
    "fecha_ven":(285, 570, 90, (0, 0, 0))
}

coords_pagina2 = {
    "referencia_pago":  (380, 123, 10, (0, 0, 0)),
    "num_autorizacion": (380, 147, 10, (0, 0, 0)),
    "total_pagado":     (380, 170, 10, (0, 0, 0)),
    "folio_seguimiento":(380, 243, 10, (0, 0, 0)),
    "linea_captura":    (380, 265, 10, (0, 0, 0))
}

coords_qr_dinamico = {"x": 966, "y": 603, "ancho": 140, "alto": 140}
PRECIO_FIJO_PAGINA2 = 1080

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

# ===================== QR =====================
def generar_qr_dinamico(folio):
    try:
        url = f"{URL_CONSULTA_BASE}/consulta/{folio}"
        qr  = qrcode.QRCode(version=2,
                            error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=4, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color=(220,220,220)).convert("RGB")
        return img, url
    except Exception as e:
        logger.error(f"[ERROR QR] {e}")
        return None, None

# ===================== PDF417 =====================
def generar_codigo_ine(contenido, ruta_salida):
    try:
        codes = pdf417gen.encode(contenido, columns=6, security_level=5)
        image = pdf417gen.render_image(codes)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        ancho, alto = image.size
        img_gris    = Image.new('RGB', (ancho, alto), color=(220,220,220))
        pixels      = image.load()
        pixels_gris = img_gris.load()
        for y in range(alto):
            for x in range(ancho):
                pixel = pixels[x, y]
                if isinstance(pixel, tuple):
                    if sum(pixel[:3]) < 384:
                        pixels_gris[x, y] = (0,0,0)
                else:
                    if pixel < 128:
                        pixels_gris[x, y] = (0,0,0)
        img_gris.save(ruta_salida)
    except Exception as e:
        logger.error(f"[ERROR PDF417] {e}")
        Image.new('RGB', (200,50), color=(220,220,220)).save(ruta_salida)

# ===================== PDF =====================
def generar_pdf_unificado(datos: dict) -> str:
    fol          = datos["folio"]
    fecha_exp_dt = datos["fecha_exp"]
    fecha_ven_dt = datos["fecha_ven"]

    if isinstance(fecha_exp_dt, date) and not isinstance(fecha_exp_dt, datetime):
        fecha_exp_dt = datetime.combine(fecha_exp_dt, datetime.min.time()).replace(tzinfo=TZ_CDMX)
    elif fecha_exp_dt.tzinfo is None:
        fecha_exp_dt = fecha_exp_dt.replace(tzinfo=TZ_CDMX)
    else:
        fecha_exp_dt = fecha_exp_dt.astimezone(TZ_CDMX)

    if isinstance(fecha_ven_dt, date) and not isinstance(fecha_ven_dt, datetime):
        fecha_ven_dt = datetime.combine(fecha_ven_dt, datetime.min.time()).replace(tzinfo=TZ_CDMX)
    elif fecha_ven_dt.tzinfo is None:
        fecha_ven_dt = fecha_ven_dt.replace(tzinfo=TZ_CDMX)
    else:
        fecha_ven_dt = fecha_ven_dt.astimezone(TZ_CDMX)

    ahora_dt = now_cdmx()
    out      = os.path.join(OUTPUT_DIR, f"{fol}.pdf")

    try:
        doc1 = fitz.open(PLANTILLA_PDF)
        pg1  = doc1[0]

        for campo in ["marca","linea","anio","serie","nombre","color"]:
            if campo in coords_jalisco:
                x, y, s, col = coords_jalisco[campo]
                pg1.insert_text((x,y), str(datos.get(campo,"")), fontsize=s, color=col, fontname="hebo")

        pg1.insert_text(coords_jalisco["fecha_ven"][:2],
                        fecha_ven_dt.strftime("%d/%m/%Y"),
                        fontsize=coords_jalisco["fecha_ven"][2],
                        color=coords_jalisco["fecha_ven"][3])

        pg1.insert_text((860,364), fol, fontsize=14, color=(0,0,0), fontname="hebo")
        pg1.insert_text((475,830), fecha_exp_dt.strftime("%d/%m/%Y"), fontsize=32, color=(0,0,0), fontname="hebo")

        fol_rep      = obtener_folio_representativo()
        folio_grande = f"4A-DVM/{fol_rep}"
        pg1.insert_text((240,830), folio_grande, fontsize=32, color=(0,0,0), fontname="hebo")
        pg1.insert_text((480,182), folio_grande, fontsize=63, color=(0,0,0), fontname="hebo")

        folio_chico = f"DVM-{fol_rep}   {ahora_dt.strftime('%d/%m/%Y')}  {ahora_dt.strftime('%H:%M:%S')}"
        pg1.insert_text((915,760), folio_chico, fontsize=14, color=(0,0,0), fontname="hebo")
        pg1.insert_text((935,600), f"*{fol}*", fontsize=30, color=(0,0,0), fontname="Courier")

        contenido_ine = (
            f"FOLIO:  {fol}\nMARCA:  {datos.get('marca','')}\n"
            f"SUBMARCA:  {datos.get('linea','')}\nAÑO:  {datos.get('anio','')}\n"
            f"SERIE:  {datos.get('serie','')}\nMOTOR:  {datos.get('motor','')}\n"
            f"COLOR:  {datos.get('color','')}\nNOMBRE:  {datos.get('nombre','')}"
        )
        ine_img_path = os.path.join(OUTPUT_DIR, f"{fol}_inecode.png")
        generar_codigo_ine(contenido_ine, ine_img_path)
        pg1.insert_image(fitz.Rect(932.65,807,1141.395,852.127),
                         filename=ine_img_path, keep_proportion=False, overlay=True)
        pg1.insert_text((915,775), "EXPEDICION: VENTANILLA DIGITAL",
                        fontsize=12, color=(0,0,0), fontname="hebo")

        img_qr, _ = generar_qr_dinamico(fol)
        if img_qr:
            buf = BytesIO()
            img_qr.save(buf, format="PNG")
            buf.seek(0)
            qr_pix = fitz.Pixmap(buf.read())
            pg1.insert_image(
                fitz.Rect(coords_qr_dinamico["x"], coords_qr_dinamico["y"],
                          coords_qr_dinamico["x"]+coords_qr_dinamico["ancho"],
                          coords_qr_dinamico["y"]+coords_qr_dinamico["alto"]),
                pixmap=qr_pix, overlay=True)

        doc2 = fitz.open(PLANTILLA_BUENO)
        pg2  = doc2[0]
        pg2.insert_text((380,195), fecha_exp_dt.strftime("%d/%m/%Y %H:%M"),
                        fontsize=10, fontname="helv", color=(0,0,0))
        pg2.insert_text((380,290), str(datos.get('serie','')),
                        fontsize=10, fontname="helv", color=(0,0,0))

        fp2 = generar_folios_pagina2()
        pg2.insert_text(coords_pagina2["referencia_pago"][:2],  str(fp2["referencia_pago"]),
                        fontsize=coords_pagina2["referencia_pago"][2],  color=coords_pagina2["referencia_pago"][3])
        pg2.insert_text(coords_pagina2["num_autorizacion"][:2], str(fp2["num_autorizacion"]),
                        fontsize=coords_pagina2["num_autorizacion"][2], color=coords_pagina2["num_autorizacion"][3])
        pg2.insert_text(coords_pagina2["total_pagado"][:2],     f"${PRECIO_FIJO_PAGINA2}.00 MN",
                        fontsize=coords_pagina2["total_pagado"][2],     color=coords_pagina2["total_pagado"][3])
        pg2.insert_text(coords_pagina2["folio_seguimiento"][:2],str(fp2["folio_seguimiento"]),
                        fontsize=coords_pagina2["folio_seguimiento"][2],color=coords_pagina2["folio_seguimiento"][3])
        pg2.insert_text(coords_pagina2["linea_captura"][:2],    str(fp2["linea_captura"]),
                        fontsize=coords_pagina2["linea_captura"][2],    color=coords_pagina2["linea_captura"][3])

        doc_final = fitz.open()
        doc_final.insert_pdf(doc1)
        doc_final.insert_pdf(doc2)
        doc_final.save(out)
        doc_final.close(); doc1.close(); doc2.close()
        logger.info(f"[PDF] ✅ {out}")

    except Exception as e:
        logger.error(f"[ERROR PDF] {e}")
        doc_fallback = fitz.open()
        doc_fallback.new_page().insert_text((50,50), f"ERROR - Folio: {fol}", fontsize=12)
        doc_fallback.save(out)
        doc_fallback.close()

    return out

# ===================== RUTAS =====================

@app.route('/')
def inicio():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()

        if username == 'Serg890105tm3' and password == 'Serg890105tm3':
            session['admin']    = True
            session['username'] = 'Serg890105tm3'
            return redirect(url_for('admin'))

        resp = supabase.table("verificaciondigitalcdmx")\
            .select("*").eq("username",username).eq("password",password).execute()

        if resp.data:
            u = resp.data[0]
            session['user_id']  = u.get('id')
            session['username'] = u['username']
            session['admin']    = False
            return redirect(url_for('registro_usuario'))

        flash('Usuario o contraseña incorrectos','error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── ADMIN ───────────────────────────────────────────────────────────────────

@app.route('/admin')
def admin():
    if not session.get('admin'):
        return redirect(url_for('login'))
    return render_template('panel.html')


@app.route('/crear_usuario', methods=['GET','POST'])
def crear_usuario():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        folios   = int(request.form['folios'])

        existe = supabase.table("verificaciondigitalcdmx")\
            .select("id").eq("username",username).limit(1).execute()

        if existe.data:
            flash('Error: el usuario ya existe.','error')
        else:
            supabase.table("verificaciondigitalcdmx").insert({
                "username":       username,
                "password":       password,
                "folios_asignac": folios,
                "folios_usados":  0,
                "pagado":         False
            }).execute()
            flash('Usuario creado.','success')

    return render_template('crear_usuario.html')


@app.route('/registro_admin', methods=['GET','POST'])
def registro_admin():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        folio_manual = request.form.get('folio','').strip()
        if folio_manual and not re.fullmatch(r"\d{9}", folio_manual):
            flash("❌ Folio debe tener 9 dígitos.","error")
            return redirect(url_for('registro_admin'))

        marca        = request.form.get('marca','').strip().upper()
        linea        = request.form.get('linea','').strip().upper()
        anio         = request.form.get('anio','').strip()
        numero_serie = request.form.get('serie','').strip().upper()
        numero_motor = request.form.get('motor','').strip().upper()
        color        = request.form.get('color','').strip().upper() or 'BLANCO'
        nombre       = request.form.get('nombre','').strip().upper() or 'SIN NOMBRE'

        if not all([marca, linea, anio, numero_serie, numero_motor]):
            flash("❌ Faltan campos.","error")
            return redirect(url_for('registro_admin'))

        fecha_expedicion_str = request.form.get('fecha_expedicion','').strip()
        if fecha_expedicion_str:
            try:
                fecha_exp = datetime.strptime(fecha_expedicion_str,'%Y-%m-%d').replace(tzinfo=TZ_CDMX)
            except:
                flash("❌ Fecha inválida.","error")
                return redirect(url_for('registro_admin'))
        else:
            fecha_exp = now_cdmx()

        vigencia_map = {'30':30,'60':60,'90':90,'180':180,'365':365}
        vigencia     = vigencia_map.get(request.form.get('vigencia','30'), 30)
        fecha_ven    = fecha_exp + timedelta(days=vigencia)

        datos = {
            "folio":     folio_manual if folio_manual else None,
            "marca":     marca,  "linea":  linea,  "anio":  anio,
            "serie":     numero_serie,  "motor": numero_motor,
            "color":     color,  "nombre": nombre,
            "fecha_exp": fecha_exp,  "fecha_ven": fecha_ven
        }

        if not guardar_folio_con_reintento(datos, "ADMIN"):
            flash("❌ Error al registrar.","error")
            return redirect(url_for('registro_admin'))

        generar_pdf_unificado(datos)
        flash('✅ Permiso generado.','success')
        return render_template('exitoso.html',
                               folio=datos["folio"],
                               serie=numero_serie,
                               fecha_generacion=fecha_exp.strftime('%d/%m/%Y %H:%M'))

    return render_template('registro_admin.html')


# ── admin_folios CON FILTROS GET ─────────────────────────────────────────────

@app.route('/admin_folios')
def admin_folios():
    if not session.get('admin'):
        return redirect(url_for('login'))

    # Parámetros GET
    filtro       = request.args.get('filtro', '').strip()
    criterio     = request.args.get('criterio', 'folio')        # folio | numero_serie
    ordenar      = request.args.get('ordenar', 'desc')          # desc | asc
    estado_filtro= request.args.get('estado', 'todos')          # todos | vigente | vencido
    fecha_inicio = request.args.get('fecha_inicio', '')
    fecha_fin    = request.args.get('fecha_fin', '')

    # Traer todos los folios de Jalisco ordenados
    orden_desc = (ordenar == 'desc')
    query = supabase.table("folios_registrados")\
        .select("*").eq("entidad", ENTIDAD)\
        .order("fecha_expedicion", desc=orden_desc)

    # Filtro por texto (folio o serie exacto desde BD)
    if filtro:
        if criterio == 'numero_serie':
            query = query.ilike("numero_serie", f"%{filtro}%")
        else:
            query = query.ilike("folio", f"%{filtro}%")

    # Filtro por rango de fechas
    if fecha_inicio:
        query = query.gte("fecha_expedicion", fecha_inicio)
    if fecha_fin:
        query = query.lte("fecha_expedicion", fecha_fin)

    folios = query.execute().data or []

    hoy = today_cdmx()
    resultado = []
    for f in folios:
        try:
            fv = parse_date_any(f.get('fecha_vencimiento'))
            f['estado'] = "VIGENTE" if hoy <= fv else "VENCIDO"
        except:
            f['estado'] = 'ERROR'

        # Filtro por estado (en Python después de calcular)
        if estado_filtro == 'vigente' and f['estado'] != 'VIGENTE':
            continue
        if estado_filtro == 'vencido' and f['estado'] != 'VENCIDO':
            continue

        resultado.append(f)

    return render_template('admin_folios.html',
                           folios=resultado,
                           filtro=filtro,
                           criterio=criterio,
                           ordenar=ordenar,
                           estado=estado_filtro,
                           fecha_inicio=fecha_inicio,
                           fecha_fin=fecha_fin)


@app.route('/editar_folio/<folio>', methods=['GET','POST'])
def editar_folio(folio):
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        supabase.table("folios_registrados").update({
            "marca":             request.form['marca'],
            "linea":             request.form['linea'],
            "anio":              request.form['anio'],
            "numero_serie":      request.form['serie'],
            "numero_motor":      request.form['motor'],
            "fecha_expedicion":  request.form['fecha_expedicion'],
            "fecha_vencimiento": request.form['fecha_vencimiento']
        }).eq("folio",folio).execute()
        flash("Folio actualizado.","success")
        return redirect(url_for('admin_folios'))

    resp = supabase.table("folios_registrados").select("*").eq("folio",folio).execute()
    if not resp.data:
        flash("Folio no encontrado.","error")
        return redirect(url_for('admin_folios'))

    return render_template("editar_folio.html", folio=resp.data[0])


@app.route('/eliminar_folio', methods=['POST'])
def eliminar_folio():
    """Elimina un solo folio."""
    if not session.get('admin'):
        return redirect(url_for('login'))
    folio = request.form['folio']
    supabase.table("folios_registrados").delete().eq("folio",folio).execute()
    flash("Folio eliminado.","success")
    return redirect(url_for('admin_folios'))


@app.route('/eliminar_folios_masivo', methods=['POST'])
def eliminar_folios_masivo():
    """Elimina múltiples folios seleccionados con checkbox."""
    if not session.get('admin'):
        return redirect(url_for('login'))

    folios_a_eliminar = request.form.getlist('folios')

    if not folios_a_eliminar:
        flash("No seleccionaste ningún folio.","error")
        return redirect(url_for('admin_folios'))

    eliminados = 0
    errores    = 0
    for folio in folios_a_eliminar:
        try:
            supabase.table("folios_registrados").delete().eq("folio", folio).execute()
            eliminados += 1
        except Exception as e:
            logger.error(f"[ERROR] Eliminar {folio}: {e}")
            errores += 1

    if eliminados:
        flash(f"✅ {eliminados} folio(s) eliminado(s) correctamente.", "success")
    if errores:
        flash(f"⚠️ {errores} folio(s) no pudieron eliminarse.", "error")

    return redirect(url_for('admin_folios'))


# ── Gestión de usuarios (pagado / pendiente) ─────────────────────────────────

@app.route('/admin/usuarios')
def admin_usuarios():
    if not session.get('admin'):
        return redirect(url_for('login'))
    resp     = supabase.table("verificaciondigitalcdmx")\
        .select("*").order("id",desc=True).execute()
    usuarios = resp.data or []
    for u in usuarios:
        u['timer_info'] = get_timer_info(u)
    return render_template("admin_usuarios.html", usuarios=usuarios)


@app.route('/admin/marcar_pagado/<int:user_id>', methods=['POST'])
def marcar_pagado(user_id):
    if not session.get('admin'):
        return redirect(url_for('login'))
    supabase.table("verificaciondigitalcdmx")\
        .update({"pagado":True}).eq("id",user_id).execute()
    flash("Usuario marcado como PAGADO.","success")
    return redirect(url_for('admin_usuarios'))


@app.route('/admin/marcar_pendiente/<int:user_id>', methods=['POST'])
def marcar_pendiente(user_id):
    if not session.get('admin'):
        return redirect(url_for('login'))
    supabase.table("verificaciondigitalcdmx")\
        .update({"pagado":False,"created_at":datetime.utcnow().isoformat()})\
        .eq("id",user_id).execute()
    flash("Marcado como PENDIENTE. Timer reiniciado.","warning")
    return redirect(url_for('admin_usuarios'))


# ── API timer ─────────────────────────────────────────────────────────────────

@app.route('/api/timer_estado')
def api_timer_estado():
    if not session.get('username') or session.get('admin'):
        return jsonify({"error":"no auth"}), 401

    resp = supabase.table("verificaciondigitalcdmx")\
        .select("pagado,created_at,folios_asignac,folios_usados")\
        .eq("username",session['username']).limit(1).execute()

    if not resp.data:
        return jsonify({"error":"no encontrado"}), 404

    u      = resp.data[0]
    asig   = int(u.get("folios_asignac",0))
    usados = int(u.get("folios_usados",0))

    return jsonify({
        "pagado":     u.get("pagado",False),
        "timer":      get_timer_info(u),
        "porcentaje": round((usados/asig)*100) if asig > 0 else 0
    })


# ─── USUARIO (3RO) ───────────────────────────────────────────────────────────

@app.route('/registro_usuario', methods=['GET','POST'])
def registro_usuario():
    if not session.get('username'):
        return redirect(url_for('login'))
    if session.get('admin'):
        return redirect(url_for('admin'))

    user_data = supabase.table("verificaciondigitalcdmx")\
        .select("*").eq("username",session['username']).limit(1).execute()

    if not user_data.data:
        flash("Usuario no encontrado.","error")
        return redirect(url_for('login'))

    usuario            = user_data.data[0]
    folios_asignados   = int(usuario.get('folios_asignac',0))
    folios_usados      = int(usuario.get('folios_usados',0))
    folios_disponibles = folios_asignados - folios_usados
    folios_info        = {
        "folios_asignac": folios_asignados,
        "folios_usados":  folios_usados,
        "pagado":         usuario.get("pagado", False),
        "created_at":     usuario.get("created_at")
    }
    pct = round((folios_usados / folios_asignados)*100) if folios_asignados > 0 else 0

    if request.method == 'POST':
        if folios_disponibles <= 0:
            flash("⚠️ Sin folios disponibles.","error")
            return render_template('registro_usuario.html',
                                   folios_info=folios_info,
                                   porcentaje=pct,
                                   fecha_hoy=today_cdmx().isoformat())

        marca        = request.form.get('marca','').strip().upper()
        linea        = request.form.get('linea','').strip().upper()
        anio         = request.form.get('anio','').strip()
        numero_serie = request.form.get('serie','').strip().upper()
        numero_motor = request.form.get('motor','').strip().upper()
        color        = request.form.get('color','').strip().upper() or 'BLANCO'
        nombre       = request.form.get('nombre','').strip().upper() or 'SIN NOMBRE'

        if not all([marca, linea, anio, numero_serie, numero_motor]):
            flash("❌ Faltan campos obligatorios.","error")
            return render_template('registro_usuario.html',
                                   folios_info=folios_info,
                                   porcentaje=pct,
                                   fecha_hoy=today_cdmx().isoformat())

        fecha_inicio_str = request.form.get('fecha_inicio','').strip()
        if fecha_inicio_str:
            try:
                ahora = datetime.strptime(fecha_inicio_str,'%Y-%m-%d').replace(tzinfo=TZ_CDMX)
            except:
                flash("❌ Fecha inválida.","error")
                return render_template('registro_usuario.html',
                                       folios_info=folios_info,
                                       porcentaje=pct,
                                       fecha_hoy=today_cdmx().isoformat())
        else:
            ahora = now_cdmx()

        vigencia = int(request.form.get('vigencia', 30))
        venc     = ahora + timedelta(days=vigencia)

        datos = {
            "folio":     None,
            "marca":     marca,   "linea":  linea,  "anio":  anio,
            "serie":     numero_serie,  "motor": numero_motor,
            "color":     color,   "nombre": nombre,
            "fecha_exp": ahora,   "fecha_ven": venc
        }

        if not guardar_folio_con_reintento(datos, session['username']):
            flash("❌ Error al registrar.","error")
            return render_template('registro_usuario.html',
                                   folios_info=folios_info,
                                   porcentaje=pct,
                                   fecha_hoy=today_cdmx().isoformat())

        generar_pdf_unificado(datos)

        supabase.table("verificaciondigitalcdmx")\
            .update({"folios_usados": folios_usados+1})\
            .eq("username",session['username']).execute()

        flash(f'✅ Folio: {datos["folio"]}','success')
        return render_template('exitoso.html',
                               folio=datos["folio"],
                               serie=numero_serie,
                               fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

    return render_template('registro_usuario.html',
                           folios_info=folios_info,
                           timer_info=get_timer_info(folios_info),
                           porcentaje=pct,
                           fecha_hoy=today_cdmx().isoformat())


@app.route('/mis_permisos')
def mis_permisos():
    if not session.get('username') or session.get('admin'):
        return redirect(url_for('login'))

    permisos = supabase.table("folios_registrados")\
        .select("*").eq("creado_por",session['username'])\
        .order("fecha_expedicion",desc=True).execute().data or []

    hoy = today_cdmx()
    for p in permisos:
        try:
            fe = parse_date_any(p.get('fecha_expedicion'))
            fv = parse_date_any(p.get('fecha_vencimiento'))
            p['fecha_formateada'] = fe.strftime('%d/%m/%Y')
            p['estado']           = "VIGENTE" if hoy <= fv else "VENCIDO"
            p['tiene_pdf']        = os.path.exists(
                os.path.join(OUTPUT_DIR, f"{p['folio']}.pdf"))
        except:
            p['fecha_formateada'] = 'Error'
            p['estado']           = 'ERROR'
            p['tiene_pdf']        = False

    usr_data = supabase.table("verificaciondigitalcdmx")\
        .select("folios_asignac,folios_usados")\
        .eq("username",session['username']).limit(1).execute().data
    usr_row  = usr_data[0] if usr_data else {"folios_asignac":0,"folios_usados":0}

    return render_template('mis_permisos.html',
                           permisos=permisos,
                           total_generados=len(permisos),
                           folios_asignados=int(usr_row.get('folios_asignac',0)),
                           folios_usados=int(usr_row.get('folios_usados',0)))


# ─── CONSULTA PÚBLICA ────────────────────────────────────────────────────────

@app.route('/consulta_folio', methods=['GET','POST'])
def consulta_folio():
    resultado = None
    if request.method == 'POST':
        folio     = request.form['folio'].strip()
        registros = supabase.table("folios_registrados")\
            .select("*").eq("folio",folio).limit(1).execute().data

        if not registros:
            resultado = {"estado":"NO REGISTRADO","color":"rojo","folio":folio}
        else:
            r      = registros[0]
            fexp   = parse_date_any(r.get('fecha_expedicion'))
            fven   = parse_date_any(r.get('fecha_vencimiento'))
            hoy    = today_cdmx()
            estado = "VIGENTE" if hoy <= fven else "VENCIDO"
            resultado = {
                "estado":           estado,
                "color":            "verde" if estado=="VIGENTE" else "cafe",
                "folio":            folio,
                "fecha_expedicion": fexp.strftime('%d/%m/%Y'),
                "fecha_vencimiento":fven.strftime('%d/%m/%Y'),
                "marca":            r.get('marca',''),
                "linea":            r.get('linea',''),
                "año":              r.get('anio',''),
                "numero_serie":     r.get('numero_serie',''),
                "numero_motor":     r.get('numero_motor',''),
                "entidad":          r.get('entidad',ENTIDAD)
            }
        return render_template('resultado_consulta.html', resultado=resultado)

    return render_template('consulta_folio.html')


@app.route('/consulta/<folio>')
def consulta_folio_directo(folio):
    row = supabase.table("folios_registrados")\
        .select("*").eq("folio",folio).limit(1).execute().data

    if not row:
        return render_template("resultado_consulta.html",
                               resultado={"estado":"NO REGISTRADO","color":"rojo","folio":folio})

    r      = row[0]
    fe     = parse_date_any(r.get('fecha_expedicion'))
    fv     = parse_date_any(r.get('fecha_vencimiento'))
    hoy    = today_cdmx()
    estado = "VIGENTE" if hoy <= fv else "VENCIDO"

    return render_template("resultado_consulta.html", resultado={
        "estado":           estado,
        "color":            "verde" if estado=="VIGENTE" else "cafe",
        "folio":            folio,
        "fecha_expedicion": fe.strftime("%d/%m/%Y"),
        "fecha_vencimiento":fv.strftime("%d/%m/%Y"),
        "marca":            r.get('marca',''),
        "linea":            r.get('linea',''),
        "año":              r.get('anio',''),
        "numero_serie":     r.get('numero_serie',''),
        "numero_motor":     r.get('numero_motor',''),
        "entidad":          r.get('entidad',ENTIDAD)
    })


# ─── DESCARGAS ───────────────────────────────────────────────────────────────

@app.route('/descargar_recibo/<folio>')
def descargar_recibo(folio):
    if not session.get('username'):
        return redirect(url_for('login'))

    if not session.get('admin'):
        resp = supabase.table("folios_registrados")\
            .select("creado_por").eq("folio",folio).limit(1).execute()
        if resp.data and resp.data[0].get("creado_por") != session['username']:
            flash("No tienes permiso para descargar este archivo.","error")
            return redirect(url_for('mis_permisos'))

    ruta_pdf = os.path.join(OUTPUT_DIR, f"{folio}.pdf")
    if not os.path.exists(ruta_pdf):
        flash("PDF no encontrado.","error")
        return redirect(url_for('mis_permisos') if not session.get('admin') else url_for('admin_folios'))

    return send_file(ruta_pdf,
                     as_attachment=True,
                     download_name=f"{folio}_jalisco.pdf",
                     mimetype='application/pdf')


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logger.info("🚀 SERVIDOR JALISCO INICIADO")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
