"""
Guard generation for AOT compiled functions.

Guards check that runtime arguments match the assumptions
made during compilation. If guards fail, execution falls
back to the original Python function.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum, auto
import threading

from pyaot.types.inference import InferredType, IRTypeKind
from pyaot.logging import log_guard_failure


class GuardKind(Enum):
    """Types of guards."""
    TYPE = auto()       # isinstance check
    SHAPE = auto()      # Array shape check
    DTYPE = auto()      # Array dtype check
    GLOBAL_VERSION = auto()  # Global variable versioning
    VALUE_RANGE = auto()     # Value bounds check


@dataclass
class Guard:
    """A single guard check.
    
    Guards are lightweight checks that determine if the
    native fast path can be taken.
    """
    kind: GuardKind
    arg_index: int
    expected: Any
    description: str
    
    def check(self, arg: Any) -> bool:
        """Check if the guard passes for the given argument."""
        if self.kind == GuardKind.TYPE:
            return isinstance(arg, self.expected)
        
        elif self.kind == GuardKind.SHAPE:
            if not hasattr(arg, 'shape'):
                return False
            return arg.shape == self.expected
        
        elif self.kind == GuardKind.DTYPE:
            if not hasattr(arg, 'dtype'):
                return False
            return str(arg.dtype) == self.expected
        
        elif self.kind == GuardKind.VALUE_RANGE:
            low, high = self.expected
            return low <= arg <= high
        
        return True  # Unknown guard type passes


class GlobalVersionGuard:
    """Guard for global variable versions.
    
    Tracks version counters for global variables that the
    compiled function depends on.
    """
    # Class-level shared state
    _versions: Dict[str, int] = {}
    _lock = threading.Lock()
    
    def __init__(self, global_name: str, module_name: str, expected_version: int):
        self.global_name = global_name
        self.module_name = module_name
        self.expected_version = expected_version
    
    @classmethod
    def get_version(cls, module_name: str, global_name: str) -> int:
        """Get the current version of a global variable."""
        key = f"{module_name}.{global_name}"
        return cls._versions.get(key, 0)
    
    @classmethod
    def increment_version(cls, module_name: str, global_name: str) -> int:
        """Increment and return the new version."""
        key = f"{module_name}.{global_name}"
        with cls._lock:
            version = cls._versions.get(key, 0) + 1
            cls._versions[key] = version
            return version
    
    def check(self) -> bool:
        """Check if the global version matches."""
        current = self.get_version(self.module_name, self.global_name)
        return current == self.expected_version


@dataclass
class GuardSet:
    """Collection of guards for a compiled function.
    
    All guards must pass for the native fast path to be taken.
    """
    arg_guards: List[Guard] = field(default_factory=list)
    global_guards: List[GlobalVersionGuard] = field(default_factory=list)
    function_name: str = ""
    
    def add_type_guard(
        self,
        arg_index: int,
        expected_type: type,
        description: str = "",
    ) -> None:
        """Add a type guard for an argument."""
        self.arg_guards.append(Guard(
            kind=GuardKind.TYPE,
            arg_index=arg_index,
            expected=expected_type,
            description=description or f"arg{arg_index} is {expected_type.__name__}",
        ))
    
    def add_shape_guard(
        self,
        arg_index: int,
        expected_shape: Tuple[int, ...],
        description: str = "",
    ) -> None:
        """Add a shape guard for an array argument."""
        self.arg_guards.append(Guard(
            kind=GuardKind.SHAPE,
            arg_index=arg_index,
            expected=expected_shape,
            description=description or f"arg{arg_index}.shape == {expected_shape}",
        ))
    
    def add_dtype_guard(
        self,
        arg_index: int,
        expected_dtype: str,
        description: str = "",
    ) -> None:
        """Add a dtype guard for an array argument."""
        self.arg_guards.append(Guard(
            kind=GuardKind.DTYPE,
            arg_index=arg_index,
            expected=expected_dtype,
            description=description or f"arg{arg_index}.dtype == {expected_dtype}",
        ))
    
    def add_global_guard(
        self,
        module_name: str,
        global_name: str,
    ) -> None:
        """Add a global version guard."""
        version = GlobalVersionGuard.get_version(module_name, global_name)
        self.global_guards.append(GlobalVersionGuard(
            global_name=global_name,
            module_name=module_name,
            expected_version=version,
        ))
    
    def check_all(self, args: Tuple[Any, ...]) -> bool:
        """Check all guards.
        
        Returns True if all guards pass, False otherwise.
        Logs guard failures at debug level.
        """
        # Check argument guards
        for guard in self.arg_guards:
            if guard.arg_index >= len(args):
                log_guard_failure(
                    self.function_name,
                    "missing_arg",
                    f"arg{guard.arg_index}",
                    "not provided",
                )
                return False
            
            arg = args[guard.arg_index]
            if not guard.check(arg):
                log_guard_failure(
                    self.function_name,
                    guard.description,
                    guard.expected,
                    getattr(arg, 'shape', type(arg)),
                )
                return False
        
        # Check global guards
        for guard in self.global_guards:
            if not guard.check():
                log_guard_failure(
                    self.function_name,
                    f"global_{guard.global_name}",
                    guard.expected_version,
                    GlobalVersionGuard.get_version(guard.module_name, guard.global_name),
                )
                return False
        
        return True


class GuardBuilder:
    """Builds guard sets from inferred types.
    
    Creates the minimal set of guards needed to ensure
    the compiled code's assumptions are met.
    """
    
    def __init__(
        self,
        check_shapes: bool = True,
        check_dtypes: bool = True,
    ):
        """Initialize the builder.
        
        Args:
            check_shapes: Generate shape guards for arrays.
            check_dtypes: Generate dtype guards for arrays.
        """
        self.check_shapes = check_shapes
        self.check_dtypes = check_dtypes
    
    def build_guards(
        self,
        arg_types: List[InferredType],
        function_name: str = "",
    ) -> GuardSet:
        """Build a guard set from inferred types.
        
        Args:
            arg_types: List of inferred argument types.
            function_name: Name of the function for logging.
            
        Returns:
            GuardSet with appropriate guards.
        """
        guards = GuardSet(function_name=function_name)
        
        for i, itype in enumerate(arg_types):
            # Add type guard
            python_type = self._get_python_type(itype)
            if python_type:
                guards.add_type_guard(i, python_type)
            
            # Add array-specific guards
            if itype.kind == IRTypeKind.NDARRAY:
                if self.check_shapes and itype.shape:
                    guards.add_shape_guard(i, itype.shape)
                
                if self.check_dtypes and itype.dtype:
                    guards.add_dtype_guard(i, itype.dtype)
        
        return guards
    
    def _get_python_type(self, itype: InferredType) -> Optional[type]:
        """Get the Python type to check for."""
        type_map = {
            IRTypeKind.BOOL: bool,
            IRTypeKind.INT32: int,
            IRTypeKind.INT64: int,
            IRTypeKind.FLOAT32: float,
            IRTypeKind.FLOAT64: float,
        }
        
        if itype.kind in type_map:
            return type_map[itype.kind]
        
        if itype.kind == IRTypeKind.NDARRAY:
            # Try to import numpy for the type check
            try:
                import numpy as np
                return np.ndarray
            except ImportError:
                return None
        
        return None
