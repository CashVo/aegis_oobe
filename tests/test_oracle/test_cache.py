# tests/test_oracle/test_cache.py
"""Unit tests for the Oracle Response Cache."""

import pytest
import asyncio
import os
import tempfile

from aegis.schemas.oracle import OracleAction, OracleRequest, OracleResponse
from aegis.agents.oracle.cache import ResponseCache


@pytest.fixture
def cache_db_path(tmp_path):
    return str(tmp_path / "test_oracle_cache.db")


@pytest.fixture
def cache_config(cache_db_path):
    return {
        "enabled": True,
        "db_path": cache_db_path,
        "ttl_seconds": 60,
        "max_entries": 100,
    }


@pytest.fixture
def sample_request():
    return OracleRequest(
        action=OracleAction.QUERY,
        prompt="What is Python?",
        temperature=0.7,
        max_tokens=500,
    )


@pytest.fixture
def sample_response():
    return OracleResponse(
        success=True,
        content="Python is a programming language.",
        llm_used="test-model",
        tokens_used={"prompt": 10, "completion": 8, "total": 18},
    )


class TestResponseCache:

    @pytest.mark.asyncio
    async def test_initialize(self, cache_config):
        cache = ResponseCache(cache_config)
        await cache.initialize()
        assert cache._initialized is True
        await cache.flush()

    @pytest.mark.asyncio
    async def test_store_and_retrieve(
        self, cache_config, sample_request, sample_response
    ):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)

        result = await cache.get(key)
        assert result is not None
        assert result["content"] == "Python is a programming language."
        assert result["llm_used"] == "test-model"

        await cache.flush()

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache_config):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        result = await cache.get("nonexistent_key")
        assert result is None

        await cache.flush()

    @pytest.mark.asyncio
    async def test_cache_disabled(self, cache_config, sample_request, sample_response):
        cache_config["enabled"] = False
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)

        result = await cache.get(key)
        assert result is None  # Cache disabled, always miss

    @pytest.mark.asyncio
    async def test_compute_key_deterministic(self, cache_config, sample_request):
        cache = ResponseCache(cache_config)
        key1 = cache.compute_key(sample_request, "model-a")
        key2 = cache.compute_key(sample_request, "model-a")
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_compute_key_varies_by_model(self, cache_config, sample_request):
        cache = ResponseCache(cache_config)
        key1 = cache.compute_key(sample_request, "model-a")
        key2 = cache.compute_key(sample_request, "model-b")
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_invalidate(self, cache_config, sample_request, sample_response):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)
        assert (await cache.get(key)) is not None

        await cache.invalidate(key)
        assert (await cache.get(key)) is None

        await cache.flush()

    @pytest.mark.asyncio
    async def test_stats(self, cache_config, sample_request, sample_response):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)
        await cache.get(key)  # One hit

        stats = await cache.stats()
        assert stats["enabled"] is True
        assert stats["total_entries"] == 1
        assert stats["total_hits"] >= 1

        await cache.flush()
