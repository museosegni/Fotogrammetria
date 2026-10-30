"""Riconoscimento automatico degli elementi di prospetto su ortofoto.

Pipeline (coordinate di lavoro: pixel dell'immagine ridotta, convenzione "bordi":
il pixel (c, r) occupa [c, c+1] x [r, r+1], v cresce verso il basso):

1. maschera facciata   alpha -> sfondo uniforme dai bordi -> GrabCut
2. aperture            zone scure (soglia adattiva) rettangolari, dentro la facciata,
                       espanse fino al colore del muro (telaio/mazzetta inclusi)
3. copertura           zone di colore diverso dal muro, attaccate al profilo
                       superiore della sagoma (oppure taglio orizzontale a --gronda-mm)
4. muro                facciata - copertura
5. soglie              fascia di colore diverso dal muro subito sotto ogni apertura;
                       se non rilevata: dimensioni di default (layer "stimata")
6. regolarizzazione    allineamento di quote simili (stesso piano / stessa colonna)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .immagine import Georef


# ---------------------------------------------------------------------------
# Parametri
# ---------------------------------------------------------------------------
@dataclass
class Parametri:
    passo_mm: float = 1.0                 # arrotondamento coordinate finali
    lato_max_proc_px: int = 6000          # riduzione immagine per l'analisi
    tolleranza_sfondo: float = 12.0       # deltaE (Lab 8 bit) per sfondo uniforme
    finestra_min_mm: float = 350.0
    finestra_max_mm: float = 4000.0
    finestra_rettangolarita: float = 0.65
    contrasto_scuro: float = 12.0         # quanto un'apertura e' piu' scura del contorno
    blocco_adattivo_mm: float = 2500.0
    espansione_max_mm: float = 200.0      # max telaio/mazzetta inclusi nella sagoma
    soglia_colore: float = 12.0           # deltaE per "diverso dal muro"
    soglia_colore_copertura: float = 20.0
    copertura_area_min_m2: float = 0.3
    gronda_mm: float | None = None        # forza taglio orizzontale muro/copertura
    semplifica_mm: float = 30.0
    angolo_snap_deg: float = 6.0
    allinea_mm: float = 20.0
    soglia_cerca_mm: float = 250.0
    soglia_spessore_min_mm: float = 15.0
    soglia_sporgenza_max_mm: float = 250.0
    soglia_spessore_default_mm: float = 40.0
    soglia_sporgenza_default_mm: float = 30.0
    soglie: str = "auto"                  # auto | rilevate | nessuna


# ---------------------------------------------------------------------------
# Risultato (tutto in mm, gia' arrotondato)
# ---------------------------------------------------------------------------
@dataclass
class Rett:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def larghezza(self):
        return self.xmax - self.xmin

    @property
    def altezza(self):
        return self.ymax - self.ymin

    def vertici(self):
        return [(self.xmin, self.ymin), (self.xmax, self.ymin),
                (self.xmax, self.ymax), (self.xmin, self.ymax)]


@dataclass
class Soglia:
    rett: Rett
    stimata: bool
    finestra: int


@dataclass
class Risultato:
    muro: list = field(default_factory=list)        # liste di (x, y)
    copertura: list = field(default_factory=list)
    finestre: list = field(default_factory=list)    # Rett
    soglie: list = field(default_factory=list)      # Soglia
    avvisi: list = field(default_factory=list)
    metodo_maschera: str = ""
    controllo: np.ndarray | None = None             # immagine di controllo (BGR)


# ---------------------------------------------------------------------------
# Utilita'
# ---------------------------------------------------------------------------
def arrotonda(x: float, passo: float) -> float:
    q = x / passo
    r = math.floor(q + 0.5) if q >= 0 else -math.floor(-q + 0.5)
    v = r * passo
    return float(int(v)) if passo >= 1 and float(v).is_integer() else round(v, 6)


def _dispari(n: float, minimo: int = 3) -> int:
    n = max(minimo, int(round(n)))
    return n if n % 2 else n + 1


def _deltae(lab: np.ndarray, ref: np.ndarray) -> np.ndarray:
    return np.linalg.norm(lab.astype(np.float32) - ref.astype(np.float32), axis=-1)


def _riempi_e_tieni(m: np.ndarray, area_min_px: float = 0.0, solo_max: bool = False) -> np.ndarray:
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnts = [c for c in cnts if cv2.contourArea(c) >= area_min_px]
    if solo_max and cnts:
        cnts = [max(cnts, key=cv2.contourArea)]
    out = np.zeros(m.shape, np.uint8)
    if cnts:
        cv2.drawContours(out, cnts, -1, 1, cv2.FILLED)
    return out


# ---------------------------------------------------------------------------
# 1. Maschera facciata
# ---------------------------------------------------------------------------
def maschera_facciata(bgr, alpha, lab, mmpx, par: Parametri):
    h, w = bgr.shape[:2]
    if alpha is not None and (alpha < 128).any() and (alpha >= 128).any():
        m, metodo = (alpha >= 128).astype(np.uint8), "trasparenza (alpha)"
    else:
        lab_s = cv2.GaussianBlur(lab, (0, 0), max(1.0, 8.0 / mmpx))  # toglie il rumore
        bordo = np.concatenate([lab_s[0], lab_s[-1], lab_s[:, 0], lab_s[:, -1]]).astype(np.float32)
        ref = np.median(bordo, axis=0)
        if (_deltae(bordo, ref) < par.tolleranza_sfondo).mean() > 0.6:
            cand = (_deltae(lab_s, ref) < par.tolleranza_sfondo).astype(np.uint8)
            _, etich = cv2.connectedComponents(cand, connectivity=8)
            ids = np.unique(np.concatenate([etich[0], etich[-1], etich[:, 0], etich[:, -1]]))
            ids = ids[ids != 0]
            m = (~np.isin(etich, ids)).astype(np.uint8)
            metodo = "sfondo uniforme"
        else:
            s = min(1.0, 800.0 / max(h, w))
            small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            gm = np.full(small.shape[:2], cv2.GC_PR_FGD, np.uint8)
            b = max(2, int(0.02 * max(small.shape[:2])))
            gm[:b, :] = gm[-b:, :] = cv2.GC_PR_BGD
            gm[:, :b] = gm[:, -b:] = cv2.GC_PR_BGD
            bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
            try:
                cv2.grabCut(small, gm, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
                fg = ((gm == cv2.GC_FGD) | (gm == cv2.GC_PR_FGD)).astype(np.uint8)
                m = cv2.resize(fg, (w, h), interpolation=cv2.INTER_NEAREST)
                metodo = "GrabCut"
            except cv2.error:
                m, metodo = np.ones((h, w), np.uint8), "intera immagine"
            if m.mean() < 0.2:
                m, metodo = np.ones((h, w), np.uint8), "intera immagine"
    ko = _dispari(30.0 / mmpx)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (ko, ko)))
    k = _dispari(100.0 / mmpx)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    m = _riempi_e_tieni(m, solo_max=True)
    return m, metodo


# ---------------------------------------------------------------------------
# Poligoni
# ---------------------------------------------------------------------------
def _area_segno(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _togli_collineari(P, tol=1e-6):
    P = [tuple(p) for p in P]
    cambiato = True
    while cambiato and len(P) > 3:
        cambiato = False
        for i in range(len(P)):
            a, b, c = np.array(P[i - 1]), np.array(P[i]), np.array(P[(i + 1) % len(P)])
            ab, bc = b - a, c - b
            if np.linalg.norm(ab) < tol or np.linalg.norm(bc) < tol or \
               (abs(ab[0] * bc[1] - ab[1] * bc[0]) < tol * max(np.linalg.norm(ab) * np.linalg.norm(bc), 1)
                    and np.dot(ab, bc) > 0):
                del P[i]
                cambiato = True
                break
    return np.array(P, float)


def ortogonalizza(P, snap_deg):
    P = P.astype(float).copy()
    n = len(P)
    for _ in range(3):
        for i in range(n):
            j = (i + 1) % n
            d = P[j] - P[i]
            ang = math.degrees(math.atan2(abs(d[1]), abs(d[0])))
            if ang < snap_deg:
                P[i, 1] = P[j, 1] = (P[i, 1] + P[j, 1]) / 2
            elif ang > 90 - snap_deg:
                P[i, 0] = P[j, 0] = (P[i, 0] + P[j, 0]) / 2
    return P


def offset_poligono(P, d):
    """Sposta ogni lato verso l'esterno di d (giunti a spigolo vivo)."""
    n = len(P)
    if n < 3 or d == 0:
        return P
    s = 1.0 if _area_segno(P) > 0 else -1.0
    norm = []
    for i in range(n):
        e = P[(i + 1) % n] - P[i]
        L = np.linalg.norm(e) or 1.0
        norm.append(s * np.array([e[1], -e[0]]) / L)
    Q = []
    for i in range(n):
        a1, d1 = P[i - 1] + norm[i - 1] * d, P[i] - P[i - 1]
        a2, d2 = P[i] + norm[i] * d, P[(i + 1) % n] - P[i]
        cr = d1[0] * d2[1] - d1[1] * d2[0]
        q = None
        if abs(cr) > 1e-9:
            t = ((a2[0] - a1[0]) * d2[1] - (a2[1] - a1[1]) * d2[0]) / cr
            q = a1 + d1 * t
        if q is None or np.linalg.norm(q - P[i]) > 3 * abs(d):  # limite di spigolo
            q = P[i] + (norm[i - 1] + norm[i]) / 2 * d
        Q.append(q)
    return np.array(Q)


def poligoni_da_maschera(m, mmpx, par: Parametri, area_min_px):
    out = []
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    for c in cnts:
        if cv2.contourArea(c) < area_min_px:
            continue
        P = cv2.approxPolyDP(c, max(1.0, par.semplifica_mm / mmpx), True).reshape(-1, 2).astype(float) + 0.5
        if len(P) < 3:
            continue
        P = ortogonalizza(P, par.angolo_snap_deg)
        P = _togli_collineari(P)
        if len(P) < 3:
            continue
        out.append(offset_poligono(P, 0.5))  # da centri pixel a bordi pixel
    return out


def aggancia(P, riferimenti, tol):
    """Aggancia i vertici di P a vertici o lati dei poligoni di riferimento entro tol."""
    if not riferimenti:
        return P
    V = np.vstack(riferimenti)
    lati = [(R[i], R[(i + 1) % len(R)]) for R in riferimenti for i in range(len(R))]
    Q = P.copy()
    for k, p in enumerate(P):
        dv = np.linalg.norm(V - p, axis=1)
        if dv.min() <= tol:
            Q[k] = V[dv.argmin()]
            continue
        best, bd = None, tol
        for a, b in lati:
            ab = b - a
            L2 = float(ab @ ab)
            if L2 == 0:
                continue
            t = min(1.0, max(0.0, float((p - a) @ ab) / L2))
            q = a + t * ab
            dd = float(np.linalg.norm(p - q))
            if dd <= bd:
                best, bd = q, dd
        if best is not None:
            Q[k] = best
    return Q


# ---------------------------------------------------------------------------
# 2. Aperture
# ---------------------------------------------------------------------------
def rileva_aperture(gray, maschera, mmpx, par: Parametri):
    interno = cv2.erode(maschera, cv2.getStructuringElement(
        cv2.MORPH_RECT, (_dispari(60 / mmpx), _dispari(60 / mmpx))))
    blocco = _dispari(par.blocco_adattivo_mm / mmpx, 3)
    blocco = min(blocco, _dispari(min(gray.shape) - 2, 3))
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    # fuori facciata = valore medio, per non falsare la media locale ai bordi
    media = int(np.median(g[maschera > 0])) if maschera.any() else 128
    g = np.where(maschera > 0, g, media).astype(np.uint8)
    scuro = cv2.adaptiveThreshold(g, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV,
                                  blocco, par.contrasto_scuro)
    scuro &= interno
    kc = _dispari(80 / mmpx)
    ko = _dispari(40 / mmpx)
    scuro = cv2.morphologyEx(scuro, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kc, kc)))
    scuro = cv2.morphologyEx(scuro, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (ko, ko)))
    cnts, _ = cv2.findContours(scuro, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lmin, lmax = par.finestra_min_mm / mmpx, par.finestra_max_mm / mmpx
    rett = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (lmin <= w <= lmax and lmin <= h <= lmax):
            continue
        if not (0.2 <= h / w <= 6.0):
            continue
        cv2_area = cv2.contourArea(cv2.convexHull(c))
        if cv2_area / float(w * h) < par.finestra_rettangolarita:
            continue
        rett.append([float(x), float(y), float(x + w), float(y + h)])
    return rett


def _colore_muro_attorno(lab, maschera, r, mmpx, escludi):
    """Mediana Lab di un anello 150-300 mm a sinistra, destra e sopra il rettangolo."""
    h, w = maschera.shape
    a, b = int(150 / mmpx), int(300 / mmpx)
    x1, y1, x2, y2 = [int(round(v)) for v in r]
    zone = [(y1, y2, x1 - b, x1 - a), (y1, y2, x2 + a, x2 + b), (y1 - b, y1 - a, x1, x2)]
    pix = []
    for r1, r2, c1, c2 in zone:
        r1, r2, c1, c2 = max(0, r1), min(h, r2), max(0, c1), min(w, c2)
        if r2 > r1 and c2 > c1:
            sel = (maschera[r1:r2, c1:c2] > 0) & (escludi[r1:r2, c1:c2] == 0)
            pix.append(lab[r1:r2, c1:c2][sel])
    pix = np.concatenate(pix) if pix else np.empty((0, 3))
    if len(pix) < 20:
        return None
    return np.median(pix.astype(np.float32), axis=0)


def espandi_a_muro(lab, maschera, rett, mmpx, par: Parametri, escludi):
    """Allarga ogni lato finche' la striscia esterna ha il colore del muro."""
    h, w = maschera.shape
    kmax = int(par.espansione_max_mm / mmpx)
    out, refs = [], []
    for r in rett:
        ref = _colore_muro_attorno(lab, maschera, r, mmpx, escludi)
        x1, y1, x2, y2 = [int(round(v)) for v in r]
        if ref is not None:
            interno = np.median(lab[y1:y2, x1:x2].reshape(-1, 3).astype(np.float32), axis=0)
            if float(np.linalg.norm(interno - ref)) < 2 * par.soglia_colore:
                continue  # muro liscio fra elementi chiari: non e' un'apertura
        refs.append(ref)
        if ref is None:
            out.append(r)
            continue
        cy1, cy2 = int(y1 + 0.15 * (y2 - y1)), int(y2 - 0.15 * (y2 - y1)) + 1
        cx1, cx2 = int(x1 + 0.15 * (x2 - x1)), int(x2 - 0.15 * (x2 - x1)) + 1

        def passi(fetta):
            for k in range(kmax + 1):
                sl = fetta(k)
                if sl is None or sl[1].size == 0 or sl[1].mean() < 0.5:
                    return k  # bordo immagine o fuori facciata
                s = lab[sl[0]]
                if float(np.linalg.norm(np.median(s.reshape(-1, 3).astype(np.float32), axis=0) - ref)) \
                        < par.soglia_colore:
                    return k
            return kmax

        def fetta(sl):
            return None if sl is None else (sl, maschera[sl])

        sx = passi(lambda k: fetta((slice(cy1, cy2), x1 - 1 - k) if x1 - 1 - k >= 0 else None))
        dx = passi(lambda k: fetta((slice(cy1, cy2), x2 + k) if x2 + k < w else None))
        su = passi(lambda k: fetta((y1 - 1 - k, slice(cx1, cx2)) if y1 - 1 - k >= 0 else None))
        giu = passi(lambda k: fetta((y2 + k, slice(cx1, cx2)) if y2 + k < h else None))
        # sotto c'e' spesso la soglia: il telaio inferiore non supera quello laterale
        giu = min(giu, int(round((sx + dx) / 2)))
        r2 = [x1 - sx, y1 - su, x2 + dx, y2 + giu]
        # mai oltre il bordo inferiore della facciata (porte)
        col = np.where(maschera[:, min(max((x1 + x2) // 2, 0), w - 1)] > 0)[0]
        if len(col):
            r2[3] = min(r2[3], col[-1] + 1)
        out.append(r2)
    return out, refs


def raggruppa(valori, tol):
    """Indici raggruppati per valori vicini (catena con passo <= tol, ampiezza <= 2*tol)."""
    ordine = np.argsort(valori)
    gruppi, cur = [], [ordine[0]] if len(ordine) else []
    for i in ordine[1:]:
        if valori[i] - valori[cur[-1]] <= tol and valori[i] - valori[cur[0]] <= 2 * tol:
            cur.append(i)
        else:
            gruppi.append(cur)
            cur = [i]
    if cur:
        gruppi.append(cur)
    return gruppi


def regolarizza(rett, tol_px):
    if len(rett) < 2:
        return rett
    R = np.array(rett, float)
    for col in range(4):
        for g in raggruppa(R[:, col], tol_px):
            if len(g) > 1:
                R[g, col] = np.median(R[g, col])
    return [list(r) for r in R if r[2] > r[0] and r[3] > r[1]]


# ---------------------------------------------------------------------------
# 3. Copertura
# ---------------------------------------------------------------------------
def rileva_copertura(lab, maschera, aperture_m, mmpx, par: Parametri):
    h, w = maschera.shape
    righe = np.where(maschera.any(axis=1))[0]
    if len(righe) == 0:
        return np.zeros_like(maschera)
    top, bot = righe[0], righe[-1]
    if par.gronda_mm is not None:
        return None  # gestito dal chiamante (taglio orizzontale)
    # colore di riferimento del muro: fascia centrale, senza aperture
    r1, r2 = int(top + 0.35 * (bot - top)), int(top + 0.75 * (bot - top)) + 1
    sel = (maschera[r1:r2] > 0) & (aperture_m[r1:r2] == 0)
    if sel.sum() < 50:
        return np.zeros_like(maschera)
    ref = np.median(lab[r1:r2][sel].astype(np.float32), axis=0)
    s = max(0.5, 40.0 / mmpx)
    lab_s = cv2.GaussianBlur(lab, (0, 0), s)
    cand = ((_deltae(lab_s, ref) > par.soglia_colore_copertura) & (maschera > 0) & (aperture_m == 0))
    cand = cand.astype(np.uint8)
    k = _dispari(60 / mmpx)
    el = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    cand = cv2.morphologyEx(cv2.morphologyEx(cand, cv2.MORPH_OPEN, el), cv2.MORPH_CLOSE, el)
    # bordo superiore della sagoma (pixel di facciata con sfondo sopra, meta' alta)
    bordo = (maschera > 0) & (cv2.erode(maschera, np.ones((3, 3), np.uint8)) == 0)
    bordo[int(top + 0.5 * (bot - top)):] = False
    bordo = cv2.dilate(bordo.astype(np.uint8), cv2.getStructuringElement(
        cv2.MORPH_RECT, (_dispari(30 / mmpx), _dispari(30 / mmpx))))
    n, etich, stat, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    amin = par.copertura_area_min_m2 * 1e6 / (mmpx * mmpx)
    grezza = np.zeros_like(maschera)
    for i in range(1, n):
        if stat[i, cv2.CC_STAT_AREA] < amin:
            continue
        comp = etich == i
        if (comp & (bordo > 0)).any():
            grezza[comp] = 1
    if not grezza.any():
        return grezza
    # rifinitura senza la deriva della sfocatura: ogni pixel va alla classe
    # (muro / copertura) di colore piu' vicino, solo nell'intorno della zona grezza
    nucleo = cv2.erode(grezza, el) > 0
    ref_cop = np.median(lab[nucleo if nucleo.any() else grezza > 0].astype(np.float32), axis=0)
    lab_l = cv2.GaussianBlur(lab, (0, 0), 1.0)
    vicino = (_deltae(lab_l, ref_cop) < _deltae(lab_l, ref)).astype(np.uint8)
    kd = _dispari(150 / mmpx)
    zona = cv2.dilate(grezza, cv2.getStructuringElement(cv2.MORPH_RECT, (kd, kd)))
    fine = vicino & zona & maschera & (1 - aperture_m)
    k2 = _dispari(20 / mmpx)
    el2 = cv2.getStructuringElement(cv2.MORPH_RECT, (k2, k2))
    fine = cv2.morphologyEx(cv2.morphologyEx(fine, cv2.MORPH_OPEN, el2), cv2.MORPH_CLOSE, el2)
    n, etich = cv2.connectedComponents(fine, connectivity=8)
    tieni = np.unique(etich[(grezza > 0) & (fine > 0)])
    fine = np.isin(etich, tieni[tieni != 0]).astype(np.uint8)
    return _riempi_e_tieni(fine, amin) & maschera


# ---------------------------------------------------------------------------
# 5. Soglie
# ---------------------------------------------------------------------------
def rileva_soglia(lab, maschera, r, ref, mmpx, par: Parametri):
    """Ritorna (x1, y1, x2, y2) in px o None."""
    if ref is None:
        return None
    h, w = maschera.shape
    x1, y1, x2, y2 = [int(round(v)) for v in r]
    cerca = int(par.soglia_cerca_mm / mmpx)
    ext = int(par.soglia_sporgenza_max_mm / mmpx)
    if y2 + 2 >= h:
        return None
    cx1, cx2 = max(0, x1), min(w, x2)
    d = []
    for rr in range(y2, min(h, y2 + cerca)):
        d.append(float(np.linalg.norm(np.median(lab[rr, cx1:cx2].astype(np.float32), axis=0) - ref)))
    d = np.array(d)
    inizio = 0
    while inizio < min(3, len(d)) and d[inizio] <= par.soglia_colore:
        inizio += 1
    fine = inizio
    while fine < len(d) and d[fine] > par.soglia_colore:
        fine += 1
    spessore = fine - inizio
    if spessore * mmpx < par.soglia_spessore_min_mm or fine >= len(d):
        return None
    ry1, ry2 = y2 + inizio, y2 + fine
    c1, c2 = max(0, x1 - ext), min(w, x2 + ext)
    banda = lab[ry1:ry2, c1:c2].astype(np.float32)
    dc = np.linalg.norm(np.median(banda, axis=0) - ref, axis=1) > par.soglia_colore
    centro = (x1 + x2) // 2 - c1
    if not (0 <= centro < len(dc)) or not dc[centro]:
        return None
    a = centro
    while a > 0 and dc[a - 1]:
        a -= 1
    b = centro
    while b < len(dc) - 1 and dc[b + 1]:
        b += 1
    sx, dx = c1 + a, c1 + b + 1
    if sx <= c1 or dx >= c2:  # la fascia continua oltre la ricerca: marcapiano, non soglia
        return None
    return [float(min(sx, x1)), float(ry1), float(max(dx, x2)), float(ry2)]


# ---------------------------------------------------------------------------
# Pipeline completa
# ---------------------------------------------------------------------------
def analizza(bgr, alpha, geo: Georef, par: Parametri | None = None) -> Risultato:
    par = par or Parametri()
    res = Risultato()
    H0, W0 = bgr.shape[:2]
    f = min(1.0, par.lato_max_proc_px / float(max(H0, W0)))
    if f < 1.0:
        bgr = cv2.resize(bgr, (int(round(W0 * f)), int(round(H0 * f))), interpolation=cv2.INTER_AREA)
        if alpha is not None:
            alpha = cv2.resize(alpha, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    fx, fy = bgr.shape[1] / float(W0), bgr.shape[0] / float(H0)
    mmpx = geo.mm_px / fx
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    def a_mm(u, v):
        return geo.x0 + (u / fx) * geo.mm_px, geo.y0 - (v / fy) * geo.mm_px

    def da_mm_v(Y):
        return (geo.y0 - Y) / geo.mm_px * fy

    # 1. facciata
    masc, res.metodo_maschera = maschera_facciata(bgr, alpha, lab, mmpx, par)
    if res.metodo_maschera == "intera immagine":
        res.avvisi.append("Sfondo non separato: tutta l'immagine e' considerata facciata.")

    # 2. aperture
    rett = rileva_aperture(gray, masc, mmpx, par)
    aperture_m = np.zeros_like(masc)
    for x1, y1, x2, y2 in rett:
        aperture_m[int(y1):int(y2), int(x1):int(x2)] = 1
    rett, refs = espandi_a_muro(lab, masc, rett, mmpx, par, aperture_m)
    rett = regolarizza(rett, par.allinea_mm / mmpx)
    if len(rett) != len(refs):  # regolarizza puo' scartare rettangoli degeneri
        refs = [None] * len(rett)
    aperture_m[:] = 0
    for x1, y1, x2, y2 in rett:
        aperture_m[max(0, int(y1)):int(math.ceil(y2)), max(0, int(x1)):int(math.ceil(x2))] = 1

    # 3. copertura
    if par.gronda_mm is not None:
        g = int(round(da_mm_v(par.gronda_mm)))
        cop = masc.copy()
        cop[max(0, g):] = 0
    else:
        cop = rileva_copertura(lab, masc, aperture_m, mmpx, par)
    # aperture dentro la copertura (es. riflessi sulle tegole) -> scartate
    tenute = []
    for i, r in enumerate(rett):
        x1, y1, x2, y2 = [int(round(v)) for v in r]
        zona = cop[max(0, y1):y2, max(0, x1):x2]
        if zona.size and zona.mean() > 0.5:
            continue
        tenute.append(i)
    rett = [rett[i] for i in tenute]
    refs = [refs[i] for i in tenute]

    # 4. muro = facciata - copertura
    muro_m = (masc & (1 - cop)).astype(np.uint8)
    # toglie le strisce sottili di copertura rimaste sul bordo della sagoma
    kr = _dispari(60 / mmpx)
    muro_m = cv2.morphologyEx(muro_m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kr, kr)))
    amin = 0.25 * 1e6 / (mmpx * mmpx)
    poli_cop = poligoni_da_maschera(cop, mmpx, par, par.copertura_area_min_m2 * 1e6 / mmpx ** 2)
    poli_muro = poligoni_da_maschera(_riempi_e_tieni(muro_m, amin), mmpx, par, amin)
    poli_muro = [aggancia(P, poli_cop, par.semplifica_mm / mmpx) for P in poli_muro]

    # 5. soglie
    righe_fondo = {}
    soglie_px = []
    if par.soglie != "nessuna":
        spess_d = par.soglia_spessore_default_mm / mmpx
        spor_d = par.soglia_sporgenza_default_mm / mmpx
        for i, (r, ref) in enumerate(zip(rett, refs)):
            x1, y1, x2, y2 = r
            cc = int(min(max((x1 + x2) / 2, 0), masc.shape[1] - 1))
            if cc not in righe_fondo:
                col = np.where(masc[:, cc] > 0)[0]
                righe_fondo[cc] = col[-1] + 1 if len(col) else masc.shape[0]
            if righe_fondo[cc] - y2 < 150 / mmpx:   # porta a terra: niente soglia
                continue
            if ref is None:
                ref = _colore_muro_attorno(lab, masc, r, mmpx, aperture_m)
            s = rileva_soglia(lab, masc, r, ref, mmpx, par)
            if s is not None:
                soglie_px.append((s, False, i))
            elif par.soglie == "auto":
                soglie_px.append(([x1 - spor_d, y2, x2 + spor_d, y2 + spess_d], True, i))

    # --- conversione in mm e arrotondamento --------------------------------
    p = par.passo_mm

    def rett_mm(r):
        X1, Y1 = a_mm(r[0], r[3])
        X2, Y2 = a_mm(r[2], r[1])
        return Rett(arrotonda(X1, p), arrotonda(Y1, p), arrotonda(X2, p), arrotonda(Y2, p))

    def poli_mm(P):
        Q = []
        for u, v in P:
            X, Y = a_mm(u, v)
            q = (arrotonda(X, p), arrotonda(Y, p))
            if not Q or q != Q[-1]:
                Q.append(q)
        if len(Q) > 1 and Q[0] == Q[-1]:
            Q.pop()
        Q = [tuple(map(float, q)) for q in _togli_collineari(np.array(Q, float))] if len(Q) >= 3 else Q
        return Q if len(Q) >= 3 else None

    res.finestre = [rett_mm(r) for r in rett]
    for s, stimata, i in soglie_px:
        R = rett_mm(s)
        if R.larghezza > 0 and R.altezza > 0:
            res.soglie.append(Soglia(R, stimata, i))
    res.muro = [q for q in (poli_mm(P) for P in poli_muro) if q]
    res.copertura = [q for q in (poli_mm(P) for P in poli_cop) if q]
    if not res.finestre:
        res.avvisi.append("Nessuna apertura riconosciuta: provare --contrasto piu' basso o --finestra-min diversa.")
    if not res.copertura:
        res.avvisi.append("Copertura non riconosciuta (colore simile al muro?): usare eventualmente --gronda-mm.")

    res.controllo = _immagine_controllo(bgr, poli_muro, poli_cop, rett, soglie_px)
    return res


def _immagine_controllo(bgr, poli_muro, poli_cop, rett, soglie_px):
    img = (bgr.astype(np.float32) * 0.6).astype(np.uint8)
    t = max(1, int(round(max(img.shape[:2]) / 800)))

    def pl(P, col):
        cv2.polylines(img, [np.round(P).astype(np.int32)], True, col, t, cv2.LINE_AA)

    for P in poli_cop:
        pl(P, (0, 0, 255))
    for P in poli_muro:
        pl(P, (0, 255, 0))
    for r in rett:
        cv2.rectangle(img, (int(r[0]), int(r[1])), (int(r[2]), int(r[3])), (255, 255, 0), t)
    for s, stimata, _ in soglie_px:
        cv2.rectangle(img, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])),
                      (0, 165, 255) if stimata else (0, 255, 255), t)
    return img
