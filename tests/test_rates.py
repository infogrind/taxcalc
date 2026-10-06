from decimal import Decimal

import pytest

from taxcalc.errors import TaxcalcError
from taxcalc.rates import _packaged_dir, available_years, load_rates


def test_packaged_years():
    assert available_years() == [2024, 2025, 2026]


@pytest.mark.parametrize("year", [2024, 2025, 2026])
def test_packaged_rates_load(year):
    rates = load_rates(year)
    assert rates.year == year
    assert rates.zurich.communes["Zürich"] == Decimal(119)


def test_steuerfuss_values():
    assert load_rates(2025).zurich.canton_steuerfuss == Decimal(98)
    assert load_rates(2026).zurich.canton_steuerfuss == Decimal(95)


def test_unknown_year():
    with pytest.raises(
        TaxcalcError, match=r"no tax rates for 1999 \(available: 2024, 2025, 2026\)"
    ):
        load_rates(1999)


def test_override_dir_adds_year_and_wins(tmp_path):
    text = (_packaged_dir() / "2026.toml").read_text(encoding="utf-8")
    (tmp_path / "2027.toml").write_text(text, encoding="utf-8")
    (tmp_path / "2026.toml").write_text(
        text.replace("canton_steuerfuss = 95", "canton_steuerfuss = 90"), encoding="utf-8"
    )
    assert available_years(tmp_path) == [2024, 2025, 2026, 2027]
    assert load_rates(2027, tmp_path).zurich.canton_steuerfuss == Decimal(95)
    assert load_rates(2026, tmp_path).zurich.canton_steuerfuss == Decimal(90)


def test_override_dir_missing_is_fine(tmp_path):
    assert available_years(tmp_path / "nope") == [2024, 2025, 2026]


def _broken(tmp_path, old, new):
    text = (_packaged_dir() / "2026.toml").read_text(encoding="utf-8")
    assert old in text
    (tmp_path / "2026.toml").write_text(text.replace(old, new), encoding="utf-8")


def test_invalid_toml(tmp_path):
    _broken(tmp_path, "[federal]", "[federal")
    with pytest.raises(TaxcalcError, match="could not read rates file"):
        load_rates(2026, tmp_path)


def test_bad_number_names_the_key(tmp_path):
    _broken(tmp_path, "canton_steuerfuss = 95", 'canton_steuerfuss = "95"')
    with pytest.raises(TaxcalcError, match="zurich.canton_steuerfuss must be a number"):
        load_rates(2026, tmp_path)


def test_bad_bracket_row(tmp_path):
    _broken(tmp_path, "[7000, 0], [5000, 2]", "[7000], [5000, 2]")
    with pytest.raises(TaxcalcError, match=r"zurich.income.single.brackets\[0\] must be a list"):
        load_rates(2026, tmp_path)


def test_unsorted_federal_steps(tmp_path):
    _broken(tmp_path, "[15200, 0, 0.77], [33200,", "[35200, 0, 0.77], [33200,")
    with pytest.raises(TaxcalcError, match="federal.single.steps thresholds must be strictly"):
        load_rates(2026, tmp_path)


def test_missing_tarif_table(tmp_path):
    _broken(tmp_path, "[zurich.assets.married]", "[zurich.assets.other]")
    with pytest.raises(TaxcalcError, match="zurich.assets.married must be a table"):
        load_rates(2026, tmp_path)
