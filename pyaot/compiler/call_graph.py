"""
Call Graph Analysis for Multi-Function Compilation.

Analyzes function call relationships to enable inter-procedural optimization
and compilation of entire call chains as a single unit.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from collections import defaultdict


@dataclass
class CallSite:
    """Represents a call site within a function."""
    caller: str           # Name of caller function
    callee: str           # Name of callee function
    line_no: int          # Line number in source
    arg_count: int        # Number of arguments
    is_method: bool       # True if method call (x.foo())
    is_dynamic: bool      # True if callee is dynamic (getattr, etc.)
    call_count: int = 0   # Observed call count (from profiling)


@dataclass
class CallGraphNode:
    """Node in the call graph representing a function."""
    name: str
    func: Optional[Callable] = None
    
    # Call relationships
    callees: List[str] = field(default_factory=list)    # Functions this calls
    callers: List[str] = field(default_factory=list)    # Functions that call this
    call_sites: List[CallSite] = field(default_factory=list)
    
    # Analysis metadata
    is_leaf: bool = False
    is_recursive: bool = False
    depth: int = 0           # Max depth from entry
    hotness: float = 0.0     # Hotness score from profiling


@dataclass
class CallChain:
    """
    A chain of function calls suitable for joint compilation.
    
    Example: main -> process -> helper forms a chain of length 3.
    """
    functions: List[CallGraphNode]
    entry: str
    total_calls: int = 0
    estimated_benefit: float = 0.0
    
    @property
    def length(self) -> int:
        return len(self.functions)
    
    def __str__(self) -> str:
        names = " → ".join(n.name for n in self.functions)
        return f"CallChain({names}, calls={self.total_calls})"


@dataclass
class CallGraph:
    """
    Complete call graph for a set of functions.
    
    Enables:
    - Finding hot call chains
    - Identifying inlining opportunities
    - Dead code detection
    """
    nodes: Dict[str, CallGraphNode] = field(default_factory=dict)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (caller, callee)
    entry_points: List[str] = field(default_factory=list)
    
    def add_node(self, name: str, func: Optional[Callable] = None) -> CallGraphNode:
        """Add a node to the graph."""
        if name not in self.nodes:
            self.nodes[name] = CallGraphNode(name=name, func=func)
        elif func is not None:
            self.nodes[name].func = func
        return self.nodes[name]
    
    def add_edge(self, caller: str, callee: str) -> None:
        """Add an edge (call relationship) to the graph."""
        self.edges.append((caller, callee))
        
        caller_node = self.add_node(caller)
        callee_node = self.add_node(callee)
        
        if callee not in caller_node.callees:
            caller_node.callees.append(callee)
        if caller not in callee_node.callers:
            callee_node.callers.append(caller)
    
    def get_callees(self, func_name: str) -> List[str]:
        """Get all functions called by a function."""
        node = self.nodes.get(func_name)
        return node.callees if node else []
    
    def get_callers(self, func_name: str) -> List[str]:
        """Get all functions that call a function."""
        node = self.nodes.get(func_name)
        return node.callers if node else []
    
    def is_leaf(self, func_name: str) -> bool:
        """Check if function is a leaf (calls nothing)."""
        node = self.nodes.get(func_name)
        return len(node.callees) == 0 if node else True
    
    def is_recursive(self, func_name: str) -> bool:
        """Check if function is recursive (directly or indirectly)."""
        visited = set()
        
        def dfs(name: str) -> bool:
            if name in visited:
                return name == func_name
            visited.add(name)
            
            node = self.nodes.get(name)
            if not node:
                return False
            
            for callee in node.callees:
                if callee == func_name or dfs(callee):
                    return True
            return False
        
        return dfs(func_name)
    
    def find_chains(self, max_length: int = 5) -> List[CallChain]:
        """Find all call chains up to max_length."""
        chains = []
        
        for entry in self.entry_points:
            self._find_chains_from(entry, [], chains, max_length)
        
        return chains
    
    def _find_chains_from(
        self,
        current: str,
        path: List[str],
        chains: List[CallChain],
        max_length: int,
    ) -> None:
        """DFS to find chains from current node."""
        if current in path:  # Avoid cycles
            return
        
        path = path + [current]
        
        if len(path) >= 2:
            # Create chain from path
            nodes = [self.nodes[n] for n in path if n in self.nodes]
            if nodes:
                chains.append(CallChain(
                    functions=nodes,
                    entry=path[0],
                ))
        
        if len(path) >= max_length:
            return
        
        node = self.nodes.get(current)
        if node:
            for callee in node.callees:
                self._find_chains_from(callee, path, chains, max_length)


class CallGraphAnalyzer:
    """
    Builds and analyzes call graphs for multi-function compilation.
    
    Usage:
        analyzer = CallGraphAnalyzer()
        graph = analyzer.build_graph(entry_function)
        hot_chains = analyzer.find_hot_chains(graph, min_calls=1000)
    """
    
    def __init__(self):
        self._visitor = _CallVisitor()
    
    def build_graph(self, entry: Callable, follow_calls: bool = True) -> CallGraph:
        """
        Build call graph starting from entry function.
        
        Args:
            entry: Entry point function.
            follow_calls: If True, recursively analyze callees.
            
        Returns:
            CallGraph with all reachable functions.
        """
        graph = CallGraph()
        graph.entry_points.append(entry.__name__)
        
        visited = set()
        to_visit = [entry]
        
        while to_visit:
            func = to_visit.pop()
            name = func.__name__
            
            if name in visited:
                continue
            visited.add(name)
            
            # Add node
            node = graph.add_node(name, func)
            
            # Analyze function for calls
            call_sites = self._analyze_function(func)
            node.call_sites = call_sites
            
            for site in call_sites:
                graph.add_edge(name, site.callee)
                
                # Try to get callee function
                if follow_calls and not site.is_dynamic:
                    callee_func = self._resolve_callee(func, site.callee)
                    if callee_func and callee_func not in to_visit:
                        to_visit.append(callee_func)
        
        # Mark leaf nodes
        for node in graph.nodes.values():
            node.is_leaf = len(node.callees) == 0
            node.is_recursive = graph.is_recursive(node.name)
        
        return graph
    
    def _analyze_function(self, func: Callable) -> List[CallSite]:
        """Analyze function source for call sites."""
        try:
            source = inspect.getsource(func)
            tree = ast.parse(source)
            
            self._visitor.reset(func.__name__)
            self._visitor.visit(tree)
            
            return self._visitor.call_sites
        except (OSError, TypeError):
            # Can't get source
            return []
    
    def _resolve_callee(self, caller: Callable, callee_name: str) -> Optional[Callable]:
        """Try to resolve callee name to actual function."""
        # Check caller's globals
        caller_globals = getattr(caller, '__globals__', {})
        if callee_name in caller_globals:
            obj = caller_globals[callee_name]
            if callable(obj):
                return obj
        
        # Check builtins
        import builtins
        if hasattr(builtins, callee_name):
            return None  # Don't follow builtins
        
        return None
    
    def find_hot_chains(
        self,
        graph: CallGraph,
        min_calls: int = 100,
        max_length: int = 5,
    ) -> List[CallChain]:
        """
        Find hot call chains suitable for joint compilation.
        
        Args:
            graph: Call graph to analyze.
            min_calls: Minimum total calls in chain.
            max_length: Maximum chain length.
            
        Returns:
            List of hot CallChain objects, sorted by benefit.
        """
        chains = graph.find_chains(max_length)
        
        # Filter by hotness
        hot_chains = []
        for chain in chains:
            total_calls = sum(
                sum(s.call_count for s in n.call_sites)
                for n in chain.functions
            )
            
            if total_calls >= min_calls or len(chain.functions) >= 2:
                chain.total_calls = total_calls
                chain.estimated_benefit = self._estimate_benefit(chain)
                hot_chains.append(chain)
        
        # Sort by estimated benefit
        hot_chains.sort(key=lambda c: c.estimated_benefit, reverse=True)
        
        return hot_chains
    
    def _estimate_benefit(self, chain: CallChain) -> float:
        """Estimate optimization benefit of compiling chain together."""
        # Each eliminated call boundary saves ~50-200ns
        call_savings = (len(chain.functions) - 1) * 100  # ns per call
        
        # More calls = more benefit
        total_benefit = call_savings * chain.total_calls
        
        # Adjust for chain length (longer chains have more overhead)
        if len(chain.functions) > 4:
            total_benefit *= 0.8  # Diminishing returns
        
        return total_benefit


class _CallVisitor(ast.NodeVisitor):
    """AST visitor to find call sites."""
    
    def __init__(self):
        self.call_sites: List[CallSite] = []
        self.caller_name: str = ""
    
    def reset(self, caller_name: str) -> None:
        self.call_sites = []
        self.caller_name = caller_name
    
    def visit_Call(self, node: ast.Call) -> Any:
        callee_name = self._get_callee_name(node.func)
        is_dynamic = callee_name is None
        
        site = CallSite(
            caller=self.caller_name,
            callee=callee_name or "<dynamic>",
            line_no=node.lineno,
            arg_count=len(node.args),
            is_method=isinstance(node.func, ast.Attribute),
            is_dynamic=is_dynamic,
        )
        self.call_sites.append(site)
        
        self.generic_visit(node)
        return None
    
    def _get_callee_name(self, node: ast.expr) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None
