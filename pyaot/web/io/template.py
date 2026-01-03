"""Template compilation for Jinja2 subset.

Compiles simple Jinja2 templates to native string concatenation,
avoiding interpreter overhead for hot template rendering paths.

Supported syntax:
- {{ variable }} - Variable interpolation
- {% if condition %} ... {% endif %} - Conditionals
- {% for item in items %} ... {% endfor %} - Simple loops
- {{ object.attribute }} - Attribute access
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from pyaot.compiler.ir import (
    IRModule,
    IRFunction,
    IRBasicBlock,
    IRInstruction,
    IRType,
    IRValue,
    Opcode,
)


class TemplateNodeType(Enum):
    """Types of template AST nodes."""
    TEXT = auto()           # Literal text
    VARIABLE = auto()       # {{ var }}
    ATTRIBUTE = auto()      # {{ obj.attr }}
    IF = auto()             # {% if %}
    ELSE = auto()           # {% else %}
    ENDIF = auto()          # {% endif %}
    FOR = auto()            # {% for %}
    ENDFOR = auto()         # {% endfor %}


@dataclass
class TemplateNode:
    """A node in the template AST."""
    type: TemplateNodeType
    content: str = ""
    children: List["TemplateNode"] = field(default_factory=list)
    # For loops/conditionals
    variable: str = ""
    iterable: str = ""
    condition: str = ""


class TemplateAnalyzer:
    """Parses Jinja2 templates into an AST for compilation.
    
    This analyzer handles a subset of Jinja2 syntax suitable for
    high-performance web template rendering.
    """
    
    # Regex patterns for template syntax
    VAR_PATTERN = re.compile(r'\{\{\s*(.+?)\s*\}\}')
    TAG_PATTERN = re.compile(r'\{%\s*(.+?)\s*%\}')
    
    def __init__(self) -> None:
        self._template: str = ""
        self._pos: int = 0
    
    def analyze(self, template: str) -> List[TemplateNode]:
        """Parse template string into AST nodes.
        
        Args:
            template: Jinja2 template string.
            
        Returns:
            List of TemplateNode representing the template structure.
        """
        nodes: List[TemplateNode] = []
        self._template = template
        self._pos = 0
        
        while self._pos < len(template):
            # Check for variable interpolation {{ }}
            var_match = self.VAR_PATTERN.match(template, self._pos)
            if var_match:
                expr = var_match.group(1).strip()
                if '.' in expr:
                    # Attribute access
                    nodes.append(TemplateNode(
                        type=TemplateNodeType.ATTRIBUTE,
                        content=expr,
                    ))
                else:
                    # Simple variable
                    nodes.append(TemplateNode(
                        type=TemplateNodeType.VARIABLE,
                        content=expr,
                    ))
                self._pos = var_match.end()
                continue
            
            # Check for template tags {% %}
            tag_match = self.TAG_PATTERN.match(template, self._pos)
            if tag_match:
                tag_content = tag_match.group(1).strip()
                node = self._parse_tag(tag_content)
                if node:
                    nodes.append(node)
                self._pos = tag_match.end()
                continue
            
            # Literal text - collect until next {{ or {%
            text_end = len(template)
            next_var = template.find('{{', self._pos)
            next_tag = template.find('{%', self._pos)
            
            if next_var != -1:
                text_end = min(text_end, next_var)
            if next_tag != -1:
                text_end = min(text_end, next_tag)
            
            if text_end > self._pos:
                nodes.append(TemplateNode(
                    type=TemplateNodeType.TEXT,
                    content=template[self._pos:text_end],
                ))
                self._pos = text_end
            else:
                # Should not reach here, but safety
                self._pos += 1
        
        return nodes
    
    def _parse_tag(self, tag_content: str) -> Optional[TemplateNode]:
        """Parse a template tag like if/for/endif/endfor."""
        parts = tag_content.split(None, 1)
        if not parts:
            return None
        
        keyword = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if keyword == "if":
            return TemplateNode(
                type=TemplateNodeType.IF,
                condition=args.strip(),
            )
        elif keyword == "else":
            return TemplateNode(type=TemplateNodeType.ELSE)
        elif keyword == "endif":
            return TemplateNode(type=TemplateNodeType.ENDIF)
        elif keyword == "for":
            # Parse "item in items"
            match = re.match(r'(\w+)\s+in\s+(.+)', args)
            if match:
                return TemplateNode(
                    type=TemplateNodeType.FOR,
                    variable=match.group(1),
                    iterable=match.group(2).strip(),
                )
        elif keyword == "endfor":
            return TemplateNode(type=TemplateNodeType.ENDFOR)
        
        return None


class TemplateCompiler:
    """Compiles template AST to PyAOT IR for native execution.
    
    Generates efficient string concatenation code that can be
    further compiled to native machine code.
    """
    
    def __init__(self) -> None:
        self._module: Optional[IRModule] = None
        self._function: Optional[IRFunction] = None
        self._block: Optional[IRBasicBlock] = None
        self._string_parts: List[IRValue] = []
    
    def compile(self, nodes: List[TemplateNode], template_name: str = "render") -> IRModule:
        """Compile template nodes to PyAOT IR.
        
        Args:
            nodes: Parsed template AST nodes.
            template_name: Name for the generated function.
            
        Returns:
            IRModule containing the compiled template function.
        """
        self._module = IRModule(name=f"template_{template_name}")
        
        # Function signature: render(context: ptr) -> ptr (string result)
        func = IRFunction(
            name=template_name,
            return_type=IRType.ptr(),
            arg_names=["context"],
            arg_types=[IRType.ptr()],
        )
        self._module.add_function(func)
        self._function = func
        
        # Create entry block
        self._block = func.new_block("entry")
        self._string_parts = []
        
        # Compile each node
        for node in nodes:
            self._compile_node(node)
        
        # Generate string concatenation and return
        result = self._generate_concat()
        self._emit(Opcode.RET, operands=[result])
        
        return self._module
    
    def _compile_node(self, node: TemplateNode) -> None:
        """Compile a single template node."""
        if node.type == TemplateNodeType.TEXT:
            # Literal text - store as constant
            text_val = self._function.new_value(IRType.ptr(), "text")
            self._emit(Opcode.CONST_INT, result=text_val, operands=[id(node.content)])
            self._string_parts.append(text_val)
            
        elif node.type == TemplateNodeType.VARIABLE:
            # Variable lookup from context
            var_val = self._function.new_value(IRType.ptr(), f"var_{node.content}")
            self._emit(Opcode.GETATTR, result=var_val, operands=[
                self._function.get_local("context"),
                node.content,
            ])
            self._string_parts.append(var_val)
            
        elif node.type == TemplateNodeType.ATTRIBUTE:
            # Attribute access (obj.attr)
            parts = node.content.split('.', 1)
            obj_val = self._function.new_value(IRType.ptr(), f"obj_{parts[0]}")
            self._emit(Opcode.GETATTR, result=obj_val, operands=[
                self._function.get_local("context"),
                parts[0],
            ])
            if len(parts) > 1:
                attr_val = self._function.new_value(IRType.ptr(), f"attr_{parts[1]}")
                self._emit(Opcode.GETATTR, result=attr_val, operands=[obj_val, parts[1]])
                self._string_parts.append(attr_val)
            else:
                self._string_parts.append(obj_val)
                
        # IF/FOR handled via control flow (simplified for now)
        # Full implementation would generate branching IR
    
    def _generate_concat(self) -> IRValue:
        """Generate string concatenation for all parts."""
        if not self._string_parts:
            # Empty result
            empty = self._function.new_value(IRType.ptr(), "empty")
            self._emit(Opcode.CONST_INT, result=empty, operands=[0])
            return empty
        
        if len(self._string_parts) == 1:
            return self._string_parts[0]
        
        # Chain concatenations
        result = self._string_parts[0]
        for i, part in enumerate(self._string_parts[1:], 1):
            new_result = self._function.new_value(IRType.ptr(), f"concat_{i}")
            self._emit(Opcode.CALL, result=new_result, operands=["str_concat", result, part])
            result = new_result
        
        return result
    
    def _emit(
        self,
        opcode: Opcode,
        result: Optional[IRValue] = None,
        operands: List[Any] = None,
    ) -> None:
        """Emit an instruction to the current block."""
        if operands is None:
            operands = []
        inst = IRInstruction(opcode=opcode, result=result, operands=operands)
        self._block.append(inst)


def compile_template(template: str, name: str = "render") -> IRModule:
    """Convenience function to compile a template string.
    
    Args:
        template: Jinja2 template string.
        name: Name for the generated function.
        
    Returns:
        Compiled IRModule.
    """
    analyzer = TemplateAnalyzer()
    nodes = analyzer.analyze(template)
    
    compiler = TemplateCompiler()
    return compiler.compile(nodes, name)
