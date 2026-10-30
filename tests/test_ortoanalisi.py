import os
import sys

import ezdxf
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from sintetica import facciata_gronda, facciata_timpano  # noqa: E402

from ortoanalisi.__main__ import main  # noqa: E402
from ortoanalisi.immagine import Georef, georef_da_worldfile  # noqa: E402
from ortoanalisi.rileva import Parametri, analizza, arrotonda  # noqa: E402

TOL = 15.0  # mm


def _verifica_finestre(res, verita):
    assert len(res.finestre) == len(verita)
    for x1, y1, x2, y2 in verita:
        r = min(res.finestre, key=lambda r: abs(r.xmin - x1) + abs(r.ymin - y1))
        assert abs(r.xmin - x1) <= TOL and abs(r.xmax - x2) <= TOL
        assert abs(r.ymin - y1) <= TOL and abs(r.ymax - y2) <= TOL


@pytest.mark.parametrize("crea", [facciata_gronda, facciata_timpano])
def test_riconoscimento(crea):
    f = crea()
    geo = Georef(mm_px=f.mm_px, x0=0.0, y0=f.H_mm)
    res = analizza(f.img, f.alpha, geo, Parametri())
    _verifica_finestre(res, f.verita["finestre"])
    assert len(res.muro) == 1 and len(res.copertura) >= 1
    rilevate = [s for s in res.soglie if not s.stimata]
    assert len(rilevate) == len(f.verita["soglie"])
    # tutte le coordinate sono mm interi
    for P in res.muro + res.copertura + [r.vertici() for r in res.finestre]:
        for x, y in P:
            assert float(x).is_integer() and float(y).is_integer()


def test_gronda_e_muro():
    f = facciata_gronda()
    res = analizza(f.img, None, Georef(f.mm_px, 0.0, f.H_mm), Parametri())
    xs = [p[0] for p in res.muro[0]]
    ys = [p[1] for p in res.muro[0]]
    assert abs(min(xs) - 1000) <= TOL and abs(max(xs) - 13000) <= TOL
    assert abs(min(ys) - 1000) <= TOL and abs(max(ys) - 8000) <= TOL
    yc = [p[1] for p in res.copertura[0]]
    assert abs(min(yc) - 8000) <= TOL and abs(max(yc) - 9500) <= TOL


def test_cli_dxf(tmp_path):
    import cv2
    f = facciata_timpano()
    img = tmp_path / "prospetto.png"
    cv2.imwrite(str(img), f.bgra())
    assert main([str(img), "--mm-pixel", "4", "--etichette"]) == 0
    doc = ezdxf.readfile(str(tmp_path / "prospetto_rilievo.dxf"))
    msp = doc.modelspace()
    assert len(msp.query("INSERT")) == 0          # niente blocchi
    assert doc.header["$INSUNITS"] == 4
    pl = msp.query("LWPOLYLINE")
    assert len(pl) > 0 and all(p.closed for p in pl)
    for p in pl:
        for x, y in p.get_points("xy"):
            assert float(x).is_integer() and float(y).is_integer()
    assert (tmp_path / "prospetto_rilievo.csv").exists()
    assert (tmp_path / "prospetto_rilievo_controllo.png").exists()


def test_arrotonda():
    assert arrotonda(1734.37, 1) == 1734
    assert arrotonda(1734.5, 1) == 1735
    assert arrotonda(-1734.5, 1) == -1735
    assert arrotonda(4512345678.37, 1) == 4512345678
    assert arrotonda(1737.6, 5) == 1740


def test_worldfile(tmp_path):
    wf = tmp_path / "a.tfw"
    wf.write_text("0.002\n0\n0\n-0.002\n100.001\n50.001\n")
    g = georef_da_worldfile(str(wf), 1000.0)
    assert g.mm_px == pytest.approx(2.0)
    assert g.x0 == pytest.approx(100000.0) and g.y0 == pytest.approx(50002.0)
