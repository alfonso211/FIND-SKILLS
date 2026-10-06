"""Genera documentos de identidad SIMULADOS (datos ficticios) para probar la lectura automática."""
import io

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.mrz import digito

FUENTE_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def mrz_dni(soporte="BAA000589", dni="99999999R", nac="800101", sexo="F", cad="310602",
            apellidos="MARTIN<SANZ", nombre="LUCIA", tipo="ID"):
    l1 = f"{tipo}ESP{soporte}{digito(soporte)}{dni}".ljust(30, "<")
    l2 = f"{nac}{digito(nac)}{sexo}{cad}{digito(cad)}ESP".ljust(29, "<")
    l2 += digito(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29])
    l3 = f"{apellidos}<<{nombre}".ljust(30, "<")
    return [l1, l2, l3]


def mrz_pasaporte(numero="XDB123456", pais="FRA", nac="850315", sexo="M", cad="300101",
                  apellidos="DUPONT", nombre="JEAN<PIERRE"):
    l1 = f"P<{pais}{apellidos}<<{nombre}".ljust(44, "<")
    personal = "<" * 14
    l2 = f"{numero}{digito(numero)}{pais}{nac}{digito(nac)}{sexo}{cad}{digito(cad)}{personal}<"
    l2 += digito(l2[0:10] + l2[13:20] + l2[21:43])
    return [l1, l2]


def tarjeta(lineas_texto, lineas_mrz, ancho=1300, girar=0, borroso=False, formato="PNG"):
    img = Image.new("RGB", (ancho, int(ancho * 0.63)), (235, 238, 242))
    d = ImageDraw.Draw(img)
    f, fm = ImageFont.truetype(FUENTE, 30), ImageFont.truetype(FUENTE_MONO, 38)
    y = 40
    for t in lineas_texto:
        d.text((40, y), t, font=f, fill=(20, 20, 20))
        y += 42
    y = img.height - 50 * len(lineas_mrz) - 30
    for ln in lineas_mrz:
        d.text((30, y), ln, font=fm, fill=(10, 10, 10))
        y += 50
    if borroso:
        img = img.filter(ImageFilter.GaussianBlur(1.2))
    if girar:
        img = img.rotate(girar, expand=True, fillcolor=(255, 255, 255))
    out = io.BytesIO()
    if formato == "PDF":
        img.save(out, "PDF", resolution=200)
    else:
        img.save(out, formato, quality=70)
    return out.getvalue()


def reverso_dni(**kw):
    texto = ["DOMICILIO", "C. MAYOR 1 P03 B", "SEVILLA", "SEVILLA", "LUGAR DE NACIMIENTO", "SEVILLA"]
    return tarjeta(texto, mrz_dni(), **kw)


def foto_camara(doc: bytes, angulo=6.0, escala=0.45, luz=0.4, semilla=1) -> bytes:
    """Simula una foto de webcam/móvil: documento pequeño y torcido sobre la mesa, luz irregular, JPEG."""
    import numpy as np
    rnd = np.random.default_rng(semilla)
    ancho, alto = 1920, 1080
    fondo = Image.fromarray(rnd.normal(120, 25, (alto, ancho, 3)).clip(0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))
    card = Image.open(io.BytesIO(doc)).convert("RGB")
    w = int(ancho * escala)
    card = card.resize((w, int(w * card.height / card.width)), Image.LANCZOS)
    mascara = Image.new("L", card.size, 255).rotate(angulo, expand=True)
    card = card.rotate(angulo, expand=True)
    fondo.paste(card, ((ancho - card.width) // 2, (alto - card.height) // 2), mascara)
    a = np.asarray(fondo).astype(float) * np.linspace(1 - luz, 1, ancho)[None, :, None]
    out = io.BytesIO()
    Image.fromarray(a.clip(0, 255).astype("uint8")).save(out, "JPEG", quality=70)
    return out.getvalue()
