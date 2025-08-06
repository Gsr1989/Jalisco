from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client, Client
import fitz
import os
import vonage
import qrcode

app = Flask(__name__)
app.secret_key = 'clave_muy_segura_123456'

# Supabase config
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Vonage
VONAGE_KEY = "3a43e40b"
VONAGE_SECRET = "RF1Uvng7cxLTddp9"
vonage_client = vonage.Client(key=VONAGE_KEY, secret=VONAGE_SECRET)
sms = vonage.Sms(vonage_client)

def subir_pdf_supabase(path_local: str, nombre_remoto: str):
    with open(path_local, "rb") as f:
        res = supabase.storage.from_("pdfs").upload(nombre_remoto, f, {"content-type": "application/pdf"})
    return res

# ENTIDAD FIJA PARA ESTE SISTEMA
ENTIDAD = "cdmx"

def enviar_sms(numero: str, folio: str):
    mensaje = (
        f"⚠️ AVISO: El permiso con folio {folio} ha vencido. "
        "Evita corralón y multas. Renueva hoy mismo. "
        "No respondas a este mensaje. Contáctanos por WhatsApp."
    )
    return sms.send_message({
        "from": "ValidacionMX",
        "to": f"52{numero}",
        "text": mensaje,
    })

@app.route('/')
def inicio():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Admin hardcode
        if username == 'Gsr89roja.' and password == 'serg890105':
            session['admin'] = True
            return redirect(url_for('admin'))

        # Usuario normal
        resp = supabase.table("verificaciondigitalcdmx")\
            .select("*")\
            .eq("username", username)\
            .eq("password", password)\
            .execute()

        if resp.data:
            session['user_id'] = resp.data[0]['id']
            session['username'] = resp.data[0]['username']
            return redirect(url_for('registro_usuario'))

        flash('Credenciales incorrectas', 'error')

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

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import fitz  # PyMuPDF

@app.route('/registro_usuario', methods=['GET', 'POST'])
def registro_usuario():
    if 'username' not in session or not session['username']:
        flash("Sesión no válida. Inicia sesión de nuevo.", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':
        folio = request.form['folio']
        marca = request.form['marca']
        linea = request.form['linea']
        anio = request.form['anio']
        numero_serie = request.form['serie']
        numero_motor = request.form['motor']
        vigencia = int(request.form['vigencia'])

        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
        venc = ahora + timedelta(days=vigencia)

        try:
            # Generar PDF
            doc = fitz.open("jalisco.pdf")
            page = doc[0]
            fecha_hora_str = ahora.strftime('%d/%m/%Y %H:%M')
            page.insert_text((380, 195), fecha_hora_str, fontsize=10, fontname="helv", color=(0, 0, 0))
            os.makedirs("documentos", exist_ok=True)
            output_path = f"documentos/{folio}.pdf"
            doc.save(output_path)
        except Exception as e:
            flash(f"Error al generar el PDF: {e}", 'error')
            return redirect(url_for('registro_usuario'))

        flash('Permiso generado correctamente.', 'success')
        return render_template('exitoso.html', folio=folio, serie=numero_serie, fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

    return render_template('registro_usuario.html')
    
@app.route('/registro_admin', methods=['GET', 'POST'])
def registro_admin():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        d = request.form
        fol = d['folio']
        ahora = datetime.now()
        f_exp_iso = ahora.isoformat()
        f_ven_iso = (ahora + timedelta(days=30)).isoformat()
        os.makedirs("documentos", exist_ok=True)

        # === PDF ORIGINAL ===
        out_original = os.path.join("documentos", f"{fol}_jalisco.pdf")
        doc = fitz.open("jalisco.pdf")
        pg = doc[0]

        for campo in ["marca", "linea", "anio", "serie", "motor"]:
            pg.insert_text((100, 100 + 40 * ["marca", "linea", "anio", "serie", "motor"].index(campo)), d.get(campo, ""), fontsize=12, color=(0, 0, 0))

        pg.insert_text((930, 391), fol, fontsize=14, color=(0, 0, 0))
        pg.insert_text((910, 620), f"*{fol}*", fontsize=30, color=(0, 0, 0), fontname="Courier")
        pg.insert_text((1083, 800), "DIGITAL", fontsize=14, color=(0, 0, 0))
        doc.save(out_original)
        doc.close()

        # === PDF CON QR ===
        out_qr = os.path.join("documentos", f"{fol}_jalisco1.pdf")
        doc2 = fitz.open("jalisco1.pdf")
        pg2 = doc2[0]

        qr_url = f"https://serviciodigital-jaliscogobmx.onrender.com/consulta_folio?folio={fol}"
        qr_img = qrcode.make(qr_url)
        qr_img = qr_img.resize((int(2 * 28.35), int(2 * 28.35)))  # 2 cm x 2 cm
        qr_path = os.path.join("documentos", f"{fol}_qr.png")
        qr_img.save(qr_path)

        x0 = 792 - 56.7  # 3 cm desde la derecha
        y0 = 0           # 0 desde abajo (esquina inferior derecha)
        pg2.insert_image(fitz.Rect(x0, y0, x0 + 56.7, y0 + 56.7), filename=qr_path)
        doc2.save(out_qr)
        doc2.close()

        # === Guardar en Supabase
        supabase.table("folios_registrados").insert({
            "folio": fol,
            "marca": d['marca'],
            "linea": d['linea'],
            "anio": d['anio'],
            "numero_serie": d['serie'],
            "numero_motor": d['motor'],
            "numero_telefono": d.get('telefono', '0'),
            "fecha_expedicion": f_exp_iso,
            "fecha_vencimiento": f_ven_iso,
            "entidad": "cdmx"
        }).execute()

        subir_pdf_supabase(out_original, f"{fol}_jalisco.pdf")
        subir_pdf_supabase(out_qr, f"{fol}_jalisco1.pdf")

        flash('Folio admin registrado y PDFs subidos.', 'success')
        return render_template('exitoso.html',
                               folio=fol,
                               serie=d['serie'],
                               fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'))

    return render_template('registro_admin.html')

# ⬅️ AQUÍ VAN, FUERA DE LAS RUTAS


# ⬇️ ABAJO VIENE LA RUTA, COMO SIEMPRE


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
                "entidad": r.get('entidad', '')
            }
        return render_template('resultado_consulta.html', resultado=resultado)
    return render_template('consulta_folio.html')

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

@app.route('/enviar_sms_manual', methods=['POST'])
def enviar_sms_manual():
    if not session.get('admin'):
        return redirect(url_for('login'))
    folio = request.form['folio']
    telefono = request.form.get('telefono')
    try:
        enviar_sms(telefono, folio)
        flash(f"SMS enviado al {telefono} para el folio {folio}.", "success")
    except Exception as e:
        flash(f"Error al enviar SMS: {e}", "error")
    return redirect(url_for('admin_folios'))

@app.route('/enviar_alertas', methods=['POST'])
def enviar_alertas():
    if not session.get('admin'):
        return redirect(url_for('login'))
    hoy = datetime.now().date()
    enviados = 0
    for r in supabase.table("folios_registrados").select("*").execute().data:
        try:
            if datetime.fromisoformat(r['fecha_vencimiento']).date()<=hoy and r.get('numero_telefono'):
                enviar_sms(r['numero_telefono'], r['folio'])
                enviados += 1
        except:
            pass
    flash(f"Se enviaron {enviados} SMS de alerta.", "success")
    return redirect(url_for('admin_folios'))

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

# --- 👇AQUÍ VA TU NUEVA FUNCIÓN DE DESCARGA UNIVERSAL🖕 ---

@app.route('/descargar_pdf/<folio>')
def descargar_pdf(folio):
    try:
        filepath = os.path.join("documentos", f"{folio}_jalisco.pdf")
        return send_file(filepath, as_attachment=True)
    except FileNotFoundError:
        return f"No se encontró el archivo {folio}_jalisco.pdf", 404

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/consulta_permiso_guadalajara')
def consulta_permiso_guadalajara():
    return render_template('consulta_permiso_guadalajara.html')

@app.route("/formulario_jalisco", methods=["GET", "POST"])
def formulario_jalisco():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        d = request.form
        fol = generar_folio_jalisco()
        ahora = datetime.now()
        f_exp_iso = ahora.isoformat()
        f_ven_iso = (ahora + timedelta(days=30)).isoformat()

        os.makedirs("documentos", exist_ok=True)

        # === SOLO GENERAR jalisco.pdf CON FECHA Y HORA ===
        ruta_pdf = os.path.join("documentos", f"{fol}_jalisco.pdf")
        try:
            doc = fitz.open("jalisco.pdf")
            page = doc[0]
            fecha_hora = ahora.strftime("%d/%m/%Y %H:%M")
            page.insert_text((380, 195), fecha_hora, fontsize=10, fontname="helv", color=(0, 0, 0))
            doc.save(ruta_pdf)
            doc.close()
        except Exception as e:
            flash(f"Error al generar el PDF: {e}", "error")

        # === GUARDAR EN SUPABASE ===
        _guardar(
            fol,
            "Jalisco",
            d["serie"],
            d["marca"],
            d["linea"],
            d["motor"],
            d["anio"],
            d["color"],
            f_exp_iso,
            f_ven_iso,
            d["nombre"]
        )

        return render_template("exitoso.html", folio=fol, jalisco=True)

    return render_template("formulario_jalisco.html")

@app.route('/verificar_archivos')
def verificar_archivos():
    folio = request.args.get('folio')
    base = f'documentos/{folio}_jalisco.pdf'
    qr = f'documentos/{folio}_jalisco1.pdf'
    return {
        "base_existe": os.path.exists(base),
        "qr_existe": os.path.exists(qr)
    }

if __name__ == '__main__':
    app.run(debug=True)
