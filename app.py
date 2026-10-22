import pandas as pd
import streamlit as st

from automata import (TOKENS, a_dot, a_sql, aristas_agrupadas, construir, etiqueta, quintupla, tokenizar)

st.set_page_config(page_title="Analizador Léxico - Mermas e Inventarios", layout="wide")

EJEMPLO = """Lote: LOTE-742
Producto: Leche entera
Proveedor: Gloria
Fecha: 15/10/2026
Motivo: D
Cantidad: 45KG"""

st.title("Analizador Léxico de Reportes de Mermas e Inventarios")
st.caption("Teoría de la Computación · Gourmet Express S.A.C. · ER → AFND (con ε) → AFD (sin ε ni λ)")

with st.sidebar:
    st.header("Opciones")
    minimiza = st.checkbox("Minimizar el AFD", value=False,
                           help="Por defecto el AFD es el que resulta del método de subconjuntos.")
    st.markdown("**Leyenda de los gráficos**  \n`␣` = espacio · `letra` = A-Z, a-z, á é í ó ú ñ · `ε` = transición vacía (solo AFND)")

# ------------------------------------------------------------------ A) CASO
st.header("A) Caso: ficha de merma")
archivo = st.file_uploader("Cargar ficha (.txt)", type=["txt"])
texto_inicial = archivo.getvalue().decode("utf-8", errors="replace") if archivo else EJEMPLO
texto = st.text_area("o escribe / pega la ficha (una línea por campo)", texto_inicial, height=170)
st.button("Analizar", type="primary")  # Streamlit recalcula en cada interacción

tokens, errores = tokenizar(texto, minimiza)

# ------------------------------------------------------------------ B) RESULTADO
st.header("B) Resultado")
if errores:
    for (nl, col, msg) in errores:
        st.error(f"Línea {nl}, columna {col}: {msg}")
else:
    st.success(f"Análisis léxico correcto: {len(tokens)} lexemas reconocidos, 0 errores.")
    sql, faltan = a_sql(tokens)
    if sql:
        st.code(sql, language="sql")
    else:
        st.warning("La ficha es léxicamente válida pero está incompleta o repetida"
                   + (f" (faltan: {', '.join(faltan)})" if faltan else "")
                   + ". La verificación de la estructura corresponde al analizador sintáctico.")

# ------------------------------------------------------------------ C) PROCESO INTERNO
st.header("C) Proceso interno")
st.subheader("3.1 Análisis léxico")
if tokens:
    st.dataframe(pd.DataFrame([{"Línea": t["línea"], "Lexema": t["lexema"], "Token asignado": t["token"],
                                "Expresión regular": t["er"].replace(" ", "␣")} for t in tokens]),
                 use_container_width=True, hide_index=True)
    with st.expander("Recorrido del AFD para cada lexema"):
        for t in tokens:
            st.markdown(f"`{t['lexema']}` → " + " → ".join(t["camino"]))
else:
    st.info("Sin lexemas válidos para mostrar.")

st.subheader("Tokens definidos (agrupados)")
st.dataframe(pd.DataFrame([{"Token": n, "Expresión regular": er.replace(" ", "␣"), "Agrupa": d}
                           for n, er, d in TOKENS]), use_container_width=True, hide_index=True)

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
    st.graphviz_chart(a_dot(a), use_container_width=True)
    st.markdown("#### Tabla de transiciones")
    filas = [{"Estado actual": ("→ " if e == a.inicial else "") + e + (" *" if e in a.finales else ""),
              "Símbolo(s)": et, "Estado destino": d} for (e, et, d) in aristas_agrupadas(a)]
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True, height=min(38 * (len(filas) + 1) + 3, 900))
    st.caption("→ estado inicial · * estado final" + (" · ε = transición vacía" if a.es_afnd else
               " · el AFD no tiene transiciones ε/λ; las transiciones no listadas llevan a un estado de error implícito"))

st.subheader("Relación ER → AFND → AFD")
st.markdown(f"La ER de **{nombre}** se convierte en un AFND con ε (construcción de Thompson, {len(afnd.estados)} estados) "
            f"y este en un AFD (método de subconjuntos{' + minimización' if minimiza else ''}, {len(afd.estados)} estados). "
            "Los tres reconocen exactamente el mismo lenguaje.")
