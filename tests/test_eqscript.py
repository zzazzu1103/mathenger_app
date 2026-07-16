from mathenger.hwp.eqscript import to_latex


def test_basic_super_sub():
    assert to_latex("x ^{3} -3x ^{2}") == "x ^{3} - 3 x ^{2}"


def test_fraction():
    assert to_latex("{3+ sqrt {3}} over {4}") == r"\frac{3 + \sqrt{3}}{4}"


def test_abs_delims():
    assert to_latex("LEFT | a _{ 4} RIGHT |") == r"\left| a _{4} \right|"


def test_brace_delims():
    assert to_latex("LEFT { a _{ n} RIGHT }") == r"\left\{ a _{n} \right\}"


def test_sum():
    assert to_latex("sum _{k=1} ^{9} a _{ k}") == r"\sum _{k = 1} ^{9} a _{k}"


def test_degree_and_hangul():
    out = to_latex("60° rm 홀수")
    assert r"^{\circ}" in out and r"\text{홀수}" in out


def test_never_raises():
    # 깨진 입력이어도 예외 없이 원본 반환
    assert to_latex("{{{ over over") is not None
