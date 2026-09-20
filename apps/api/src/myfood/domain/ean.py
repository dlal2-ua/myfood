"""EAN-13: dígito de control, EAN interno de recetas (prefijo 20, rango de uso interno) y dibujo
del código de barras en SVG para imprimir etiquetas."""

from __future__ import annotations

import secrets

INTERNAL_PREFIX = "20"

# Codificación de cada dígito en 7 módulos (1 = barra): conjuntos L, G y R del estándar EAN-13.
_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
      "0110001", "0101111", "0111011", "0110111", "0001011"]  # fmt: skip
_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
      "0111001", "0000101", "0010001", "0001001", "0010111"]  # fmt: skip
_R = ["1110010", "1100110", "1101100", "1000010", "1011100",
      "1001110", "1010000", "1000100", "1001000", "1110100"]  # fmt: skip
# Qué conjunto (L o G) usa cada uno de los 6 dígitos de la izquierda según el primer dígito.
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
           "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]  # fmt: skip


def check_digit(first_twelve: str) -> int:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first_twelve))
    return (10 - total % 10) % 10


def is_valid_ean13(ean: str) -> bool:
    return len(ean) == 13 and ean.isdigit() and check_digit(ean[:12]) == int(ean[12])


def is_internal_ean(ean: str) -> bool:
    return is_valid_ean13(ean) and ean.startswith(INTERNAL_PREFIX)


def generate_internal_ean() -> str:
    body = INTERNAL_PREFIX + "".join(str(secrets.randbelow(10)) for _ in range(10))
    return body + str(check_digit(body))


def _modules(ean: str) -> str:
    parity = _PARITY[int(ean[0])]
    left = "".join((_L if parity[i] == "L" else _G)[int(d)] for i, d in enumerate(ean[1:7]))
    right = "".join(_R[int(d)] for d in ean[7:])
    return "101" + left + "01010" + right + "101"


def ean13_svg(ean: str, title: str = "", subtitle: str = "") -> str:
    """Etiqueta imprimible: el código de barras EAN-13 y, encima, el nombre de la receta."""
    if not is_valid_ean13(ean):
        raise ValueError("EAN-13 no válido")
    module = 2
    quiet = 11 * module
    bars = _modules(ean)
    width = quiet * 2 + len(bars) * module
    bar_top = 46 if title or subtitle else 10
    bar_height = 70
    height = bar_top + bar_height + 22
    rects = []
    for i, bit in enumerate(bars):
        if bit == "1":
            # Las barras de guarda (inicio, centro y fin) bajan un poco, como en una etiqueta real.
            guard = i < 3 or 45 <= i < 50 or i >= 92
            h = bar_height + (8 if guard else 0)
            rects.append(
                f'<rect x="{quiet + i * module}" y="{bar_top}" width="{module}" height="{h}"/>'
            )
    digits = f"{ean[0]}  {ean[1:7]}  {ean[7:]}"
    escaped_title = _escape(title)
    escaped_subtitle = _escape(subtitle)
    center = width / 2
    label = (
        f'<text x="{center}" y="20" text-anchor="middle" font-size="16" '
        f'font-weight="bold">{escaped_title}</text>'
        if title
        else ""
    )
    sub = (
        f'<text x="{center}" y="37" text-anchor="middle" font-size="12">{escaped_subtitle}</text>'
        if subtitle
        else ""
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" font-family="Arial, Helvetica, sans-serif" role="img" '
        f'aria-label="Código de barras {ean}">'
        f'<rect width="100%" height="100%" fill="#fff"/>{label}{sub}'
        f'<g fill="#000">{"".join(rects)}</g>'
        f'<text x="{width / 2}" y="{bar_top + bar_height + 18}" text-anchor="middle" '
        f'font-size="14" letter-spacing="2">{digits}</text></svg>'
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
