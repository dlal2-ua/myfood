"""Genera el logo, la portada y todos los iconos de MyFood (PWA, favicon, Android) a partir del
logo original `docs/brand/myfood-logo-original.jpg`.

    apps/api/.venv/bin/python scripts/build_brand_assets.py        # o: uv run --project apps/api python ...

El original es un dibujo de trazo sobre fondo blanco: se recorta a su caja y lo casi blanco se hace
transparente (los colores del trazo no se tocan). Todos los iconos llevan fondo blanco y el dibujo
centrado; los «maskable» y los de Android dejan margen para que ninguna máscara (círculo,
cuadrado redondeado) lo recorte.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "brand" / "myfood-logo-original.jpg"
WEB_PUBLIC = ROOT / "apps" / "web" / "public"
ANDROID_RES = ROOT / "apps" / "mobile" / "android" / "app" / "src" / "main" / "res"

WHITE = (255, 255, 255, 255)

# Densidades de Android: (carpeta, lado del icono en px, lado del icono adaptativo en px).
LAUNCHER = {
    "mdpi": (48, 108),
    "hdpi": (72, 162),
    "xhdpi": (96, 216),
    "xxhdpi": (144, 324),
    "xxxhdpi": (192, 432),
}
SPLASH = {
    "drawable": (480, 320),
    "drawable-port-mdpi": (320, 480),
    "drawable-port-hdpi": (480, 800),
    "drawable-port-xhdpi": (720, 1280),
    "drawable-port-xxhdpi": (960, 1600),
    "drawable-port-xxxhdpi": (1280, 1920),
    "drawable-land-mdpi": (480, 320),
    "drawable-land-hdpi": (800, 480),
    "drawable-land-xhdpi": (1280, 720),
    "drawable-land-xxhdpi": (1600, 960),
    "drawable-land-xxxhdpi": (1920, 1280),
}


def load_mark() -> Image.Image:
    """El dibujo recortado a su caja, con lo casi blanco transparente."""
    rgb = Image.open(SOURCE).convert("RGB")
    ink = ImageChops.invert(rgb.convert("L")).point(lambda v: 255 if v > 20 else 0)
    box = ink.getbbox()
    if box is None:
        raise SystemExit("El logo original no tiene dibujo.")
    rgb = rgb.crop(box)
    r, g, b = (ImageChops.invert(channel) for channel in rgb.split())
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)  # 0 = blanco puro
    alpha = distance.point(lambda v: 0 if v < 6 else min(255, (v - 6) * 255 // 34))
    mark = rgb.convert("RGBA")
    mark.putalpha(alpha)
    return mark


def fit_width(mark: Image.Image, width: int) -> Image.Image:
    return mark.resize((width, round(width * mark.height / mark.width)), Image.LANCZOS)


def square(mark: Image.Image, side: int, ratio: float, background=WHITE, shape: str = "square") -> Image.Image:
    """Lienzo cuadrado con el dibujo centrado (ocupa `ratio` del lado). `shape`: square, rounded o
    circle (lo de fuera de la forma queda transparente)."""
    canvas = Image.new("RGBA", (side, side), background if background else (0, 0, 0, 0))
    small = fit_width(mark, round(side * ratio))
    canvas.alpha_composite(small, ((side - small.width) // 2, (side - small.height) // 2))
    if shape != "square":
        mask = Image.new("L", (side * 4, side * 4), 0)
        draw = ImageDraw.Draw(mask)
        if shape == "circle":
            draw.ellipse((0, 0, side * 4 - 1, side * 4 - 1), fill=255)
        else:
            draw.rounded_rectangle((0, 0, side * 4 - 1, side * 4 - 1), radius=side * 4 * 22 // 100, fill=255)
        canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), mask.resize((side, side), Image.LANCZOS)))
    return canvas


def silhouette(mark: Image.Image, side: int) -> Image.Image:
    """Silueta blanca sobre transparente: es lo que Android espera en el icono de las notificaciones."""
    small = square(mark, side, 0.86, background=None)
    white = Image.new("RGBA", small.size, (255, 255, 255, 0))
    white.putalpha(small.getchannel("A"))
    return white


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    print("  ", path.relative_to(ROOT))


def main() -> None:
    mark = load_mark()
    print(f"Dibujo recortado: {mark.width}x{mark.height}")

    print("Web:")
    save(fit_width(mark, 256), WEB_PUBLIC / "brand" / "logo-mark.png")
    save(fit_width(mark, 1200), WEB_PUBLIC / "brand" / "logo-cover.png")
    save(square(mark, 192, 0.82), WEB_PUBLIC / "icon-192.png")
    save(square(mark, 512, 0.82), WEB_PUBLIC / "icon-512.png")
    save(square(mark, 512, 0.58), WEB_PUBLIC / "icon-maskable-512.png")
    save(square(mark, 180, 0.80), WEB_PUBLIC / "apple-icon.png")
    save(silhouette(mark, 96), WEB_PUBLIC / "badge-96.png")
    favicon = [square(mark, s, 0.94) for s in (48, 32, 16)]
    (WEB_PUBLIC / "favicon.ico").parent.mkdir(parents=True, exist_ok=True)
    favicon[0].save(WEB_PUBLIC / "favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)], append_images=favicon[1:])
    print("  ", (WEB_PUBLIC / "favicon.ico").relative_to(ROOT))

    print("Android:")
    for density, (side, adaptive) in LAUNCHER.items():
        folder = ANDROID_RES / f"mipmap-{density}"
        save(square(mark, side, 0.80, shape="rounded"), folder / "ic_launcher.png")
        save(square(mark, side, 0.66, shape="circle"), folder / "ic_launcher_round.png")
        save(square(mark, adaptive, 0.54, background=None), folder / "ic_launcher_foreground.png")
    for folder, (width, height) in SPLASH.items():
        canvas = Image.new("RGBA", (width, height), WHITE)
        small = fit_width(mark, round(min(width, height) * 0.40))
        canvas.alpha_composite(small, ((width - small.width) // 2, (height - small.height) // 2))
        save(canvas.convert("RGB"), ANDROID_RES / folder / "splash.png")


if __name__ == "__main__":
    main()
