"""Unit tests for the cache module."""

import pytest
import tempfile
from pathlib import Path

from pyaot.cache import ArtifactHasher, CacheStorage, ArtifactMetadata, LRUCache
from pyaot.compiler.ir import IRFunction, IRType


class TestArtifactHasher:
    """Tests for ArtifactHasher."""
    
    def test_hash_determinism(self):
        hasher = ArtifactHasher()
        
        func = IRFunction(
            name="test_func",
            return_type=IRType.f64(),
            arg_names=["x", "y"],
            arg_types=[IRType.f64(), IRType.f64()],
        )
        
        hash1 = hasher.hash_function(func)
        hash2 = hasher.hash_function(func)
        
        assert hash1 == hash2
    
    def test_hash_different_functions(self):
        hasher = ArtifactHasher()
        
        func1 = IRFunction(
            name="func1",
            return_type=IRType.f64(),
            arg_names=["x"],
            arg_types=[IRType.f64()],
        )
        
        func2 = IRFunction(
            name="func2",
            return_type=IRType.f64(),
            arg_names=["x"],
            arg_types=[IRType.f64()],
        )
        
        hash1 = hasher.hash_function(func1)
        hash2 = hasher.hash_function(func2)
        
        assert hash1 != hash2
    
    def test_hash_includes_types(self):
        hasher = ArtifactHasher()
        
        func1 = IRFunction(
            name="func",
            return_type=IRType.f64(),
            arg_names=["x"],
            arg_types=[IRType.f64()],
        )
        
        func2 = IRFunction(
            name="func",
            return_type=IRType.i64(),  # Different return type
            arg_names=["x"],
            arg_types=[IRType.f64()],
        )
        
        hash1 = hasher.hash_function(func1)
        hash2 = hasher.hash_function(func2)
        
        assert hash1 != hash2
    
    def test_hash_with_assumptions(self):
        hasher = ArtifactHasher()
        
        func = IRFunction(
            name="func",
            return_type=IRType.f64(),
            arg_names=["x"],
            arg_types=[IRType.f64()],
        )
        
        hash1 = hasher.hash_function(func, {"shape": (10,)})
        hash2 = hasher.hash_function(func, {"shape": (20,)})
        
        assert hash1 != hash2


class TestCacheStorage:
    """Tests for CacheStorage."""
    
    def test_put_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = CacheStorage(cache_dir=Path(tmpdir))
            
            cache_key = "a" * 64  # 64 hex chars
            artifact_bytes = b"test artifact content"
            metadata = ArtifactMetadata(
                cache_key=cache_key,
                function_name="test_func",
                python_version="3.11.0",
                abi_tag="cpython311-linux-x86_64",
                created_at="2024-01-01T00:00:00",
            )
            
            storage.put(cache_key, artifact_bytes, metadata)
            
            assert storage.has(cache_key)
            
            retrieved = storage.get(cache_key)
            assert retrieved == artifact_bytes
            
            retrieved_meta = storage.get_metadata(cache_key)
            assert retrieved_meta.function_name == "test_func"
    
    def test_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = CacheStorage(cache_dir=Path(tmpdir))
            
            result = storage.get("nonexistent" + "0" * 54)
            assert result is None
    
    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = CacheStorage(cache_dir=Path(tmpdir))
            
            cache_key = "b" * 64
            storage.put(
                cache_key,
                b"content",
                ArtifactMetadata(
                    cache_key=cache_key,
                    function_name="f",
                    python_version="3.11",
                    abi_tag="test",
                    created_at="2024-01-01",
                ),
            )
            
            assert storage.has(cache_key)
            storage.remove(cache_key)
            assert not storage.has(cache_key)
    
    def test_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = CacheStorage(cache_dir=Path(tmpdir))
            
            for i in range(5):
                cache_key = f"{i:064x}"
                storage.put(
                    cache_key,
                    b"content",
                    ArtifactMetadata(
                        cache_key=cache_key,
                        function_name=f"func{i}",
                        python_version="3.11",
                        abi_tag="test",
                        created_at="2024-01-01",
                    ),
                )
            
            count = storage.clear()
            assert count == 5
    
    def test_list_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = CacheStorage(cache_dir=Path(tmpdir))
            
            for i in range(3):
                cache_key = f"{i:064x}"
                storage.put(
                    cache_key,
                    b"content",
                    ArtifactMetadata(
                        cache_key=cache_key,
                        function_name=f"func{i}",
                        python_version="3.11",
                        abi_tag="test",
                        created_at="2024-01-01",
                    ),
                )
            
            artifacts = storage.list_artifacts()
            assert len(artifacts) == 3


class TestLRUCache:
    """Tests for LRUCache."""
    
    def test_basic_operations(self):
        cache = LRUCache[str, int](max_size=3)
        
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        
        assert cache.get("a") == 1
        assert cache.get("b") == 2
        assert cache.get("c") == 3
        assert cache.get("d") is None
    
    def test_eviction(self):
        cache = LRUCache[str, int](max_size=3)
        
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("d", 4)  # Should evict "a"
        
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3
        assert cache.get("d") == 4
    
    def test_access_order(self):
        cache = LRUCache[str, int](max_size=3)
        
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        
        # Access "a" to make it recently used
        cache.get("a")
        
        # Add "d", should evict "b" (least recently used)
        cache.put("d", 4)
        
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3
        assert cache.get("d") == 4
    
    def test_remove(self):
        cache = LRUCache[str, int](max_size=3)
        cache.put("a", 1)
        
        assert cache.remove("a")
        assert cache.get("a") is None
        assert not cache.remove("a")
    
    def test_hit_rate(self):
        cache = LRUCache[str, int](max_size=3)
        cache.put("a", 1)
        
        cache.get("a")  # Hit
        cache.get("a")  # Hit
        cache.get("b")  # Miss
        
        assert cache.hit_rate == pytest.approx(2/3)
