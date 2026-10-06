# taxcalc

Estimates the tax invoice for a household in the canton of Zurich:

- **Staats- und Gemeindesteuer**: einfache Staatssteuer on income (§ 35 StG) and
  assets (§ 47 StG), multiplied by the cantonal and communal Steuerfuss, plus
  the Personalsteuer.
- **Direkte Bundessteuer**: Art. 36 DBG, including the per-child reduction.

It takes *taxable* amounts (steuerbares Einkommen / Vermögen, as on the
assessment or the tax return) like the official
[Steuerrechner](https://www.zh.ch/steuerrechner).
It does not compute deductions.

## Usage

```sh
uv run taxcalc                      # interactive
uv run taxcalc --year 2026 --income 150000 --assets 500000 --federal-income 155000
uv run taxcalc --list-communes --year 2026
```

Without `--income` it asks for everything not given as an option. Amounts can
be written as `150000`, `150'000` or `150 000`. Federal taxable income usually
differs from the cantonal one (different deductions), so it is asked
separately; it defaults to the cantonal amount.

## Configuration

On first run it asks for the household settings and offers to save them to
`$XDG_CONFIG_HOME/taxcalc/config.toml` (default `~/.config/taxcalc/config.toml`):

```toml
[household]
tarif = "married"   # "single" (Grundtarif) or "married" (Verheiratetentarif)
commune = "Zürich"
children = 0        # federal tax reduction per child
```

Command-line options (`--tarif`, `--commune`, `--children`) override it.

## Rates

One file per tax year in [`src/taxcalc/rates/`](src/taxcalc/rates/), with
comments naming the legal source. To add or correct a year without
reinstalling, put a `<year>.toml` into `~/.config/taxcalc/rates/`; it takes
precedence over the packaged file.

Updating for a new year:

- **Federal** (yearly): the ESTV publishes the tariff in a circular each
  September, see
  [Rundschreiben DBST](https://www.estv.admin.ch/de/rundschreiben-direkten-bundessteuer).
  Copy the steps of Art. 36 Abs. 1/2 and the per-child reduction.
- **Canton** (tariff adjusted every two years, start of each Steuerfuss
  period): "Verordnung über den Ausgleich der kalten Progression" in the
  [Zürcher Steuerbuch](https://www.zh.ch/de/steuern-finanzen/steuern/treuhaender/steuerbuch.html),
  ZStB-Nr. 48.1. The Staatssteuerfuss is set by the Kantonsrat.
- **Communes** (yearly, published by mid-March):
  `uv run scripts/steuerfuesse.py 2027` prints the `[zurich.communes]` table
  from the canton's open data.

`uv run pytest` checks the tables for transcription errors (federal step
continuity, cantonal bracket sums).

## Limitations

- No church tax (Kirchensteuer).
- No rate-determining income/assets (satzbestimmendes Einkommen/Vermögen) for
  income or assets taxed in other cantons or abroad.
- No separate taxes (Kapitalleistungen, Grundstückgewinnsteuer).
- `married` assumes two adults for the Personalsteuer; single parents (who
  also get the Verheiratetentarif) would pay CHF 24 less.
- Verified against the official Steuerrechner: the einfache Staatssteuer (the
  average rate is truncated to 3 decimals and the tax to whole francs) and the
  direkte Bundessteuer, and the Staats- und Gemeindesteuer (Steuerfuss
  amounts in Rappen, the total rounded to 5 Rappen).
