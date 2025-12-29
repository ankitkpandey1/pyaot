"""
Disk-persistent cache storage for compiled artifacts.

Uses a content-addressed storage scheme with atomic writes.
"""

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import platform

from pyaot.config import get_config
from pyaot.exceptions import CacheError
from pyaot.logging import log_cache_event


@dataclass
class ArtifactMetadata:
    """Metadata for a cached artifact."""
    cache_key: str
    function_name: str
    python_version: str
    abi_tag: str
    created_at: str
    source_file: Optional[str] = None
    ir_hash: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactMetadata":
        return cls(**data)


class CacheStorage:
    """Disk-persistent storage for compiled artifacts.
    
    Directory structure:
        ~/.aot_cache/
            {hash[:2]}/
                {hash}.so      # Native artifact
                {hash}.json    # Metadata
    
    Uses atomic writes via temp files + os.rename to prevent corruption.
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize cache storage.
        
        Args:
            cache_dir: Cache directory (uses config default if None).
        """
        self.cache_dir = cache_dir or get_config().cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_artifact_path(self, cache_key: str) -> Path:
        """Get path for an artifact file."""
        prefix = cache_key[:2]
        subdir = self.cache_dir / prefix
        subdir.mkdir(exist_ok=True)
        return subdir / f"{cache_key}.so"
    
    def _get_metadata_path(self, cache_key: str) -> Path:
        """Get path for metadata file."""
        prefix = cache_key[:2]
        return self.cache_dir / prefix / f"{cache_key}.json"
    
    def has(self, cache_key: str) -> bool:
        """Check if an artifact exists in cache."""
        artifact_path = self._get_artifact_path(cache_key)
        metadata_path = self._get_metadata_path(cache_key)
        return artifact_path.exists() and metadata_path.exists()
    
    def get(self, cache_key: str) -> Optional[bytes]:
        """Get artifact bytes from cache.
        
        Args:
            cache_key: The cache key (hash).
            
        Returns:
            Artifact bytes, or None if not found.
        """
        artifact_path = self._get_artifact_path(cache_key)
        
        if not artifact_path.exists():
            log_cache_event("miss", cache_key)
            return None
        
        try:
            log_cache_event("hit", cache_key)
            return artifact_path.read_bytes()
        except IOError as e:
            raise CacheError(
                f"Failed to read artifact: {e}",
                cache_key=cache_key,
                operation="read",
            )
    
    def get_metadata(self, cache_key: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata.
        
        Args:
            cache_key: The cache key (hash).
            
        Returns:
            ArtifactMetadata, or None if not found.
        """
        metadata_path = self._get_metadata_path(cache_key)
        
        if not metadata_path.exists():
            return None
        
        try:
            data = json.loads(metadata_path.read_text())
            return ArtifactMetadata.from_dict(data)
        except (IOError, json.JSONDecodeError) as e:
            raise CacheError(
                f"Failed to read metadata: {e}",
                cache_key=cache_key,
                operation="read",
            )
    
    def put(
        self,
        cache_key: str,
        artifact_bytes: bytes,
        metadata: ArtifactMetadata,
    ) -> Path:
        """Store artifact in cache with atomic write.
        
        Uses temp file + rename for atomicity.
        
        Args:
            cache_key: The cache key (hash).
            artifact_bytes: The artifact content.
            metadata: Artifact metadata.
            
        Returns:
            Path to the stored artifact.
        """
        artifact_path = self._get_artifact_path(cache_key)
        metadata_path = self._get_metadata_path(cache_key)
        
        try:
            # Write artifact atomically
            with tempfile.NamedTemporaryFile(
                dir=artifact_path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(artifact_bytes)
                tmp_artifact = tmp.name
            
            os.rename(tmp_artifact, artifact_path)
            
            # Write metadata atomically
            with tempfile.NamedTemporaryFile(
                dir=metadata_path.parent,
                delete=False,
                suffix=".tmp",
                mode="w",
            ) as tmp:
                json.dump(metadata.to_dict(), tmp, indent=2)
                tmp_metadata = tmp.name
            
            os.rename(tmp_metadata, metadata_path)
            
            log_cache_event("write", cache_key, metadata.function_name)
            return artifact_path
            
        except IOError as e:
            # Clean up partial writes
            for path in [tmp_artifact, tmp_metadata]:
                try:
                    os.unlink(path)
                except (NameError, FileNotFoundError):
                    pass
            
            raise CacheError(
                f"Failed to write artifact: {e}",
                cache_key=cache_key,
                operation="write",
            )
    
    def remove(self, cache_key: str) -> bool:
        """Remove an artifact from cache.
        
        Args:
            cache_key: The cache key (hash).
            
        Returns:
            True if artifact was removed, False if not found.
        """
        artifact_path = self._get_artifact_path(cache_key)
        metadata_path = self._get_metadata_path(cache_key)
        
        removed = False
        
        if artifact_path.exists():
            artifact_path.unlink()
            removed = True
        
        if metadata_path.exists():
            metadata_path.unlink()
            removed = True
        
        if removed:
            log_cache_event("evict", cache_key)
        
        return removed
    
    def clear(self) -> int:
        """Clear all cached artifacts.
        
        Returns:
            Number of artifacts removed.
        """
        count = 0
        for subdir in self.cache_dir.iterdir():
            if subdir.is_dir() and len(subdir.name) == 2:
                for file in subdir.iterdir():
                    file.unlink()
                    if file.suffix == ".so":
                        count += 1
                try:
                    subdir.rmdir()
                except OSError:
                    pass  # Directory not empty
        return count
    
    def list_artifacts(self) -> list:
        """List all cached artifacts.
        
        Returns:
            List of (cache_key, metadata) tuples.
        """
        artifacts = []
        for subdir in self.cache_dir.iterdir():
            if subdir.is_dir() and len(subdir.name) == 2:
                for file in subdir.iterdir():
                    if file.suffix == ".json":
                        cache_key = file.stem
                        metadata = self.get_metadata(cache_key)
                        if metadata:
                            artifacts.append((cache_key, metadata))
        return artifacts
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.
        
        Returns:
            Dict with cache stats.
        """
        total_size = 0
        artifact_count = 0
        
        for subdir in self.cache_dir.iterdir():
            if subdir.is_dir():
                for file in subdir.iterdir():
                    total_size += file.stat().st_size
                    if file.suffix == ".so":
                        artifact_count += 1
        
        return {
            "directory": str(self.cache_dir),
            "artifact_count": artifact_count,
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
        }
    
    def validate_abi(self, cache_key: str) -> bool:
        """Check if cached artifact is ABI-compatible.
        
        Args:
            cache_key: The cache key to check.
            
        Returns:
            True if compatible with current Python.
        """
        metadata = self.get_metadata(cache_key)
        if metadata is None:
            return False
        
        current_version = platform.python_version()
        
        # Check major.minor version match
        cached_parts = metadata.python_version.split(".")[:2]
        current_parts = current_version.split(".")[:2]
        
        return cached_parts == current_parts
