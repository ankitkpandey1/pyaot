"""Tests for template compiler."""

import unittest
from pyaot.web.io.template import TemplateAnalyzer, TemplateCompiler, TemplateNodeType, compile_template


class TestTemplateAnalyzer(unittest.TestCase):
    def test_parse_text_only(self):
        analyzer = TemplateAnalyzer()
        nodes = analyzer.analyze("Hello World")
        
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].type, TemplateNodeType.TEXT)
        self.assertEqual(nodes[0].content, "Hello World")
    
    def test_parse_variable(self):
        analyzer = TemplateAnalyzer()
        nodes = analyzer.analyze("Hello {{ name }}!")
        
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0].type, TemplateNodeType.TEXT)
        self.assertEqual(nodes[1].type, TemplateNodeType.VARIABLE)
        self.assertEqual(nodes[1].content, "name")
        self.assertEqual(nodes[2].type, TemplateNodeType.TEXT)
    
    def test_parse_attribute(self):
        analyzer = TemplateAnalyzer()
        nodes = analyzer.analyze("{{ user.name }}")
        
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].type, TemplateNodeType.ATTRIBUTE)
        self.assertEqual(nodes[0].content, "user.name")
    
    def test_parse_if_block(self):
        analyzer = TemplateAnalyzer()
        nodes = analyzer.analyze("{% if active %}Yes{% endif %}")
        
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0].type, TemplateNodeType.IF)
        self.assertEqual(nodes[0].condition, "active")
        self.assertEqual(nodes[1].type, TemplateNodeType.TEXT)
        self.assertEqual(nodes[2].type, TemplateNodeType.ENDIF)
    
    def test_parse_for_loop(self):
        analyzer = TemplateAnalyzer()
        nodes = analyzer.analyze("{% for item in items %}{{ item }}{% endfor %}")
        
        self.assertEqual(nodes[0].type, TemplateNodeType.FOR)
        self.assertEqual(nodes[0].variable, "item")
        self.assertEqual(nodes[0].iterable, "items")


class TestTemplateCompiler(unittest.TestCase):
    def test_compile_simple_template(self):
        template = "Hello {{ name }}!"
        ir_module = compile_template(template, "greet")
        
        self.assertIsNotNone(ir_module)
        self.assertEqual(ir_module.name, "template_greet")
        self.assertIn("greet", ir_module.functions)
    
    def test_compile_multiple_variables(self):
        template = "{{ greeting }}, {{ name }}!"
        ir_module = compile_template(template)
        
        func = ir_module.get_function("render")
        self.assertIsNotNone(func)
        # Should have entry block with instructions
        self.assertTrue(len(func.blocks) > 0)


if __name__ == "__main__":
    unittest.main()
