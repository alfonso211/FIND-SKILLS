"""Dotación estándar de los apartamentos turísticos (categoría 3 llaves): catálogo maestro por zonas con la cantidad
de cada perfil. Los perfiles siguen la capacidad base de aprovisionamiento:

    estudio   Estudio, 2 plazas                       (AMENITY_STUDIO_3K)
    1d        1 dormitorio, 2 a 4 plazas              (AMENITY_1BED_3K)
    2d        2 dormitorios, 4 a 6 plazas             (AMENITY_2BED_3K)
    vip       VIP / Premium: misma base con calidades superiores (AMENITY_VIP_3K)

En vajilla y cubertería la regla habitual es «nº de plazas + 2» unidades de repuesto. Un «—» o «No» significa que ese
perfil no lo lleva. Recepción parte de esta lista para fijar la dotación habitual de cada apartamento."""

PERFILES = {"estudio": "Estudio (2 plazas)", "1d": "1 dormitorio (2-4 plazas)", "2d": "2 dormitorios (4-6 plazas)",
            "vip": "VIP / Premium"}
CODIGO_PERFIL = {"estudio": "AMENITY_STUDIO_3K", "1d": "AMENITY_1BED_3K", "2d": "AMENITY_2BED_3K", "vip": "AMENITY_VIP_3K"}

ZONAS = {
    "salon": "Zona de estar / Salón - comedor",
    "cocina": "Cocina: electrodomésticos y gran menaje",
    "menaje": "Cocina: vajilla, cubertería y pequeño menaje",
    "dormitorio": "Dormitorios",
    "bano": "Baño(s)",
    "auxiliar": "Limpieza, climatización y elementos auxiliares",
}

# (código, zona, artículo, estudio, 1 dormitorio, 2 dormitorios, VIP)
_TABLA = [
    # 1. Salón - comedor
    ("SAL01", "salon", "Smart TV", '43"', '50"', '50"-55"', '55"-65" OLED/QLED + barra de sonido'),
    ("SAL02", "salon", "Mando a distancia TV con funda", "1", "1", "1", "1"),
    ("SAL03", "salon", "Mesa de comedor", "Integrada / barra", "1 (4 plazas)", "1 (6 plazas)", "1 de diseño (4-6 plazas)"),
    ("SAL04", "salon", "Sillas de comedor", "2", "4", "6", "4 a 6 tapizadas"),
    ("SAL05", "salon", "Sofá / sofá-cama con apertura italiana", "1 (2 plazas)", "1 sofá-cama 140", "1 sofá-cama 160",
     "Sofá de diseño, apertura premium"),
    ("SAL06", "salon", "Mesa de centro / auxiliar", "1", "1", "1-2", "1-2 de diseño"),
    ("SAL07", "salon", "Lámpara de pie / luz indirecta", "1", "1", "1", "1 regulable (dimmer)"),
    ("SAL08", "salon", "Cuadros / elementos decorativos", "1-2", "2-3", "3-4", "Set de decoración"),
    ("SAL09", "salon", "Espejo de cuerpo entero", "1", "1", "1", "1 retroiluminado"),
    ("SAL10", "salon", "Enchufes USB / tomas en pared", "2", "2-4", "4", "USB-C rápidos + cargador inalámbrico"),
    # 2. Cocina: electrodomésticos y gran menaje
    ("COC01", "cocina", "Placa de cocción (inducción / vitro)", "2 fuegos", "2-3 fuegos", "3-4 fuegos",
     "3-4 fuegos inducción flexible"),
    ("COC02", "cocina", "Campana extractora", "1", "1", "1", "1 integrada silenciosa"),
    ("COC03", "cocina", "Frigorífico", "Bajo encimera / combi", "Combi no frost", "Combi no frost",
     "Combi integrable gran formato"),
    ("COC04", "cocina", "Microondas con grill", "1", "1", "1", "1 integrable"),
    ("COC05", "cocina", "Horno convencional", "No", "Opcional", "1 integrado", "1 pirolítico / multifunción"),
    ("COC06", "cocina", "Lavavajillas", "45 cm o compacto", "45 cm", "60 cm", "60 cm integrado silencioso"),
    ("COC07", "cocina", "Lavadora / lavadora-secadora", "Central o 1", "1", "1", "1 lavadora-secadora integrada"),
    ("COC08", "cocina", "Cafetera de cápsulas", "1", "1", "1", "1 Nespresso / superautomática + espumador"),
    ("COC09", "cocina", "Hervidor de agua", "1", "1", "1", "1 de temperatura regulable"),
    ("COC10", "cocina", "Tostadora", "1", "1", "1", "1 doble ranura ancha"),
    ("COC11", "cocina", "Batidora de mano con vaso", "1", "1", "1", "1 con set de accesorios"),
    ("COC12", "cocina", "Exprimidor", "1", "1", "1", "1 eléctrico"),
    # 3. Vajilla, cubertería y pequeño menaje
    ("MEN01", "menaje", "Platos llanos", "4", "6", "8", "8-10 porcelana / gres alta gama"),
    ("MEN02", "menaje", "Platos hondos", "4", "6", "8", "8-10 porcelana / gres alta gama"),
    ("MEN03", "menaje", "Platos de postre", "4", "6", "8", "8-10 porcelana / gres alta gama"),
    ("MEN04", "menaje", "Vasos de agua / refresco", "4", "6", "8", "8-10 cristal fino"),
    ("MEN05", "menaje", "Copas de vino", "2", "4", "6", "6-8 tinto / blanco"),
    ("MEN06", "menaje", "Copas de cava / champán", "—", "—", "—", "4-6"),
    ("MEN07", "menaje", "Tazas de café con plato", "4", "6", "8", "8"),
    ("MEN08", "menaje", "Tazas de desayuno (mugs)", "4", "6", "8", "8"),
    ("MEN09", "menaje", "Tenedores", "4", "6", "8", "8-10 acero 18/10"),
    ("MEN10", "menaje", "Cuchillos de mesa", "4", "6", "8", "8-10 acero 18/10"),
    ("MEN11", "menaje", "Cucharas", "4", "6", "8", "8-10 acero 18/10"),
    ("MEN12", "menaje", "Cucharillas", "4", "6", "8", "8-10 acero 18/10"),
    ("MEN13", "menaje", "Cuchillos chuleteros", "2", "4", "6", "6"),
    ("MEN14", "menaje", "Sartenes (pequeña, mediana, grande)", "2", "3", "3", "3 aluminio forjado / antiadherente"),
    ("MEN15", "menaje", "Cazuela, cacerola y olla con tapa", "2 piezas", "3 piezas", "3 piezas",
     "3 piezas acero inoxidable inducción"),
    ("MEN16", "menaje", "Set de cuchillos (chef, panero y puntilla)", "1 set", "1 set", "1 set",
     "1 set con taco o barra imantada"),
    ("MEN17", "menaje", "Tabla de corte", "1", "1-2", "2", "2 bambú / acacia"),
    ("MEN18", "menaje", "Ensaladera / bol grande", "1", "1", "2", "2"),
    ("MEN19", "menaje", "Utensilios: cucharón, espumadera, espátula y pinzas", "1 set", "1 set", "1 set",
     "1 set silicona / madera"),
    ("MEN20", "menaje", "Abrelatas", "1", "1", "1", "1"),
    ("MEN21", "menaje", "Sacacorchos / descorchador", "1", "1", "1", "1 profesional de dos tiempos"),
    ("MEN22", "menaje", "Pelador", "1", "1", "1", "1"),
    ("MEN23", "menaje", "Colador de pasta / verduras", "1", "1", "1", "1"),
    ("MEN24", "menaje", "Escurreplatos", "1", "1", "1", "Oculto / integrado"),
    ("MEN25", "menaje", "Cubo de basura con separación de reciclaje", "1", "1", "1", "1 doble / triple con pedal"),
    ("MEN26", "menaje", "Salvamanteles térmicos", "2", "2", "3", "3-4"),
    # 4. Dormitorios
    ("DOR01", "dormitorio", "Cama principal", "150/160", "160/180", "Principal 160/180 + secundario 2x90",
     "King size 180x200 o 200x200"),
    ("DOR02", "dormitorio", "Canapé o base tapizada con cabecero", "1", "1", "2", "Tapizado de diseño"),
    ("DOR03", "dormitorio", "Mesillas de noche con luz de lectura", "1-2", "2", "4 (2 por habitación)",
     "2 a 4 con USB / cargador inductivo"),
    ("DOR04", "dormitorio", "Smart TV en dormitorio principal", "No", "Opcional", "Opcional", '1 de 43"-50" en pared'),
    ("DOR05", "dormitorio", "Armario empotrado o exento", "1 cuerpo", "2 cuerpos", "2 cuerpos por habitación",
     "Con iluminación LED interior"),
    ("DOR06", "dormitorio", "Perchas antideslizantes de madera", "8", "12", "20 (10 por habitación)", "16-24 madera maciza"),
    ("DOR07", "dormitorio", "Caja fuerte electrónica (apta para portátil)", "1", "1", "1", "1 motorizada con luz"),
    ("DOR08", "dormitorio", "Almohadas", "2", "4 (2 firmes, 2 medias)", "6-8", "Carta de almohadas"),
    ("DOR09", "dormitorio", "Protectores de colchón y almohada", "1 juego", "1 juego", "2 juegos",
     "Doble juego impermeable transpirable"),
    ("DOR10", "dormitorio", "Juego de sábanas (200+ hilos)", "1 por cama", "1 por cama", "1 por cama",
     "Algodón egipcio / satén 300+ hilos"),
    ("DOR11", "dormitorio", "Nórdico / edredón con funda y cuadrantes", "1", "1", "2", "Nórdico 4 estaciones + cojines"),
    ("DOR12", "dormitorio", "Manta auxiliar / plaid", "1", "1", "2", "2 plaids"),
    # 5. Baño(s)
    ("BAN01", "bano", "Plato de ducha con mampara", "1", "1", "1 o 2 baños", "Ducha efecto lluvia termostática"),
    ("BAN02", "bano", "Espejo de lavabo", "1", "1", "1 o 2", "Retroiluminado LED antivaho"),
    ("BAN03", "bano", "Espejo de aumento", "Opcional", "1", "1", "1 articulado iluminado"),
    ("BAN04", "bano", "Secador de pelo (mín. 1800 W)", "1", "1", "1", "1 iónico alta potencia"),
    ("BAN05", "bano", "Papelera de baño con pedal", "1", "1", "1 o 2", "Inox / negro mate cierre amortiguado"),
    ("BAN06", "bano", "Escobillero de váter cerrado", "1", "1", "1 o 2", "1 o 2 a juego con grifería"),
    ("BAN07", "bano", "Dosificadores (gel, champú, jabón de manos)", "1 set", "1 set", "1 o 2 sets",
     "Dispensadores recargables premium"),
    ("BAN08", "bano", "Toalleros y perchas", "2 perchas", "2-3 perchas", "4 perchas", "Toallero radiador eléctrico"),
    ("BAN09", "bano", "Toallas de baño (100x150)", "2", "4", "6", "6 de 550-600 g/m²"),
    ("BAN10", "bano", "Toallas de lavabo", "2", "4", "6", "6 de 550-600 g/m²"),
    ("BAN11", "bano", "Alfombrín de baño", "2", "4", "6", "6"),
    ("BAN12", "bano", "Albornoces y zapatillas de cortesía", "—", "—", "—", "2 a 4"),
    # 6. Limpieza, climatización y auxiliares
    ("AUX01", "auxiliar", "Climatización frío / calor (termostato digital)", "1 split / rejilla", "Salón + dormitorio",
     "Salón + 2 dormitorios", "Por zonas / domotizada"),
    ("AUX02", "auxiliar", "Cerradura electrónica / inteligente", "1", "1", "1", "Teclado / móvil / código PMS"),
    ("AUX03", "auxiliar", "Plancha de vapor y tabla de planchar", "1 tabla compacta", "1 juego", "1 juego",
     "Centro de planchado / vapor vertical"),
    ("AUX04", "auxiliar", "Tendedero plegable", "1", "1", "1", "1"),
    ("AUX05", "auxiliar", "Cubo de fregar con escurridor y fregona", "1", "1", "1", "1 en armario técnico"),
    ("AUX06", "auxiliar", "Escoba y recogedor", "1", "1", "1", "1"),
    ("AUX07", "auxiliar", "Aspirador / escoba eléctrica", "Opcional", "Opcional", "Opcional", "1 vertical inalámbrico"),
    ("AUX08", "auxiliar", "Extintor homologado (DB-SI)", "1 (o en pasillo)", "1 (o en pasillo)", "1 (o en pasillo)",
     "1 (o en pasillo común)"),
    ("AUX09", "auxiliar", "Manta apagafuegos en cocina", "1", "1", "1", "1"),
    ("AUX10", "auxiliar", "Botiquín de primeros auxilios", "1", "1", "1", "1"),
]

CATALOGO = [{"codigo": c, "zona": z, "articulo": a, "cantidades": dict(zip(PERFILES, cant))}
            for c, z, a, *cant in _TABLA]
POR_CODIGO = {x["codigo"]: x for x in CATALOGO}
NO_INCLUIDO = {"—", "No", ""}


def perfil_de(tipologia: str | None, vip: bool = False) -> str:
    """Perfil de dotación según la tipología de la unidad (estudio, 1 dormitorio, 2 dormitorios)."""
    if vip:
        return "vip"
    t = (tipologia or "").lower()
    if "2" in t:
        return "2d"
    if "1" in t:
        return "1d"
    if "est" in t or t in ("e", "st"):
        return "estudio"
    return "1d"


def estandar(perfil: str) -> list[dict]:
    """Dotación estándar de un perfil, lista para que recepción la ajuste (sin lo que ese perfil no lleva)."""
    return [{"codigo": x["codigo"], "zona": x["zona"], "articulo": x["articulo"], "cantidad": x["cantidades"][perfil]}
            for x in CATALOGO if x["cantidades"][perfil] not in NO_INCLUIDO]
