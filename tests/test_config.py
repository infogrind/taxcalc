import pytest

from taxcalc.config import Config, find_config_path, load_config, save_config
from taxcalc.errors import TaxcalcError


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_config_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "does-not-exist.toml")
    assert config == Config(tarif=None, commune=None, children=0)


def test_loads_household_section(tmp_path):
    path = write(tmp_path, '[household]\ntarif = "married"\ncommune = "Zürich"\nchildren = 2\n')
    assert load_config(path) == Config(tarif="married", commune="Zürich", children=2)


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    config = Config(tarif="single", commune='Aeugst a.A. "x"', children=1)
    save_config(path, config)
    assert load_config(path) == config


def test_invalid_toml_raises(tmp_path):
    with pytest.raises(TaxcalcError, match="not valid TOML"):
        load_config(write(tmp_path, "this is not [valid toml"))


def test_section_not_a_table_raises(tmp_path):
    with pytest.raises(TaxcalcError, match=r"\[household\] must be a table"):
        load_config(write(tmp_path, "household = 5\n"))


def test_unknown_section_raises(tmp_path):
    with pytest.raises(TaxcalcError, match="unknown section"):
        load_config(write(tmp_path, "[houshold]\n"))


def test_bad_tarif_raises(tmp_path):
    with pytest.raises(TaxcalcError, match="household.tarif must be one of: single, married"):
        load_config(write(tmp_path, '[household]\ntarif = "verheiratet"\n'))


def test_commune_not_a_string_raises(tmp_path):
    with pytest.raises(TaxcalcError, match="household.commune must be a string"):
        load_config(write(tmp_path, "[household]\ncommune = 261\n"))


@pytest.mark.parametrize("value", ["-1", '"2"', "true", "1.5"])
def test_bad_children_raises(tmp_path, value):
    with pytest.raises(TaxcalcError, match="household.children must be a non-negative integer"):
        load_config(write(tmp_path, f"[household]\nchildren = {value}\n"))


def test_unknown_field_raises(tmp_path):
    with pytest.raises(TaxcalcError, match=r"unknown household\.\* setting"):
        load_config(write(tmp_path, '[household]\ncomune = "Zürich"\n'))


def test_find_config_path_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert find_config_path() == tmp_path / ".config" / "taxcalc" / "config.toml"


def test_find_config_path_honors_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert find_config_path() == tmp_path / "xdg" / "taxcalc" / "config.toml"


def test_find_config_path_ignores_empty_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert find_config_path() == tmp_path / ".config" / "taxcalc" / "config.toml"


def test_find_config_path_ignores_relative_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert find_config_path() == tmp_path / ".config" / "taxcalc" / "config.toml"
