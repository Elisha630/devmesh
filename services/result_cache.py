"""
DevMesh Result Caching Service
------------------------------
LRU cache with TTL for task results, supporting invalidation and statistics.
"""

import time
import hashlib
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict


__all__ = [
    "CacheEntry",
    "ResultCache",
    "get_cache",
]


@dataclass
class CacheEntry:
    """A cached result with TTL and metadata."""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    ttl_sec: int = 3600
    hit_count: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() - self.created_at > self.ttl_sec
    
    def update_access(self) -> None:
        """Update access time and hit count."""
        self.accessed_at = time.time()
        self.hit_count += 1


class ResultCache:
    """LRU cache with TTL for task results."""
    
    def __init__(self, max_size_mb: int = 100, default_ttl_sec: int = 3600):
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.default_ttl_sec = default_ttl_sec
        self.cache: Dict[str, CacheEntry] = OrderedDict()
        self.current_size_bytes = 0
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "entries": 0,
        }
    
    def _estimate_size(self, value: Any) -> int:
        """Estimate size of a value in bytes."""
        if isinstance(value, (str, bytes)):
            return len(value if isinstance(value, bytes) else value.encode())
        elif isinstance(value, dict):
            return sum(self._estimate_size(k) + self._estimate_size(v) for k, v in value.items())
        elif isinstance(value, (list, tuple)):
            return sum(self._estimate_size(item) for item in value)
        else:
            # Rough estimate for other types
            return 64
    
    def _make_key(self, task_id: str, params: Optional[Dict] = None) -> str:
        """Create a cache key from task_id and parameters."""
        if not params:
            return task_id
        
        # Hash params for consistent key generation
        params_str = str(sorted(params.items()))
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        return f"{task_id}:{params_hash}"
    
    def get(self, task_id: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Get value from cache."""
        key = self._make_key(task_id, params)
        
        if key not in self.cache:
            self.stats["misses"] += 1
            return None
        
        entry = self.cache[key]
        
        # Check expiration
        if entry.is_expired():
            del self.cache[key]
            self.current_size_bytes -= self._estimate_size(entry.value)
            self.stats["misses"] += 1
            return None
        
        # Update access time and move to end (LRU)
        entry.update_access()
        self.cache.move_to_end(key)
        self.stats["hits"] += 1
        return entry.value
    
    def set(
        self,
        task_id: str,
        value: Any,
        params: Optional[Dict] = None,
        ttl_sec: Optional[int] = None,
    ) -> None:
        """Set value in cache."""
        key = self._make_key(task_id, params)
        ttl = ttl_sec or self.default_ttl_sec
        value_size = self._estimate_size(value)
        
        # Remove old entry if exists
        if key in self.cache:
            self.current_size_bytes -= self._estimate_size(self.cache[key].value)
            del self.cache[key]
        
        # Evict entries to make room if needed
        while self.current_size_bytes + value_size > self.max_size_bytes and self.cache:
            oldest_key, oldest_entry = self.cache.popitem(last=False)
            self.current_size_bytes -= self._estimate_size(oldest_entry.value)
            self.stats["evictions"] += 1
        
        # Add new entry
        entry = CacheEntry(key=key, value=value, ttl_sec=ttl)
        self.cache[key] = entry
        self.current_size_bytes += value_size
        self.stats["entries"] = len(self.cache)
    
    def invalidate(self, task_id: str = None, params: Optional[Dict] = None) -> int:
        """Invalidate cache entries. If task_id is None, clear all."""
        if task_id is None:
            count = len(self.cache)
            self.cache.clear()
            self.current_size_bytes = 0
            self.stats["entries"] = 0
            return count
        
        key = self._make_key(task_id, params)
        
        if key in self.cache:
            entry = self.cache[key]
            self.current_size_bytes -= self._estimate_size(entry.value)
            del self.cache[key]
            self.stats["entries"] = len(self.cache)
            return 1
        return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            **self.stats,
            "hit_rate": f"{hit_rate:.1f}%",
            "current_size_mb": self.current_size_bytes / (1024 * 1024),
            "max_size_mb": self.max_size_bytes / (1024 * 1024),
        }
    
    def cleanup_expired(self) -> int:
        """Remove expired entries."""
        expired_keys = [k for k, v in self.cache.items() if v.is_expired()]
        
        for key in expired_keys:
            entry = self.cache[key]
            self.current_size_bytes -= self._estimate_size(entry.value)
            del self.cache[key]
        
        self.stats["entries"] = len(self.cache)
        return len(expired_keys)


# Global cache instance
_cache: Optional[ResultCache] = None


def get_cache(max_size_mb: int = 100, default_ttl_sec: int = 3600) -> ResultCache:
    """Get the global result cache instance."""
    global _cache
    if _cache is None:
        _cache = ResultCache(max_size_mb, default_ttl_sec)
    return _cache


def init_cache(max_size_mb: int = 100, default_ttl_sec: int = 3600) -> ResultCache:
    """Initialize the global cache."""
    global _cache
    _cache = ResultCache(max_size_mb, default_ttl_sec)
    return _cache
