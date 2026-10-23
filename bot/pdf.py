"""bot/pdf.py — QR, PDF417 y generación del PDF unificado (2 páginas) del bot."""
import os
from io import BytesIO

import fitz
import qrcode
from PIL import Image

from config import (
    OUTPUT_DIR, PLANTILLA_PDF, PLANTILLA_BUENO, URL_CONSULTA_BASE,
    PRECIO_FIJO_PAGINA2, coords_jalisco, coords_pagina2, coords_qr_dinamico,
)
from bot.folios import (
    generar_folios_pagina2, obtener_folio_representativo, incrementar_folio_representativo,
)

try:
    import pdf417gen
    PDF417_DISPONIBLE = True
    print("[PDF417] pdf417gen disponible ✅")
except ImportError:
    PDF417_DISPONIBLE = False
    print("[PDF417] pdf417gen NO disponible, usando QR fallback")

RECT_PDF417 = fitz.Rect(932.65, 807, 1141.395, 852.127)

PDF417_W = 840
PDF417_H = 120

_plantilla1_bytes: bytes | None = None
_plantilla2_bytes: bytes | None = None

def _cargar_plantillas():
    global _plantilla1_bytes, _plantilla2_bytes
    with open(PLANTILLA_PDF, "rb") as f:
        _plantilla1_bytes = f.read()
    with open(PLANTILLA_BUENO, "rb") as f:
        _plantilla2_bytes = f.read()
    print("[PLANTILLAS] Cargadas en memoria ✅")

# ============ QR ============================================================

def _generar_qr_jalisco(folio: str):
    try:
        url = f"{URL_CONSULTA_BASE}/consulta_folio/{folio}"
        qr  = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=4, border=1)
        qr.add_data(url); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color=(220,220,220)).convert("RGB")
        print(f"[QR] Generado: {url}")
        return img
    except Exception as e:
        print(f"[ERROR QR] {e}")
        return None

# ============ PDF417 =========================================================

def _generar_pdf417(datos: dict) -> Image.Image | None:
    url_consulta = f"{URL_CONSULTA_BASE}/consulta_folio/{datos['folio']}"
    texto = (
        f"MARCA  {datos['marca']}  LINEA  {datos['linea']}  ANO  {datos['anio']}  "
        f"SERIE  {datos['serie']}  MOTOR  {datos['motor']}  COLOR  {datos['color']}  "
        f"TITULAR  {datos['nombre']}  FOLIO  {datos['folio']}  {url_consulta}"
    )
    if PDF417_DISPONIBLE:
        try:
            codes = pdf417gen.encode(texto, columns=10, security_level=2)
            img   = pdf417gen.render_image(codes, scale=2, ratio=3).convert("RGB")
            px    = img.load()
            out   = Image.new("RGB", img.size, (220, 220, 220))
            ox    = out.load()
            for y in range(img.height):
                for x in range(img.width):
                    p = px[x, y]
                    if (sum(p[:3]) if isinstance(p, tuple) else p) < 384:
                        ox[x, y] = (0, 0, 0)
            img_final = out.resize((PDF417_W, PDF417_H), Image.LANCZOS)
            print(f"[PDF417] Generado {PDF417_W}x{PDF417_H}px ✅")
            return img_final
        except Exception as e:
            print(f"[ERROR PDF417] {e} — usando QR fallback")
    try:
        qr = qrcode.QRCode(version=4, error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=2, border=1)
        qr.add_data(texto); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        img = img.resize((PDF417_W, PDF417_H), Image.NEAREST)
        print(f"[QR FALLBACK] Generado {PDF417_W}x{PDF417_H}px")
        return img
    except Exception as e:
        print(f"[ERROR QR FALLBACK] {e}")
        return None

# ============ GENERACIÓN PDF ==================================================

def _generar_pdf_unificado(datos: dict) -> str:
    fol        = datos["folio"]
    fecha_exp  = datos["fecha_exp"]
    fecha_ven  = datos["fecha_ven"]
    ahora_cdmx = fecha_exp
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, f"{fol}_completo.pdf")
    try:
        doc1 = fitz.open(stream=_plantilla1_bytes, filetype="pdf")
        pg1  = doc1[0]
        for campo in ["marca", "linea", "anio", "serie", "nombre", "color"]:
            if campo in coords_jalisco and campo in datos:
                x, y, s, col = coords_jalisco[campo]
                pg1.insert_text((x, y), datos[campo], fontsize=s, color=col, fontname="hebo")
        pg1.insert_text(coords_jalisco["fecha_ven"][:2], fecha_ven.strftime("%d/%m/%Y"),
                        fontsize=coords_jalisco["fecha_ven"][2], color=coords_jalisco["fecha_ven"][3])
        pg1.insert_text((860, 364), fol, fontsize=14, color=(0,0,0), fontname="hebo")
        pg1.insert_text((475, 830), fecha_exp.strftime("%d/%m/%Y"),
                        fontsize=32, color=(0,0,0), fontname="hebo")
        fol_rep      = obtener_folio_representativo()
        folio_grande = f"4A-DVM/{fol_rep}"
        pg1.insert_text((240, 830), folio_grande, fontsize=32, color=(0,0,0), fontname="hebo")
        pg1.insert_text((480, 182), folio_grande, fontsize=63, color=(0,0,0), fontname="hebo")
        folio_chico = (f"DVM-{fol_rep}   {ahora_cdmx.strftime('%d/%m/%Y')}  "
                       f"{ahora_cdmx.strftime('%H:%M:%S')}")
        pg1.insert_text((915, 760), folio_chico, fontsize=14, color=(0,0,0), fontname="hebo")
        incrementar_folio_representativo(fol_rep)
        pg1.insert_text((935, 600), f"*{fol}*", fontsize=30, color=(0,0,0), fontname="Courier")
        pg1.insert_text((915, 775), "EXPEDICION: VENTANILLA 32",
                        fontsize=12, color=(0,0,0), fontname="hebo")
        img_qr = _generar_qr_jalisco(fol)
        if img_qr:
            buf = BytesIO(); img_qr.save(buf, format="PNG"); buf.seek(0)
            pg1.insert_image(
                fitz.Rect(coords_qr_dinamico["x"], coords_qr_dinamico["y"],
                          coords_qr_dinamico["x"]+coords_qr_dinamico["ancho"],
                          coords_qr_dinamico["y"]+coords_qr_dinamico["alto"]),
                pixmap=fitz.Pixmap(buf.read()), overlay=True)
            print("[QR] Insertado ✅")
        img_pdf417 = _generar_pdf417(datos)
        if img_pdf417:
            buf2 = BytesIO(); img_pdf417.save(buf2, format="PNG"); buf2.seek(0)
            pg1.insert_image(RECT_PDF417, pixmap=fitz.Pixmap(buf2.read()),
                             keep_proportion=False, overlay=True)
            print("[PDF417] Insertado ✅")
        doc2 = fitz.open(stream=_plantilla2_bytes, filetype="pdf")
        pg2  = doc2[0]
        pg2.insert_text((380, 195), fecha_exp.strftime("%d/%m/%Y %H:%M"),
                        fontsize=10, fontname="helv", color=(0,0,0))
        pg2.insert_text((380, 290), datos["serie"],
                        fontsize=10, fontname="helv", color=(0,0,0))
        fp2 = generar_folios_pagina2()
        pg2.insert_text(coords_pagina2["referencia_pago"][:2],   str(fp2["referencia_pago"]),     fontsize=coords_pagina2["referencia_pago"][2],   color=coords_pagina2["referencia_pago"][3])
        pg2.insert_text(coords_pagina2["num_autorizacion"][:2],  str(fp2["num_autorizacion"]),    fontsize=coords_pagina2["num_autorizacion"][2],  color=coords_pagina2["num_autorizacion"][3])
        pg2.insert_text(coords_pagina2["total_pagado"][:2],      f"${PRECIO_FIJO_PAGINA2}.00 MN", fontsize=coords_pagina2["total_pagado"][2],      color=coords_pagina2["total_pagado"][3])
        pg2.insert_text(coords_pagina2["folio_seguimiento"][:2], fp2["folio_seguimiento"],        fontsize=coords_pagina2["folio_seguimiento"][2], color=coords_pagina2["folio_seguimiento"][3])
        pg2.insert_text(coords_pagina2["linea_captura"][:2],     str(fp2["linea_captura"]),       fontsize=coords_pagina2["linea_captura"][2],     color=coords_pagina2["linea_captura"][3])
        doc_final = fitz.open()
        doc_final.insert_pdf(doc1); doc_final.insert_pdf(doc2)
        doc_final.save(out)
        doc_final.close(); doc1.close(); doc2.close()
        print(f"[PDF UNIFICADO] ✅ {out}")
    except Exception as e:
        print(f"[ERROR] Generando PDF: {e}")
        doc_fb = fitz.open()
        doc_fb.new_page().insert_text((50, 50), f"ERROR - Folio: {fol}", fontsize=12)
        doc_fb.save(out); doc_fb.close()
    return out
