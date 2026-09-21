import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const PUBLIC = join(__dirname, "..", "public");

function pngSize(path: string): [number, number] {
  const buf = readFileSync(path);
  expect(buf.subarray(1, 4).toString("ascii")).toBe("PNG");
  return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
}

describe("marca: manifiesto e iconos", () => {
  const manifest = JSON.parse(readFileSync(join(PUBLIC, "manifest.json"), "utf-8")) as {
    icons: { src: string; sizes: string; purpose?: string }[];
    background_color: string;
  };

  it("cada icono del manifiesto existe y mide lo que declara", () => {
    expect(manifest.icons.length).toBeGreaterThanOrEqual(3);
    for (const icon of manifest.icons) {
      const [w, h] = icon.sizes.split("x").map(Number);
      expect(pngSize(join(PUBLIC, icon.src))).toEqual([w, h]);
    }
  });

  it("hay un icono «maskable» (con margen de seguridad) además de los normales", () => {
    const purposes = manifest.icons.map((i) => i.purpose);
    expect(purposes).toContain("any");
    expect(purposes).toContain("maskable");
  });

  it("el fondo de arranque es blanco, como el de los iconos", () => {
    expect(manifest.background_color.toLowerCase()).toBe("#ffffff");
  });

  it("existen el icono de Apple, el de avisos, el favicon y las imágenes de marca de la web", () => {
    expect(pngSize(join(PUBLIC, "apple-icon.png"))).toEqual([180, 180]);
    expect(pngSize(join(PUBLIC, "badge-96.png"))).toEqual([96, 96]);
    expect(existsSync(join(PUBLIC, "favicon.ico"))).toBe(true);
    expect(pngSize(join(PUBLIC, "brand", "logo-mark.png"))[0]).toBe(256);
    expect(pngSize(join(PUBLIC, "brand", "logo-cover.png"))[0]).toBe(1200);
  });

  it("el service worker guarda en caché el logo y usa el icono de avisos monocromo", () => {
    const sw = readFileSync(join(PUBLIC, "sw.js"), "utf-8");
    expect(sw).toContain("/brand/logo-mark.png");
    expect(sw).toContain('badge: "/badge-96.png"');
    for (const asset of ["/icon-192.png", "/icon-512.png"]) expect(existsSync(join(PUBLIC, asset))).toBe(true);
  });
});
