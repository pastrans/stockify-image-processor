"""Procesa en local una carpeta de fotos, sin AWS.

Uso: python cli.py samples out
"""
import sys
from pathlib import Path

# Permite importar el paquete desde src/ sin instalarlo
sys.path.insert(0, str(Path(__file__).parent / "src"))
from image_processor.processing import process_image

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(exist_ok=True)
for f in sorted(p for p in src.iterdir() if p.suffix.lower() in EXTENSIONES):
    (dst / f"{f.stem}.jpg").write_bytes(process_image(f.read_bytes()))
    print("ok", f.name)
