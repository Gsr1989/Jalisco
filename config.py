"""
config.py — Constantes y cliente Supabase compartidos por el bot (FastAPI/aiogram)
y por la web (Flask). Una sola Supabase para todo.
"""
import os
import pytz
from supabase import create_client, Client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------ SUPABASE (misma DB para bot + web) ------------
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------ BOT ------------
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
BASE_URL       = os.getenv("BASE_URL", "").rstrip("/")
PRECIO_PERMISO = 250
ZONA_MEXICO    = pytz.timezone("America/Mexico_City")

# ------------ ARCHIVOS / PLANTILLAS ------------
OUTPUT_DIR        = "documentos"
PLANTILLA_PDF     = "jalisco1.pdf"
PLANTILLA_BUENO   = "jalisco.pdf"
URL_CONSULTA_BASE = "https://https-setran-jalisco-gob-mx-inicio.onrender.com"
ENTIDAD           = "jalisco"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("static/pdfs", exist_ok=True)

# ------------ COORDENADAS PDF (idénticas en bot y web) ------------
PRECIO_FIJO_PAGINA2 = 1080

coords_jalisco = {
    "marca":     (340, 332, 14, (0,0,0)),
    "serie":     (920, 332, 14, (0,0,0)),
    "linea":     (340, 360, 14, (0,0,0)),
    "anio":      (340, 389, 14, (0,0,0)),
    "color":     (340, 418, 14, (0,0,0)),
    "nombre":    (340, 304, 14, (0,0,0)),
    "fecha_ven": (285, 570, 90, (0,0,0)),
}

coords_pagina2 = {
    "referencia_pago":   (380, 123, 10, (0,0,0)),
    "num_autorizacion":  (380, 147, 10, (0,0,0)),
    "total_pagado":      (380, 170, 10, (0,0,0)),
    "folio_seguimiento": (380, 243, 10, (0,0,0)),
    "linea_captura":     (380, 265, 10, (0,0,0)),
}

coords_qr_dinamico = {"x": 966, "y": 603, "ancho": 140, "alto": 140}
