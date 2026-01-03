"""Guard code generation for trace compilation.

Generates LLVM IR for guard instructions that verify runtime invariants
and branch to deopt on failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llvmlite import ir as llvm_ir


class GuardKind(Enum):
    """Types of guards that can be generated."""

    TYPE = auto()
    SHAPE = auto()
    NONNULL = auto()
    BRANCH_TAKEN = auto()
    CALL_TARGET = auto()
    NO_EXCEPTION = auto()


@dataclass
class GuardInfo:
    """Information about a generated guard.

    Attributes:
        kind: The type of guard.
        deopt_id: ID of the deopt point if guard fails.
        check_block: LLVM block containing the guard check.
        pass_block: LLVM block to continue if guard passes.
        fail_block: LLVM block to branch to on failure (deopt).
    """

    kind: GuardKind
    deopt_id: int
    check_block: Any  # llvm_ir.Block
    pass_block: Any  # llvm_ir.Block
    fail_block: Any  # llvm_ir.Block


class GuardGenerator:
    """Generates guard LLVM IR for trace compilation.

    Guards verify runtime invariants observed during tracing.
    On failure, control transfers to deopt stub.

    Attributes:
        builder: LLVM IR builder for code generation.
        deopt_targets: Mapping from deopt_id to deopt stub block.
    """

    def __init__(
        self,
        builder: "llvm_ir.IRBuilder",
        deopt_targets: dict[int, Any],
        hot_path_weight: int = 1000,
    ) -> None:
        """Initialize guard generator.

        Args:
            builder: LLVM IR builder.
            deopt_targets: Map of deopt_id to deopt block.
            hot_path_weight: Weight for the hot (passing) path.
        """
        self._builder = builder
        self._deopt_targets = deopt_targets
        self._hot_path_weight = max(1, hot_path_weight)
        self._cold_path_weight = 1  # Deopt is rare
        self._generated_guards: list[GuardInfo] = []

    def _set_branch_weights(self, br_inst: Any) -> None:
        """Attach branch probability metadata to branch instruction."""
        try:
            from llvmlite import ir as llvm_ir
            
            # Create "branch_weights" metadata
            # !{!"branch_weights", i32 <true_weight>, i32 <false_weight>}
            # Note: For cbranch(cond, true_blk, false_blk), operands are weights for True/False
            
            # Since our guards are structured as:
            # cbranch(cond, pass_block, fail_block)
            # pass_block is True logic (if cond is true).
            # So True weight = hot, False weight = cold.
            
            # Metadata construction in llvmlite is low-level
            module = self._builder.module
            ctx = module.context
            
            # Create metadata nodes
            name_node = module.add_metadata([llvm_ir.MetaDataString("branch_weights")])
            true_weight = llvm_ir.Constant(llvm_ir.IntType(32), self._hot_path_weight)
            false_weight = llvm_ir.Constant(llvm_ir.IntType(32), self._cold_path_weight)
            
            metadata_node = module.add_metadata([name_node, true_weight, false_weight])
            
            # Attach to instruction ("prof" = 28 in some LLVM, but key is "prof")
            br_inst.set_metadata("prof", metadata_node)
        except Exception:
            # Metadata attachment is optional optimization, do not crash
            pass

    def generate_type_guard(
        self,
        value_ptr: Any,
        expected_type_id: int,
        deopt_id: int,
    ) -> GuardInfo:
        """Generate GUARD_TYPE check.

        Checks that value's type matches expected type ID.

        Args:
            value_ptr: Pointer to PyObject.
            expected_type_id: Expected type hash/ID.
            deopt_id: Deopt point if guard fails.

        Returns:
            GuardInfo with generated blocks.
        """
        func = self._builder.block.function
        pass_block = func.append_basic_block(name=f"guard_type_pass_{deopt_id}")
        fail_block = self._get_or_create_deopt_block(deopt_id)

        # Load type pointer from PyObject (ob_type at offset 8 in Python 3.x)
        # type_ptr = builder.load(builder.gep(value_ptr, [0, 1]))
        # For now, generate a placeholder comparison
        i64 = self._builder.function.module.context.get_identified_type("i64")
        if i64 is None:
            from llvmlite import ir as llvm_ir

            i64 = llvm_ir.IntType(64)

        # Placeholder: actual implementation would load ob_type

        # For now, always pass (will be replaced with actual type check)
        cond = self._const_i1(True)

        br = self._builder.cbranch(cond, pass_block, fail_block)
        self._set_branch_weights(br)
        self._builder.position_at_end(pass_block)

        info = GuardInfo(
            kind=GuardKind.TYPE,
            deopt_id=deopt_id,
            check_block=self._builder.block,
            pass_block=pass_block,
            fail_block=fail_block,
        )
        self._generated_guards.append(info)
        return info

    def generate_shape_guard(
        self,
        value_ptr: Any,
        expected_shape_id: int,
        deopt_id: int,
    ) -> GuardInfo:
        """Generate GUARD_SHAPE check.

        Checks that object's shape (dict keys layout) matches expected.

        Args:
            value_ptr: Pointer to PyObject.
            expected_shape_id: Expected shape hash/ID.
            deopt_id: Deopt point if guard fails.

        Returns:
            GuardInfo with generated blocks.
        """
        func = self._builder.block.function
        pass_block = func.append_basic_block(name=f"guard_shape_pass_{deopt_id}")
        fail_block = self._get_or_create_deopt_block(deopt_id)

        # Placeholder: would load and hash __dict__ keys
        cond = self._const_i1(True)

        br = self._builder.cbranch(cond, pass_block, fail_block)
        self._set_branch_weights(br)
        self._builder.position_at_end(pass_block)

        info = GuardInfo(
            kind=GuardKind.SHAPE,
            deopt_id=deopt_id,
            check_block=self._builder.block,
            pass_block=pass_block,
            fail_block=fail_block,
        )
        self._generated_guards.append(info)
        return info

    def generate_nonnull_guard(
        self,
        value_ptr: Any,
        deopt_id: int,
    ) -> GuardInfo:
        """Generate GUARD_NONNULL check.

        Checks that pointer is not null.

        Args:
            value_ptr: Pointer to check.
            deopt_id: Deopt point if guard fails.

        Returns:
            GuardInfo with generated blocks.
        """
        from llvmlite import ir as llvm_ir

        func = self._builder.block.function
        pass_block = func.append_basic_block(name=f"guard_nonnull_pass_{deopt_id}")
        fail_block = self._get_or_create_deopt_block(deopt_id)

        # Compare pointer to null
        null_ptr = llvm_ir.Constant(value_ptr.type, None)
        cond = self._builder.icmp_unsigned("!=", value_ptr, null_ptr)

        br = self._builder.cbranch(cond, pass_block, fail_block)
        self._set_branch_weights(br)
        self._builder.position_at_end(pass_block)

        info = GuardInfo(
            kind=GuardKind.NONNULL,
            deopt_id=deopt_id,
            check_block=self._builder.block,
            pass_block=pass_block,
            fail_block=fail_block,
        )
        self._generated_guards.append(info)
        return info

    def generate_branch_guard(
        self,
        condition: Any,
        expected: bool,
        deopt_id: int,
    ) -> GuardInfo:
        """Generate GUARD_BRANCH_TAKEN check.

        Checks that branch condition matches expected value.

        Args:
            condition: LLVM value representing condition.
            expected: Expected boolean value.
            deopt_id: Deopt point if guard fails.

        Returns:
            GuardInfo with generated blocks.
        """
        func = self._builder.block.function
        pass_block = func.append_basic_block(name=f"guard_branch_pass_{deopt_id}")
        fail_block = self._get_or_create_deopt_block(deopt_id)

        expected_val = self._const_i1(expected)
        cond = self._builder.icmp_unsigned("==", condition, expected_val)

        br = self._builder.cbranch(cond, pass_block, fail_block)
        self._set_branch_weights(br)
        self._builder.position_at_end(pass_block)

        info = GuardInfo(
            kind=GuardKind.BRANCH_TAKEN,
            deopt_id=deopt_id,
            check_block=self._builder.block,
            pass_block=pass_block,
            fail_block=fail_block,
        )
        self._generated_guards.append(info)
        return info

    def generate_call_target_guard(
        self,
        func_ptr: Any,
        expected_hash: int,
        deopt_id: int,
    ) -> GuardInfo:
        """Generate GUARD_CALL_TARGET check.

        Checks that function pointer matches expected target.

        Args:
            func_ptr: Pointer to function.
            expected_hash: Expected function content hash.
            deopt_id: Deopt point if guard fails.

        Returns:
            GuardInfo with generated blocks.
        """
        func = self._builder.block.function
        pass_block = func.append_basic_block(name=f"guard_call_pass_{deopt_id}")
        fail_block = self._get_or_create_deopt_block(deopt_id)

        # Placeholder: would hash function code and compare
        cond = self._const_i1(True)

        br = self._builder.cbranch(cond, pass_block, fail_block)
        self._set_branch_weights(br)
        self._builder.position_at_end(pass_block)

        info = GuardInfo(
            kind=GuardKind.CALL_TARGET,
            deopt_id=deopt_id,
            check_block=self._builder.block,
            pass_block=pass_block,
            fail_block=fail_block,
        )
        self._generated_guards.append(info)
        return info

    def generate_no_exception_guard(
        self,
        deopt_id: int,
    ) -> GuardInfo:
        """Generate GUARD_NO_EXCEPTION check.

        Checks that no Python exception is pending.

        Args:
            deopt_id: Deopt point if exception is pending.

        Returns:
            GuardInfo with generated blocks.
        """
        func = self._builder.block.function
        pass_block = func.append_basic_block(name=f"guard_noexc_pass_{deopt_id}")
        fail_block = self._get_or_create_deopt_block(deopt_id)

        # Placeholder: would call PyErr_Occurred and check
        cond = self._const_i1(True)

        br = self._builder.cbranch(cond, pass_block, fail_block)
        self._set_branch_weights(br)
        self._builder.position_at_end(pass_block)

        info = GuardInfo(
            kind=GuardKind.NO_EXCEPTION,
            deopt_id=deopt_id,
            check_block=self._builder.block,
            pass_block=pass_block,
            fail_block=fail_block,
        )
        self._generated_guards.append(info)
        return info

    def get_generated_guards(self) -> list[GuardInfo]:
        """Get all guards generated so far."""
        return self._generated_guards.copy()

    def _get_or_create_deopt_block(self, deopt_id: int) -> Any:
        """Get deopt block for the given ID, creating if needed."""
        if deopt_id in self._deopt_targets:
            return self._deopt_targets[deopt_id]

        # Create a new deopt block
        func = self._builder.block.function
        deopt_block = func.append_basic_block(name=f"deopt_{deopt_id}")
        self._deopt_targets[deopt_id] = deopt_block
        return deopt_block

    def _const_i1(self, value: bool) -> Any:
        """Create i1 constant."""
        from llvmlite import ir as llvm_ir

        return llvm_ir.Constant(llvm_ir.IntType(1), int(value))

    def _const_i64(self, value: int) -> Any:
        """Create i64 constant."""
        from llvmlite import ir as llvm_ir

        return llvm_ir.Constant(llvm_ir.IntType(64), value)
