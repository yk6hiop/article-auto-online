from __future__ import annotations

import os

from online_app.runtime_config import apply_environment_overrides


class _FakeCore:
    API_KEYS_NORMAL = [{"name": "固定キー", "key": "AIzaHardcoded"}]
    API_KEYS_MOECHIN = [{"name": "固定もえちん", "key": "AIzaMoeHardcoded"}]
    SITES_NORMAL = {
        "2": {"name": "結びのマリッジ", "url": "https://old.example", "user": "old", "pass": "oldpass", "type": "A"}
    }
    SITES_MOECHIN = {
        "7": {"name": "もえちん", "url": "https://moe.example", "user": "moe", "pass": "moepass", "type": "C"}
    }
    SITES_ALL = {**SITES_NORMAL, **SITES_MOECHIN}


def test_apply_environment_overrides_replaces_keys_and_wp_sites():
    old_env = {k: os.environ.get(k) for k in [
        "ONLINE_GEMINI_KEYS_NORMAL_JSON",
        "ONLINE_GEMINI_KEYS_MOECHIN_JSON",
        "ONLINE_WP_SITE_OVERRIDES_JSON",
    ]}
    try:
        os.environ["ONLINE_GEMINI_KEYS_NORMAL_JSON"] = '[{"name":"env normal","key":"env-key"}]'
        os.environ["ONLINE_GEMINI_KEYS_MOECHIN_JSON"] = '[{"name":"env moechin","key":"env-moe-key"}]'
        os.environ["ONLINE_WP_SITE_OVERRIDES_JSON"] = '{"2":{"url":"https://new.example","user":"new-user","pass":"new-pass"}}'

        core = apply_environment_overrides(_FakeCore())

        assert core.API_KEYS_NORMAL == [{"name": "env normal", "key": "env-key"}]
        assert core.API_KEYS_MOECHIN == [{"name": "env moechin", "key": "env-moe-key"}]
        assert core.SITES_NORMAL["2"]["url"] == "https://new.example"
        assert core.SITES_NORMAL["2"]["user"] == "new-user"
        assert core.SITES_NORMAL["2"]["pass"] == "new-pass"
        assert core.SITES_ALL["2"]["url"] == "https://new.example"
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
