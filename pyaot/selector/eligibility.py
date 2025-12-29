"""
Eligibility checking for AOT compilation.

Analyzes function AST to determine if it adheres to the
compilable Python subset.

Allowed:
- Pure or mostly-pure functions
- Numeric types (int, float, bool)
- Typed containers (lists, tuples with stable shapes)
- NumPy arrays / buffers
- Deterministic loops
- Function calls to other compiled or whitelisted functions

Disallowed:
- eval, exec
- Dynamic attribute injection
- Monkey patching
- Reflection (getattr with dynamic names)
- Arbitrary object mutation
- Dynamic imports
- Exception-driven control flow (except local handling)
"""

import ast
import inspect
import textwrap
from dataclasses import dataclass, field
from typing import Optional, Set, List, Callable
from pathlib import Path

from pyaot.profiler.data import FunctionProfile
from pyaot.exceptions import EligibilityError


# Disallowed function names
DISALLOWED_CALLS = frozenset({
    'eval',
    'exec',
    'compile',
    '__import__',
    'importlib.import_module',
    'globals',
    'locals',
    'vars',
    'dir',
    'delattr',
    'setattr',
})

# Disallowed AST node types
DISALLOWED_NODES = frozenset({
    'Global',      # global statement
    'Nonlocal',    # nonlocal statement (sometimes ok, but risky)
})

# Whitelisted modules for calls
WHITELISTED_MODULES = frozenset({
    'numpy',
    'np',
    'math',
    'operator',
    'functools',
    'itertools',
    'builtins',
})


@dataclass
class EligibilityResult:
    """Result of eligibility checking for a function."""
    eligible: bool
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # AST analysis results
    has_eval_exec: bool = False
    has_dynamic_getattr: bool = False
    has_dynamic_import: bool = False
    has_global_mutation: bool = False
    has_exception_control_flow: bool = False
    uses_reflection: bool = False
    
    def add_reason(self, reason: str) -> None:
        """Add a rejection reason."""
        self.reasons.append(reason)
        self.eligible = False
    
    def add_warning(self, warning: str) -> None:
        """Add a warning (doesn't affect eligibility)."""
        self.warnings.append(warning)
    
    def summary(self) -> str:
        """Get a summary of the result."""
        if self.eligible:
            return "eligible"
        return "; ".join(self.reasons)


class EligibilityChecker:
    """Checks if functions are eligible for AOT compilation.
    
    Performs AST analysis to detect disallowed patterns.
    """
    
    def __init__(
        self,
        whitelist_modules: Optional[Set[str]] = None,
        allow_exception_handling: bool = True,
    ):
        """Initialize the checker.
        
        Args:
            whitelist_modules: Additional modules to whitelist for calls.
            allow_exception_handling: Allow local try/except blocks.
        """
        self.whitelist_modules = set(WHITELISTED_MODULES)
        if whitelist_modules:
            self.whitelist_modules.update(whitelist_modules)
        self.allow_exception_handling = allow_exception_handling
    
    def check_function(
        self,
        func: Callable,
    ) -> EligibilityResult:
        """Check if a function is eligible for compilation.
        
        Args:
            func: The function to check.
            
        Returns:
            EligibilityResult with analysis results.
        """
        result = EligibilityResult(eligible=True)
        
        # Get source code
        try:
            source = inspect.getsource(func)
            # Dedent to handle functions defined inside classes/tests
            source = textwrap.dedent(source)
        except (OSError, TypeError) as e:
            result.add_reason(f"Cannot get source: {e}")
            return result
        
        # Parse AST
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            result.add_reason(f"Syntax error: {e}")
            return result
        
        # Find the function definition
        func_def = self._find_function_def(tree, func.__name__)
        if func_def is None:
            result.add_reason("Could not find function definition in AST")
            return result
        
        # Run all checks
        self._check_disallowed_calls(func_def, result)
        self._check_dynamic_getattr(func_def, result)
        self._check_dynamic_import(func_def, result)
        self._check_global_mutation(func_def, result)
        self._check_exception_control_flow(func_def, result)
        self._check_disallowed_nodes(func_def, result)
        
        return result
    
    def check_from_profile(
        self,
        profile: FunctionProfile,
    ) -> EligibilityResult:
        """Check eligibility from a function profile.
        
        Attempts to load the function from its module and check it.
        
        Args:
            profile: The function profile.
            
        Returns:
            EligibilityResult with analysis results.
        """
        result = EligibilityResult(eligible=True)
        
        # Try to get the source file
        try:
            source_path = Path(profile.filename)
            if not source_path.exists():
                result.add_reason(f"Source file not found: {profile.filename}")
                return result
            
            source = source_path.read_text()
        except Exception as e:
            result.add_reason(f"Cannot read source: {e}")
            return result
        
        # Parse AST
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            result.add_reason(f"Syntax error: {e}")
            return result
        
        # Find the function definition
        func_name = profile.qualname.split('.')[-1]  # Handle methods
        func_def = self._find_function_def(tree, func_name)
        if func_def is None:
            result.add_reason(f"Could not find '{func_name}' in AST")
            return result
        
        # Run all checks
        self._check_disallowed_calls(func_def, result)
        self._check_dynamic_getattr(func_def, result)
        self._check_dynamic_import(func_def, result)
        self._check_global_mutation(func_def, result)
        self._check_exception_control_flow(func_def, result)
        self._check_disallowed_nodes(func_def, result)
        
        return result
    
    def _find_function_def(
        self,
        tree: ast.AST,
        name: str,
    ) -> Optional[ast.FunctionDef]:
        """Find a function definition by name in the AST."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    return node
        return None
    
    def _check_disallowed_calls(
        self,
        node: ast.AST,
        result: EligibilityResult,
    ) -> None:
        """Check for calls to disallowed functions."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                
                # Direct call: eval(...)
                if isinstance(func, ast.Name):
                    if func.id in DISALLOWED_CALLS:
                        result.add_reason(f"Disallowed call: {func.id}()")
                        result.has_eval_exec = func.id in ('eval', 'exec')
                
                # Attribute call: os.system(...)
                elif isinstance(func, ast.Attribute):
                    if func.attr in DISALLOWED_CALLS:
                        result.add_reason(f"Disallowed call: {func.attr}()")
    
    def _check_dynamic_getattr(
        self,
        node: ast.AST,
        result: EligibilityResult,
    ) -> None:
        """Check for dynamic getattr usage."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                
                if isinstance(func, ast.Name) and func.id == 'getattr':
                    # Check if attribute name is dynamic (not a constant)
                    if len(child.args) >= 2:
                        attr_arg = child.args[1]
                        if not isinstance(attr_arg, ast.Constant):
                            result.add_reason("Dynamic getattr() with non-constant attribute")
                            result.has_dynamic_getattr = True
                            result.uses_reflection = True
    
    def _check_dynamic_import(
        self,
        node: ast.AST,
        result: EligibilityResult,
    ) -> None:
        """Check for dynamic imports."""
        for child in ast.walk(node):
            # __import__("module")
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name) and func.id == '__import__':
                    result.add_reason("Dynamic import: __import__()")
                    result.has_dynamic_import = True
                
                # importlib.import_module(...)
                if isinstance(func, ast.Attribute) and func.attr == 'import_module':
                    result.add_reason("Dynamic import: import_module()")
                    result.has_dynamic_import = True
            
            # import statement inside function
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                result.add_warning("Import inside function (may affect performance)")
    
    def _check_global_mutation(
        self,
        node: ast.AST,
        result: EligibilityResult,
    ) -> None:
        """Check for global state mutation."""
        for child in ast.walk(node):
            if isinstance(child, ast.Global):
                # global statement - might mutate
                result.add_warning("Uses 'global' statement - may mutate global state")
                result.has_global_mutation = True
            
            if isinstance(child, ast.Nonlocal):
                result.add_warning("Uses 'nonlocal' statement")
    
    def _check_exception_control_flow(
        self,
        node: ast.AST,
        result: EligibilityResult,
    ) -> None:
        """Check for exception-driven control flow."""
        if self.allow_exception_handling:
            return  # Local handling allowed
        
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                result.add_reason("Exception-driven control flow")
                result.has_exception_control_flow = True
                break
    
    def _check_disallowed_nodes(
        self,
        node: ast.AST,
        result: EligibilityResult,
    ) -> None:
        """Check for disallowed AST node types."""
        for child in ast.walk(node):
            node_type = type(child).__name__
            if node_type in DISALLOWED_NODES:
                result.add_reason(f"Disallowed syntax: {node_type}")
