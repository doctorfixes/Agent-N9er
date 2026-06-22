import os
import sys
import importlib

import pytest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)


def _reload_config(**env_overrides):
    old_env = {}
    for k, v in env_overrides.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    import shared.config as cfg
    importlib.reload(cfg)

    for k, old_v in old_env.items():
        if old_v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old_v

    return cfg


class TestConfigProfiles:
    def test_development_defaults(self):
        cfg = _reload_config(VERIXIO_ENV="development")
        assert cfg.MAX_RETRIES == 3
        assert cfg.DEFAULT_TIMEOUT == 10.0
        assert cfg.LOG_LEVEL == "DEBUG"
        assert cfg.DB_BACKEND == "sqlite"

    def test_staging_profile(self):
        cfg = _reload_config(VERIXIO_ENV="staging")
        assert cfg.MAX_RETRIES == 3
        assert cfg.RETRY_BACKOFF == 0.5
        assert cfg.DEFAULT_TIMEOUT == 15.0
        assert cfg.LOG_LEVEL == "INFO"
        assert cfg.DB_BACKEND == "postgres"
        assert "staging" in cfg.CORS_ORIGINS[0]

    def test_production_profile(self):
        cfg = _reload_config(VERIXIO_ENV="production")
        assert cfg.MAX_RETRIES == 5
        assert cfg.RETRY_BACKOFF == 1.0
        assert cfg.PIPELINE_TIMEOUT == 30.0
        assert cfg.RATE_LIMIT_MAX_REQUESTS == 500
        assert cfg.LOG_LEVEL == "WARNING"
        assert cfg.DB_BACKEND == "postgres"
        assert "agentn9ner.com" in cfg.CORS_ORIGINS[0]

    def test_env_var_overrides_profile(self):
        cfg = _reload_config(VERIXIO_ENV="production", MAX_RETRIES="10")
        assert cfg.MAX_RETRIES == 10

    def test_unknown_env_falls_back_to_development(self):
        cfg = _reload_config(VERIXIO_ENV="unknown")
        assert cfg.MAX_RETRIES == 3
        assert cfg.LOG_LEVEL == "DEBUG"

    def test_cors_origins_split(self):
        cfg = _reload_config(
            VERIXIO_ENV="development",
            CORS_ORIGINS="http://localhost:3000,http://localhost:8080"
        )
        assert len(cfg.CORS_ORIGINS) == 2
        assert "http://localhost:8080" in cfg.CORS_ORIGINS


class TestConfigValues:
    def test_all_timeouts_positive(self):
        cfg = _reload_config(VERIXIO_ENV="development")
        assert cfg.DEFAULT_TIMEOUT > 0
        assert cfg.PIPELINE_TIMEOUT > 0
        assert cfg.QUICK_TIMEOUT > 0

    def test_pipeline_timeout_gte_default(self):
        for env in ("development", "staging", "production"):
            cfg = _reload_config(VERIXIO_ENV=env)
            assert cfg.PIPELINE_TIMEOUT >= cfg.DEFAULT_TIMEOUT

    def test_production_retries_gte_development(self):
        dev = _reload_config(VERIXIO_ENV="development")
        prod = _reload_config(VERIXIO_ENV="production")
        assert prod.MAX_RETRIES >= dev.MAX_RETRIES
