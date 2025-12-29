"""
Profile data structures for PyAOT.

Stores function call statistics, type signatures, and shape information.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any, Optional
from collections import Counter
import hashlib


@dataclass
class TypeSignature:
    """Represents the type signature of a function call.
    
    Stores argument types and shapes for tracking stability.
    """
    arg_types: Tuple[str, ...]  # Tuple of type names
    kwarg_types: Dict[str, str]  # Keyword arg name -> type name
    
    def __hash__(self) -> int:
        return hash((self.arg_types, tuple(sorted(self.kwarg_types.items()))))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TypeSignature):
            return False
        return self.arg_types == other.arg_types and self.kwarg_types == other.kwarg_types
    
    def to_dict(self) -> dict:
        return {
            "arg_types": list(self.arg_types),
            "kwarg_types": self.kwarg_types,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TypeSignature":
        return cls(
            arg_types=tuple(data["arg_types"]),
            kwarg_types=data["kwarg_types"],
        )


@dataclass
class ShapeSignature:
    """Represents shape information for array arguments.
    
    Tracks shapes of NumPy arrays and similar buffer types.
    """
    arg_shapes: Tuple[Optional[Tuple[int, ...]], ...]  # Shape per arg (None if not array)
    
    def __hash__(self) -> int:
        return hash(self.arg_shapes)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ShapeSignature):
            return False
        return self.arg_shapes == other.arg_shapes
    
    def to_dict(self) -> dict:
        return {
            "arg_shapes": [list(s) if s else None for s in self.arg_shapes],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ShapeSignature":
        return cls(
            arg_shapes=tuple(
                tuple(s) if s else None for s in data["arg_shapes"]
            ),
        )


@dataclass
class FunctionProfile:
    """Profile data for a single function.
    
    Tracks call frequency, execution time, and type/shape signatures
    for stability analysis.
    """
    # Identity
    module: str
    qualname: str
    filename: str
    lineno: int
    
    # Call statistics
    call_count: int = 0
    total_time_ns: int = 0  # Inclusive wall-time in nanoseconds
    
    # Type signatures observed (signature -> count)
    type_signatures: Counter = field(default_factory=Counter)
    
    # Shape signatures observed (signature -> count)
    shape_signatures: Counter = field(default_factory=Counter)
    
    # Callees (function_key -> call count from this function)
    callees: Counter = field(default_factory=Counter)
    
    # Side effect indicators
    has_global_reads: bool = False
    has_global_writes: bool = False
    has_io: bool = False
    
    @property
    def key(self) -> str:
        """Unique key for this function."""
        return f"{self.module}:{self.qualname}"
    
    @property
    def avg_time_ns(self) -> float:
        """Average execution time per call."""
        if self.call_count == 0:
            return 0.0
        return self.total_time_ns / self.call_count
    
    @property
    def total_time_sec(self) -> float:
        """Total time in seconds."""
        return self.total_time_ns / 1e9
    
    def record_call(
        self,
        duration_ns: int,
        type_sig: TypeSignature,
        shape_sig: ShapeSignature,
    ) -> None:
        """Record a function call with timing and signatures."""
        self.call_count += 1
        self.total_time_ns += duration_ns
        self.type_signatures[type_sig] += 1
        self.shape_signatures[shape_sig] += 1
    
    def get_dominant_type_signature(self) -> Optional[TypeSignature]:
        """Get the most common type signature."""
        if not self.type_signatures:
            return None
        return self.type_signatures.most_common(1)[0][0]
    
    def get_dominant_shape_signature(self) -> Optional[ShapeSignature]:
        """Get the most common shape signature."""
        if not self.shape_signatures:
            return None
        return self.shape_signatures.most_common(1)[0][0]
    
    def get_type_stability(self) -> float:
        """Calculate type stability score.
        
        Returns:
            Ratio of calls matching the dominant type signature.
        """
        if self.call_count == 0:
            return 0.0
        if not self.type_signatures:
            return 0.0
        dominant_count = self.type_signatures.most_common(1)[0][1]
        return dominant_count / self.call_count
    
    def get_shape_stability(self) -> float:
        """Calculate shape stability score.
        
        Returns:
            Ratio of calls matching the dominant shape signature.
        """
        if self.call_count == 0:
            return 0.0
        if not self.shape_signatures:
            return 1.0  # No shapes = stable
        dominant_count = self.shape_signatures.most_common(1)[0][1]
        return dominant_count / self.call_count
    
    def get_stability_score(self) -> float:
        """Calculate combined stability score per specification.
        
        Formula: 0.5 * type_stability + 0.5 * shape_stability
        """
        return 0.5 * self.get_type_stability() + 0.5 * self.get_shape_stability()
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "module": self.module,
            "qualname": self.qualname,
            "filename": self.filename,
            "lineno": self.lineno,
            "call_count": self.call_count,
            "total_time_ns": self.total_time_ns,
            "type_signatures": [
                {"signature": sig.to_dict(), "count": count}
                for sig, count in self.type_signatures.items()
            ],
            "shape_signatures": [
                {"signature": sig.to_dict(), "count": count}
                for sig, count in self.shape_signatures.items()
            ],
            "callees": dict(self.callees),
            "has_global_reads": self.has_global_reads,
            "has_global_writes": self.has_global_writes,
            "has_io": self.has_io,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FunctionProfile":
        """Deserialize from dictionary."""
        profile = cls(
            module=data["module"],
            qualname=data["qualname"],
            filename=data["filename"],
            lineno=data["lineno"],
            call_count=data["call_count"],
            total_time_ns=data["total_time_ns"],
            has_global_reads=data.get("has_global_reads", False),
            has_global_writes=data.get("has_global_writes", False),
            has_io=data.get("has_io", False),
        )
        
        # Restore type signatures
        for item in data.get("type_signatures", []):
            sig = TypeSignature.from_dict(item["signature"])
            profile.type_signatures[sig] = item["count"]
        
        # Restore shape signatures
        for item in data.get("shape_signatures", []):
            sig = ShapeSignature.from_dict(item["signature"])
            profile.shape_signatures[sig] = item["count"]
        
        # Restore callees
        profile.callees = Counter(data.get("callees", {}))
        
        return profile


@dataclass
class ProfileData:
    """Container for all profiling data.
    
    Stores function profiles keyed by function identifier.
    """
    functions: Dict[str, FunctionProfile] = field(default_factory=dict)
    python_version: str = ""
    profile_duration_ns: int = 0
    
    def get_or_create(
        self,
        module: str,
        qualname: str,
        filename: str,
        lineno: int,
    ) -> FunctionProfile:
        """Get existing profile or create new one."""
        key = f"{module}:{qualname}"
        if key not in self.functions:
            self.functions[key] = FunctionProfile(
                module=module,
                qualname=qualname,
                filename=filename,
                lineno=lineno,
            )
        return self.functions[key]
    
    def get(self, key: str) -> Optional[FunctionProfile]:
        """Get a function profile by key."""
        return self.functions.get(key)
    
    def __len__(self) -> int:
        return len(self.functions)
    
    def __iter__(self):
        return iter(self.functions.values())
    
    def get_hash(self) -> str:
        """Get a content hash of the profile data."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "python_version": self.python_version,
            "profile_duration_ns": self.profile_duration_ns,
            "functions": {
                key: profile.to_dict()
                for key, profile in self.functions.items()
            },
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProfileData":
        """Deserialize from dictionary."""
        profile_data = cls(
            python_version=data.get("python_version", ""),
            profile_duration_ns=data.get("profile_duration_ns", 0),
        )
        for key, func_data in data.get("functions", {}).items():
            profile_data.functions[key] = FunctionProfile.from_dict(func_data)
        return profile_data
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ProfileData":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def save(self, path: str) -> None:
        """Save to file."""
        with open(path, "w") as f:
            f.write(self.to_json())
    
    @classmethod
    def load(cls, path: str) -> "ProfileData":
        """Load from file."""
        with open(path, "r") as f:
            return cls.from_json(f.read())
