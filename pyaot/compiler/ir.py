"""
Intermediate Representation (IR) for PyAOT.

A typed IR that serves as the target for AST lowering and
source for LLVM code generation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum, auto


class IRTypeKind(Enum):
    """Kinds of IR types."""
    VOID = auto()
    BOOL = auto()
    INT32 = auto()
    INT64 = auto()
    FLOAT32 = auto()
    FLOAT64 = auto()
    PTR = auto()      # Generic pointer
    ARRAY = auto()    # Array type (includes shape info)
    PYOBJ = auto()    # Python object pointer (PyObject*)


@dataclass
class IRType:
    """Type in the IR."""
    kind: IRTypeKind
    element_type: Optional["IRType"] = None  # For arrays
    shape: Optional[tuple] = None  # For arrays with known shape
    
    @classmethod
    def void(cls) -> "IRType":
        return cls(kind=IRTypeKind.VOID)
    
    @classmethod
    def i32(cls) -> "IRType":
        return cls(kind=IRTypeKind.INT32)
    
    @classmethod
    def i64(cls) -> "IRType":
        return cls(kind=IRTypeKind.INT64)
    
    @classmethod
    def f32(cls) -> "IRType":
        return cls(kind=IRTypeKind.FLOAT32)
    
    @classmethod
    def f64(cls) -> "IRType":
        return cls(kind=IRTypeKind.FLOAT64)
    
    @classmethod
    def ptr(cls) -> "IRType":
        return cls(kind=IRTypeKind.PTR)
    
    @classmethod
    def array(cls, element_type: "IRType", shape: Optional[tuple] = None) -> "IRType":
        return cls(kind=IRTypeKind.ARRAY, element_type=element_type, shape=shape)
    
    @classmethod
    def pyobj(cls) -> "IRType":
        """Python object pointer (PyObject*)."""
        return cls(kind=IRTypeKind.PYOBJ)
    
    def to_llvm_str(self) -> str:
        """Get LLVM type string."""
        mapping = {
            IRTypeKind.VOID: "void",
            IRTypeKind.BOOL: "i1",
            IRTypeKind.INT32: "i32",
            IRTypeKind.INT64: "i64",
            IRTypeKind.FLOAT32: "float",
            IRTypeKind.FLOAT64: "double",
            IRTypeKind.PTR: "ptr",
            IRTypeKind.ARRAY: "ptr",  # Arrays passed as pointers
        }
        return mapping.get(self.kind, "ptr")
    
    def __str__(self) -> str:
        if self.kind == IRTypeKind.ARRAY:
            elem = str(self.element_type) if self.element_type else "?"
            if self.shape:
                return f"[{self.shape}, {elem}]"
            return f"[*, {elem}]"
        return self.kind.name.lower()


class Opcode(Enum):
    """IR instruction opcodes."""
    # Constants
    CONST_INT = auto()
    CONST_FLOAT = auto()
    CONST_BOOL = auto()
    
    # Memory
    LOAD = auto()
    STORE = auto()
    ALLOCA = auto()
    GEP = auto()  # GetElementPtr
    
    # Arithmetic
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    NEG = auto()
    
    # Floating point
    FADD = auto()
    FSUB = auto()
    FMUL = auto()
    FDIV = auto()
    FNEG = auto()
    
    # Comparison
    EQ = auto()
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    
    # Control flow
    BR = auto()        # Unconditional branch
    BR_COND = auto()   # Conditional branch
    RET = auto()       # Return
    
    # Function calls
    CALL = auto()
    
    # Type conversion
    SITOFP = auto()    # Signed int to float
    FPTOSI = auto()    # Float to signed int
    ZEXT = auto()      # Zero extend
    SEXT = auto()      # Sign extend
    TRUNC = auto()     # Truncate
    
    # Array operations
    ARRAY_LOAD = auto()   # Load from array
    ARRAY_STORE = auto()  # Store to array
    ARRAY_LEN = auto()    # Get array length
    
    # Object operations (Phase 3)
    GETATTR = auto()      # Get attribute from object
    SETATTR = auto()      # Set attribute on object
    GET_TYPE = auto()     # Get type of object (Py_TYPE)
    
    # Guard operations (Phase 3)
    GUARD_TYPE = auto()   # Guard: type(obj) is expected_type
    GUARD_FAIL = auto()   # Branch to fallback on guard failure
    
    # Python interop
    BOX = auto()          # Box native value to PyObject
    UNBOX = auto()        # Unbox PyObject to native value


@dataclass
class IRValue:
    """A value in the IR (result of an instruction or argument)."""
    name: str
    type: IRType
    is_arg: bool = False


@dataclass
class IRInstruction:
    """An instruction in the IR."""
    opcode: Opcode
    result: Optional[IRValue] = None
    operands: List[Union[IRValue, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        ops = ", ".join(str(o) for o in self.operands)
        if self.result:
            return f"{self.result.name} = {self.opcode.name} {ops}"
        return f"{self.opcode.name} {ops}"


@dataclass
class IRBasicBlock:
    """A basic block in the IR (sequence of instructions with single entry/exit)."""
    name: str
    instructions: List[IRInstruction] = field(default_factory=list)
    predecessors: List["IRBasicBlock"] = field(default_factory=list)
    successors: List["IRBasicBlock"] = field(default_factory=list)
    
    def append(self, inst: IRInstruction) -> None:
        """Append an instruction to this block."""
        self.instructions.append(inst)
    
    def is_terminated(self) -> bool:
        """Check if block ends with a terminator."""
        if not self.instructions:
            return False
        last = self.instructions[-1]
        return last.opcode in (Opcode.RET, Opcode.BR, Opcode.BR_COND)
    
    def __str__(self) -> str:
        lines = [f"{self.name}:"]
        for inst in self.instructions:
            lines.append(f"  {inst}")
        return "\n".join(lines)


@dataclass
class IRFunction:
    """A function in the IR."""
    name: str
    return_type: IRType
    arg_names: List[str] = field(default_factory=list)
    arg_types: List[IRType] = field(default_factory=list)
    blocks: List[IRBasicBlock] = field(default_factory=list)
    
    # Internal state
    _value_counter: int = field(default=0, repr=False)
    _block_counter: int = field(default=0, repr=False)
    _locals: Dict[str, IRValue] = field(default_factory=dict, repr=False)
    
    def __post_init__(self):
        # Create argument values
        for name, typ in zip(self.arg_names, self.arg_types):
            self._locals[name] = IRValue(name=name, type=typ, is_arg=True)
    
    def new_value(self, typ: IRType, prefix: str = "v") -> IRValue:
        """Create a new value with a unique name."""
        self._value_counter += 1
        name = f"{prefix}{self._value_counter}"
        return IRValue(name=name, type=typ)
    
    def new_block(self, prefix: str = "bb") -> IRBasicBlock:
        """Create a new basic block."""
        self._block_counter += 1
        name = f"{prefix}{self._block_counter}"
        block = IRBasicBlock(name=name)
        self.blocks.append(block)
        return block
    
    def get_entry_block(self) -> Optional[IRBasicBlock]:
        """Get the entry block."""
        return self.blocks[0] if self.blocks else None
    
    def get_local(self, name: str) -> Optional[IRValue]:
        """Get a local value by name."""
        return self._locals.get(name)
    
    def set_local(self, name: str, value: IRValue) -> None:
        """Set a local value."""
        self._locals[name] = value
    
    def __str__(self) -> str:
        args = ", ".join(f"{n}: {t}" for n, t in zip(self.arg_names, self.arg_types))
        lines = [f"fn {self.name}({args}) -> {self.return_type}:"]
        for block in self.blocks:
            lines.append(str(block))
        return "\n".join(lines)


@dataclass
class IRModule:
    """A module containing multiple functions."""
    name: str
    functions: Dict[str, IRFunction] = field(default_factory=dict)
    
    def add_function(self, func: IRFunction) -> None:
        """Add a function to the module."""
        self.functions[func.name] = func
    
    def get_function(self, name: str) -> Optional[IRFunction]:
        """Get a function by name."""
        return self.functions.get(name)
    
    def __str__(self) -> str:
        lines = [f"module {self.name}:", ""]
        for func in self.functions.values():
            lines.append(str(func))
            lines.append("")
        return "\n".join(lines)
