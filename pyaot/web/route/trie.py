"""Route learning and trie-based classification."""

from __future__ import annotations

import re
from typing import Dict, Any, Optional

class RouteTrieNode:
    def __init__(self):
        self.children: Dict[str, RouteTrieNode] = {}
        self.template: Optional[str] = None
        self.count: int = 0

class RouteLearner:
    """Learns route templates from observed paths."""
    
    def __init__(self):
        self.root = RouteTrieNode()
        self._cache: Dict[str, str] = {}
        
    def extract_and_learn(self, path: str) -> str:
        """Extract template and learn pattern."""
        # Fast path check
        if path in self._cache:
            return self._cache[path]
            
        parts = path.strip("/").split("/")
        template_parts = []
        node = self.root
        
        for part in parts:
            if part.isdigit():
                seg = "<id>"
            elif len(part) == 36 and part.count("-") == 4:
                seg = "<uuid>"
            elif len(part) > 20 and part.isalnum():
                seg = "<token>"
            else:
                seg = part
            
            template_parts.append(seg)
            if seg not in node.children:
                node.children[seg] = RouteTrieNode()
            node = node.children[seg]
            
        template = "/" + "/".join(template_parts)
        node.template = template
        node.count += 1
        
        # Simple bounded cache
        if len(self._cache) < 1000:
            self._cache[path] = template
            
        return template
