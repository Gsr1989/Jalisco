"""web/routes_admin.py — Panel admin: usuarios, registro admin, gestión de folios y pagos."""
import re
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session

from config import supabase
from web.app import app
from web.utils import logger, TZ_CDMX, now_cdmx, today_cdmx, parse_date_any
from web.folios import guardar_folio_con_reintento, get_timer_info
from web.pdf import generar_pdf_unificado


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


@app.route('/admin_folios')
def admin_folios():
    if not session.get('admin'):
        return redirect(url_for('login'))

    folios = supabase.table("folios_registrados")\
        .select("*")\
        .order("fecha_expedicion", desc=True)\
        .execute().data or []

    hoy = today_cdmx()
    for f in folios:
        try:
            fv = parse_date_any(f.get('fecha_vencimiento'))
            f['estado'] = "VIGENTE" if hoy <= fv else "VENCIDO"
        except:
            f['estado'] = 'ERROR'

    return render_template('admin_folios.html', folios=folios)


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
    if not session.get('admin'):
        return redirect(url_for('login'))
    folio = request.form['folio']
    supabase.table("folios_registrados").delete().eq("folio",folio).execute()
    flash("Folio eliminado.","success")
    return redirect(url_for('admin_folios'))


@app.route('/eliminar_folios_masivo', methods=['POST'])
def eliminar_folios_masivo():
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
        flash(f"✅ {eliminados} folio(s) eliminado(s).", "success")
    if errores:
        flash(f"⚠️ {errores} folio(s) no pudieron eliminarse.", "error")

    return redirect(url_for('admin_folios'))


# ── Gestión de usuarios ───────────────────────────────────────────────────────

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
