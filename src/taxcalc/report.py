"""Plain-text rendering of the computed taxes, labelled like the Zurich tax invoice."""

from __future__ import annotations

from decimal import Decimal

from .calc import CantonalResult, FederalResult

TARIF_LABELS = {"single": "Grundtarif", "married": "Verheiratetentarif"}
WIDTH = 64


def chf(amount: Decimal) -> str:
    """Swiss number format: 12'345.65"""
    return f"{amount:,.2f}".replace(",", "'")


def pct(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def _line(label: str, amount: Decimal) -> str:
    value = chf(amount)
    return f"  {label}{' ' * max(1, WIDTH - 2 - len(label) - len(value))}{value}"


def _rule() -> str:
    return "  " + "-" * (WIDTH - 2)


def format_report(
    year: int, tarif: str, children: int, cantonal: CantonalResult, federal: FederalResult
) -> str:
    c, f = cantonal, federal
    out = [
        f"Steuerperiode {year} · Gemeinde {c.commune} · {TARIF_LABELS[tarif]}"
        + (f" · {children} Kind(er)" if children else ""),
        "",
        "Staats- und Gemeindesteuer",
        _line("Steuerbares Einkommen", c.taxable_income),
        _line("Steuerbares Vermögen", c.taxable_assets),
        _line(f"Einfache Staatssteuer Einkommen ({c.income_rate}%)", c.simple_income_tax),
        _line(f"Einfache Staatssteuer Vermögen ({c.assets_rate}‰)", c.simple_assets_tax),
        _line("Total einfache Staatssteuer", c.simple_tax),
        "",
        _line(f"Staatssteuer Einkommen ({pct(c.canton_steuerfuss)})", c.canton_income_tax),
        _line(f"Staatssteuer Vermögen ({pct(c.canton_steuerfuss)})", c.canton_assets_tax),
        _line(f"Gemeindesteuer Einkommen ({pct(c.commune_steuerfuss)})", c.commune_income_tax),
        _line(f"Gemeindesteuer Vermögen ({pct(c.commune_steuerfuss)})", c.commune_assets_tax),
        _line(f"Personalsteuer ({c.persons} × {chf(c.personal_tax / c.persons)})", c.personal_tax),
        _rule(),
        _line("Total Staats- und Gemeindesteuer", c.total),
        "",
        "Direkte Bundessteuer",
        _line("Steuerbares Einkommen", f.taxable_income),
        _line("Steuer gemäss Tarif", f.tariff_tax),
    ]
    if f.child_reduction:
        out.append(_line(f"Abzug für {children} Kind(er)", -f.child_reduction))
    out += [
        _rule(),
        _line("Total direkte Bundessteuer", f.total),
        "",
        _line("TOTAL", c.total + f.total),
    ]
    return "\n".join(out) + "\n"
