"""User configuration, loaded per the XDG Base Directory Specification.

The config file lives at ``$XDG_CONFIG_HOME/taxcalc/config.toml``, falling
back to ``~/.config/taxcalc/config.toml`` when ``$XDG_CONFIG_HOME`` is
unset, empty, or not an absolute path (per the spec, such values must be
ignored in favor of the default). Rate overrides live next to it in
``rates/<year>.toml``.

Besides the household settings, the file can hold the taxable amounts of
each tax year (``[years.2026]``), so a later run can offer them as defaults.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .errors import TaxcalcError

APP_NAME = "taxcalc"
CONFIG_FILENAME = "config.toml"
TARIFS = ("single", "married")


@dataclass(frozen=True)
class YearAmounts:
    """Taxable amounts of one tax year, as entered by the user."""

    income: Decimal
    assets: Decimal
    federal_income: Decimal


@dataclass
class Config:
    # None means "not configured yet": the CLI asks for it interactively.
    tarif: str | None = None
    commune: str | None = None
    children: int = 0
    years: dict[int, YearAmounts] = field(default_factory=dict)


def find_config_dir() -> Path:
    """Resolve the config directory per the XDG Base Directory spec.

    $XDG_CONFIG_HOME must be an absolute path to count; an unset, empty,
    or relative value falls back to ~/.config, per spec.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "")
    base = (
        Path(xdg_config_home)
        if xdg_config_home and Path(xdg_config_home).is_absolute()
        else Path.home() / ".config"
    )
    return base / APP_NAME


def find_config_path() -> Path:
    return find_config_dir() / CONFIG_FILENAME


def load_config(path: Path) -> Config:
    """Load and validate the config file, or return defaults if it's absent."""
    if not path.exists():
        return Config()

    try:
        raw = path.read_bytes()
    except OSError as e:
        raise TaxcalcError(f"could not read config file {path}: {e}") from e

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise TaxcalcError(f"config file {path} is not valid UTF-8: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise TaxcalcError(f"config file {path} is not valid TOML: {e}") from e

    unknown_sections = sorted(set(data) - {"household", "years"})
    if unknown_sections:
        raise TaxcalcError(f"config file {path}: unknown section(s): {', '.join(unknown_sections)}")

    household = data.get("household", {})
    if not isinstance(household, dict):
        raise TaxcalcError(f"config file {path}: [household] must be a table")

    tarif = household.get("tarif")
    if tarif is not None and tarif not in TARIFS:
        raise TaxcalcError(
            f"config file {path}: household.tarif must be one of: {', '.join(TARIFS)}"
        )

    commune = household.get("commune")
    if commune is not None and not isinstance(commune, str):
        raise TaxcalcError(f"config file {path}: household.commune must be a string")

    children = household.get("children", 0)
    # bool is a subclass of int; `children = true` is a typo, not a count.
    if not isinstance(children, int) or isinstance(children, bool) or children < 0:
        raise TaxcalcError(f"config file {path}: household.children must be a non-negative integer")

    unknown_fields = sorted(set(household) - {"tarif", "commune", "children"})
    if unknown_fields:
        raise TaxcalcError(
            f"config file {path}: unknown household.* setting(s): {', '.join(unknown_fields)}"
        )

    return Config(tarif=tarif, commune=commune, children=children, years=_load_years(path, data))


def _load_years(path: Path, data: dict) -> dict[int, YearAmounts]:
    section = data.get("years", {})
    if not isinstance(section, dict):
        raise TaxcalcError(f"config file {path}: [years] must be a table")
    years = {}
    for key, table in section.items():
        where = f"config file {path}: years.{key}"
        if not key.isdigit():
            raise TaxcalcError(f"{where}: the key must be a year, like [years.2026]")
        if not isinstance(table, dict):
            raise TaxcalcError(f"{where} must be a table")
        unknown = sorted(set(table) - {"income", "assets", "federal_income"})
        if unknown:
            raise TaxcalcError(f"{where}: unknown setting(s): {', '.join(unknown)}")
        if "income" not in table:
            raise TaxcalcError(f"{where}: income is missing")

        def amount(name: str, value: object, where: str = where) -> Decimal:
            if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
                raise TaxcalcError(f"{where}.{name} must be a non-negative number")
            return Decimal(str(value))

        income = amount("income", table["income"])
        years[int(key)] = YearAmounts(
            income=income,
            assets=amount("assets", table.get("assets", 0)),
            federal_income=(
                amount("federal_income", table["federal_income"])
                if "federal_income" in table
                else income
            ),
        )
    return years


def _toml_amount(amount: Decimal) -> str:
    # TOML has no decimal type: whole francs as integers, anything else as a float.
    return str(int(amount)) if amount == amount.to_integral_value() else str(amount)


def save_config(path: Path, config: Config) -> None:
    """Write the config file, creating its directory if needed."""
    lines = [
        "# taxcalc settings, see https://specifications.freedesktop.org/basedir-spec/",
        "[household]",
    ]
    if config.tarif is not None:
        lines += [
            "# single = Grundtarif; married = Verheiratetentarif (also single parents)",
            f'tarif = "{config.tarif}"',
        ]
    if config.commune is not None:
        lines += [
            "# Political commune (Gemeinde) in the canton of Zurich",
            f"commune = {json.dumps(config.commune, ensure_ascii=False)}",
        ]
    lines += [
        "# Number of children, for the federal tax reduction per child (Art. 36 Abs. 2bis DBG)",
        f"children = {config.children}",
    ]
    for year, amounts in sorted(config.years.items()):
        lines += [
            "",
            "# Taxable amounts (steuerbares Einkommen/Vermögen), offered as defaults",
            f"[years.{year}]",
            f"income = {_toml_amount(amounts.income)}",
            f"assets = {_toml_amount(amounts.assets)}",
            f"federal_income = {_toml_amount(amounts.federal_income)}",
        ]
    lines.append("")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as e:
        raise TaxcalcError(f"could not write config file {path}: {e}") from e
