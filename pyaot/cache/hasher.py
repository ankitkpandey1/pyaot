"""
Content-addressed hashing for artifact caching.

Uses SHA-256 hashes of (IR + type assumptions + Python version + ABI tag)
to create unique, deterministic cache keys.
"""

import hashlib
import json
import platform
import struct
from typing import Any, Dict, Optional

from pyaot.compiler.ir import IRFunction, IRModule


def _stable_hash_dict(d: Dict[str, Any]) -> str:
    """Create a stable hash of a dictionary."""
    # Sort keys for determinism
    content = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def _get_abi_tag() -> str:
    """Get the ABI tag for the current Python installation."""
    import sys
    
    # Include Python version and implementation
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    impl = platform.python_implementation().lower()
    
    # Include platform info
    arch = platform.machine()
    system = platform.system().lower()
    
    return f"{impl}{version}-{system}-{arch}"


class ArtifactHasher:
    """Computes content-addressed hashes for artifacts.
    
    The hash includes:
    - IR content (deterministic serialization)
    - Type assumptions
    - Python version
    - ABI tag
    """
    
    def __init__(self):
        self.python_version = platform.python_version()
        self.abi_tag = _get_abi_tag()
    
    def hash_function(
        self,
        ir_func: IRFunction,
        type_assumptions: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Hash a single IR function.
        
        Args:
            ir_func: The IR function to hash.
            type_assumptions: Additional type assumptions.
            
        Returns:
            SHA-256 hash string.
        """
        hasher = hashlib.sha256()
        
        # Add function name
        hasher.update(ir_func.name.encode())
        
        # Add return type
        hasher.update(str(ir_func.return_type).encode())
        
        # Add argument types
        for arg_type in ir_func.arg_types:
            hasher.update(str(arg_type).encode())
        
        # Add argument names
        for arg_name in ir_func.arg_names:
            hasher.update(arg_name.encode())
        
        # Add IR content (blocks and instructions)
        for block in ir_func.blocks:
            hasher.update(block.name.encode())
            for inst in block.instructions:
                hasher.update(str(inst).encode())
        
        # Add type assumptions
        if type_assumptions:
            hasher.update(_stable_hash_dict(type_assumptions).encode())
        
        # Add Python version and ABI
        hasher.update(self.python_version.encode())
        hasher.update(self.abi_tag.encode())
        
        return hasher.hexdigest()
    
    def hash_module(
        self,
        ir_module: IRModule,
        type_assumptions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        """Hash an entire IR module.
        
        Args:
            ir_module: The IR module to hash.
            type_assumptions: Type assumptions per function.
            
        Returns:
            SHA-256 hash string.
        """
        hasher = hashlib.sha256()
        
        # Add module name
        hasher.update(ir_module.name.encode())
        
        # Add each function (in sorted order for determinism)
        for func_name in sorted(ir_module.functions.keys()):
            func = ir_module.functions[func_name]
            func_assumptions = None
            if type_assumptions:
                func_assumptions = type_assumptions.get(func_name)
            func_hash = self.hash_function(func, func_assumptions)
            hasher.update(func_hash.encode())
        
        return hasher.hexdigest()
    
    def hash_profile(
        self,
        module_name: str,
        function_name: str,
        type_signature: str,
        shape_signature: str,
    ) -> str:
        """Hash a profile signature for cache lookup.
        
        This creates a key based on the observed profile,
        before IR is generated.
        
        Args:
            module_name: Module containing the function.
            function_name: Function name.
            type_signature: String representation of type signature.
            shape_signature: String representation of shape signature.
            
        Returns:
            SHA-256 hash string.
        """
        hasher = hashlib.sha256()
        hasher.update(module_name.encode())
        hasher.update(function_name.encode())
        hasher.update(type_signature.encode())
        hasher.update(shape_signature.encode())
        hasher.update(self.python_version.encode())
        hasher.update(self.abi_tag.encode())
        return hasher.hexdigest()


def compute_hash(
    ir_func: IRFunction,
    type_assumptions: Optional[Dict[str, Any]] = None,
) -> str:
    """Convenience function to compute artifact hash.
    
    Args:
        ir_func: The IR function to hash.
        type_assumptions: Additional type assumptions.
        
    Returns:
        SHA-256 hash string.
    """
    hasher = ArtifactHasher()
    return hasher.hash_function(ir_func, type_assumptions)
