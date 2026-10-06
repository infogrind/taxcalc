"""Tax rate tables, one TOML file per tax year.

Packaged tables live in ``taxcalc/rates/<year>.toml``. A file with the same
name in the user's config directory (``~/.config/taxcalc/rates/``) takes
precedence, so new or corrected rates can be added without reinstalling.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from .config import TARIFS
from .errors import TaxcalcError


@dataclass(frozen=True)
class StepTariff:
    """Federal tariff: (threshold, tax at threshold, CHF per further CHF 100) steps."""

    steps: tuple[tuple[Decimal, Decimal, Decimal], ...]
    flat_from: Decimal
    flat_rate: Decimal  # percent of the whole income from flat_from on


@dataclass(frozen=True)
class BracketTariff:
    """Cantonal tariff: (width, rate) brackets plus a rate for everything above."""

    brackets: tuple[tuple[Decimal, Decimal], ...]
    top_rate: Decimal


@dataclass(frozen=True)
class FederalRates:
    income_rounding: int
    minimum_tax: Decimal
    child_reduction: Decimal
    tariffs: dict[str, StepTariff]


@dataclass(frozen=True)
class ZurichRates:
    canton_steuerfuss: Decimal
    personal_tax: Decimal
    income_rounding: int
    assets_rounding: int
    income: dict[str, BracketTariff]  # rates in percent
    assets: dict[str, BracketTariff]  # rates in per mille
    communes: dict[str, Decimal]


@dataclass(frozen=True)
class YearRates:
    year: int
    source: Path
    federal: FederalRates
    zurich: ZurichRates


def _packaged_dir() -> Path:
    return Path(str(resources.files("taxcalc") / "rates"))


def _rate_files(override_dir: Path | None) -> dict[int, Path]:
    files: dict[int, Path] = {}
    for directory in (_packaged_dir(), override_dir):
        if directory is None or not directory.is_dir():
            continue
        for path in directory.glob("*.toml"):
            if path.stem.isdigit():
                files[int(path.stem)] = path  # later directories win
    return files


def available_years(override_dir: Path | None = None) -> list[int]:
    return sorted(_rate_files(override_dir))


def load_rates(year: int, override_dir: Path | None = None) -> YearRates:
    files = _rate_files(override_dir)
    if year not in files:
        years = ", ".join(str(y) for y in sorted(files))
        raise TaxcalcError(f"no tax rates for {year} (available: {years})")
    path = files[year]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise TaxcalcError(f"could not read rates file {path}: {e}") from e
    return _Parser(path).year_rates(year, data)


class _Parser:
    """Validates a rates file, reporting problems with their dotted key path."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def fail(self, where: str, problem: str) -> TaxcalcError:
        return TaxcalcError(f"rates file {self.path}: {where} {problem}")

    def table(self, data: dict[str, Any], key: str, where: str) -> dict[str, Any]:
        value = data.get(key)
        if not isinstance(value, dict):
            raise self.fail(f"{where}.{key}".lstrip("."), "must be a table")
        return value

    def number(self, value: Any, where: str) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise self.fail(where, "must be a number")
        number = Decimal(str(value))
        if number < 0:
            raise self.fail(where, "must not be negative")
        return number

    def integer(self, data: dict[str, Any], key: str, where: str) -> int:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise self.fail(f"{where}.{key}", "must be a positive integer")
        return value

    def rows(self, data: dict[str, Any], key: str, where: str, width: int) -> list[list[Decimal]]:
        value = data.get(key)
        where = f"{where}.{key}"
        if not isinstance(value, list) or not value:
            raise self.fail(where, "must be a non-empty list")
        rows = []
        for i, row in enumerate(value):
            if not isinstance(row, list) or len(row) != width:
                raise self.fail(f"{where}[{i}]", f"must be a list of {width} numbers")
            rows.append([self.number(x, f"{where}[{i}]") for x in row])
        return rows

    def step_tariff(self, data: dict[str, Any], where: str) -> StepTariff:
        steps = self.rows(data, "steps", where, 3)
        thresholds = [s[0] for s in steps]
        if thresholds != sorted(set(thresholds)):
            raise self.fail(f"{where}.steps", "thresholds must be strictly increasing")
        return StepTariff(
            steps=tuple((s[0], s[1], s[2]) for s in steps),
            flat_from=self.number(data.get("flat_from"), f"{where}.flat_from"),
            flat_rate=self.number(data.get("flat_rate"), f"{where}.flat_rate"),
        )

    def bracket_tariff(self, data: dict[str, Any], where: str) -> BracketTariff:
        brackets = self.rows(data, "brackets", where, 2)
        return BracketTariff(
            brackets=tuple((b[0], b[1]) for b in brackets),
            top_rate=self.number(data.get("top_rate"), f"{where}.top_rate"),
        )

    def per_tarif(self, data: dict[str, Any], key: str, where: str, parse) -> dict[str, Any]:
        section = self.table(data, key, where)
        where = f"{where}.{key}".lstrip(".")
        return {t: parse(self.table(section, t, where), f"{where}.{t}") for t in TARIFS}

    def year_rates(self, year: int, data: dict[str, Any]) -> YearRates:
        fed = self.table(data, "federal", "")
        federal = FederalRates(
            income_rounding=self.integer(fed, "income_rounding", "federal"),
            minimum_tax=self.number(fed.get("minimum_tax"), "federal.minimum_tax"),
            child_reduction=self.number(fed.get("child_reduction"), "federal.child_reduction"),
            tariffs={
                t: self.step_tariff(self.table(fed, t, "federal"), f"federal.{t}") for t in TARIFS
            },
        )

        zh = self.table(data, "zurich", "")
        communes = self.table(zh, "communes", "zurich")
        zurich = ZurichRates(
            canton_steuerfuss=self.number(zh.get("canton_steuerfuss"), "zurich.canton_steuerfuss"),
            personal_tax=self.number(zh.get("personal_tax"), "zurich.personal_tax"),
            income_rounding=self.integer(zh, "income_rounding", "zurich"),
            assets_rounding=self.integer(zh, "assets_rounding", "zurich"),
            income=self.per_tarif(zh, "income", "zurich", self.bracket_tariff),
            assets=self.per_tarif(zh, "assets", "zurich", self.bracket_tariff),
            communes={
                name: self.number(value, f"zurich.communes.{name}")
                for name, value in communes.items()
            },
        )
        return YearRates(year=year, source=self.path, federal=federal, zurich=zurich)
