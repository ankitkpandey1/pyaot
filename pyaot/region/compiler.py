"""Region compiler.

Translates Python functions (regions) into native code (C) and compiles them.
"""

import ast
import inspect
import os
import subprocess
import tempfile
import sys
from typing import Callable, Optional, List, Any
import pyaot_native
from pyaot.region.tracer import Guard, TraceData

class CompilerError(Exception):
    pass

class RegionCompiler:
    """Compiles Python regions to native shared objects."""
    
    def compile(self, func: Callable, region_id: str, traces: Optional[List[TraceData]] = None) -> str:
        """Compile a region function to a native shared library.
        
        Args:
            func: The function to compile.
            region_id: Unique identifier for the region.
            traces: Optional execution traces containing guards.
            
        Returns:
            Path to the compiled shared object (.so) file.
        """
        # 1. Get AST
        try:
            source = inspect.getsource(func)
            source = self._dedent(source)
            tree = ast.parse(source)
            func_node = tree.body[0]
            if not isinstance(func_node, ast.FunctionDef):
                raise CompilerError("Target must be a function")
        except Exception as e:
            raise CompilerError(f"Failed to parse source: {e}")
            
        # 2. Generate C Code
        c_code = self._generate_c(func_node, region_id, traces)
        
        # 3. Compile to .so
        so_path = self._compile_c_to_so(c_code, region_id)
        
        return so_path

    def _dedent(self, source: str) -> str:
        """Remove common leading whitespace."""
        import textwrap
        return textwrap.dedent(source)

    def _generate_c(self, node: ast.FunctionDef, region_id: str, traces: Optional[List[TraceData]] = None) -> str:
        """Generate C code for the function."""
        c = [
            "#include <Python.h>",
            "",
            "// Global/Closure variables would be handled here (simulated via args for V1)",
            "// Entry point",
            "PyObject* pyaot_region_entry(PyObject* self, PyObject* args, PyObject* kwargs) {",
        ]
        
        # Parse arguments
        args = node.args.args
        arg_names = [a.arg for a in args]
        
        c.append(f"    // Parse arguments: {', '.join(arg_names)}")
        c.append(f'    if (PyTuple_GET_SIZE(args) < {len(arg_names)}) {{')
        c.append('        PyErr_SetString(PyExc_TypeError, "Argument count mismatch");')
        c.append('        return NULL;')
        c.append('    }')
        for i, name in enumerate(arg_names):
             c.append(f'    PyObject* {name} = PyTuple_GET_ITEM(args, {i});')
             
        # Guard Generation Logic...
        
        # Guards
        if traces and len(traces) > 0:
            c.append("    // Check Guards")
            trace = traces[-1]
            for guard in trace.guards:
                if guard.kind == 'type':
                    target_var = guard.target
                    expected_type = guard.expected
                    check = None
                    if expected_type is int:
                         check = f"PyLong_Check({target_var})"
                    elif expected_type is float:
                         check = f"PyFloat_Check({target_var})"
                    elif expected_type is str:
                         check = f"PyUnicode_Check({target_var})"
                    
                    if check:
                        c.append(f"    if (!{check}) {{")
                        c.append(f"        PyErr_SetString(PyExc_TypeError, \"Guard failure: {target_var} type mismatch\");")
                        c.append("        return NULL;")
                        c.append("    }")
        
        # Body Generation - Stack-based Code Gen approach (Recursive)
        # We'll use a simple generator that returns C strings for expressions
        # and appends statements to `c`
        
        self.var_counter = 0
        def new_tmp():
            self.var_counter += 1
            name = f"tmp_{self.var_counter}"
            c.append(f"    PyObject* {name} = NULL;")
            return name

        def emit_expr(expr_node) -> str:
            if isinstance(expr_node, ast.Name):
                return expr_node.id
                
            elif isinstance(expr_node, ast.Attribute):
                obj = emit_expr(expr_node.value)
                attr = expr_node.attr
                tmp = new_tmp()
                c.append(f"    {tmp} = PyObject_GetAttrString({obj}, \"{attr}\");")
                c.append(f"    if (!{tmp}) return NULL;")
                return tmp
                
            elif isinstance(expr_node, ast.Subscript):
                obj = emit_expr(expr_node.value)
                idx = emit_expr(expr_node.slice)
                tmp = new_tmp()
                c.append(f"    {tmp} = PyObject_GetItem({obj}, {idx});")
                c.append(f"    if (!{tmp}) return NULL;")
                return tmp

            elif isinstance(expr_node, ast.UnaryOp):
                operand = emit_expr(expr_node.operand)
                tmp = new_tmp()
                if isinstance(expr_node.op, ast.Not):
                     c.append(f"    int is_true_{tmp} = PyObject_IsTrue({operand});")
                     c.append(f"    if (is_true_{tmp} == -1) return NULL;")
                     c.append(f"    {tmp} = (is_true_{tmp} == 0) ? Py_True : Py_False;")
                     c.append(f"    Py_INCREF({tmp});") 
                return tmp

            elif isinstance(expr_node, ast.BinOp):
                left = emit_expr(expr_node.left)
                right = emit_expr(expr_node.right)
                tmp = new_tmp()
                if isinstance(expr_node.op, ast.Add):
                    c.append(f"    {tmp} = PyNumber_Add({left}, {right});")
                elif isinstance(expr_node.op, ast.Mult):
                    c.append(f"    {tmp} = PyNumber_Multiply({left}, {right});")
                else:
                    c.append(f"    PyErr_SetString(PyExc_NotImplementedError, \"Unsupported binary op\");")
                    c.append("    return NULL;")
                c.append(f"    if (!{tmp}) return NULL;")
                return tmp
                
            elif isinstance(expr_node, ast.Dict):
                tmp = new_tmp()
                c.append(f"    {tmp} = PyDict_New();")
                c.append(f"    if (!{tmp}) return NULL;")
                for k, v in zip(expr_node.keys, expr_node.values):
                     if k:
                         key = emit_expr(k)
                         val = emit_expr(v)
                         c.append(f"    if (PyDict_SetItem({tmp}, {key}, {val}) < 0) return NULL;")
                return tmp
                
            elif isinstance(expr_node, ast.Constant):
                tmp = new_tmp()
                if isinstance(expr_node.value, str):
                    c.append(f"    {tmp} = PyUnicode_FromString(\"{expr_node.value}\");")
                elif isinstance(expr_node.value, int):
                    c.append(f"    {tmp} = PyLong_FromLong({expr_node.value});")
                elif expr_node.value is None:
                     c.append(f"    {tmp} = Py_None; Py_INCREF({tmp});")
                return tmp
                
            raise CompilerError(f"Unsupported expr: {type(expr_node)}")

        def emit_stmt(stmt_node):
            if isinstance(stmt_node, ast.Return):
                if stmt_node.value:
                    res = emit_expr(stmt_node.value)
                    c.append(f"    Py_INCREF({res});")
                    c.append(f"    return {res};")
                else:
                    c.append("    Py_RETURN_NONE;")
                    
            elif isinstance(stmt_node, ast.Assign):
                 if len(stmt_node.targets) == 1 and isinstance(stmt_node.targets[0], ast.Name):
                     target_name = stmt_node.targets[0].id
                     val = emit_expr(stmt_node.value)
                     if target_name not in arg_names:
                         c.append(f"    PyObject* {target_name} = {val};")
                     else:
                         c.append(f"    {target_name} = {val};")
                     
            elif isinstance(stmt_node, ast.If):
                test = emit_expr(stmt_node.test)
                cond_var = f"cond_{self.var_counter}"
                self.var_counter += 1
                c.append(f"    int {cond_var} = PyObject_IsTrue({test});")
                c.append(f"    if ({cond_var} < 0) return NULL;")
                c.append(f"    if ({cond_var}) {{")
                for s in stmt_node.body:
                    emit_stmt(s)
                c.append("    } else {")
                for s in stmt_node.orelse:
                    emit_stmt(s)
                c.append("    }")
            
            else:
                 pass

        for stmt in node.body:
             emit_stmt(stmt)
             
        c.append("    Py_RETURN_NONE;")
        c.append("}")
        return "\n".join(c)

    def _compile_c_to_so(self, c_code: str, region_id: str) -> str:
        """Compile C source to shared object using gcc/clang."""
        build_dir = os.path.join(tempfile.gettempdir(), "pyaot_builds")
        os.makedirs(build_dir, exist_ok=True)
        
        src_path = os.path.join(build_dir, f"{region_id}.c")
        so_path = os.path.join(build_dir, f"{region_id}.so")
        
        with open(src_path, "w") as f:
            f.write(c_code)
            
        import sysconfig
        include_path = sysconfig.get_path("include")
        
        compiler = os.environ.get("CC", "gcc")
        
        cmd = [
            compiler,
            "-shared",
            "-fPIC",
            "-O3",
            f"-I{include_path}",
            "-o", so_path,
            src_path
        ]
        
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            raise CompilerError(f"Compilation failed: {e}")
            
        return so_path

# Global compiler instance
_compiler = RegionCompiler()

def compile_function(func: Callable, region_id: str, traces: Optional[List[TraceData]] = None) -> int:
    """Compile a function and load it into the native runner."""
    so_path = _compiler.compile(func, region_id, traces)
    handle = pyaot_native.load_region(region_id, so_path)
    return handle
