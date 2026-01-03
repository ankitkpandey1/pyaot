"""
Trace storage and versioning.

Persisted trace storage with versioning, checksums, and invalidation.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pyaot.web.trace.ops import (
    TraceOp,
    TraceOpcode,
    ConstantTable,
    ShapeTable,
    CallTargetTable,
)
from pyaot.web.trace.signature import RequestSignature


# Version info
TRACER_VERSION = "1.0.0"


@dataclass
class TraceHeader:
    """Metadata header for a stored trace."""

    trace_id: str
    route_id: str
    signature_hash: str
    code_version: str
    tracer_version: str = TRACER_VERSION
    creation_time: float = field(default_factory=time.time)
    checksum: str = ""

    # Eligibility metrics at time of compilation
    observation_count: int = 0
    client_prefixes: int = 0
    branch_stability: float = 0.0


@dataclass
class TraceRecord:
    """A complete stored trace with header and operations."""

    header: TraceHeader
    ops: Tuple[TraceOp, ...]

    # Metadata tables (deduplicated)
    constants: ConstantTable = field(default_factory=ConstantTable)
    shapes: ShapeTable = field(default_factory=ShapeTable)
    call_targets: CallTargetTable = field(default_factory=CallTargetTable)

    # Deopt metadata
    deopt_points: Dict[int, dict] = field(default_factory=dict)

    def compute_checksum(self) -> str:
        """Compute content checksum for integrity verification."""
        content = {
            "route_id": self.header.route_id,
            "signature_hash": self.header.signature_hash,
            "code_version": self.header.code_version,
            "tracer_version": self.header.tracer_version,
            "ops_count": len(self.ops),
            "ops_hash": hash(self.ops),
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:32]

    @property
    def is_valid(self) -> bool:
        """Check if trace is valid (checksum matches, properly terminated)."""
        if not self.ops:
            return False
        if self.header.checksum and self.header.checksum != self.compute_checksum():
            return False
        # Check proper termination
        last_op = self.ops[-1]
        return last_op.opcode in (
            TraceOpcode.RETURN,
            TraceOpcode.RAISE,
            TraceOpcode.TRACE_END,
        )


class TraceStore:
    """Persistent storage for compiled traces.

    Supports:
    - Versioned storage (code, tracer version)
    - Automatic invalidation on version change
    - Lookup by signature
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize trace store.

        Args:
            storage_path: Path for persistent storage. If None, in-memory only.
        """
        self.storage_path = storage_path
        self._traces: Dict[str, TraceRecord] = {}  # signature_hash -> trace
        self._code_version: str = ""

        if storage_path:
            storage_path.mkdir(parents=True, exist_ok=True)

    def set_code_version(self, version: str) -> None:
        """Set current code version, invalidating old traces."""
        if self._code_version and self._code_version != version:
            # Version changed - invalidate all
            self._traces.clear()
        self._code_version = version

    def store(
        self,
        route_id: str,
        signature: RequestSignature,
        ops: Tuple[TraceOp, ...],
        constants: Optional[ConstantTable] = None,
        shapes: Optional[ShapeTable] = None,
        call_targets: Optional[CallTargetTable] = None,
        observation_count: int = 0,
        client_prefixes: int = 0,
        branch_stability: float = 0.0,
    ) -> TraceRecord:
        """Store a new trace.

        Args:
            route_id: Framework route identifier
            signature: Request signature
            ops: Trace operations
            constants: Constant table
            shapes: Shape table
            call_targets: Call target table
            observation_count: Number of observations
            client_prefixes: Number of client IP prefixes
            branch_stability: Branch stability ratio

        Returns:
            The stored TraceRecord
        """
        signature_hash = hashlib.sha256(str(signature.to_tuple()).encode()).hexdigest()[
            :32
        ]

        trace_id = f"{route_id}_{signature_hash[:8]}_{int(time.time())}"

        header = TraceHeader(
            trace_id=trace_id,
            route_id=route_id,
            signature_hash=signature_hash,
            code_version=self._code_version,
            tracer_version=TRACER_VERSION,
            observation_count=observation_count,
            client_prefixes=client_prefixes,
            branch_stability=branch_stability,
        )

        record = TraceRecord(
            header=header,
            ops=ops,
            constants=constants or ConstantTable(),
            shapes=shapes or ShapeTable(),
            call_targets=call_targets or CallTargetTable(),
        )

        # Compute and set checksum
        record.header.checksum = record.compute_checksum()

        # Store
        self._traces[signature_hash] = record

        return record

    def get(self, signature: RequestSignature) -> Optional[TraceRecord]:
        """Get trace by signature."""
        signature_hash = hashlib.sha256(str(signature.to_tuple()).encode()).hexdigest()[
            :32
        ]

        trace = self._traces.get(signature_hash)

        if trace and trace.header.code_version != self._code_version:
            # Version mismatch - invalidate
            del self._traces[signature_hash]
            return None

        if trace and trace.header.tracer_version != TRACER_VERSION:
            # Tracer version mismatch - invalidate
            del self._traces[signature_hash]
            return None

        return trace

    def invalidate(self, signature: RequestSignature) -> bool:
        """Invalidate (remove) a trace by signature."""
        signature_hash = hashlib.sha256(str(signature.to_tuple()).encode()).hexdigest()[
            :32
        ]

        if signature_hash in self._traces:
            del self._traces[signature_hash]
            return True
        return False

    def invalidate_route(self, route_id: str) -> int:
        """Invalidate all traces for a route (code deploy)."""
        to_remove = [
            h for h, t in self._traces.items() if t.header.route_id == route_id
        ]
        for h in to_remove:
            del self._traces[h]
        return len(to_remove)

    def list_traces(self, route_id: Optional[str] = None) -> List[TraceRecord]:
        """List all traces, optionally filtered by route."""
        traces = list(self._traces.values())
        if route_id:
            traces = [t for t in traces if t.header.route_id == route_id]
        return traces

    def __len__(self) -> int:
        """Return number of stored traces."""
        return len(self._traces)
