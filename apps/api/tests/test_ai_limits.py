from myfood.ai.limits import IafoodLimits, load_limits, save_limits
from myfood.config import get_settings


def test_load_limits_returns_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))

    limits = load_limits()

    assert limits.per_profile_daily == 10
    assert limits.instance_daily == 30
    assert limits.max_tokens_per_call == 8000


def test_save_and_load_round_trip_through_nested_dir(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "iafood.json"
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(path))

    save_limits(IafoodLimits(per_profile_daily=5, instance_daily=50, max_tokens_per_call=4000))
    loaded = load_limits()

    assert path.exists()
    assert loaded == IafoodLimits(per_profile_daily=5, instance_daily=50, max_tokens_per_call=4000)


def test_save_limits_file_is_not_world_readable(tmp_path, monkeypatch):
    path = tmp_path / "iafood.json"
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(path))

    save_limits(IafoodLimits())

    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_save_overwrites_previous_value(tmp_path, monkeypatch):
    path = tmp_path / "iafood.json"
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(path))

    save_limits(IafoodLimits(per_profile_daily=1))
    save_limits(IafoodLimits(per_profile_daily=2))

    assert load_limits().per_profile_daily == 2
