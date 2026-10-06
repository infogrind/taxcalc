"""Print the [zurich.communes] TOML table for a tax year.

Source: Statistisches Amt Kanton Zürich, "Zürcher Gemeindesteuerfüsse - Zeitreihe"
(open data, https://www.zh.ch/de/steuern-finanzen/steuern/steuerstatistiken/aktuelle-gemeinde-steuerfuesse.html).
Uses the commune Steuerfuss for natural persons without church tax (STF_O_KIRCHE1).

Usage: uv run scripts/steuerfuesse.py 2027 >> /tmp/snippet.toml
then paste the output into src/taxcalc/rates/2027.toml.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request

CSV_URL = "https://www.web.statistik.zh.ch/ogd/data/steuerfuesse/kanton_zuerich_stf_timeseries.csv"


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    year = sys.argv[1]
    with urllib.request.urlopen(CSV_URL) as response:
        text = response.read().decode("utf-8-sig")
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r["YEAR"] == year]
    if not rows:
        print(f"no Steuerfuss data for {year} yet", file=sys.stderr)
        return 1
    print("[zurich.communes]")
    print(f"# Gemeindesteuerfuss {year} in % (without church tax), source: {CSV_URL}")
    for row in sorted(rows, key=lambda r: r["GDE_NAME"]):
        print(f'"{row["GDE_NAME"]}" = {row["STF_O_KIRCHE1"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
