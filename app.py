import pandas as pd
import streamlit as st

from automata import TOKENS, a_dot, aristas_agrupadas, construir, etiqueta, quintupla
from compilador import (GRAMATICA, ORDEN, REGLAS_SEMANTICAS, RUTA_LOG, arbol_a_dot, generar_pdf, leer_registro,
                        procesar, registrar)

st.set_page_config(page_title="MermaDSL - Compilador de Mermas e Inventarios", layout="wide")

EJEMPLO = """Lote: LOTE-742
Producto: Leche entera
Proveedor: Gloria
Fecha: 15/10/2026
Motivo: D
Cantidad: 45KG"""

PRUEBAS = {
    "Válida": EJEMPLO,
    "Error léxico (día 35)": "Lote: LOTE-742\nProducto: Leche entera\nProveedor: Gloria\nFecha: 35/10/2026\nMotivo: D\nCantidad: 45KG",
    "Error sintáctico (Fecha antes de Lote)": "Fecha: 10/10/2026\nLote: LOTE-45\nProducto: Pollo\nProveedor: Avinka\nMotivo: D\nCantidad: 15KG",
    "Error semántico (31/02)": "Lote: LOTE-742\nProducto: Leche entera\nProveedor: Gloria\nFecha: 31/02/2026\nMotivo: D\nCantidad: 45KG",
    "Error semántico (cantidad excesiva)": "Lote: LOTE-742\nProducto: Leche entera\nProveedor: Gloria\nFecha: 15/10/2026\nMotivo: P\nCantidad: 9000KG",
}

st.title("MermaDSL · Compilador de Reportes de Mermas e Inventarios")
st.caption("Teoría de la Computación · Gourmet Express S.A.C. · Léxico (ER → AFND → AFD) → Sintáctico (GLC) → Semántico → Transpilador a SQL / JSON")

with st.sidebar:
    st.header("Opciones")
    minimiza = st.checkbox("Minimizar el AFD", value=False,
                           help="Por defecto el AFD es el que resulta del método de subconjuntos.")
    st.markdown("**Leyenda de los gráficos**  \n`␣` = espacio · `letra` = A-Z, a-z, á é í ó ú ñ · `ε` = transición vacía (solo AFND)")

# ------------------------------------------------------------------ A) CASO
st.header("A) Caso: ficha de merma")
st.markdown(
    "**Qué hace el compilador.** El operario de producción digita una ficha de merma (un campo por línea). "
    "El **analizador léxico** agrupa cada línea en un token con un AFD construido desde su expresión regular; "
    "el **analizador sintáctico** verifica con la gramática libre de contexto que los campos vengan completos y en orden "
    "(y construye el árbol sintáctico); el **analizador semántico** aplica reglas de negocio (fecha real, cantidad máxima) y calcula atributos; "
    "y el **transpilador** traduce la ficha válida a una sentencia **SQL** (y a **JSON**) para la base de datos corporativa. "
    "Si una fase falla, el proceso se detiene y se informa el error. Cada ejecución queda registrada en un archivo y se puede descargar un reporte PDF.")

modo = st.radio("Ingreso de datos", ["Escribir la ficha", "Cargar un archivo .txt"], horizontal=True)
if modo == "Cargar un archivo .txt":
    archivo = st.file_uploader("Cargar ficha (.txt)", type=["txt"])
    texto = archivo.getvalue().decode("utf-8", errors="replace") if archivo else ""
    if archivo:
        st.text_area("Contenido cargado", texto, height=150, disabled=True)
else:
    ej = st.selectbox("Cargar un ejemplo de prueba", list(PRUEBAS))
    texto = st.text_area("Escribe o pega la ficha (una línea por campo)", PRUEBAS[ej], height=170, key=f"txt_{ej}")

analizar = st.button("Analizar y traducir", type="primary")
if analizar:
    r = procesar(texto, minimiza)
    registrar(r)
    st.session_state["r"] = r
r = st.session_state.get("r") or procesar(texto, minimiza)

# ------------------------------------------------------------------ B) RESULTADO
st.header("B) Resultado")
if r["valido"]:
    st.success("Ficha válida: pasó los análisis léxico, sintáctico y semántico y fue traducida.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Traducción a SQL**")
        st.code(r["sql"], language="sql")
    with c2:
        st.markdown("**Traducción a JSON**")
        st.code(r["json"], language="json")
    d1, d2, d3 = st.columns(3)
    d1.download_button("Descargar SQL", r["sql"], "mermas.sql", "text/plain")
    d2.download_button("Descargar JSON", r["json"], "mermas.json", "application/json")
else:
    st.error(f"Ficha inválida: el proceso se detuvo en el análisis {r['etapa']}.")
    for e in r["errores"]:
        st.error(e)
    d3 = st.columns(3)[2]
d3.download_button("Descargar reporte PDF", generar_pdf(r), "reporte_traduccion.pdf", "application/pdf")

with st.expander("Registro de ejecuciones (archivo " + RUTA_LOG + ")"):
    filas = leer_registro()
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True)
        with open(RUTA_LOG, "rb") as f:
            st.download_button("Descargar registro (CSV)", f.read(), RUTA_LOG, "text/csv")
    else:
        st.info("Aún no hay ejecuciones registradas. Pulsa «Analizar y traducir».")

# ------------------------------------------------------------------ C) PROCESO INTERNO
st.header("C) Proceso interno")
t_lex, t_sin, t_sem, t_tra = st.tabs(["3.1 Análisis léxico", "3.2 Análisis sintáctico", "3.3 Análisis semántico", "Traducción"])

# ---- 3.1 léxico
with t_lex:
    if r["tokens"]:
        st.dataframe(pd.DataFrame([{"Línea": t["línea"], "Lexema": t["lexema"], "Token asignado": t["token"],
                                    "Expresión regular": t["er"].replace(" ", "␣")} for t in r["tokens"]]),
                     hide_index=True)
        with st.expander("Recorrido del AFD para cada lexema"):
            for t in r["tokens"]:
                st.markdown(f"`{t['lexema']}` → " + " → ".join(t["camino"]))
    else:
        st.info("Sin lexemas válidos para mostrar.")

    st.subheader("Tokens definidos (agrupados)")
    st.dataframe(pd.DataFrame([{"Token": n, "Expresión regular": er.replace(" ", "␣"), "Agrupa": d}
                               for n, er, d in TOKENS]), hide_index=True)

    st.subheader("Autómatas por token")
    nombre = st.selectbox("Elige el token", [n for n, _, _ in TOKENS])
    er = next(e for n, e, _ in TOKENS if n == nombre)
    afnd, afd = construir(er, minimiza)
    st.markdown(f"**Expresión regular:** `{er.replace(' ', '␣')}`")
    for a, titulo in ((afnd, "AFND (con ε)"), (afd, "AFD (sin ε ni λ)")):
        st.markdown(f"### {titulo}")
        st.markdown("#### Quíntupla:  M = (Q, Σ, δ, q0, F)")
        q = quintupla(a)
        st.table(pd.DataFrame({"Componente": ["Q (estados)", "Σ (alfabeto)", "δ (transiciones)", "q0 (inicial)", "F (finales)"],
                               "Valor": [q["Q"], "{" + etiqueta(a.alfabeto) + "}", "ver gráfico y tabla de transiciones", q["q0"], q["F"]]}))
        st.markdown("#### Gráfico")
        st.graphviz_chart(a_dot(a))
        st.markdown("#### Tabla de transiciones")
        filas = [{"Estado actual": ("→ " if e == a.inicial else "") + e + (" *" if e in a.finales else ""),
                  "Símbolo(s)": et, "Estado destino": d} for (e, et, d) in aristas_agrupadas(a)]
        st.dataframe(pd.DataFrame(filas), hide_index=True, height=min(35 * (len(filas) + 1) + 3, 900))
        st.caption("→ estado inicial · * estado final" + (" · ε = transición vacía" if a.es_afnd else
                   " · el AFD no tiene transiciones ε/λ; las transiciones no listadas llevan a un estado de error implícito"))
    st.subheader("Relación ER → AFND → AFD")
    st.markdown(f"La ER de **{nombre}** se convierte en un AFND con ε (construcción de Thompson, {len(afnd.estados)} estados) "
                f"y este en un AFD (método de subconjuntos{' + minimización' if minimiza else ''}, {len(afd.estados)} estados). "
                "Los tres reconocen exactamente el mismo lenguaje.")

# ---- 3.2 sintáctico
with t_sin:
    st.subheader("Gramática libre de contexto  G = (V, T, P, S)")
    st.markdown("- **V** (variables): `" + "`, `".join(GRAMATICA["V"]) + "`\n"
                "- **T** (terminales, salen de los tokens): `" + "`, `".join(GRAMATICA["T"]) + "`\n"
                "- **S** (símbolo inicial): `" + GRAMATICA["S"] + "`")
    st.markdown("**P** (producciones):")
    st.code("\n".join(f"{i}. {p}" for i, p in enumerate(GRAMATICA["P"], 1)), language="text")
    st.caption("Producto y Proveedor usan el mismo token T_TEXTO; se distinguen por su posición y por la etiqueta del lexema.")
    st.subheader("Tabla de agrupación (token → lexemas)")
    st.dataframe(pd.DataFrame([{"Token (agrupador)": tok, "Variable": var, "Lexema esperado": f"{campo}: …"}
                               for var, campo, tok in ORDEN]), hide_index=True)
    if r["derivacion"]:
        st.subheader("Derivación por la izquierda")
        st.code("\n".join(("=> " + d) if i else d for i, d in enumerate(r["derivacion"])), language="text")
    if r["arbol"]:
        st.subheader("Árbol sintáctico")
        st.graphviz_chart(arbol_a_dot(r["arbol"]))
    elif r["etapa"] == "sintáctico":
        for e in r["errores"]:
            st.error(e)
    else:
        st.info("El árbol se construye cuando el análisis léxico es correcto.")

# ---- 3.3 semántico
with t_sem:
    st.subheader("Reglas semánticas")
    st.table(pd.DataFrame(REGLAS_SEMANTICAS, columns=["Regla", "Descripción"]))
    if r["atributos"]:
        st.subheader("Atributos calculados")
        st.dataframe(pd.DataFrame(r["atributos"], columns=["Variable", "Tipo de atributo", "Regla", "Valor"]), hide_index=True)
        st.subheader("Árbol semántico (atributos sobre el árbol)")
        ann = {a[0]: a[3] for a in r["atributos"]}
        st.graphviz_chart(arbol_a_dot(r["arbol"], ann))
    if r["etapa"] == "semántico" and r["errores"]:
        for e in r["errores"]:
            st.error(e)
    elif not r["atributos"]:
        st.info("El análisis semántico se ejecuta cuando los análisis léxico y sintáctico son correctos.")

# ---- traducción
with t_tra:
    st.markdown("El transpilador recorre el árbol anotado y genera una sentencia en un lenguaje de nivel de abstracción similar (SQL), "
                "más una representación JSON del mismo registro.")
    if r["valido"]:
        st.code(r["sql"], language="sql")
        st.code(r["json"], language="json")
    else:
        st.info("No hay traducción: la ficha no es válida.")

