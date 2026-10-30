"""Facciate sintetiche con misure note (mm) per verificare il riconoscimento."""
import cv2
import numpy as np

MURO = (120, 170, 210)      # BGR intonaco ocra
TEGOLE = (60, 80, 165)
TELAIO = (235, 235, 235)
VETRO = (55, 50, 45)
SOGLIA = (215, 220, 220)


class Facciata:
    def __init__(self, larg_mm, alt_mm, mm_px=4.0, sfondo=(255, 255, 255), alpha=False):
        self.mm_px, self.H_mm = mm_px, alt_mm
        self.w, self.h = int(larg_mm / mm_px), int(alt_mm / mm_px)
        self.img = np.zeros((self.h, self.w, 3), np.uint8)
        self.img[:] = sfondo
        self.alpha = np.zeros((self.h, self.w), np.uint8) if alpha else None
        self.verita = {"finestre": [], "soglie": []}

    def px(self, x, y):  # mm (origine basso-sinistra) -> px (bordi)
        return int(round(x / self.mm_px)), int(round((self.H_mm - y) / self.mm_px))

    def rett(self, x1, y1, x2, y2, col):
        a, b = self.px(x1, y2)
        c, d = self.px(x2, y1)
        self.img[b:d, a:c] = col
        if self.alpha is not None:
            self.alpha[b:d, a:c] = 255

    def poli(self, punti_mm, col):
        P = np.array([self.px(x, y) for x, y in punti_mm], np.int32)
        cv2.fillPoly(self.img, [P], col)
        if self.alpha is not None:
            cv2.fillPoly(self.alpha, [P], 255)

    def finestra(self, x, y, l, h, telaio=70, montante=60, soglia=(50, 50)):
        self.rett(x, y, x + l, y + h, TELAIO)
        self.rett(x + telaio, y + telaio, x + l - telaio, y + h - telaio, VETRO)
        m = x + l / 2
        self.rett(m - montante / 2, y + telaio, m + montante / 2, y + h - telaio, TELAIO)
        self.verita["finestre"].append((x, y, x + l, y + h))
        if soglia:
            sp, spor = soglia
            self.rett(x - spor, y - sp, x + l + spor, y, SOGLIA)
            self.verita["soglie"].append((x - spor, y - sp, x + l + spor, y))

    def porta(self, x, y, l, h, telaio=70):
        self.rett(x, y, x + l, y + h, TELAIO)
        self.rett(x + telaio, y, x + l - telaio, y + h - telaio, VETRO)
        self.verita["finestre"].append((x, y, x + l, y + h))

    def rumore(self, sigma=5, seme=1):
        rng = np.random.default_rng(seme)
        n = rng.normal(0, sigma, self.img.shape)
        self.img = np.clip(self.img.astype(np.float32) + n, 0, 255).astype(np.uint8)

    def bgra(self):
        return np.dstack([self.img, self.alpha]) if self.alpha is not None else self.img


def facciata_gronda():
    """Prospetto lato gronda: muro 12000x7000, falda in vista sopra, 5 finestre + 1 porta."""
    f = Facciata(14000, 10500)
    f.rett(1000, 1000, 13000, 8000, MURO)
    f.poli([(800, 8000), (13200, 8000), (12000, 9500), (2000, 9500)], TEGOLE)
    for i in range(int(14000 / 4 / 40)):  # righe dei coppi
        x = 800 + i * 160
        if 2000 <= x <= 12000:
            f.rett(x, 8000, x + 30, 9500, (50, 65, 140))
    f.verita["muro"] = (1000, 1000, 13000, 8000)
    f.verita["copertura_y"] = (8000, 9500)
    for x in (2500, 6400, 10300):
        f.finestra(x, 5200, 1200, 1500)
    f.finestra(2500, 2200, 1200, 1500)
    f.finestra(10300, 2200, 1200, 1500)
    f.porta(6450, 1000, 1100, 2300)
    f.rumore()
    return f


def facciata_timpano():
    """Prospetto a capanna su sfondo trasparente."""
    f = Facciata(11000, 10000, alpha=True)
    f.poli([(1000, 1000), (9000, 1000), (9000, 6000), (5000, 8500), (1000, 6000)], MURO)
    t = 350  # spessore falda in vista
    f.poli([(700, 5800), (5000, 8500), (9300, 5800), (9300, 5800 + t), (5000, 8500 + t),
            (700, 5800 + t)], TEGOLE)
    f.verita["muro_bbox"] = (1000, 1000, 9000, 8500)
    for x in (2000, 6800):
        f.finestra(x, 3800, 1200, 1400)
        f.finestra(x, 1600, 1200, 1400)
    f.rumore(seme=2)
    return f
