"""web/pdf.py — QR, código PDF417 y generación del PDF unificado (versión web)."""
import os
from io import BytesIO
from datetime import date, datetime

import fitz
import qrcode
import pdf417gen
from PIL import Image

from config import (
    OUTPUT_DIR, PLANTILLA_PDF, PLANTILLA_BUENO, URL_CONSULTA_BASE,
    PRECIO_FIJO_PAGINA2, coords_jalisco, coords_pagina2, coords_qr_dinamico,
)
from web.utils import logger, TZ_CDMX, now_cdmx
from web.folios import generar_folios_pagina2, obtener_folio_representativo

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
