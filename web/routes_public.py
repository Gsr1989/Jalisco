"""web/routes_public.py — Consulta pública de folios (QR) y descarga de PDF."""
import os

from flask import render_template, request, redirect, url_for, flash, session, send_file

from config import supabase, OUTPUT_DIR, ENTIDAD
from web.app import app
from web.utils import today_cdmx, parse_date_any
from web.pdf import generar_pdf_unificado


# ─── CONSULTA PÚBLICA ────────────────────────────────────────────────────────

@app.route('/consulta_folio', methods=['GET','POST'])
def consulta_folio():
    resultado = None
    if request.method == 'POST':
        folio     = request.form['folio'].strip()
        registros = supabase.table("folios_registrados")\
            .select("*").eq("folio",folio).limit(1).execute().data

        if not registros:
            resultado = {"estado":"NO SE ENCUENTRA REGISTRADO","color":"rojo","folio":folio}
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


# ── Resultado directo desde QR (/consulta_folio/980000235) ────────────────────
@app.route('/consulta_folio/<folio>')
def consulta_folio_directo_path(folio):
    """
    Ruta que usa el QR del bot.
    Escanear el QR lleva directo aquí sin que el usuario tenga que teclear nada.
    """
    row = supabase.table("folios_registrados")\
        .select("*").eq("folio", folio).limit(1).execute().data

    if not row:
        return render_template("resultado_consulta.html", resultado={
            "estado": "NO SE ENCUENTRA REGISTRADO",
            "color":  "rojo",
            "folio":  folio
        })

    r      = row[0]
    fe     = parse_date_any(r.get('fecha_expedicion'))
    fv     = parse_date_any(r.get('fecha_vencimiento'))
    hoy    = today_cdmx()
    estado = "VIGENTE" if hoy <= fv else "VENCIDO"

    return render_template("resultado_consulta.html", resultado={
        "estado":           estado,
        "color":            "verde" if estado == "VIGENTE" else "cafe",
        "folio":            folio,
        "fecha_expedicion": fe.strftime("%d/%m/%Y"),
        "fecha_vencimiento":fv.strftime("%d/%m/%Y"),
        "marca":            r.get('marca',''),
        "linea":            r.get('linea',''),
        "año":              r.get('anio',''),
        "numero_serie":     r.get('numero_serie',''),
        "numero_motor":     r.get('numero_motor',''),
        "entidad":          r.get('entidad', ENTIDAD)
    })


@app.route('/consulta/<folio>')
def consulta_folio_directo(folio):
    row = supabase.table("folios_registrados")\
        .select("*").eq("folio",folio).limit(1).execute().data

    if not row:
        return render_template("resultado_consulta.html",
                               resultado={"estado":"NO SE ENCUENTRA REGISTRADO",
                                          "color":"rojo","folio":folio})

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

    resp = supabase.table("folios_registrados")\
        .select("*").eq("folio",folio).limit(1).execute()
    registro = resp.data[0] if resp.data else None

    if not session.get('admin'):
        if registro and registro.get("creado_por") != session['username']:
            flash("No tienes permiso para descargar este archivo.","error")
            return redirect(url_for('mis_permisos'))

    ruta_pdf = os.path.join(OUTPUT_DIR, f"{folio}.pdf")

    if not os.path.exists(ruta_pdf):
        # 1) PDF generado por el bot
        ruta_bot = os.path.join(OUTPUT_DIR, f"{folio}_completo.pdf")
        if os.path.exists(ruta_bot):
            ruta_pdf = ruta_bot
        # 2) Se borró en un deploy: se vuelve a generar con los datos de Supabase
        elif registro:
            try:
                datos = {
                    "folio":     folio,
                    "marca":     registro.get("marca",""),
                    "linea":     registro.get("linea",""),
                    "anio":      registro.get("anio",""),
                    "serie":     registro.get("numero_serie",""),
                    "motor":     registro.get("numero_motor",""),
                    "color":     registro.get("color") or "BLANCO",
                    "nombre":    registro.get("nombre") or "SIN NOMBRE",
                    "fecha_exp": parse_date_any(registro.get("fecha_expedicion")),
                    "fecha_ven": parse_date_any(registro.get("fecha_vencimiento")),
                }
                generar_pdf_unificado(datos)
            except Exception as e:
                print(f"[ERROR] Regenerando PDF {folio}: {e}")

    if not os.path.exists(ruta_pdf):
        flash("PDF no encontrado.","error")
        return redirect(url_for('mis_permisos') if not session.get('admin') else url_for('admin_folios'))

    return send_file(ruta_pdf,
                     as_attachment=True,
                     download_name=f"{folio}_jalisco.pdf",
                     mimetype='application/pdf')
