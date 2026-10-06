from decimal import Decimal

import pytest

from taxcalc.calc import (
    bracket_tax,
    compute_cantonal,
    compute_federal,
    find_commune,
    floor_to,
    round_5_rappen,
    round_chf,
    simple_tax_via_rate,
    step_tax,
)
from taxcalc.errors import TaxcalcError
from taxcalc.rates import available_years, load_rates

D = Decimal
YEARS = available_years()


@pytest.fixture(scope="module")
def rates_2025():
    return load_rates(2025)


@pytest.fixture(scope="module")
def rates_2026():
    return load_rates(2026)


def test_floor_to():
    assert floor_to(D("100099.95"), 100) == D(100000)
    assert floor_to(D("1999"), 1000) == D(1000)


def test_round_chf():
    assert round_chf(D("10.024")) == D("10.02")
    assert round_chf(D("10.025")) == D("10.03")


def test_round_5_rappen():
    assert round_5_rappen(D("1003.08")) == D("1003.10")
    assert round_5_rappen(D("10.02")) == D("10.00")
    assert round_5_rappen(D("10.025")) == D("10.05")


# Data points from the official ESTV tariff table 2025 (Form. 58c), which is
# published independently of the step-wise tariff text the rates file is built from.
@pytest.mark.parametrize(
    ("tarif", "income", "tax"),
    [
        ("single", 18500, "25.41"),
        ("single", 25000, "75.46"),
        ("single", 54000, "506.40"),
        ("single", 100000, "2688.00"),
        ("single", 250000, "19513.60"),
        ("single", 800000, "92000.00"),
        ("married", 33000, "33.00"),
        ("married", 54000, "249.00"),
        ("married", 100000, "1816.00"),
        ("married", 155000, "6037.00"),
        ("married", 250000, "18387.00"),
        ("married", 800000, "89887.00"),
        ("married", 950000, "109250.00"),
    ],
)
def test_federal_tariff_2025_matches_estv_table(rates_2025, tarif, income, tax):
    assert step_tax(D(income), rates_2025.federal.tariffs[tarif]) == D(tax)


def test_federal_rounds_income_down_to_100(rates_2025):
    result = compute_federal(rates_2025, "married", D("100099"), children=0)
    assert result.taxable_income == D(100000)
    assert result.total == D("1816.00")


def test_federal_child_reduction(rates_2025):
    result = compute_federal(rates_2025, "married", D(100000), children=2)
    assert result.child_reduction == D(526)
    assert result.total == D("1290.00")


def test_federal_child_reduction_never_goes_negative(rates_2025):
    result = compute_federal(rates_2025, "married", D(40000), children=3)
    assert result.total == D(0)


def test_federal_minimum_tax(rates_2025):
    # 18'000 single -> 21.56, below the CHF 25 minimum: not levied.
    result = compute_federal(rates_2025, "single", D(18000), children=0)
    assert result.tariff_tax == D("21.56")
    assert result.total == D(0)


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("tarif", ["single", "married"])
def test_federal_steps_are_continuous(year, tarif):
    # Catches transcription errors: each step's base must equal the previous
    # step extrapolated to its threshold (the ESTV rounds bases to 5 Rappen).
    tariff = load_rates(year).federal.tariffs[tarif]
    for (t0, base0, rate0), (t1, base1, _) in zip(tariff.steps, tariff.steps[1:], strict=False):
        assert abs(base0 + (t1 - t0) / 100 * rate0 - base1) <= D("0.05"), (t0, t1)
    below_flat = step_tax(tariff.flat_from - 100, tariff)
    assert below_flat < tariff.flat_from * tariff.flat_rate / 100
    assert tariff.flat_from * tariff.flat_rate / 100 - below_flat < 15


# Thresholds of the top bracket ("für Einkommens-/Vermögensteile über") as stated in the law.
TOP_THRESHOLDS = {
    2024: {"income": (263300, 365800), "assets": (3262000, 3342000)},
    2025: {"income": (263300, 365800), "assets": (3262000, 3342000)},
    2026: {"income": (266700, 370600), "assets": (3304000, 3385000)},
}


@pytest.mark.parametrize("year", YEARS)
def test_zurich_bracket_widths_add_up_to_top_threshold(year):
    zh = load_rates(year).zurich
    for kind in ("income", "assets"):
        single, married = TOP_THRESHOLDS[year][kind]
        tariffs = getattr(zh, kind)
        assert sum(w for w, _ in tariffs["single"].brackets) == single
        assert sum(w for w, _ in tariffs["married"].brackets) == married


@pytest.mark.parametrize(
    ("tarif", "income", "simple_tax"),
    [
        ("married", 0, 0),
        ("married", 14100, 0),
        ("married", 100000, 4743),  # 2193 up to 64'100, + 32'200 × 7% + 3'700 × 8%
        ("married", 150000, 8956),  # 4447 up to 96'300, + 32'400 × 8% + 21'300 × 9%
        ("single", 300000, 28984),  # top bracket: 33'300 × 13% on top of 24'655
    ],
)
def test_zurich_simple_income_tax_2026(rates_2026, tarif, income, simple_tax):
    tariff = rates_2026.zurich.income[tarif]
    assert bracket_tax(D(income), tariff, D(100)) == D(simple_tax)


def test_zurich_simple_assets_tax_2026(rates_2026):
    tariff = rates_2026.zurich.assets["married"]
    # 161'000 free, 242'000 × 0.5‰ = 121, 97'000 × 1‰ = 97
    assert bracket_tax(D(500000), tariff, D(1000)) == D(218)


@pytest.mark.parametrize(
    ("kind", "amount", "unit", "rate", "tax"),
    [
        # The rule observed on the official Steuerrechner (married, 2026), with amounts
        # where it differs from rounding: the exact tariff taxes are 25'169 and 1'812;
        # the rate is truncated (8.2037% -> 8.203%, not 8.204%), then the tax to francs.
        ("income", 306800, 100, "8.203", 25166),
        ("assets", 1611000, 1000, "1.124", 1810),
        ("income", 0, 100, "0", 0),
        ("income", 14100, 100, "0", 0),
    ],
)
def test_simple_tax_via_rate_matches_steuerrechner(rates_2026, kind, amount, unit, rate, tax):
    tariff = getattr(rates_2026.zurich, kind)["married"]
    assert simple_tax_via_rate(D(amount), tariff, D(unit)) == (D(rate), D(tax))


def test_compute_cantonal_city_of_zurich_2026(rates_2026):
    result = compute_cantonal(rates_2026, "married", "Zürich", D("150099"), D("500999"))
    assert result.taxable_income == D(150000)
    assert result.taxable_assets == D(500000)
    assert result.income_rate == D("5.970")  # 8956 / 150000 = 5.97066%
    assert result.simple_income_tax == D(8955)
    assert result.canton_income_tax == D("8507.25")  # 95%
    assert result.commune_income_tax == D("10656.45")  # 119%
    assert result.canton_assets_tax == D("207.10")
    assert result.commune_assets_tax == D("259.42")
    assert result.personal_tax == D(48)
    assert result.simple_tax == D(9173)
    assert result.total == D("19678.20")  # 19'678.22 rounded to 5 Rappen


def test_compute_cantonal_matches_steuerrechner(rates_2026):
    # Full Staats- und Gemeindesteuer, rounded the way the official Steuerrechner does.
    result = compute_cantonal(rates_2026, "married", "Zürich", D(306800), D(1611000))
    assert result.simple_tax == D(26976)  # 25'166 + 1'810
    assert result.total == D("57776.65")  # 57'776.64 rounded to 5 Rappen


def test_compute_cantonal_single_pays_one_personal_tax(rates_2026):
    result = compute_cantonal(rates_2026, "single", "Zürich", D(0), D(0))
    assert result.total == D(24)


def test_find_commune_ignores_case_and_accents(rates_2026):
    assert find_commune(rates_2026.zurich, "zurich") == "Zürich"
    assert find_commune(rates_2026.zurich, " ZÜRICH ") == "Zürich"


def test_find_commune_unknown(rates_2026):
    with pytest.raises(TaxcalcError, match="unknown commune 'Bern'"):
        find_commune(rates_2026.zurich, "Bern")
