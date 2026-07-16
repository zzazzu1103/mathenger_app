"""한글 수식(EQEDIT) 스크립트를 LaTeX로 변환한다 (미리보기 렌더링용).

한글 수식은 `{A} over {B}`, `sqrt {x}`, `LEFT | ... RIGHT |`, `sum _{}^{}`,
`cases{ A # B }` 같은 자체 문법을 쓴다. 완벽한 변환기는 아니지만 기출
수학 문제에 나오는 대부분의 표현을 브라우저(MathJax)에서 원본과 비슷하게
보여줄 수 있을 만큼 커버한다. 변환 실패 시 예외 없이 원본 스크립트를
그대로 돌려주어 미리보기가 깨지지 않게 한다.
"""

from __future__ import annotations

# 단순 치환 명령어 (한글 수식 토큰 → LaTeX)
_SYMBOLS = {
    "times": r"\times", "div": r"\div", "cdot": r"\cdot", "cdots": r"\cdots",
    "CDOTS": r"\cdots", "LDOTS": r"\ldots", "ldots": r"\ldots",
    "DOTSAXIS": r"\cdots", "VDOTS": r"\vdots", "DDOTS": r"\ddots",
    "pm": r"\pm", "mp": r"\mp", "ANGLE": r"\angle", "angle": r"\angle",
    "INF": r"\infty", "inf": r"\infty", "PARTIAL": r"\partial",
    "NEQ": r"\neq", "neq": r"\neq", "LEQ": r"\le", "leq": r"\le",
    "GEQ": r"\ge", "geq": r"\ge", "APPROX": r"\approx", "SIMEQ": r"\simeq",
    "TIMES": r"\times", "DIV": r"\div", "prime": r"'", "circ": r"\circ",
    "sum": r"\sum", "int": r"\int", "prod": r"\prod", "lim": r"\lim",
    "sin": r"\sin", "cos": r"\cos", "tan": r"\tan", "log": r"\log",
    "ln": r"\ln", "exp": r"\exp", "max": r"\max", "min": r"\min",
    "RIGHTARROW": r"\rightarrow", "LEFTARROW": r"\leftarrow",
    "->": r"\rightarrow", "<-": r"\leftarrow", "in": r"\in", "notin": r"\notin",
    "subset": r"\subset", "cup": r"\cup", "cap": r"\cap", "emptyset": r"\emptyset",
}
_GREEK = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau",
    "phi", "chi", "psi", "omega",
]
for _g in _GREEK:
    _SYMBOLS[_g] = "\\" + _g
    _SYMBOLS[_g.upper()] = "\\" + _g.capitalize()  # GAMMA → \Gamma

_ACCENTS = {"bar": r"\overline", "hat": r"\hat", "vec": r"\vec",
            "dot": r"\dot", "ddot": r"\ddot", "tilde": r"\tilde", "widetilde": r"\widetilde"}
_DROP = {"rm", "it", "bold", "roman"}  # 서체 지정은 미리보기에서 무시
# LEFT/RIGHT 뒤 중괄호는 그룹이 아니라 구분자다. 전처리에서 이 마커로 바꾼다.
_LBRACE, _RBRACE = "\x01{", "\x01}"
_DELIMS = {"(": "(", ")": ")", "[": "[", "]": "]", "|": "|",
           _LBRACE: r"\{", _RBRACE: r"\}",
           "<": r"\langle", ">": r"\rangle", ".": "."}


def _has_hangul(s: str) -> bool:
    return any("가" <= c <= "힣" or "㄰" <= c <= "㆏" for c in s)


def _tokenize(s: str) -> list[str]:
    tokens: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
        elif c in "{}^_&#()[]|":
            tokens.append(c)
            i += 1
        elif c.isalpha():
            j = i
            while j < n and s[j].isalpha():
                j += 1
            word = s[i:j]
            # 'rmABC'처럼 서체 지정이 이름에 붙은 경우 분리
            for pref in ("roman", "bold", "rm", "it"):
                if word.startswith(pref) and len(word) > len(pref) and word[len(pref)].isupper():
                    tokens.append(pref)
                    tokens.append(word[len(pref):])
                    break
            else:
                tokens.append(word)
            i = j
        elif c.isdigit() or c == ".":
            j = i
            while j < n and (s[j].isdigit() or s[j] == "."):
                j += 1
            tokens.append(s[i:j])
            i = j
        else:
            tokens.append(c)
            i += 1
    return tokens


def _mark_delim_braces(tokens: list[str]) -> list[str]:
    """LEFT/RIGHT 바로 뒤의 `{` `}`를 그룹이 아닌 구분자 마커로 바꾼다."""
    out = list(tokens)
    for i in range(len(out) - 1):
        if out[i] in ("LEFT", "left", "RIGHT", "right"):
            if out[i + 1] == "{":
                out[i + 1] = _LBRACE
            elif out[i + 1] == "}":
                out[i + 1] = _RBRACE
    return out


def _build_tree(tokens: list[str]) -> list:
    """`{ }`를 중첩 리스트로 묶는다."""
    stack: list[list] = [[]]
    for tok in tokens:
        if tok == "{":
            group: list = []
            stack[-1].append(group)
            stack.append(group)
        elif tok == "}":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].append(tok)
    return stack[0]


def _render(items: list) -> str:
    atoms: list[str] = []
    i, n = 0, len(items)
    while i < n:
        it = items[i]
        if isinstance(it, list):
            atoms.append("{" + _render(it) + "}")
            i += 1
            continue
        w = it
        if w in _DROP:
            i += 1
        elif w == "over":
            atoms.append("\x00OVER\x00")
            i += 1
        elif w in ("^", "_"):
            nxt, i = _next_atom(items, i + 1)
            atoms.append(w + "{" + nxt + "}")
        elif w == "sqrt":
            nxt, i = _next_atom(items, i + 1)
            atoms.append(r"\sqrt{" + nxt + "}")
        elif w in _ACCENTS:
            nxt, i = _next_atom(items, i + 1)
            atoms.append(_ACCENTS[w] + "{" + nxt + "}")
        elif w in ("cases", "matrix", "pile", "eqalign"):
            body, i = _next_group(items, i + 1)
            atoms.append(_render_matrix(w, body))
        elif w in ("LEFT", "left", "RIGHT", "right"):
            side = "\\left" if w.lower() == "left" else "\\right"
            delim = "."
            if i + 1 < n and isinstance(items[i + 1], str) and items[i + 1] in _DELIMS:
                delim = _DELIMS[items[i + 1]]
                i += 2
            else:
                i += 1
            atoms.append(side + delim)
        elif w in _DELIMS and w in "()[]|":
            atoms.append(_DELIMS[w])
            i += 1
        elif w in ("°", "˚"):
            atoms.append(r"^{\circ}")
            i += 1
        elif w in _SYMBOLS:
            atoms.append(_SYMBOLS[w])
            i += 1
        elif _has_hangul(w):
            atoms.append(r"\text{" + w + "}")
            i += 1
        else:
            atoms.append(w)
            i += 1

    # 중위 연산자 over → \frac (양쪽 피연산자가 없을 때도 안전하게)
    while "\x00OVER\x00" in atoms:
        k = atoms.index("\x00OVER\x00")
        has_left = k >= 1
        has_right = k + 1 < len(atoms)
        left = atoms[k - 1] if has_left else "{}"
        right = atoms[k + 1] if has_right else "{}"
        frac = r"\frac{" + _strip_braces(left) + "}{" + _strip_braces(right) + "}"
        lo = k - 1 if has_left else k
        hi = k + 2 if has_right else k + 1
        atoms[lo:hi] = [frac]

    return " ".join(a for a in atoms if a)


def _next_atom(items: list, i: int) -> tuple[str, int]:
    if i >= len(items):
        return "", i
    it = items[i]
    if isinstance(it, list):
        return _render(it), i + 1
    if it in _SYMBOLS:
        return _SYMBOLS[it], i + 1
    return it, i + 1


def _next_group(items: list, i: int) -> tuple[list, int]:
    if i < len(items) and isinstance(items[i], list):
        return items[i], i + 1
    return [], i


def _render_matrix(kind: str, body: list) -> str:
    rows: list[list] = [[]]
    for it in body:
        if it == "#":
            rows.append([])
        else:
            rows[-1].append(it)
    rendered = [" \\\\ ".join([_render(r)]) for r in rows]
    env = "cases" if kind == "cases" else "matrix"
    return "\\begin{" + env + "}" + " \\\\ ".join(_render(r) for r in rows) + "\\end{" + env + "}"


def _strip_braces(s: str) -> str:
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return s[1:-1]
    return s


def to_latex(script: str) -> str:
    """한글 수식 스크립트를 LaTeX 문자열로 변환한다."""
    try:
        cleaned = script.replace("`", " ")
        tree = _build_tree(_mark_delim_braces(_tokenize(cleaned)))
        latex = _render(tree).replace("\x00OVER\x00", "")  # 남은 마커 제거(방어)
        return latex if latex.strip() else script
    except Exception:
        return script
