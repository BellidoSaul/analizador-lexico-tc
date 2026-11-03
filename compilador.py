"""Compilador (transpilador) del DSL de fichas de merma: léxico -> sintáctico -> semántico -> traducción.

Usa el analizador léxico de automata.py (ER -> AFND -> AFD) y agrega:
  * análisis sintáctico (GLC, derivación por la izquierda y árbol sintáctico),
  * análisis semántico (reglas de negocio y atributos sintetizados / heredados),
  * traducción a SQL y JSON,
  * reporte PDF y registro de cada ejecución en un archivo CSV.
"""
import csv
import io
import json
import os
from datetime import date, datetime

from automata import TOKENS, tokenizar

# ------------------------------------------------------------------ GRAMÁTICA
# Posición -> (variable, campo esperado, token esperado)
ORDEN = [
    ("<Lote>", "Lote", "T_LOTE"),
    ("<Producto>", "Producto", "T_TEXTO"),
    ("<Proveedor>", "Proveedor", "T_TEXTO"),
    ("<Fecha>", "Fecha", "T_FECHA"),
    ("<Motivo>", "Motivo", "T_MOTIVO"),
    ("<Cantidad>", "Cantidad", "T_CANTIDAD"),
]

GRAMATICA = {
    "V": ["<Reporte>"] + [v for v, _, _ in ORDEN],
    "T": [n for n, _, _ in TOKENS],
    "S": "<Reporte>",
    "P": ["<Reporte> -> " + " ".join(v for v, _, _ in ORDEN)]
         + [f"{v} -> {t}" for v, _, t in ORDEN],
}

# Reglas de negocio (semánticas). Ajustables.
MAX_KG = 5000
MOTIVOS = {"D": "DAÑADO", "P": "PERECIBLE"}


def campo_de(lexema):
    return lexema.split(":", 1)[0].strip()


def valor_de(lexema):
    return lexema.split(":", 1)[1].strip()


# ------------------------------------------------------------------ SINTÁCTICO
def analizar_sintaxis(tokens):
    """Parser descendente predictivo (LL(1)) para <Reporte>. Devuelve (arbol, derivacion, errores)."""
    errores = []
    hijos = []
    for i, (var, campo, tok) in enumerate(ORDEN):
        if i >= len(tokens):
            errores.append((None, f"Error sintáctico: falta el campo «{campo}» ({tok}); la ficha termina antes de completar <Reporte>."))
            break
        t = tokens[i]
        if t["token"] != tok or campo_de(t["lexema"]) != campo:
            errores.append((t["línea"], f"Error sintáctico en la línea {t['línea']}: se esperaba «{campo}» ({tok}) "
                                        f"pero se encontró «{campo_de(t['lexema'])}» ({t['token']}). "
                                        f"Se viola la producción <Reporte> -> {' '.join(v for v, _, _ in ORDEN)}."))
            break
        hijos.append({"nombre": var, "hijos": [{"nombre": tok, "lexema": t["lexema"], "hijos": []}]})
    else:
        if len(tokens) > len(ORDEN):
            ex = tokens[len(ORDEN)]
            errores.append((ex["línea"], f"Error sintáctico en la línea {ex['línea']}: «{campo_de(ex['lexema'])}» sobra o está repetido; "
                                         "después de <Cantidad> la ficha debe terminar."))
    arbol = {"nombre": "<Reporte>", "hijos": hijos} if not errores else None

    # derivación por la izquierda
    forma = ["<Reporte>"]
    deriv = [" ".join(forma)]
    forma = [v for v, _, _ in ORDEN]
    deriv.append(" ".join(forma) + "      [P1]")
    for i, (var, campo, tok) in enumerate(ORDEN):
        if i >= len(hijos):
            break
        forma[i] = tok
        deriv.append(" ".join(forma) + f"      [{var} -> {tok}]")
    return arbol, deriv, errores


def arbol_a_dot(arbol, anotado=None):
    """DOT del árbol sintáctico. `anotado` = {variable: 'atributo'} para mostrar atributos semánticos."""
    anotado = anotado or {}
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    L = ["digraph T {", 'bgcolor="transparent";', 'node [fontname="Helvetica", fontsize=11];']
    n = [0]

    def rec(nodo):
        mi = f"n{n[0]}"
        n[0] += 1
        if nodo["hijos"]:
            et = nodo["nombre"] + (("\\n" + esc(anotado[nodo["nombre"]])) if nodo["nombre"] in anotado else "")
            L.append(f'{mi} [shape=ellipse, label="{et}"];')
            for h in nodo["hijos"]:
                L.append(f"{mi} -> {rec(h)};")
        else:
            L.append(f'{mi} [shape=box, style=filled, fillcolor="#e8f0fe", label="{nodo["nombre"]}\\n{esc(nodo.get("lexema", ""))}"];')
        return mi

    rec(arbol)
    L.append("}")
    return "\n".join(L)


# ------------------------------------------------------------------ SEMÁNTICO
def analizar_semantica(arbol):
    """Calcula atributos y valida reglas de negocio. Devuelve (registro, atributos, errores)."""
    reg, attrs, errores = {}, [], []
    for h in arbol["hijos"]:
        var, hoja = h["nombre"], h["hijos"][0]
        campo, val = campo_de(hoja["lexema"]), valor_de(hoja["lexema"])
        if var in ("<Producto>", "<Proveedor>"):
            attrs.append((var, "heredado", f"campo = {campo} (lo fija la posición en la producción)", val))
            reg[campo.lower()] = val
        elif var == "<Lote>":
            attrs.append((var, "sintetizado", "lote.val = código de trazabilidad", val))
            reg["lote"] = val
        elif var == "<Fecha>":
            d, m, y = (int(x) for x in val.split("/"))
            try:
                iso = date(y, m, d).isoformat()
                attrs.append((var, "sintetizado", "fecha.iso = AAAA-MM-DD", iso))
                reg["fecha"] = iso
            except ValueError:
                errores.append(f"Error semántico: la fecha {val} no existe en el calendario (S1).")
        elif var == "<Motivo>":
            attrs.append((var, "sintetizado", f"motivo.desc = {val} -> descripción", MOTIVOS[val]))
            reg["motivo"] = val
        elif var == "<Cantidad>":
            kg = int(val[:-2])
            attrs.append((var, "sintetizado", "cantidad.kg = entero sin la unidad", str(kg)))
            if kg > MAX_KG:
                errores.append(f"Error semántico: la cantidad {kg} KG supera el máximo permitido por reporte ({MAX_KG} KG) (S2).")
            else:
                reg["cantidad_kg"] = kg
    return reg, attrs, errores


REGLAS_SEMANTICAS = [
    ("S1", "La fecha debe existir en el calendario (p. ej. 31/02 es inválida; el AFD solo valida el formato)."),
    ("S2", f"La cantidad no puede superar {MAX_KG} KG por reporte (regla de negocio configurable)."),
    ("S3", "Motivo D = DAÑADO y P = PERECIBLE (atributo sintetizado)."),
    ("S4", "Producto y Proveedor comparten T_TEXTO; su campo se hereda de la posición en la producción."),
]


# ------------------------------------------------------------------ TRADUCCIÓN
def traducir(reg):
    sql = ("INSERT INTO mermas (lote, producto, proveedor, fecha, motivo, cantidad_kg)\n"
           f"VALUES ('{reg['lote']}', '{reg['producto']}', '{reg['proveedor']}', "
           f"'{reg['fecha']}', '{reg['motivo']}', {reg['cantidad_kg']});")
    js = json.dumps({"lote": reg["lote"], "producto": reg["producto"], "proveedor": reg["proveedor"],
                     "fecha": reg["fecha"], "motivo": reg["motivo"], "motivo_desc": MOTIVOS[reg["motivo"]],
                     "cantidad_kg": reg["cantidad_kg"]}, ensure_ascii=False, indent=2)
    return sql, js


# ------------------------------------------------------------------ PIPELINE
def procesar(texto, minimiza=False):
    """Ejecuta todas las fases y se detiene en la primera que falle."""
    r = {"texto": texto, "momento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tokens": [], "errores": [],
         "arbol": None, "derivacion": [], "registro": None, "atributos": [], "sql": None, "json": None,
         "etapa": "léxico", "valido": False}
    if not texto.strip():
        r["errores"] = ["Error léxico: la ficha está vacía."]
        return r
    tokens, err = tokenizar(texto, minimiza)
    r["tokens"] = tokens
    if err:
        r["errores"] = [f"Línea {nl}, columna {c}: {m}" for nl, c, m in err]
        return r
    r["etapa"] = "sintáctico"
    arbol, deriv, err = analizar_sintaxis(tokens)
    r["derivacion"] = deriv
    if err:
        r["errores"] = [m for _, m in err]
        return r
    r["arbol"] = arbol
    r["etapa"] = "semántico"
    reg, attrs, err = analizar_semantica(arbol)
    r["atributos"] = attrs
    if err:
        r["errores"] = err
        return r
    r["registro"] = reg
    r["sql"], r["json"] = traducir(reg)
    r["etapa"], r["valido"] = "traducción", True
    return r


# ------------------------------------------------------------------ REGISTRO (archivo)
RUTA_LOG = "registro_traducciones.csv"
COLUMNAS_LOG = ["fecha_hora", "estado", "etapa", "lote", "detalle"]


def registrar(r, ruta=RUTA_LOG):
    """Agrega una fila al archivo CSV de registro (se crea si no existe)."""
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(COLUMNAS_LOG)
        lote = (r["registro"] or {}).get("lote") or next(
            (valor_de(t["lexema"]) for t in r["tokens"] if t["token"] == "T_LOTE"), "")
        detalle = r["sql"].replace("\n", " ") if r["valido"] else " | ".join(r["errores"])
        w.writerow([r["momento"], "VÁLIDA" if r["valido"] else "INVÁLIDA", r["etapa"], lote, detalle])


def leer_registro(ruta=RUTA_LOG):
    if not os.path.exists(ruta):
        return []
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ PDF
def generar_pdf(r):
    """Reporte PDF de la traducción (tokens, gramática, árbol, semántica y SQL/JSON)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.graphics.shapes import Drawing, Line, Rect, String

    est = getSampleStyleSheet()
    h1, h2, nrm = est["Heading1"], est["Heading2"], est["BodyText"]
    mono = ParagraphStyle("mono", parent=nrm, fontName="Courier", fontSize=8, leading=10)
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ancho = A4[0] - 4 * cm

    def tabla(filas, cols, cab=True):
        data = [[Paragraph(esc(c), ParagraphStyle("c", parent=nrm, fontSize=8, leading=10)) for c in f] for f in filas]
        t = Table(data, colWidths=cols, repeatRows=1 if cab else 0)
        sty = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if cab:
            sty.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe5f1")))
        t.setStyle(TableStyle(sty))
        return t

    S = [Paragraph("Reporte de traducción - Fichas de mermas e inventarios", h1),
         Paragraph("Teoría de la Computación · Gourmet Express S.A.C. · DSL con analizador léxico, sintáctico, semántico y transpilador a SQL", nrm),
         Paragraph(f"Fecha y hora: {r['momento']}", nrm), Spacer(1, 8)]
    veredicto = "FICHA VÁLIDA: traducida a SQL" if r["valido"] else f"FICHA INVÁLIDA: el proceso se detuvo en el análisis {r['etapa']}"
    S += [Paragraph(f"<b>Resultado: {veredicto}</b>", h2), Paragraph("Ficha de entrada", h2),
          Preformatted(r["texto"].strip(), mono)]
    if r["errores"]:
        S += [Paragraph("Errores detectados", h2)] + [Paragraph("- " + esc(e), nrm) for e in r["errores"]]
    if r["tokens"]:
        S += [Paragraph("3.1 Análisis léxico (lexemas agrupados)", h2),
              tabla([["Línea", "Lexema", "Token", "Expresión regular"]] +
                    [[t["línea"], t["lexema"], t["token"], t["er"].replace(" ", "_")] for t in r["tokens"]],
                    [1.2 * cm, 4.3 * cm, 2.7 * cm, ancho - 8.2 * cm]),
              Paragraph("_ representa el espacio en blanco.", nrm)]
    if r["derivacion"]:
        S += [Paragraph("3.2 Análisis sintáctico", h2),
              Paragraph("G = (V, T, P, S), S = &lt;Reporte&gt;. Producciones: " + "; ".join(esc(p) for p in GRAMATICA["P"]), nrm),
              Paragraph("Derivación por la izquierda:", nrm),
              Preformatted("\n".join("=> " + d if i else d for i, d in enumerate(r["derivacion"])), mono)]
    if r["arbol"]:
        hh = 4.2 * cm
        d = Drawing(ancho, hh)
        n = len(r["arbol"]["hijos"])
        paso = ancho / n
        d.add(Rect(ancho / 2 - 1.2 * cm, hh - 0.8 * cm, 2.4 * cm, 0.7 * cm, strokeColor=colors.black, fillColor=colors.white))
        d.add(String(ancho / 2, hh - 0.55 * cm, "<Reporte>", textAnchor="middle", fontSize=8))
        for i, h in enumerate(r["arbol"]["hijos"]):
            x = paso * i + paso / 2
            d.add(Line(ancho / 2, hh - 0.8 * cm, x, hh - 1.8 * cm))
            d.add(Rect(x - paso / 2 + 2, hh - 2.5 * cm, paso - 4, 0.7 * cm, strokeColor=colors.black, fillColor=colors.white))
            d.add(String(x, hh - 2.25 * cm, h["nombre"], textAnchor="middle", fontSize=7))
            d.add(Line(x, hh - 2.5 * cm, x, hh - 3.1 * cm))
            hoja = h["hijos"][0]
            d.add(Rect(x - paso / 2 + 2, hh - 3.8 * cm, paso - 4, 0.7 * cm, strokeColor=colors.black, fillColor=colors.HexColor("#e8f0fe")))
            d.add(String(x, hh - 3.55 * cm, hoja["nombre"], textAnchor="middle", fontSize=6))
        S += [Paragraph("Árbol sintáctico", h2), d]
    if r["atributos"]:
        S += [Paragraph("3.3 Análisis semántico", h2),
              tabla([["Variable", "Tipo de atributo", "Regla", "Valor"]] + [list(a) for a in r["atributos"]],
                    [2.4 * cm, 2.6 * cm, ancho - 8 * cm, 3 * cm]),
              Spacer(1, 4)] + [Paragraph(f"{c}: {esc(t)}", nrm) for c, t in REGLAS_SEMANTICAS]
    if r["valido"]:
        S += [Paragraph("Traducción a SQL", h2), Preformatted(r["sql"], mono),
              Paragraph("Traducción a JSON", h2), Preformatted(r["json"], mono)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                      title="Reporte de traducción").build(S)
    return buf.getvalue()
