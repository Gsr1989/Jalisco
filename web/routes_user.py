"""web/routes_user.py — Zona de usuarios (terceros): API del timer, registro de permisos y mis permisos."""
import os
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session, jsonify

from config import supabase, OUTPUT_DIR
from web.app import app
from web.utils import TZ_CDMX, now_cdmx, today_cdmx, parse_date_any
from web.folios import guardar_folio_con_reintento, get_timer_info
from web.pdf import generar_pdf_unificado


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
