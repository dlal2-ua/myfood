"""EAN-13: dígito de control, EAN interno de recetas y dibujo de la etiqueta."""

import re

import pytest

from myfood.domain import ean


@pytest.mark.parametrize(
    "code", ["4006381333931", "5901234123457", "8414807501103", "0012345678905"]
)
def test_real_ean_13_codes_are_valid(code):
    assert ean.is_valid_ean13(code)


@pytest.mark.parametrize(
    "code", ["4006381333932", "590123412345", "59012341234570", "abcdefghijklm", ""]
)
def test_wrong_check_digit_length_or_characters_are_invalid(code):
    assert not ean.is_valid_ean13(code)


def test_check_digit_of_a_known_code():
    assert ean.check_digit("400638133393") == 1
    assert ean.check_digit("590123412345") == 7


def test_generated_internal_eans_are_valid_use_the_internal_prefix_and_differ():
    codes = {ean.generate_internal_ean() for _ in range(50)}
    assert len(codes) == 50
    assert all(c.startswith("20") and ean.is_internal_ean(c) for c in codes)


def test_a_regular_ean_is_not_internal():
    assert not ean.is_internal_ean("8414807501103")


def test_the_barcode_has_95_modules_with_guard_bars():
    modules = ean._modules("5901234123457")
    assert len(modules) == 95
    assert modules[:3] == "101" and modules[-3:] == "101"
    assert modules[45:50] == "01010"


def test_first_digit_selects_the_parity_pattern_of_the_left_half():
    # 4006381333931 empieza por 4 -> LGLLGG (0=L, 0=G, 6=L…): el primer dígito solo elige paridad
    left = ean._modules("4006381333931")[3:45]
    assert left[:7] == ean._L[0]
    assert left[7:14] == ean._G[0]
    assert left[14:21] == ean._L[6]


def test_the_svg_label_shows_the_name_the_servings_and_the_digits():
    svg = ean.ean13_svg("5901234123457", "Lentejas de la abuela", "4 raciones")
    assert svg.startswith("<svg")
    assert "Lentejas de la abuela" in svg
    assert "4 raciones" in svg
    assert "5  901234  123457" in svg
    assert len(re.findall(r"<rect x=", svg)) > 40


def test_the_label_escapes_markup_in_the_name():
    svg = ean.ean13_svg("5901234123457", '<script>alert("x")</script>', "")
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_an_invalid_ean_cannot_be_drawn():
    with pytest.raises(ValueError):
        ean.ean13_svg("5901234123450")
