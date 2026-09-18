"""OCR de tickets de compra (Fase 7, `docs`/documento 1: "Escaneo de
tickets de compra (OCR) — para dar de alta la despensa rápidamente sin
teclear"). Reconocimiento óptico clásico (Tesseract) — no es un modelo de
razonamiento (R2): igual que Whisper con la voz, no decide nada, solo
convierte una imagen en texto plano. Interpretar qué línea es qué alimento
lo hace después el mismo resolutor de Smart Log/importación de recetas
(`ai/flows/food_resolution.py`), ahí sí con iafood, solo como parser de
texto (nunca calcula nutrientes ni precios)."""

import io

import pytesseract
from PIL import Image

_MAX_LINES = 60


def extract_lines(image_bytes: bytes) -> list[str]:
    """Devuelve las líneas de texto no vacías reconocidas en la imagen, en
    el orden en que Tesseract las encuentra (de arriba a abajo del
    ticket)."""
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("L")  # escala de grises: mejora el OCR en fotos de móvil con sombras
    raw_text = pytesseract.image_to_string(image, lang="spa")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return lines[:_MAX_LINES]
