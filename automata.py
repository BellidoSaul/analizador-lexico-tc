"""Núcleo del analizador léxico: ER -> AFND (Thompson, con ε) -> AFD (subconjuntos, sin ε).

Notación de ER soportada: concatenación, | (unión), * + ? , ( ), clases [A-Z0-9], literales,
y \\x para escapar un símbolo especial. El espacio es un símbolo normal (se muestra como ␣).
"""
from collections import deque
from dataclasses import dataclass, field

EPS = None  # etiqueta de la transición ε (λ)

LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÁÉÍÓÚáéíóúÑñ"
DIGITOS = "0123456789"
NOMBRES_CLASES = {frozenset(LETRAS): "letra"}  # los dígitos se muestran como el rango 0-9


# ---------------------------------------------------------------- parser de ER
class _Parser:
    def __init__(self, er):
        self.s, self.i, self.n = er, 0, 0  # n = contador de estados

    def nuevo(self):
        self.n += 1
        return self.n - 1

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else None

    def eat(self):
        c = self.s[self.i]
        self.i += 1
        return c

    # fragmento = (inicio, fin, [aristas]); arista = (origen, etiqueta, destino)
    def union(self):
        frags = [self.concat()]
        while self.peek() == "|":
            self.eat()
            frags.append(self.concat())
        if len(frags) == 1:
            return frags[0]
        s, f = self.nuevo(), self.nuevo()
        aristas = []
        for (a, b, ar) in frags:
            aristas += ar + [(s, EPS, a), (b, EPS, f)]
        return (s, f, aristas)

    def concat(self):
        frag = None
        while self.peek() not in (None, "|", ")"):
            nxt = self.postfijo()
            if frag is None:
                frag = nxt
            else:  # une fin(frag) con inicio(nxt): válido porque fin no tiene salidas e inicio no tiene entradas
                a, b, ar = frag
                c, d, ar2 = nxt
                ar2 = [(a2 if a2 != c else b, l, b2 if b2 != c else b) for (a2, l, b2) in ar2]
                frag = (a, d, ar + ar2)
        if frag is None:
            raise ValueError("ER vacía o mal formada")
        return frag

    def postfijo(self):
        a, b, ar = self.atomo()
        while self.peek() in ("*", "+", "?"):
            op = self.eat()
            s, f = self.nuevo(), self.nuevo()
            ar = ar + [(s, EPS, a), (b, EPS, f)]
            if op in ("*", "+"):
                ar.append((b, EPS, a))
            if op in ("*", "?"):
                ar.append((s, EPS, f))
            a, b = s, f
        return (a, b, ar)

    def atomo(self):
        c = self.peek()
        if c == "(":
            self.eat()
            frag = self.union()
            if self.peek() != ")":
                raise ValueError("Falta ')' en la ER")
            self.eat()
            return frag
        if c == "[":
            return self.simbolos(self.clase())
        if c == "\\":
            self.eat()
            return self.simbolos({self.eat()})
        if c in ("*", "+", "?", ")", "|"):
            raise ValueError(f"Operador inesperado '{c}'")
        return self.simbolos({self.eat()})

    def clase(self):
        self.eat()  # [
        out = set()
        while self.peek() != "]":
            if self.peek() is None:
                raise ValueError("Falta ']' en la ER")
            c = self.eat()
            if self.peek() == "-" and self.s[self.i + 1:self.i + 2] not in ("]", ""):
                self.eat()
                d = self.eat()
                out |= {chr(x) for x in range(ord(c), ord(d) + 1)}
            else:
                out.add(c)
        self.eat()  # ]
        return out

    def simbolos(self, conj):
        a, b = self.nuevo(), self.nuevo()
        return (a, b, [(a, frozenset(conj), b)])


# ---------------------------------------------------------------- autómatas
@dataclass
class Automata:
    estados: list          # nombres 'q0', 'q1', ...
    alfabeto: list         # símbolos (caracteres)
    trans: dict            # (estado, simbolo|EPS) -> set(estados)
    inicial: str
    finales: set
    es_afnd: bool = False
    nombres_extra: dict = field(default_factory=dict)  # estado -> conjunto NFA (para AFD)

    # -- simulación (solo AFD)
    def paso(self, estado, c):
        d = self.trans.get((estado, c))
        return next(iter(d)) if d else None

    def recorrer(self, texto):
        """Devuelve (camino, aceptada, posicion_de_fallo)."""
        e, camino = self.inicial, [self.inicial]
        for i, c in enumerate(texto):
            e2 = self.paso(e, c)
            if e2 is None:
                return camino, False, i
            e = e2
            camino.append(e)
        return camino, e in self.finales, len(texto)


def _cierre(trans, S):
    pila, res = list(S), set(S)
    while pila:
        s = pila.pop()
        for t in trans.get((s, EPS), ()):
            if t not in res:
                res.add(t)
                pila.append(t)
    return frozenset(res)


def er_a_afnd(er):
    p = _Parser(er)
    ini, fin, aristas = p.union()
    if p.i != len(er):
        raise ValueError("ER mal formada cerca de la posición %d" % p.i)
    # renumerar en orden BFS
    ady = {}
    for (a, l, b) in aristas:
        ady.setdefault(a, []).append((l, b))
    orden, vistos, cola = [], {ini}, deque([ini])
    while cola:
        s = cola.popleft()
        orden.append(s)
        for (_, t) in sorted(ady.get(s, []), key=lambda x: x[1]):
            if t not in vistos:
                vistos.add(t)
                cola.append(t)
    nom = {s: f"q{i}" for i, s in enumerate(orden)}
    trans, alfabeto = {}, set()
    for (a, l, b) in aristas:
        if a not in nom:
            continue
        if l is EPS:
            trans.setdefault((nom[a], EPS), set()).add(nom[b])
        else:
            for c in l:
                alfabeto.add(c)
                trans.setdefault((nom[a], c), set()).add(nom[b])
    return Automata([nom[s] for s in orden], sorted(alfabeto), trans, nom[ini], {nom[fin]}, es_afnd=True)


def afnd_a_afd(nfa):
    ini = _cierre(nfa.trans, {nfa.inicial})
    nombres, cola, trans = {ini: "q0"}, deque([ini]), {}
    while cola:
        S = cola.popleft()
        for c in nfa.alfabeto:
            mov = set()
            for s in S:
                mov |= nfa.trans.get((s, c), set())
            if not mov:
                continue
            T = _cierre(nfa.trans, mov)
            if T not in nombres:
                nombres[T] = f"q{len(nombres)}"
                cola.append(T)
            trans[(nombres[S], c)] = {nombres[T]}
    finales = {n for S, n in nombres.items() if S & nfa.finales}
    return Automata(list(nombres.values()), nfa.alfabeto, trans, "q0", finales, False,
                    {n: sorted(S, key=lambda x: int(x[1:])) for S, n in nombres.items()})


def minimizar(afd):
    """Minimización por refinamiento de particiones (Moore) sobre el AFD parcial."""
    MUERTO = "__m"
    est = afd.estados + [MUERTO]

    def d(e, c):
        if e == MUERTO:
            return MUERTO
        t = afd.trans.get((e, c))
        return next(iter(t)) if t else MUERTO

    clase = {e: (e in afd.finales) for e in est}
    while True:
        firma = {e: (clase[e], tuple(clase[d(e, c)] for c in afd.alfabeto)) for e in est}
        ids = {}
        nueva = {e: ids.setdefault(firma[e], len(ids)) for e in est}
        if len(set(nueva.values())) == len(set(clase.values())):
            break
        clase = nueva
    clase = nueva
    c_muerto = clase[MUERTO]
    orden, nom = [], {}
    cola = deque([clase[afd.inicial]])
    reps = {}
    for e in afd.estados:
        reps.setdefault(clase[e], e)
    while cola:
        k = cola.popleft()
        if k in nom or k == c_muerto:
            continue
        nom[k] = f"q{len(nom)}"
        orden.append(k)
        for c in afd.alfabeto:
            k2 = clase[d(reps[k], c)]
            if k2 not in nom and k2 != c_muerto:
                cola.append(k2)
    trans = {}
    for k in orden:
        for c in afd.alfabeto:
            k2 = clase[d(reps[k], c)]
            if k2 != c_muerto:
                trans[(nom[k], c)] = {nom[k2]}
    finales = {nom[k] for k in orden if reps[k] in afd.finales}
    return Automata([nom[k] for k in orden], afd.alfabeto, trans, nom[clase[afd.inicial]], finales)


# ---------------------------------------------------------------- presentación
def _vis(c):
    return "␣" if c == " " else c


def _cat(c):
    return 'd' if '0' <= c <= '9' else 'U' if 'A' <= c <= 'Z' else 'l' if 'a' <= c <= 'z' else ''


def etiqueta(simbolos):
    """Agrupa símbolos para mostrarlos: letra, rangos como 0-9 o A-Z, etc."""
    s = set(simbolos)
    partes = []
    for conj, nombre in NOMBRES_CLASES.items():
        if conj <= s:
            partes.append(nombre)
            s -= conj
    xs = sorted(s)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and ord(xs[j + 1]) == ord(xs[j]) + 1 and _cat(xs[j]) == _cat(xs[j + 1]) != '':
            j += 1
        if j - i >= 2:
            partes.append(f"{_vis(xs[i])}-{_vis(xs[j])}")
        else:
            partes += [_vis(x) for x in xs[i:j + 1]]
        i = j + 1
    return ",".join(partes)


def aristas_agrupadas(a):
    """[(origen, 'etiqueta', destino)] con los símbolos que comparten origen y destino unidos."""
    g = {}
    for (e, c), dests in a.trans.items():
        for t in dests:
            g.setdefault((e, t), {"s": set(), "eps": False})
            if c is EPS:
                g[(e, t)]["eps"] = True
            else:
                g[(e, t)]["s"].add(c)
    filas = []
    num = lambda x: int(x[1:])
    for (e, t) in sorted(g, key=lambda k: (num(k[0]), num(k[1]))):
        et = etiqueta(g[(e, t)]["s"]) if g[(e, t)]["s"] else ""
        if g[(e, t)]["eps"]:
            et = (et + "," if et else "") + "ε"
        filas.append((e, et, t))
    return filas


def a_dot(a, grupo=None, fs=11):
    """DOT del autómata. Con `grupo` (lista de estados) dibuja solo esa parte; los nodos punteados
    son estados de otra parte del mismo autómata."""
    q = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    gr = set(a.estados) if grupo is None else set(grupo)
    L = ['digraph G {', 'rankdir=LR;', 'bgcolor="transparent";',
         'node [shape=circle, fontname="Helvetica", fontsize=%d, width=0.45];' % fs,
         'edge [fontname="Helvetica", fontsize=%d];' % fs]
    if a.inicial in gr:
        L += ['__s [shape=none, label="", width=0];', f'__s -> {a.inicial};']
    for e in a.estados:
        if e in gr:
            L.append(f'{e} [shape={"doublecircle" if e in a.finales else "circle"}];')
    ext = set()
    for (o, et, d) in aristas_agrupadas(a):
        if o in gr and d in gr:
            L.append(f'{o} -> {d} [label="{q(et)}"];')
        elif o in gr:
            ext.add(d); L.append(f'{o} -> x_{d} [label="{q(et)}"];')
        elif d in gr:
            ext.add(o); L.append(f'x_{o} -> {d} [label="{q(et)}"];')
    for e in sorted(ext):
        L.append(f'x_{e} [shape=box, style=dashed, label="{e}"];')
    L.append("}")
    return "\n".join(L)


def quintupla(a):
    sigma = "{" + ", ".join(_vis(c) for c in a.alfabeto) + "}"
    return {"Q": "{" + ", ".join(a.estados) + "}", "Σ": etiqueta(a.alfabeto) + "   →   " + sigma,
            "q0": a.inicial, "F": "{" + ", ".join(sorted(a.finales, key=lambda x: int(x[1:]))) + "}"}


# ---------------------------------------------------------------- tokens y lexer
_L = "[A-Za-zÁÉÍÓÚáéíóúÑñ]"
TOKENS = [  # (nombre, ER, descripción)   ␣ = espacio
    ("T_LOTE", "Lote: [A-Z]+-[0-9]+", "Campo Lote con su código de trazabilidad"),
    ("T_TEXTO", f"(Producto|Proveedor): {_L}+( {_L}+)*", "Campos Producto y Proveedor (agrupados: mismo patrón)"),
    ("T_FECHA", "Fecha: (0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/20[2-9][0-9]", "Campo Fecha DD/MM/AAAA"),
    ("T_MOTIVO", "Motivo: (D|P)", "Campo Motivo de la merma (D = dañado, P = perecible)"),
    ("T_CANTIDAD", "Cantidad: [1-9][0-9]*KG", "Campo Cantidad en kilogramos"),
]


def construir(er, minimiza=False):
    nfa = er_a_afnd(er)
    dfa = afnd_a_afd(nfa)
    return nfa, (minimizar(dfa) if minimiza else dfa)


def tokenizar(texto, minimiza=False):
    """Devuelve (tokens, errores). Cada línea no vacía debe ser UN lexema agrupado (campo: valor)."""
    afds = {n: construir(er, minimiza)[1] for n, er, _ in TOKENS}
    sigma = set().union(*[set(a.alfabeto) for a in afds.values()])
    tokens, errores = [], []
    for nl, linea in enumerate(texto.splitlines(), 1):
        lex = linea.strip()
        if not lex:
            continue
        ajeno = [i for i, c in enumerate(lex) if c not in sigma]
        if ajeno:
            errores.append((nl, ajeno[0] + 1, f"Error léxico: el carácter '{lex[ajeno[0]]}' no pertenece al alfabeto Σ"))
            continue
        ok = False
        for n, er, _ in TOKENS:
            camino, acepta, _ = afds[n].recorrer(lex)
            if acepta:
                tokens.append({"línea": nl, "lexema": lex, "token": n, "er": er, "camino": camino})
                ok = True
                break
        if ok:
            continue
        mejor = max(((afds[n].recorrer(lex)[2], n) for n, _, _ in TOKENS))
        pos, n = mejor
        a = afds[n]
        camino = a.recorrer(lex)[0]
        esperados = sorted({c for (e, c) in a.trans if e == camino[-1]})
        if pos >= len(lex):
            msg = f"Error léxico: lexema incompleto para {n}; falta continuar con: {etiqueta(esperados)}"
        else:
            msg = f"Error léxico: '{lex[pos]}' inesperado en {n}; se esperaba: {etiqueta(esperados) or 'fin de línea'}"
        errores.append((nl, min(pos, len(lex)) + 1, msg))
    return tokens, errores


def a_sql(tokens):
    campos = {}
    for t in tokens:
        k, v = t["lexema"].split(": ", 1)
        campos[k] = v
    req = ["Lote", "Producto", "Proveedor", "Fecha", "Motivo", "Cantidad"]
    falt = [c for c in req if c not in campos]
    if falt or len(tokens) != len(req):
        return None, falt
    d, m, y = campos["Fecha"].split("/")
    return ("INSERT INTO mermas (lote, producto, proveedor, fecha, motivo, cantidad_kg)\n"
            f"VALUES ('{campos['Lote']}', '{campos['Producto']}', '{campos['Proveedor']}', "
            f"'{y}-{m}-{d}', '{campos['Motivo']}', {campos['Cantidad'][:-2]});"), []
