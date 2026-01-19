import requests
import os

# Crear carpeta static si no existe
if not os.path.exists('static'):
    os.makedirs('static')
    print("📁 Carpeta 'static' creada")

urls = {
    'logotipo.svg': 'https://setran.jalisco.gob.mx/assets/images/logo_jalisco_2024_2030.svg',
    'accesibilidad.svg': 'https://setran.jalisco.gob.mx/assets/images/ico_accesibilidad.svg',
    'favicon.ico': 'https://setran.jalisco.gob.mx/assets/favicon.ico',
    'logo_meta.png': 'https://setran.jalisco.gob.mx/assets/images/logos/logo_jal_meta_2024_2030.png'
}

print("🚀 Iniciando descarga de imágenes...\n")

for filename, url in urls.items():
    print(f"📥 Descargando {filename}...")
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()  # Verifica errores HTTP
        
        with open(f'static/{filename}', 'wb') as f:
            f.write(r.content)
        
        print(f"✅ {filename} descargado correctamente")
    except Exception as e:
        print(f"❌ Error descargando {filename}: {e}")

print("\n🎉 ¡Proceso completado! Revisa tu carpeta /static/")
