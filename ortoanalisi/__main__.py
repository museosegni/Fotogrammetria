"""Uso: python -m ortoanalisi ORTOFOTO [opzioni]"""
from __future__ import annotations

import argparse
import os
import sys

from .esporta import scrivi_controllo, scrivi_csv, scrivi_dxf
from .immagine import georef_automatica, leggi_immagine
from .rileva import Parametri, analizza


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ortoanalisi",
        description="Riconosce muro, copertura, finestre e soglie su un'ortofoto di prospetto "
                    "e li restituisce in DXF come polilinee con coordinate in mm interi.")
    ap.add_argument("ortofoto", help="immagine (TIF/JPG/PNG), meglio se con sfondo trasparente o uniforme")
    ap.add_argument("-o", "--output", help="file DXF di uscita (default: <ortofoto>_rilievo.dxf)")
    ap.add_argument("--mm-pixel", type=float, help="dimensione pixel in mm (se manca: world file / GeoTIFF)")
    ap.add_argument("--unita-world", choices=["m", "cm", "mm"], default="m",
                    help="unita' del world file/GeoTIFF (default m)")
    ap.add_argument("--passo", type=float, default=1.0, help="arrotondamento coordinate in mm (default 1)")
    ap.add_argument("--finestra-min", type=float, default=350.0, help="lato minimo apertura mm")
    ap.add_argument("--finestra-max", type=float, default=4000.0, help="lato massimo apertura mm")
    ap.add_argument("--contrasto", type=float, default=12.0,
                    help="quanto un'apertura deve essere piu' scura del muro (0-255, default 12)")
    ap.add_argument("--allinea", type=float, default=20.0,
                    help="allinea quote di aperture entro questa tolleranza mm (0 = disattiva)")
    ap.add_argument("--risoluzione-max", type=int, default=6000,
                    help="lato massimo (px) dell'immagine usata per l'analisi (default 6000)")
    ap.add_argument("--semplifica", type=float, default=30.0, help="tolleranza semplificazione contorni mm")
    ap.add_argument("--gronda-mm", type=float, help="forza il limite muro/copertura alla quota Y indicata (mm)")
    ap.add_argument("--soglie", choices=["auto", "rilevate", "nessuna"], default="auto",
                    help="auto: rilevate + stimate dove non trovate; rilevate: solo rilevate")
    ap.add_argument("--soglia-spessore", type=float, default=40.0, help="spessore soglia stimata mm")
    ap.add_argument("--soglia-sporgenza", type=float, default=30.0, help="sporgenza laterale soglia stimata mm")
    ap.add_argument("--etichette", action="store_true", help="scrive L x H delle finestre nel DXF")
    ap.add_argument("--senza-immagine", action="store_true", help="non inserisce l'ortofoto nel DXF")
    a = ap.parse_args(argv)

    bgr, alpha = leggi_immagine(a.ortofoto)
    geo = georef_automatica(a.ortofoto, bgr.shape[0], a.mm_pixel, a.unita_world)
    par = Parametri(passo_mm=a.passo, lato_max_proc_px=a.risoluzione_max, finestra_min_mm=a.finestra_min, finestra_max_mm=a.finestra_max,
                    contrasto_scuro=a.contrasto, allinea_mm=a.allinea if a.allinea > 0 else 1e-6,
                    semplifica_mm=a.semplifica, gronda_mm=a.gronda_mm, soglie=a.soglie,
                    soglia_spessore_default_mm=a.soglia_spessore,
                    soglia_sporgenza_default_mm=a.soglia_sporgenza)
    res = analizza(bgr, alpha, geo, par)

    base = os.path.splitext(a.output or (os.path.splitext(a.ortofoto)[0] + "_rilievo.dxf"))[0]
    dxf = base + ".dxf"
    scrivi_dxf(res, dxf, geo, None if a.senza_immagine else a.ortofoto,
               (bgr.shape[1], bgr.shape[0]), a.etichette)
    scrivi_csv(res, base + ".csv")
    scrivi_controllo(res, base + "_controllo.png")

    print(f"Scala: {geo.mm_px:g} mm/px ({geo.origine}) - facciata: {res.metodo_maschera}")
    print(f"Muro: {len(res.muro)}  Copertura: {len(res.copertura)}  Aperture: {len(res.finestre)}  "
          f"Soglie: {sum(not s.stimata for s in res.soglie)} rilevate, "
          f"{sum(s.stimata for s in res.soglie)} stimate")
    for i, r in enumerate(res.finestre, 1):
        print(f"  F{i}: {r.larghezza:g} x {r.altezza:g} mm  (x {r.xmin:g}, y {r.ymin:g})")
    for av in res.avvisi:
        print("ATTENZIONE:", av)
    print(f"Creati: {dxf}, {base}.csv, {base}_controllo.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
