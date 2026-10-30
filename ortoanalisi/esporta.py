"""Scrittura DXF (solo LWPOLYLINE, unita' mm), report CSV e immagine di controllo."""
from __future__ import annotations

import csv
import os

import cv2
import ezdxf
from ezdxf import units

from .immagine import Georef
from .rileva import Risultato

LAYER = {
    "MURO": ("ORTO_MURO", 7),
    "COPERTURA": ("ORTO_COPERTURA", 1),
    "FINESTRA": ("ORTO_FINESTRA", 4),
    "SOGLIA": ("ORTO_SOGLIA", 3),
    "SOGLIA_STIMATA": ("ORTO_SOGLIA_STIMATA", 30),
    "TESTI": ("ORTO_TESTI", 8),
    "IMMAGINE": ("ORTO_IMMAGINE", 9),
}


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def scrivi_dxf(res: Risultato, percorso_dxf: str, geo: Georef, percorso_img: str | None = None,
               dim_img_px: tuple[int, int] | None = None, etichette: bool = False,
               altezza_testo: float = 80.0):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for nome, colore in LAYER.values():
        if nome not in doc.layers:
            doc.layers.add(nome, color=colore)
    msp = doc.modelspace()

    # ortofoto come riferimento esterno (sotto a tutto)
    if percorso_img and dim_img_px:
        w, h = dim_img_px
        rel = os.path.relpath(os.path.abspath(percorso_img), os.path.dirname(os.path.abspath(percorso_dxf)))
        idef = doc.add_image_def(filename=rel, size_in_pixel=(w, h))
        msp.add_image(idef, insert=(geo.x0, geo.y0 - h * geo.mm_px),
                      size_in_units=(w * geo.mm_px, h * geo.mm_px), rotation=0,
                      dxfattribs={"layer": LAYER["IMMAGINE"][0]})

    def pl(punti, chiave):
        msp.add_lwpolyline(punti, format="xy", close=True, dxfattribs={"layer": LAYER[chiave][0]})

    for P in res.muro:
        pl(P, "MURO")
    for P in res.copertura:
        pl(P, "COPERTURA")
    for i, r in enumerate(res.finestre, 1):
        pl(r.vertici(), "FINESTRA")
        if etichette:
            msp.add_text(f"F{i} {_fmt(r.larghezza)}x{_fmt(r.altezza)}", height=altezza_testo,
                         dxfattribs={"layer": LAYER["TESTI"][0]}).set_placement(
                ((r.xmin + r.xmax) / 2, (r.ymin + r.ymax) / 2),
                align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    for s in res.soglie:
        pl(s.rett.vertici(), "SOGLIA_STIMATA" if s.stimata else "SOGLIA")
    doc.saveas(percorso_dxf)


def scrivi_csv(res: Risultato, percorso_csv: str):
    with open(percorso_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["tipo", "id", "x_min", "y_min", "x_max", "y_max", "larghezza_mm", "altezza_mm", "note"])
        for i, r in enumerate(res.finestre, 1):
            w.writerow(["finestra", f"F{i}", _fmt(r.xmin), _fmt(r.ymin), _fmt(r.xmax), _fmt(r.ymax),
                        _fmt(r.larghezza), _fmt(r.altezza), ""])
        for s in res.soglie:
            r = s.rett
            w.writerow(["soglia", f"S{s.finestra + 1}", _fmt(r.xmin), _fmt(r.ymin), _fmt(r.xmax),
                        _fmt(r.ymax), _fmt(r.larghezza), _fmt(r.altezza),
                        "stimata (default)" if s.stimata else "rilevata"])
        for tipo, lista in (("muro", res.muro), ("copertura", res.copertura)):
            for i, P in enumerate(lista, 1):
                xs, ys = [p[0] for p in P], [p[1] for p in P]
                w.writerow([tipo, f"{tipo[0].upper()}{i}", _fmt(min(xs)), _fmt(min(ys)), _fmt(max(xs)),
                            _fmt(max(ys)), _fmt(max(xs) - min(xs)), _fmt(max(ys) - min(ys)),
                            f"{len(P)} vertici"])


def scrivi_controllo(res: Risultato, percorso_png: str):
    if res.controllo is not None:
        ok, buf = cv2.imencode(".png", res.controllo)
        if ok:
            buf.tofile(percorso_png)
