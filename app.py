"""web/app.py — Instancia Flask + configuración. Las rutas viven en routes_*.py.
Sin Blueprints a propósito: así los endpoints se siguen llamando igual (url_for('login'), etc.)
y los templates existentes funcionan sin tocarse."""
import os
from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import BASE_DIR

# ===================== FLASK CONFIG =====================
# templates/ y static/ siguen en la raíz del proyecto, igual que antes
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
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

# Registrar rutas (al final para evitar import circular)
from web import routes_auth, routes_admin, routes_user, routes_public  # noqa: E402,F401
