"""Command-line entry point: collects the inputs (interactively or via flags) and prints the taxes.

`main(argv)` only parses arguments and converts TaxcalcError into an exit
code; `_run(...)` does the work with plain arguments so tests can call it
directly.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .calc import compute_cantonal, compute_federal, find_commune
from .config import TARIFS, Config, YearAmounts, find_config_dir, load_config, save_config
from .errors import TaxcalcError
from .rates import YearRates, available_years, load_rates
from .report import TARIF_LABELS, chf, format_report, pct

DEFAULT_COMMUNE = "Zürich"


def parse_amount(text: str) -> Decimal:
    """Parse a CHF amount like 123'456, 123 456 or 123456.50."""
    cleaned = text.strip().removeprefix("CHF").strip()
    for separator in ("'", "’", " ", "_"):
        cleaned = cleaned.replace(separator, "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a valid amount: {text!r}") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"amount must be zero or positive: {text!r}")
    return amount


def parse_tarif(text: str) -> str:
    choice = text.strip().lower()
    aliases = {"g": "single", "grundtarif": "single", "v": "married", "verheiratet": "married"}
    choice = aliases.get(choice, choice)
    if choice not in TARIFS:
        raise ValueError(f"tarif must be one of: {', '.join(TARIFS)}")
    return choice


def parse_yes_no(text: str) -> bool:
    answer = text.strip().lower()
    if answer in ("y", "yes", "j", "ja"):
        return True
    if answer in ("n", "no", "nein"):
        return False
    raise ValueError("please answer y or n")


def parse_children(text: str) -> int:
    if not text.strip().isdigit():
        raise ValueError(f"not a valid number of children: {text!r}")
    return int(text)


def ask[T](question: str, parse: Callable[[str], T], default: str | None = None) -> T:
    """Prompt until the answer parses; an empty answer takes the default."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        try:
            answer = input(f"{question}{suffix}: ")
        except EOFError:
            raise TaxcalcError(f"no answer given for: {question}") from None
        if not answer.strip() and default is not None:
            answer = default
        try:
            return parse(answer)
        except (ValueError, TaxcalcError) as e:
            print(f"  {e}", file=sys.stderr)


def _parse_year(text: str, years: list[int]) -> int:
    if not text.strip().isdigit() or int(text) not in years:
        raise ValueError(
            f"no tax rates for {text.strip()!r}; available: {', '.join(map(str, years))}"
        )
    return int(text)


def default_year(years: list[int], today: datetime.date) -> int:
    past = [y for y in years if y <= today.year]
    return max(past) if past else min(years)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taxcalc",
        description=(
            "Estimate Staats- und Gemeindesteuer (canton of Zurich) and direkte Bundessteuer "
            "from taxable income and assets. Asks for anything not given as an option; "
            "with --income it runs non-interactively."
        ),
    )
    parser.add_argument("--year", type=int, help="tax year (Steuerperiode)")
    parser.add_argument("--income", type=parse_amount, help="taxable income, cantonal")
    parser.add_argument("--assets", type=parse_amount, help="taxable assets (default 0)")
    parser.add_argument(
        "--federal-income",
        type=parse_amount,
        help="taxable income, federal (default: same as --income)",
    )
    parser.add_argument("--tarif", type=parse_tarif, help="single or married (overrides config)")
    parser.add_argument("--commune", help="commune in the canton of Zurich (overrides config)")
    parser.add_argument("--children", type=parse_children, help="number of children")
    parser.add_argument(
        "--list-communes", action="store_true", help="list communes and their Steuerfuss"
    )
    return parser


def _list_communes(rates: YearRates) -> int:
    zh = rates.zurich
    print(f"Steuerfüsse {rates.year} (Kanton {pct(zh.canton_steuerfuss)})")
    for name, steuerfuss in sorted(zh.communes.items()):
        print(f"  {name:<30} {pct(steuerfuss)}")
    return 0


def _run(
    *,
    year: int | None,
    income: Decimal | None,
    assets: Decimal | None,
    federal_income: Decimal | None,
    tarif: str | None,
    commune: str | None,
    children: int | None,
    list_communes: bool,
    config: Config,
    config_dir: Path,
    today: datetime.date,
) -> int:
    rates_dir = config_dir / "rates"
    interactive = income is None and not list_communes
    years = available_years(rates_dir)

    if year is None:
        fallback = default_year(years, today)
        year = (
            ask(
                f"Tax year ({min(years)}–{max(years)})",
                lambda s: _parse_year(s, years),
                str(fallback),
            )
            if interactive
            else fallback
        )
    rates = load_rates(year, rates_dir)

    if list_communes:
        return _list_communes(rates)

    # Household settings: command line, then config file, then ask (and offer to save).
    asked = False
    tarif = tarif or config.tarif
    if tarif is None:
        if not interactive:
            raise TaxcalcError("no tarif configured; pass --tarif or run interactively")
        tarif = ask("Tarif: single (Grundtarif) or married (Verheiratetentarif)", parse_tarif)
        asked = True
    commune = commune or config.commune
    if commune is None:
        if not interactive:
            raise TaxcalcError("no commune configured; pass --commune or run interactively")
        commune = ask(
            "Commune (Gemeinde)", lambda s: find_commune(rates.zurich, s), DEFAULT_COMMUNE
        )
        asked = True
    commune = find_commune(rates.zurich, commune)
    if children is None:
        if asked:
            children = ask("Number of children", parse_children, str(config.children))
        else:
            children = config.children

    config_path = config_dir / "config.toml"
    if asked:
        if ask(f"Save these settings to {config_path}? (y/n)", parse_yes_no, "y"):
            config = replace(config, tarif=tarif, commune=commune, children=children)
            save_config(config_path, config)
            print(f"Saved. Edit {config_path} to change them later.")
    elif interactive:
        print(
            f"Settings: {TARIF_LABELS[tarif]}, Gemeinde {commune}, {children} child(ren) "
            f"(from {config_path})"
        )

    # Amounts saved for this year (if any) are offered as defaults.
    saved = config.years.get(year)
    if interactive:
        income = ask(
            "Steuerbares Einkommen, Staats- und Gemeindesteuer (CHF)",
            parse_amount,
            chf(saved.income) if saved else None,
        )
        assets = ask(
            "Steuerbares Vermögen (CHF)", parse_amount, chf(saved.assets) if saved else "0"
        )
        federal_income = ask(
            "Steuerbares Einkommen, direkte Bundessteuer (CHF)",
            parse_amount,
            chf(saved.federal_income if saved else income),
        )
        print()
    assert income is not None
    assets = Decimal(0) if assets is None else assets
    federal_income = income if federal_income is None else federal_income

    cantonal = compute_cantonal(rates, tarif, commune, income, assets)
    federal = compute_federal(rates, tarif, federal_income, children)
    print(format_report(year, tarif, children, cantonal, federal), end="")

    amounts = YearAmounts(income=income, assets=assets, federal_income=federal_income)
    if interactive and amounts != saved:
        print()
        if ask(f"Save income and assets for {year} in config.toml? (y/n)", parse_yes_no, "y"):
            save_config(config_path, replace(config, years={**config.years, year: amounts}))
            print(f"Saved to {config_path}; they will be offered as defaults next time.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        config_dir = find_config_dir()
        return _run(
            year=args.year,
            income=args.income,
            assets=args.assets,
            federal_income=args.federal_income,
            tarif=args.tarif,
            commune=args.commune,
            children=args.children,
            list_communes=args.list_communes,
            config=load_config(config_dir / "config.toml"),
            config_dir=config_dir,
            today=datetime.date.today(),
        )
    except TaxcalcError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
