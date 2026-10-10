"""Centra el producto sobre su cartulina extendiendo el fondo real (ver CLAUDE.md).

No se quita el fondo: el producto, su sombra y su brillo se conservan. Solo se
reemplazan las paredes de la caja y lo que queda fuera de la foto.
"""
import os
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps

MODELO = Path(os.environ.get(
    "U2NET_MODEL", Path(__file__).resolve().parents[2] / "models" / "u2net.onnx"))

LADO_TRABAJO = 768      # resolución a la que se calculan las máscaras
OCUPACION = 0.8         # fracción del lado del cuadrado que ocupa el producto
MAX_AMPLIACION = 2.0    # límite de ampliación para productos pequeños (evita borrosidad)
TOL_VECINO = (3, 2, 2)  # diferencia LAB máxima entre píxeles vecinos de la cartulina
TOL_GLOBAL = 45         # distancia LAB máxima al color muestreado de la cartulina
TEX_FACTOR = 3.0        # textura máxima de la cartulina, relativa a la muestreada
TEX_MIN = 12.0          # ... y en valor absoluto (para cartulinas muy lisas)

_sesion = None


def process_image(data: bytes, size: int = 1920) -> bytes:
    img = np.array(ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB"))
    out = componer(img, size)
    buf = BytesIO()
    Image.fromarray(out).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def componer(img: np.ndarray, size: int) -> np.ndarray:
    h, w = img.shape[:2]
    k = LADO_TRABAJO / max(h, w)
    small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)

    prob = mascara_producto(small)
    producto = filtrar_componentes(prob > 0.5)
    if not producto.any():
        raise ValueError("No se detectó ningún producto en la foto")

    color_fondo, semillas = muestrear_fondo(small, producto)
    cartulina = detectar_cartulina(small, producto, color_fondo, semillas)
    paredes = detectar_paredes(cartulina, producto)

    caja = recorte_cuadrado(producto, k, w, h, size)

    # Todo se lleva al lienzo de salida (size x size)
    lienzo, valido = recortar(img, caja, size)
    escala = lambda m: recortar(cv2.resize(m.astype(np.float32), (w, h)), caja, size)[0]
    prob_out = escala(prob)
    cartulina_out = escala(cartulina) > 0.5
    # Los últimos píxeles de la foto suelen venir oscurecidos por el lente: se descartan
    r = max(1, int(size * 0.006))
    valido = cv2.erode(valido.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8),
                       borderType=cv2.BORDER_REPLICATE) > 0
    rellenar = (escala(paredes) > 0.5) | ~valido

    if not rellenar.any():
        return lienzo
    fondo = superficie_fondo(lienzo, cartulina_out & ~rellenar, color_fondo)
    return mezclar(lienzo, fondo, rellenar, prob_out)


def mascara_producto(rgb: np.ndarray) -> np.ndarray:
    """Probabilidad [0, 1] de que cada píxel sea producto (u2net)."""
    global _sesion
    if _sesion is None:
        _sesion = ort.InferenceSession(str(MODELO), providers=["CPUExecutionProvider"])
    x = cv2.resize(rgb, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = (x / max(x.max(), 1e-6) - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    p = _sesion.run(None, {_sesion.get_inputs()[0].name: x})[0][0, 0]
    p = (p - p.min()) / max(p.max() - p.min(), 1e-6)
    return cv2.resize(p, (rgb.shape[1], rgb.shape[0]))


def filtrar_componentes(mascara: np.ndarray) -> np.ndarray:
    """Quita manchas sueltas; conserva varios objetos de tamaño parecido (p. ej. pines)."""
    n, etiquetas, stats, _ = cv2.connectedComponentsWithStats(mascara.astype(np.uint8), 8)
    if n <= 1:
        return mascara
    areas = stats[1:, cv2.CC_STAT_AREA]
    minimo = max(0.02 * areas.max(), 0.0003 * mascara.size)
    return np.isin(etiquetas, 1 + np.flatnonzero(areas >= minimo))


def lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)


def distancia(lab_img: np.ndarray, color: np.ndarray) -> np.ndarray:
    # La luminosidad pesa la mitad: los degradados de luz de la cartulina varían sobre todo en L
    d = lab_img - color
    return np.sqrt((0.5 * d[..., 0]) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)


def anillo(producto: np.ndarray, r_in: float, r_out: float) -> np.ndarray:
    lado = max(producto.shape)
    elipse = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m = producto.astype(np.uint8)
    exterior = cv2.dilate(m, elipse(max(1, int(lado * r_out))))
    interior = cv2.dilate(m, elipse(max(1, int(lado * r_in))))
    return (exterior > 0) & (interior == 0)


def muestrear_fondo(small: np.ndarray, producto: np.ndarray):
    """Color de la cartulina (LAB) y píxeles semilla alrededor del producto."""
    zona = anillo(producto, 0.015, 0.05)
    if not zona.any():
        zona = ~producto
    lab_img = lab(small)
    color = np.median(lab_img[zona], axis=0)
    # Semillas: píxeles del anillo cercanos al color típico (descarta sombras y paredes)
    ys, xs = np.nonzero(zona & (distancia(lab_img, color) < 12))
    return color, list(zip(xs, ys))


def detectar_cartulina(small, producto, color, semillas) -> np.ndarray:
    """Región continua de cartulina: relleno por inundación desde las semillas.

    La tolerancia es entre vecinos, así sigue los degradados suaves de luz pero se
    detiene en los bordes de las paredes. El tope global evita fugas por bordes difusos.
    """
    suave = cv2.GaussianBlur(small, (0, 0), 1.5)
    lab_img = lab(suave)
    h, w = producto.shape
    tex = textura(small)
    # La cartulina es lisa; las paredes de papel aluminio tienen mucho detalle fino
    tex_cartulina = np.median(tex[tuple(np.array(semillas).T[::-1])]) if semillas else 0
    barrera = (producto | (distancia(lab_img, color) > TOL_GLOBAL)
               | (tex > max(TEX_FACTOR * tex_cartulina, TEX_MIN)))
    mascara = np.zeros((h + 2, w + 2), np.uint8)
    mascara[1:-1, 1:-1][barrera] = 1
    lab8 = cv2.cvtColor(suave, cv2.COLOR_RGB2LAB)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (2 << 8)
    rng = np.random.default_rng(0)
    for i in rng.permutation(len(semillas))[:300]:
        x, y = semillas[i]
        if mascara[y + 1, x + 1] == 0:
            cv2.floodFill(lab8, mascara, (int(x), int(y)), 0, TOL_VECINO, TOL_VECINO, flags)
    return mascara[1:-1, 1:-1] == 2


def textura(rgb: np.ndarray) -> np.ndarray:
    """Energía local de detalle fino (magnitud del gradiente de L, promediada)."""
    L = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.blur(np.sqrt(gx * gx + gy * gy), (9, 9))


def detectar_paredes(cartulina: np.ndarray, producto: np.ndarray) -> np.ndarray:
    """Lo que no es cartulina ni producto y toca el borde de la foto (paredes, mesa...)."""
    lado = max(producto.shape)
    r = max(1, int(lado * 0.01))
    halo = cv2.dilate(producto.astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    resto = (~cartulina & ~halo).astype(np.uint8)
    n, etiquetas = cv2.connectedComponents(resto, connectivity=8)
    borde = np.unique(np.concatenate([etiquetas[0], etiquetas[-1], etiquetas[:, 0], etiquetas[:, -1]]))
    borde = borde[borde > 0]
    return np.isin(etiquetas, borde)


def recorte_cuadrado(producto: np.ndarray, k: float, w: int, h: int, size: int):
    """Caja cuadrada (x0, y0, lado) en píxeles de la foto original; puede salirse de ella."""
    ys, xs = np.nonzero(producto)
    x0, x1 = xs.min() / k, (xs.max() + 1) / k
    y0, y1 = ys.min() / k, (ys.max() + 1) / k
    lado = max(x1 - x0, y1 - y0) / OCUPACION
    lado = max(lado, size / MAX_AMPLIACION)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # Si el producto está cortado por un borde de la foto, se alinea con ese borde
    # en vez de centrarlo (si no, se vería el corte flotando sobre fondo inventado)
    margen = 0.01 * max(w, h)
    toca = lambda a, b: a <= margen and not b
    if toca(x0, x1 >= w - margen):
        cx = lado / 2
    elif toca(w - x1, x0 <= margen):
        cx = w - lado / 2
    if toca(y0, y1 >= h - margen):
        cy = lado / 2
    elif toca(h - y1, y0 <= margen):
        cy = h - lado / 2
    lado = int(round(lado))
    return int(round(cx - lado / 2)), int(round(cy - lado / 2)), lado


def recortar(img: np.ndarray, caja, size: int):
    """Recorta la caja (rellenando con ceros lo que sale de la foto) y la lleva a size x size."""
    x0, y0, lado = caja
    h, w = img.shape[:2]
    ix0, iy0 = max(x0, 0), max(y0, 0)
    ix1, iy1 = min(x0 + lado, w), min(y0 + lado, h)
    pad = (iy0 - y0, y0 + lado - iy1, ix0 - x0, x0 + lado - ix1)
    trozo = cv2.copyMakeBorder(img[iy0:iy1, ix0:ix1], *pad, cv2.BORDER_CONSTANT, value=0)
    valido = cv2.copyMakeBorder(np.ones((iy1 - iy0, ix1 - ix0), np.float32), *pad,
                                cv2.BORDER_CONSTANT, value=0)
    reducir = lado > size
    trozo = cv2.resize(trozo, (size, size), interpolation=cv2.INTER_AREA if reducir else cv2.INTER_CUBIC)
    # Los píxeles del borde que se mezclaron con el relleno negro también cuentan como inválidos
    valido = cv2.resize(valido, (size, size),
                        interpolation=cv2.INTER_AREA if reducir else cv2.INTER_LINEAR) > 0.999
    return trozo, valido


def superficie_fondo(lienzo: np.ndarray, limpio: np.ndarray, color_lab: np.ndarray) -> np.ndarray:
    """Superficie suave que extiende el color de la cartulina limpia, con grano.

    Cada píxel a rellenar toma el color de la cartulina limpia más cercana, y se
    difumina más cuanto más lejos está. Así el relleno continúa el tono exacto del
    borde (degradados de luz, viñeteado) y se vuelve uniforme al alejarse.
    """
    size = lienzo.shape[0]
    lado = 256  # la superficie es suave: se calcula en baja resolución
    f = lienzo.astype(np.float32)
    m = cv2.resize(limpio.astype(np.float32), (lado, lado), interpolation=cv2.INTER_AREA)
    suma = cv2.resize(f * limpio[..., None], (lado, lado), interpolation=cv2.INTER_AREA)
    base = m > 0.5
    if base.sum() < 50:
        # Casi no hay cartulina visible: color plano muestreado
        rgb = cv2.cvtColor(np.uint8([[color_lab]]), cv2.COLOR_LAB2RGB)[0, 0].astype(np.float32)
        return np.broadcast_to(rgb, lienzo.shape).astype(np.uint8)
    color = suma[base] / m[base][:, None]
    dist, etiquetas = cv2.distanceTransformWithLabels(
        (~base).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    cercano = color[etiquetas - 1]  # las etiquetas siguen el orden de np.nonzero(base)
    cerca, lejos = cv2.GaussianBlur(cercano, (0, 0), 2), cv2.GaussianBlur(cercano, (0, 0), 12)
    t = np.clip(dist / 24, 0, 1)[..., None]
    fondo = cv2.resize(cerca * (1 - t) + lejos * t, (size, size), interpolation=cv2.INTER_CUBIC)

    # Grano: misma intensidad que el ruido de alta frecuencia de la cartulina real
    detalle = (f - cv2.GaussianBlur(f, (0, 0), 3))[limpio]
    sigma = 1.4826 * np.median(np.abs(detalle - np.median(detalle, axis=0)), axis=0)
    ruido = np.random.default_rng(1).standard_normal(lienzo.shape).astype(np.float32)
    ruido = cv2.GaussianBlur(ruido, (0, 0), 0.7)
    ruido /= max(ruido.std(), 1e-6)
    return np.clip(fondo + ruido * sigma, 0, 255).astype(np.uint8)


def mezclar(lienzo, fondo, rellenar, prob_producto) -> np.ndarray:
    """Pone el fondo en la zona a rellenar con borde difuminado, sin tocar el producto."""
    size = lienzo.shape[0]
    r = max(2, int(size * 0.04))
    elipse = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m = rellenar.astype(np.float32)
    alfa = cv2.GaussianBlur(cv2.dilate(m, elipse), (0, 0), r / 2)
    alfa = np.maximum(alfa, m) * (1 - np.clip(prob_producto * 1.5, 0, 1))
    alfa = alfa[..., None]
    return (lienzo * (1 - alfa) + fondo * alfa).astype(np.uint8)
