"""Unit tests for TraceOp and related data structures.

Tests Trace IR opcodes, side-effect classification, and metadata tables.
"""

from pyaot.web.trace.ops import (
    TraceOp,
    TraceOpcode,
    SideEffectKind,
    DeoptMetadata,
    ConstantTable,
    ShapeTable,
    CallTargetTable,
)


class TestTraceOpcode:
    """Tests for TraceOpcode enum."""

    def test_guard_opcodes_exist(self) -> None:
        """All guard opcodes are defined."""
        assert TraceOpcode.GUARD_TYPE
        assert TraceOpcode.GUARD_SHAPE
        assert TraceOpcode.GUARD_NONNULL
        assert TraceOpcode.GUARD_BRANCH_TAKEN
        assert TraceOpcode.GUARD_CALL_TARGET
        assert TraceOpcode.GUARD_NO_EXCEPTION

    def test_control_opcodes_exist(self) -> None:
        """All control flow opcodes are defined."""
        assert TraceOpcode.BRANCH
        assert TraceOpcode.RETURN
        assert TraceOpcode.RAISE
        assert TraceOpcode.DEOPT
        assert TraceOpcode.TRACE_END


class TestTraceOp:
    """Tests for TraceOp dataclass."""

    def test_default_values(self) -> None:
        """TraceOp has sensible defaults."""
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        assert op.opcode == TraceOpcode.LOAD_CONST
        assert op.operands == ()
        assert op.metadata_id == 0
        assert op.side_effect == SideEffectKind.PURE
        assert op.deopt_id is None

    def test_is_guard_true_for_guards(self) -> None:
        """is_guard returns True for guard opcodes."""
        op = TraceOp(opcode=TraceOpcode.GUARD_TYPE)

        assert op.is_guard() is True

    def test_is_guard_false_for_non_guards(self) -> None:
        """is_guard returns False for non-guard opcodes."""
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        assert op.is_guard() is False

    def test_is_control_true_for_control_ops(self) -> None:
        """is_control returns True for control flow opcodes."""
        for opcode in [
            TraceOpcode.BRANCH,
            TraceOpcode.RETURN,
            TraceOpcode.RAISE,
            TraceOpcode.DEOPT,
            TraceOpcode.TRACE_END,
        ]:
            op = TraceOp(opcode=opcode)
            assert op.is_control() is True

    def test_ends_trace_for_terminal_ops(self) -> None:
        """ends_trace returns True for terminal opcodes."""
        for opcode in [TraceOpcode.RETURN, TraceOpcode.RAISE, TraceOpcode.TRACE_END]:
            op = TraceOp(opcode=opcode)
            assert op.ends_trace() is True

    def test_ends_trace_for_external_commit(self) -> None:
        """ends_trace returns True for external commit side effect."""
        op = TraceOp(
            opcode=TraceOpcode.CALL_DIRECT,
            side_effect=SideEffectKind.EXTERNAL_COMMIT,
        )

        assert op.ends_trace() is True


class TestSideEffectKind:
    """Tests for SideEffectKind enum."""

    def test_all_kinds_exist(self) -> None:
        """All side effect kinds are defined."""
        assert SideEffectKind.PURE
        assert SideEffectKind.LOCAL_MUTATION
        assert SideEffectKind.EXTERNAL_COMMIT


class TestConstantTable:
    """Tests for ConstantTable deduplication."""

    def test_add_returns_id(self) -> None:
        """add returns constant ID."""
        table = ConstantTable()
        const_id = table.add(42)

        assert const_id == 0

    def test_add_deduplicates(self) -> None:
        """add returns same ID for same constant."""
        table = ConstantTable()
        id1 = table.add(42)
        id2 = table.add(42)

        assert id1 == id2

    def test_get_retrieves_constant(self) -> None:
        """get retrieves constant by ID."""
        table = ConstantTable()
        const_id = table.add("hello")

        assert table.get(const_id) == "hello"

    def test_len_counts_unique(self) -> None:
        """len returns number of unique constants."""
        table = ConstantTable()
        table.add(1)
        table.add(2)
        table.add(1)  # Duplicate

        assert len(table) == 2


class TestShapeTable:
    """Tests for ShapeTable deduplication."""

    def test_add_returns_id(self) -> None:
        """add returns shape ID."""
        table = ShapeTable()
        shape_id = table.add(123, ("x", "y"))

        assert shape_id == 0

    def test_add_deduplicates(self) -> None:
        """add returns same ID for same shape."""
        table = ShapeTable()
        id1 = table.add(123, ("x", "y"))
        id2 = table.add(123, ("x", "y"))

        assert id1 == id2

    def test_different_shapes_get_different_ids(self) -> None:
        """Different shapes get different IDs."""
        table = ShapeTable()
        id1 = table.add(123, ("x",))
        id2 = table.add(123, ("x", "y"))

        assert id1 != id2


class TestCallTargetTable:
    """Tests for CallTargetTable deduplication."""

    def test_add_returns_id(self) -> None:
        """add returns call target ID."""
        table = CallTargetTable()
        target_id = table.add("abc123")

        assert target_id == 0

    def test_add_deduplicates(self) -> None:
        """add returns same ID for same hash."""
        table = CallTargetTable()
        id1 = table.add("abc123")
        id2 = table.add("abc123")

        assert id1 == id2


class TestDeoptMetadata:
    """Tests for DeoptMetadata dataclass."""

    def test_creation(self) -> None:
        """DeoptMetadata can be created with all fields."""
        metadata = DeoptMetadata(
            deopt_id=0,
            bytecode_pc=42,
            live_locals=("x", "y"),
            stack_depth=2,
            reg_to_local={0: "x", 1: "y"},
        )

        assert metadata.deopt_id == 0
        assert metadata.bytecode_pc == 42
        assert metadata.live_locals == ("x", "y")
        assert metadata.stack_depth == 2
        assert metadata.reg_to_local == {0: "x", 1: "y"}
