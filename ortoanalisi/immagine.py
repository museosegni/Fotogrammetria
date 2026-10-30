"""Lettura dell'ortofoto e della sua scala/georeferenziazione."""
from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Georef:
    """Trasformazione pixel -> mm (assi allineati, nessuna rotazione).

    mm_px : dimensione del pixel in mm
    x0    : X (mm) del bordo sinistro dell'immagine
    y0    : Y (mm) del bordo superiore dell'immagine
    """
    mm_px: float
    x0: float = 0.0
    y0: float = 0.0
    origine: str = "manuale"


def leggi_immagine(percorso: str):
    """Restituisce (bgr uint8, alpha uint8 | None). Supporta 8/16 bit e percorsi non ASCII."""
    dati = np.fromfile(percorso, dtype=np.uint8)
    img = cv2.imdecode(dati, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Impossibile leggere l'immagine: {percorso}")
    if img.dtype == np.uint16:
        img = (img / 257.0).round().astype(np.uint8)
    elif img.dtype != np.uint8:
        f = img.astype(np.float64)
        f = (f - np.nanmin(f)) / max(np.nanmax(f) - np.nanmin(f), 1e-9) * 255.0
        img = np.nan_to_num(f).astype(np.uint8)
    alpha = None
    if img.ndim == 2:
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        alpha = img[:, :, 3].copy()
        bgr = np.ascontiguousarray(img[:, :, :3])
    elif img.shape[2] == 2:  # grigio + alpha
        alpha = img[:, :, 1].copy()
        bgr = cv2.cvtColor(np.ascontiguousarray(img[:, :, 0]), cv2.COLOR_GRAY2BGR)
    else:
        bgr = np.ascontiguousarray(img[:, :, :3])
    return bgr, alpha


_EST_WORLD = {
    ".tif": [".tfw", ".tifw", ".tfwx"], ".tiff": [".tfw", ".tiffw", ".tifw"],
    ".jpg": [".jgw", ".jpgw"], ".jpeg": [".jgw", ".jpegw"],
    ".png": [".pgw", ".pngw"], ".bmp": [".bpw", ".bmpw"],
}


def trova_worldfile(percorso: str) -> str | None:
    base, est = os.path.splitext(percorso)
    candidati = [base + e for e in _EST_WORLD.get(est.lower(), [])] + [base + ".wld", percorso + "w"]
    for c in candidati:
        for v in (c, c.upper(), base + os.path.splitext(c)[1].upper()):
            if os.path.isfile(v):
                return v
    return None


def georef_da_worldfile(percorso_wf: str, fattore_mm: float) -> Georef:
    with open(percorso_wf, encoding="utf-8", errors="ignore") as fh:
        v = [float(r.strip().replace(",", ".")) for r in fh if r.strip()][:6]
    a, d, b, e, c, f = v
    if abs(b) > 1e-12 or abs(d) > 1e-12:
        raise ValueError("World file con rotazione: non supportato (ruotare l'ortofoto sul piano di facciata).")
    if abs(abs(a) - abs(e)) > 1e-6 * abs(a):
        raise ValueError("Pixel non quadrati nel world file: non supportato.")
    # c, f = centro del pixel in alto a sinistra
    return Georef(mm_px=abs(a) * fattore_mm,
                  x0=(c - a / 2.0) * fattore_mm,
                  y0=(f - e / 2.0) * fattore_mm,
                  origine=f"world file {os.path.basename(percorso_wf)}")


def georef_da_geotiff(percorso: str, fattore_mm: float) -> Georef | None:
    try:
        import tifffile  # opzionale
    except ImportError:
        return None
    try:
        with tifffile.TiffFile(percorso) as t:
            tags = t.pages[0].tags
            scala = tags.get(33550)
            tie = tags.get(33922)
            if scala is None or tie is None:
                return None
            sx, sy = scala.value[0], scala.value[1]
            i, j, _, x, y, _ = tie.value[:6]
    except Exception:
        return None
    if abs(sx - sy) > 1e-6 * sx:
        return None
    # tie point: pixel (i, j) (angolo) -> (x, y)
    return Georef(mm_px=sx * fattore_mm,
                  x0=(x - i * sx) * fattore_mm,
                  y0=(y + j * sy) * fattore_mm,
                  origine="GeoTIFF")


def georef_automatica(percorso: str, altezza_px: int, mm_pixel: float | None,
                      unita_world: str = "m") -> Georef:
    """Ordine: --mm-pixel esplicito > world file > GeoTIFF."""
    fattore = {"m": 1000.0, "cm": 10.0, "mm": 1.0}[unita_world]
    if mm_pixel:
        return Georef(mm_px=float(mm_pixel), x0=0.0, y0=altezza_px * float(mm_pixel),
                      origine="--mm-pixel (origine in basso a sinistra)")
    wf = trova_worldfile(percorso)
    if wf:
        return georef_da_worldfile(wf, fattore)
    g = georef_da_geotiff(percorso, fattore)
    if g:
        return g
    raise ValueError("Scala sconosciuta: indicare --mm-pixel oppure fornire un world file (.tfw/.jgw/.pgw).")
