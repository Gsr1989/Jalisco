from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client, Client
import fitz
import os
import vonage
import qrcode
from PIL import Image

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

@app.route('/registro_usuario', methods=['GET', 'POST'])
def registro_usuario():
    if not session.get('username'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        folio = request.form['folio']
        marca = request.form['marca']
        linea = request.form['linea']
        anio = request.form['anio']
        numero_serie = request.form['serie']
        numero_motor = request.form['motor']
        vigencia = int(request.form['vigencia'])

        if supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data:
            flash('Error: el folio ya existe.', 'error')
            return redirect(url_for('registro_usuario'))

        usr_data = supabase.table("verificaciondigitalcdmx")\
            .select("folios_asignac, folios_usados")\
            .eq("username", session['username']).execute().data

        if not usr_data:
            flash('Usuario no válido.', 'error')
            return redirect(url_for('login'))

        usr = usr_data[0]
        if usr['folios_asignac'] - usr['folios_usados'] <= 0:
            flash('No tienes folios disponibles.', 'error')
            return redirect(url_for('registro_usuario'))

        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
        venc = ahora + timedelta(days=vigencia)

        supabase.table("folios_registrados").insert({
            "folio": folio,
            "marca": marca,
            "linea": linea,
            "anio": anio,
            "numero_serie": numero_serie,
            "numero_motor": numero_motor,
            "fecha_expedicion": ahora.isoformat(),
            "fecha_vencimiento": venc.isoformat(),
            "entidad": "cdmx"
        }).execute()

        os.makedirs("documentos", exist_ok=True)
        try:
            # === RECIBO ===
            doc = fitz.open("jalisco.pdf")
            page = doc[0]
            fecha_hora_str = ahora.strftime('%d/%m/%Y %H:%M')
            page.insert_text((380, 195), fecha_hora_str, fontsize=10, fontname="helv", color=(0, 0, 0))

            fol_rep = int(obtener_folio_representativo())
            page.insert_text((328, 804), str(fol_rep), fontsize=32, color=(0, 0, 0))
            page.insert_text((653, 200), str(fol_rep), fontsize=45, color=(0, 0, 0))

            doc.save(f"documentos/{folio}.pdf")
            doc.close()

            # === PERMISO FINAL ===
            doc1 = fitz.open("jalisco1.pdf")
            page1 = doc1[0]
            page1.insert_text((328, 804), str(fol_rep), fontsize=32, color=(0, 0, 0))
            page1.insert_text((653, 200), str(fol_rep), fontsize=45, color=(0, 0, 0))

            doc1.save(f"documentos/{folio}_jalisco1.pdf")
            doc1.close()

            incrementar_folio_representativo(fol_rep)

        except Exception as e:
            flash(f"Error al generar PDF: {e}", 'error')

        supabase.table("verificaciondigitalcdmx").update({
            "folios_usados": usr['folios_usados'] + 1
        }).eq("username", session['username']).execute()

        flash('Folio registrado correctamente.', 'success')
        return render_template(
            'exitoso.html',
            folio=folio,
            serie=numero_serie,
            fecha_generacion=ahora.strftime('%d/%m/%Y %H:%M'),
            permiso_final=True
        )

    datos = supabase.table("verificaciondigitalcdmx")\
        .select("folios_asignac, folios_usados")\
        .eq("username", session['username']).execute().data

    if not datos:
        flash("No se encontró información de folios.", "error")
        return redirect(url_for('login'))

    return render_template('registro_usuario.html', folios_info=datos[0])

# ⬅️ AQUÍ VAN, FUERA DE LAS RUTAS

# Folio representativo solo visual, inicia en 1 y se incrementa cada vez
folio_visual_actual = 1

def obtener_folio_representativo():
    global folio_visual_actual
    return folio_visual_actual

def incrementar_folio_representativo(_):
    global folio_visual_actual
    folio_visual_actual += 1
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

# --- AQUÍ VA TU NUEVA FUNCIÓN DE DESCARGA UNIVERSAL ---
@app.route('/descargar_pdf/<folio>')
def descargar_pdf(folio):
    # Busca entidad para el folio
    registro = supabase.table("folios_registrados").select("entidad").eq("folio", folio).execute().data
    if not registro:
        flash("No se encontró el folio.", "error")
        return redirect(request.referrer or url_for('admin_folios'))
    entidad = registro[0].get('entidad', '').lower()

    # CDMX = recibo base
    if entidad == "cdmx":
        pdf_path = f"documentos/{folio}.pdf"
    else:
        pdf_path = f"documentos/{folio}_{entidad}.pdf"

    if not os.path.exists(pdf_path):
        flash("PDF no existe para este folio y entidad.", "error")
        return redirect(request.referrer or url_for('admin_folios'))
    
    return send_file(pdf_path, as_attachment=True)

@app.route('/descargar_permiso/<folio>')
def descargar_permiso(folio):
    permiso_path = f"documentos/{folio}_jalisco1.pdf"
    if not os.path.exists(permiso_path):
        flash("Permiso no encontrado.", "error")
        return redirect(request.referrer or url_for('admin_folios'))
    
    return send_file(permiso_path, as_attachment=True)

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

        # === PDF BASE ===
        out_original = os.path.join("documentos", f"{fol}_jalisco.pdf")
        doc = fitz.open("jalisco.pdf")
        pg = doc[0]

        for campo in ["marca", "linea", "anio", "serie", "nombre", "color"]:
            x, y, s, col = coords_jalisco[campo]
            pg.insert_text((x, y), d.get(campo, ""), fontsize=s, color=col)

        pg.insert_text(coords_jalisco["fecha_ven"][:2], (ahora + timedelta(days=30)).strftime("%d/%m/%Y"), fontsize=coords_jalisco["fecha_ven"][2], color=coords_jalisco["fecha_ven"][3])
        pg.insert_text((930, 391), fol, fontsize=14, color=(0, 0, 0))

        fol_representativo = int(obtener_folio_representativo())
        pg.insert_text((328, 804), str(fol_representativo), fontsize=32, color=(0, 0, 0))
        pg.insert_text((653, 200), str(fol_representativo), fontsize=45, color=(0, 0, 0))
        incrementar_folio_representativo(fol_representativo)

        pg.insert_text((910, 620), f"*{fol}*", fontsize=30, color=(0, 0, 0), fontname="Courier")
        pg.insert_text((1083, 800), "DIGITAL", fontsize=14, color=(0, 0, 0))

        contenido_ine = f"""
FOLIO:{fol} MARCA:{d.get('marca')} LINEA:{d.get('linea')} ANIO:{d.get('anio')} SERIE:{d.get('serie')} MOTOR:{d.get('motor')}
"""
        ine_img_path = os.path.join("documentos", f"{fol}_inecode.png")
        generar_codigo_ine(contenido_ine, ine_img_path)
        pg.insert_image(fitz.Rect(937.65, 75, 1168.955, 132), filename=ine_img_path, keep_proportion=False, overlay=True)

        doc.save(out_original)
        doc.close()

        _guardar(
            fol, "Jalisco", d["serie"], d["marca"], d["linea"],
            d["motor"], d["anio"], d["color"], f_exp_iso, f_ven_iso, d["nombre"]
        )

        return render_template("exitoso.html", folio=fol, jalisco=True)

    return render_template("formulario_jalisco.html")

@app.route('/registro_admin', methods=['GET', 'POST'])
def registro_admin():
    if not session.get('admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        folio = request.form['folio']
        marca = request.form['marca']
        linea = request.form['linea']
        anio = request.form['anio']
        numero_serie = request.form['serie']
        numero_motor = request.form['motor']
        color = request.form.get('color', '')
        nombre = request.form.get('nombre', '')

        ahora = datetime.now()
        f_exp_iso = ahora.isoformat()
        f_ven_iso = (ahora + timedelta(days=30)).isoformat()

        if supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data:
            flash('Error: El folio ya existe.', 'error')
            return redirect(url_for('registro_admin'))

        supabase.table("folios_registrados").insert({
            "folio": folio,
            "marca": marca,
            "linea": linea,
            "anio": anio,
            "numero_serie": numero_serie,
            "numero_motor": numero_motor,
            "fecha_expedicion": f_exp_iso,
            "fecha_vencimiento": f_ven_iso,
            "entidad": "cdmx"
        }).execute()

        try:
            os.makedirs("documentos", exist_ok=True)
            fecha_hora_str = ahora.strftime('%d/%m/%Y %H:%M')
            fecha_exp_str = ahora.strftime('%d/%m/%Y')
            fecha_ven_str = (ahora + timedelta(days=30)).strftime('%d/%m/%Y')
            folio_visual = int(obtener_folio_representativo())

            # === RECIBO BASE ===
            doc = fitz.open("jalisco.pdf")
            page = doc[0]
            page.insert_text((380, 195), fecha_hora_str, fontsize=10, fontname="helv", color=(0, 0, 0))
            page.insert_text((328, 804), str(folio_visual), fontsize=32, color=(0, 0, 0))
            page.insert_text((653, 200), str(folio_visual), fontsize=45, color=(0, 0, 0))
            doc.save(f"documentos/{folio}.pdf")
            doc.close()

            # === PERMISO FINAL ===
            doc1 = fitz.open("jalisco1.pdf")
            page1 = doc1[0]

            datos = {
                "folio": folio,
                "marca": marca,
                "linea": linea,
                "anio": anio,
                "serie": numero_serie,
                "motor": numero_motor,
                "color": color,
                "nombre": nombre,
                "fecha_exp": fecha_exp_str,
                "fecha_exp_completa": fecha_hora_str,
                "fecha_ven": fecha_ven_str
            }

            for campo, valor in datos.items():
                if campo in coords_jalisco:
                    x, y, size, color_text = coords_jalisco[campo]
                    page1.insert_text((x, y), str(valor).upper(), fontsize=size, color=color_text)

            # Folio visual (grande)
            page1.insert_text((328, 804), str(folio_visual), fontsize=32, color=(0, 0, 0))
            page1.insert_text((653, 200), str(folio_visual), fontsize=45, color=(0, 0, 0))

            doc1.save(f"documentos/{folio}_jalisco1.pdf")
            doc1.close()

            incrementar_folio_representativo(folio_visual)

        except Exception as e:
            flash(f"Error al generar los PDFs: {e}", 'error')
            return redirect(url_for('registro_admin'))

        flash('Permiso registrado exitosamente.', 'success')
        return render_template("exitoso.html", folio=folio)

    return render_template("registro_admin.html")
    
if __name__ == '__main__':
    app.run(debug=True)
