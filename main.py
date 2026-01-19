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

app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

# Supabase config
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Config general
OUTPUT_DIR = "documentos"
PLANTILLA_PDF = "jalisco1.pdf"
PLANTILLA_BUENO = "jalisco.pdf"
URL_CONSULTA_BASE = "https://serviciodigital-jaliscogobmx.onrender.com"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============ COORDENADAS PDF ============
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

coords_qr_dinamico = {
    "x": 966,
    "y": 603,
    "ancho": 140,
    "alto": 140
}

PRECIO_FIJO_PAGINA2 = 1080

# ============ SISTEMA DE FOLIOS ANTI-DUPLICADOS ============
PREFIJO_CDMX = 122000000

def _leer_ultimo_folio_cdmx_db():
    """Busca el último folio CDMX directamente en Supabase"""
    try:
        inicio = PREFIJO_CDMX
        fin = PREFIJO_CDMX + 100000000
        
        resp = supabase.table("folios_registrados")\
            .select("folio")\
            .eq("entidad", "cdmx")\
            .gte("folio", str(inicio))\
            .lt("folio", str(fin))\
            .order("folio", desc=True)\
            .limit(1)\
            .execute()
        
        if resp.data and len(resp.data) > 0:
            ultimo = int(resp.data[0]["folio"])
            print(f"[FOLIO CDMX] Último en DB: {ultimo}")
            return ultimo
        
        print(f"[FOLIO CDMX] No hay folios, empezando en: {inicio}")
        return inicio - 1
        
    except Exception as e:
        print(f"[ERROR] Consultando último folio: {e}")
        return PREFIJO_CDMX - 1

def generar_folio_cdmx():
    """Genera el siguiente folio disponible consultando SIEMPRE la DB"""
    ultimo = _leer_ultimo_folio_cdmx_db()
    
    if ultimo < PREFIJO_CDMX:
        siguiente = PREFIJO_CDMX
    else:
        siguiente = ultimo + 1
    
    while str(siguiente)[0] == '0' or siguiente >= PREFIJO_CDMX + 100000000:
        if siguiente >= PREFIJO_CDMX + 100000000:
            siguiente = PREFIJO_CDMX
        else:
            siguiente += 1
    
    folio = f"{siguiente:09d}"
    print(f"[FOLIO CDMX] Generado: {folio}")
    return folio

def guardar_folio_con_reintento(datos, username):
    """Guarda con sistema que INCREMENTA el folio automáticamente si está duplicado"""
    max_intentos = 200000
    
    # Generar folio inicial UNA SOLA VEZ
    if "folio" not in datos or not datos.get("folio") or not re.fullmatch(r"\d{9}", str(datos.get("folio", ""))):
        datos["folio"] = generar_folio_cdmx()
    
    folio_inicial = int(datos["folio"])
    
    for intento in range(max_intentos):
        # Calcular el folio actual sumando el número de intento
        folio_actual = folio_inicial + intento
        
        # Validar que esté en rango
        if folio_actual < PREFIJO_CDMX or folio_actual >= PREFIJO_CDMX + 100000000:
            print(f"[ERROR] Folio {folio_actual} fuera de rango")
            return False
        
        # Convertir a string con formato de 9 dígitos
        folio_str = f"{folio_actual:09d}"
        
        # Asegurarse de que no empiece con 0
        if folio_str[0] == '0':
            continue
        
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
                "entidad": "cdmx",
                "estado": "ACTIVO",
                "username": username
            }).execute()
            
            # GUARDAR el folio exitoso en el diccionario
            datos["folio"] = folio_str
            print(f"[ÉXITO] ✅ Folio {folio_str} guardado (intento {intento + 1})")
            return True
            
        except Exception as e:
            em = str(e).lower()
            if "duplicate" in em or "unique constraint" in em or "23505" in em:
                # El folio está duplicado, el loop automáticamente probará el siguiente
                print(f"[DUPLICADO] {folio_str} existe, probando {folio_actual + 1}... (intento {intento + 1}/{max_intentos})")
                continue
            
            print(f"[ERROR BD] {e}")
            return False
    
    print(f"[ERROR FATAL] No se encontró folio disponible tras {max_intentos} intentos")
    return False

# ============ FOLIOS PÁGINA 2 ============
def generar_folios_pagina2() -> dict:
    """Genera folios incrementales simples para página 2"""
    timestamp = int(time.time())
    
    return {
        "referencia_pago": 273312001734 + timestamp % 1000000,
        "num_autorizacion": 370803 + timestamp % 100000,
        "folio_seguimiento": f"GZ{timestamp % 1000}xy{timestamp % 10}",
        "linea_captura": 41340816 + timestamp % 1000000
    }

def obtener_folio_representativo():
    """Genera folio representativo simple basado en timestamp"""
    return 21385 + int(time.time()) % 100000

# ============ FUNCIONES GENERACIÓN PDF ============
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
        return img_qr, url_directa
    except Exception as e:
        print(f"[ERROR QR] {e}")
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
        print(f"[PDF417] Código generado: {ruta_salida}")
    except Exception as e:
        print(f"[ERROR PDF417] {e}")
        img_fallback = Image.new('RGB', (200, 50), color=(220, 220, 220))
        img_fallback.save(ruta_salida)

def generar_pdf_unificado(datos: dict) -> str:
    fol = datos["folio"]
    fecha_exp = datos["fecha_exp"]
    fecha_ven = datos["fecha_ven"]
    
    zona_mexico = ZoneInfo("America/Mexico_City")
    ahora_cdmx = datetime.now(zona_mexico)
    
    out = os.path.join(OUTPUT_DIR, f"{fol}.pdf")
    
    try:
        # PÁGINA 1
        doc1 = fitz.open(PLANTILLA_PDF)
        pg1 = doc1[0]
        
        # Insertar datos básicos
        for campo in ["marca", "linea", "anio", "serie", "nombre", "color"]:
            if campo in coords_jalisco and campo in datos:
                x, y, s, col = coords_jalisco[campo]
                pg1.insert_text((x, y), datos.get(campo, ""), fontsize=s, color=col, fontname="hebo")
        
        # Fecha vencimiento
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
        
        # Folio chico con fecha y hora
        fecha_str = ahora_cdmx.strftime("%d/%m/%Y")
        hora_str = ahora_cdmx.strftime("%H:%M:%S")
        folio_chico = f"DVM-{fol_rep}   {fecha_str}  {hora_str}"
        pg1.insert_text((915, 760), folio_chico, fontsize=14, color=(0, 0, 0), fontname="hebo")
        
        # Código de barras simple
        pg1.insert_text((935, 600), f"*{fol}*", fontsize=30, color=(0, 0, 0), fontname="Courier")
        
        # Código PDF417
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
        
        # QR dinámico
        img_qr, url_qr = generar_qr_dinamico(fol)
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
        
        # PÁGINA 2
        doc2 = fitz.open(PLANTILLA_BUENO)
        pg2 = doc2[0]
        
        fecha_hora_str = fecha_exp.strftime("%d/%m/%Y %H:%M")
        pg2.insert_text((380, 195), fecha_hora_str, fontsize=10, fontname="helv", color=(0, 0, 0))
        pg2.insert_text((380, 290), datos['serie'], fontsize=10, fontname="helv", color=(0, 0, 0))
        
        # Folios página 2
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
        
        # Unificar PDFs
        doc_final = fitz.open()
        doc_final.insert_pdf(doc1)
        doc_final.insert_pdf(doc2)
        doc_final.save(out)
        
        doc_final.close()
        doc1.close()
        doc2.close()
        
        print(f"[PDF UNIFICADO] Generado: {out}")
        
    except Exception as e:
        print(f"[ERROR PDF] {e}")
        doc_fallback = fitz.open()
        page = doc_fallback.new_page()
        page.insert_text((50, 50), f"ERROR - Folio: {fol}", fontsize=12)
        doc_fallback.save(out)
        doc_fallback.close()
    
    return out

# ============ RUTAS FLASK ============
@app.route('/')
def inicio():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == 'Serg890105tm3' and password == 'Serg890105tm3':
            session['admin'] = True
            return redirect(url_for('admin'))

        resp = supabase.table("verificaciondigitalcdmx")\
            .select("*")\
            .eq("username", username)\
            .eq("password", password)\
            .execute()

        if resp.data:
            session['user_id'] = resp.data[0]['id']
            session['username'] = resp.data[0]['username']
            return redirect(url_for('registro_usuario'))

        flash('Usuario o contraseña incorrectos', 'error')
        return render_template('login.html')
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
    if 'username' not in session or not session['username']:
        flash("Sesión no válida. Inicia sesión de nuevo.", "error")
        return redirect(url_for('login'))

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
        if folios_disponibles <= 0:
            flash("⚠️ Ya no tienes folios disponibles. Contacta al administrador.", "error")
            return render_template('registro_usuario.html', folios_info=folios_info)

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
            ok = guardar_folio_con_reintento(datos, session['username'])
            if not ok:
                flash("❌ No se pudo registrar el folio. Intenta de nuevo.", "error")
                return render_template('registro_usuario.html', folios_info=folios_info)

            folio_final = datos["folio"]
            pdf_path = generar_pdf_unificado(datos)

            supabase.table("verificaciondigitalcdmx")\
                .update({"folios_usados": folios_usados + 1})\
                .eq("username", session['username'])\
                .execute()

            flash(f'✅ Permiso generado. Folio: {folio_final}. Te quedan {folios_disponibles - 1} folios.', 'success')
            return render_template('exitoso.html', 
                                 folio=folio_final, 
                                 serie=numero_serie, 
                                 fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

        except Exception as e:
            flash(f"Error al generar el permiso: {e}", 'error')
            return render_template('registro_usuario.html', folios_info=folios_info)

    return render_template('registro_usuario.html', folios_info=folios_info)
    
@app.route('/mis_folios')
def mis_folios():
    if 'username' not in session or not session['username']:
        flash("Sesión no válida. Inicia sesión de nuevo.", "error")
        return redirect(url_for('login'))

    # Traer los folios generados por este usuario
    registros = supabase.table("folios_registrados")\
        .select("*")\
        .eq("username", session['username'])\
        .order("fecha_expedicion", desc=True)\
        .execute().data or []

    hoy = datetime.now()

    # Agregar estado VIGENTE / VENCIDO para mostrar bonito
    for r in registros:
        try:
            fv = datetime.fromisoformat(r["fecha_vencimiento"])
            r["estado_actual"] = "VIGENTE" if hoy <= fv else "VENCIDO"
        except:
            r["estado_actual"] = "DESCONOCIDO"

    return render_template("mis_folios.html", folios=registros)

@app.route('/registro_admin', methods=['GET', 'POST'])
def registro_admin():
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
        venc = ahora + timedelta(days=30)

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
            pdf_path = generar_pdf_unificado(datos)

            flash('Permiso generado correctamente.', 'success')
            return render_template('exitoso.html',
                                 folio=folio_final,
                                 serie=numero_serie,
                                 fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

        except Exception as e:
            flash(f"Error: {e}", 'error')
            return redirect(url_for('registro_admin'))

    return render_template('registro_admin.html')

@app.route('/consulta_folio', methods=['GET','POST'])
def consulta_folio():
    resultado = None
    if request.method == 'POST':
        folio = request.form['folio'].strip().upper()
        registros = supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data
        if not registros:
            resultado = {"estado":"NO SE ENCUENTRA REGISTRADO","color":"rojo","folio":folio}
        else:
            r = registros[0]
            fexp = datetime.fromisoformat(r['fecha_expedicion'])
            fven = datetime.fromisoformat(r['fecha_vencimiento'])
            estado = "VIGENTE" if datetime.now() <= fven else "VENCIDO"
            color = "verde" if estado=="VIGENTE" else "cafe"
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
                "entidad": r.get('entidad', 'cdmx')
            }
        return render_template('resultado_consulta.html', resultado=resultado)
    return render_template('consulta_folio.html')

@app.route('/consulta/<folio>')
def consulta_folio_directo(folio):
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
        "entidad": r.get('entidad', 'cdmx')
    }
    
    return render_template("resultado_consulta.html", resultado=resultado)

@app.route('/admin_folios')
def admin_folios():
    if not session.get('admin'):
        return redirect(url_for('login'))
    
    filtro = request.args.get('filtro','').strip()
    criterio = request.args.get('criterio','folio')
    ordenar = request.args.get('ordenar','desc')
    estado_filtro = request.args.get('estado','todos')
    fecha_inicio = request.args.get('fecha_inicio','')
    fecha_fin = request.args.get('fecha_fin','')
    
    query = supabase.table("folios_registrados").select("*")
    
    if filtro:
        if criterio=="folio":
            query = query.ilike("folio",f"%{filtro}%")
        elif criterio=="numero_serie":
            query = query.ilike("numero_serie",f"%{filtro}%")
    
    registros = query.execute().data or []
    hoy = datetime.now()
    filtrados=[]
    
    for fol in registros:
        try:
            fe = datetime.fromisoformat(fol['fecha_expedicion'])
            fv = datetime.fromisoformat(fol['fecha_vencimiento'])
        except:
            continue
        fol["estado"] = "VIGENTE" if hoy<=fv else "VENCIDO"
        if estado_filtro=="vigente" and fol["estado"]!="VIGENTE": continue
        if estado_filtro=="vencido" and fol["estado"]!="VENCIDO": continue
        if fecha_inicio:
            try:
                fi = datetime.strptime(fecha_inicio,"%Y-%m-%d")
                if fe<fi: continue
            except: pass
        if fecha_fin:
            try:
                ff = datetime.strptime(fecha_fin,"%Y-%m-%d")
                if fe>ff: continue
            except: pass
        filtrados.append(fol)
    
    filtrados.sort(key=lambda x:x['fecha_expedicion'],reverse=(ordenar=='desc'))
    
    return render_template('admin_folios.html',
        folios=filtrados,
        filtro=filtro,
        criterio=criterio,
        ordenar=ordenar,
        estado=estado_filtro,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin
    )

@app.route('/editar_folio/<folio>', methods=['GET','POST'])
def editar_folio(folio):
    if not session.get('admin'):
        return redirect(url_for('login'))
    if request.method=='POST':
        data = {
            "marca": request.form['marca'],
            "linea": request.form['linea'],
            "anio": request.form['anio'],
            "numero_serie": request.form['serie'],
            "numero_motor": request.form['motor'],
            "fecha_expedicion": request.form['fecha_expedicion'],
            "fecha_vencimiento": request.form['fecha_vencimiento']
        }
        supabase.table("folios_registrados").update(data).eq("folio",folio).execute()
        flash("Folio actualizado correctamente.","success")
        return redirect(url_for('admin_folios'))
    resp = supabase.table("folios_registrados").select("*").eq("folio",folio).execute().data
    if resp:
        return render_template('editar_folio.html', folio=resp[0])
    flash("Folio no encontrado.","error")
    return redirect(url_for('admin_folios'))

@app.route('/eliminar_folio', methods=['POST'])
def eliminar_folio():
    if not session.get('admin'):
        return redirect(url_for('login'))
    folio = request.form['folio']
    supabase.table("folios_registrados").delete().eq("folio",folio).execute()
    flash("Folio eliminado correctamente.","success")
    return redirect(url_for('admin_folios'))

@app.route('/eliminar_folios_masivo', methods=['POST'])
def eliminar_folios_masivo():
    if not session.get('admin'):
        return redirect(url_for('login'))
    folios = request.form.getlist('folios')
    if not folios:
        flash("No seleccionaste ningún folio.", "error")
        return redirect(url_for('admin_folios'))
    try:
        supabase.table("folios_registrados").delete().in_("folio", folios).execute()
        flash(f"Se eliminaron {len(folios)} folios correctamente.", "success")
    except Exception as e:
        flash(f"Error al eliminar folios: {e}", "error")
    return redirect(url_for('admin_folios'))

@app.route('/descargar_recibo/<folio>')
def descargar_recibo(folio):
    ruta_pdf = f"documentos/{folio}.pdf"
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
