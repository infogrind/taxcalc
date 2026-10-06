"""The actual tax formulas, operating on validated YearRates."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from .errors import TaxcalcError
from .rates import BracketTariff, StepTariff, YearRates, ZurichRates

HUNDRED = Decimal(100)
THOUSAND = Decimal(1000)
CENT = Decimal("0.01")
FIVE_RAPPEN = Decimal("0.05")
RATE_PRECISION = Decimal("0.001")


def floor_to(amount: Decimal, step: int) -> Decimal:
    """Round down to a multiple of step (taxable amounts are always rounded down)."""
    return (amount / step).to_integral_value(rounding=ROUND_FLOOR) * step


def round_chf(amount: Decimal) -> Decimal:
    """Round to whole Rappen, as in the official ESTV tariff tables."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def round_5_rappen(amount: Decimal) -> Decimal:
    """Round to the nearest 5 Rappen, as the cantonal invoice total is."""
    return (amount / FIVE_RAPPEN).to_integral_value(rounding=ROUND_HALF_UP) * FIVE_RAPPEN


def step_tax(income: Decimal, tariff: StepTariff) -> Decimal:
    """Tax per a federal-style tariff: base at a threshold plus a rate per further CHF 100."""
    if income >= tariff.flat_from:
        return income * tariff.flat_rate / HUNDRED
    tax = Decimal(0)
    for threshold, base, per_hundred in tariff.steps:
        if income < threshold:
            break
        tax = base + (income - threshold) / HUNDRED * per_hundred
    return tax


def bracket_tax(amount: Decimal, tariff: BracketTariff, unit: Decimal) -> Decimal:
    """Progressive tax over (width, rate) brackets; rates are in 1/unit (100 = %, 1000 = ‰)."""
    tax = Decimal(0)
    remaining = amount
    for width, rate in tariff.brackets:
        part = min(remaining, width)
        tax += part * rate / unit
        remaining -= part
        if remaining <= 0:
            return tax
    return tax + remaining * tariff.top_rate / unit


def simple_tax_via_rate(
    amount: Decimal, tariff: BracketTariff, unit: Decimal
) -> tuple[Decimal, Decimal]:
    """Einfache Staatssteuer as the Zurich tax office computes it: (rate, tax).

    The tariff tax is turned into an average rate (in % or ‰ per unit),
    truncated to 3 decimals; that rate times the amount, truncated to whole
    francs, is the tax. This matches the official Steuerrechner, e.g.
    306'800 married 2026: tariff 25'169 -> 8.203% (not 8.204) -> 25'166.
    """
    if amount <= 0:
        return Decimal(0), Decimal(0)
    exact = bracket_tax(amount, tariff, unit)
    rate = (exact / amount * unit).quantize(RATE_PRECISION, rounding=ROUND_FLOOR)
    return rate, (amount * rate / unit).to_integral_value(rounding=ROUND_FLOOR)


@dataclass(frozen=True)
class FederalResult:
    taxable_income: Decimal  # after rounding
    tariff_tax: Decimal
    child_reduction: Decimal
    total: Decimal


def compute_federal(rates: YearRates, tarif: str, income: Decimal, children: int) -> FederalResult:
    fed = rates.federal
    taxable = floor_to(income, fed.income_rounding)
    tariff_tax = round_chf(step_tax(taxable, fed.tariffs[tarif]))
    reduction = min(tariff_tax, children * fed.child_reduction)
    total = tariff_tax - reduction
    if total < fed.minimum_tax:
        total = Decimal(0)
    return FederalResult(taxable, tariff_tax, reduction, total)


@dataclass(frozen=True)
class CantonalResult:
    commune: str
    taxable_income: Decimal  # after rounding
    taxable_assets: Decimal  # after rounding
    income_rate: Decimal  # Steuersatz in %
    assets_rate: Decimal  # Steuersatz in ‰
    simple_income_tax: Decimal  # einfache Staatssteuer on income
    simple_assets_tax: Decimal  # einfache Staatssteuer on assets
    canton_steuerfuss: Decimal
    commune_steuerfuss: Decimal
    canton_income_tax: Decimal
    canton_assets_tax: Decimal
    commune_income_tax: Decimal
    commune_assets_tax: Decimal
    personal_tax: Decimal
    persons: int

    @property
    def simple_tax(self) -> Decimal:
        return self.simple_income_tax + self.simple_assets_tax

    @property
    def canton_total(self) -> Decimal:
        return self.canton_income_tax + self.canton_assets_tax

    @property
    def commune_total(self) -> Decimal:
        return self.commune_income_tax + self.commune_assets_tax

    @property
    def total(self) -> Decimal:
        # The Steuerrechner rounds only this total to 5 Rappen (e.g. ...3.08 -> ...3.10).
        return round_5_rappen(self.canton_total + self.commune_total + self.personal_tax)


def _fold(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def find_commune(zurich: ZurichRates, name: str) -> str:
    """Resolve a commune name case- and accent-insensitively ("zurich" -> "Zürich")."""
    matches = [c for c in zurich.communes if _fold(c) == _fold(name)]
    if not matches:
        raise TaxcalcError(
            f"unknown commune {name!r} (run `taxcalc --list-communes` to see all communes)"
        )
    return matches[0]


def compute_cantonal(
    rates: YearRates, tarif: str, commune: str, income: Decimal, assets: Decimal
) -> CantonalResult:
    zh = rates.zurich
    commune = find_commune(zh, commune)
    taxable_income = floor_to(income, zh.income_rounding)
    taxable_assets = floor_to(assets, zh.assets_rounding)
    income_rate, simple_income = simple_tax_via_rate(taxable_income, zh.income[tarif], HUNDRED)
    assets_rate, simple_assets = simple_tax_via_rate(taxable_assets, zh.assets[tarif], THOUSAND)
    canton_sf = zh.canton_steuerfuss
    commune_sf = zh.communes[commune]
    persons = 2 if tarif == "married" else 1

    def apply(simple: Decimal, steuerfuss: Decimal) -> Decimal:
        return round_chf(simple * steuerfuss / HUNDRED)

    return CantonalResult(
        commune=commune,
        taxable_income=taxable_income,
        taxable_assets=taxable_assets,
        income_rate=income_rate,
        assets_rate=assets_rate,
        simple_income_tax=simple_income,
        simple_assets_tax=simple_assets,
        canton_steuerfuss=canton_sf,
        commune_steuerfuss=commune_sf,
        canton_income_tax=apply(simple_income, canton_sf),
        canton_assets_tax=apply(simple_assets, canton_sf),
        commune_income_tax=apply(simple_income, commune_sf),
        commune_assets_tax=apply(simple_assets, commune_sf),
        personal_tax=persons * zh.personal_tax,
        persons=persons,
    )
