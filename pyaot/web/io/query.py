"""Query Profiler & Analyzer.

Analyzes recorded traces to identify and extract database query patterns.
"""

from dataclasses import dataclass
from typing import List, Any
from pyaot.web.trace.store import TraceRecord
from pyaot.web.trace.ops import TraceOpcode


@dataclass
class QueryInfo:
    """Information about a detected database query."""
    sql: str
    count: int = 1


class QueryAnalyzer:
    """Analyzes trace for DB queries."""
    
    def analyze(self, trace: TraceRecord) -> List[QueryInfo]:
        """Analyze a trace record for SQL queries.
        
        Args:
            trace: The recorded trace to analyze.
            
        Returns:
            List of detected queries.
        """
        queries = []
        reg_defs: dict[int, Any] = {} 
        
        for op in trace.ops:
            # Track register definitions
            if op.opcode == TraceOpcode.LOAD_CONST:
                dst = op.operands[0]
                const_id = op.operands[1]
                # trace.constants is a ConstantTable
                try:
                    value = trace.constants.get(const_id)
                    reg_defs[dst] = value
                except IndexError:
                    pass

            # Inspect calls
            elif op.opcode == TraceOpcode.CALL_DIRECT:
                 # operands: dst, call_id, *arg_regs
                 if len(op.operands) < 2:
                     continue
                     
                 dst = op.operands[0]
                 call_id = op.operands[1]
                 arg_regs = op.operands[2:]
                 
                 try:
                     target_hash, name = trace.call_targets.get(call_id)
                 except IndexError:
                     continue
                 
                 # Heuristic: Check for 'execute'
                 if "execute" in name.lower():
                     # Scan all args for SQL-like strings
                     # (Handles methods where arg[0] is self, or functions where arg[0] is sql)
                     for reg in arg_regs:
                         if reg in reg_defs:
                             val = reg_defs[reg]
                             if isinstance(val, str) and ("SELECT" in val.upper() or "INSERT" in val.upper()):
                                 queries.append(QueryInfo(sql=val))
                                 break
        
        return queries
