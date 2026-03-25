"""
LaTeX Processor Service
Handles preservation, validation, and processing of LaTeX content in questions
"""
import re
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger('extraction')


@dataclass
class LaTeXExpression:
    """Represents a LaTeX expression found in text"""
    original: str
    cleaned: str
    display_mode: bool  # True for $$...$$ or \[...\], False for $...$
    start_pos: int
    end_pos: int
    is_valid: bool
    error: Optional[str] = None


class LaTeXProcessor:
    """
    Process and preserve LaTeX content in question text
    
    Features:
    - Extract LaTeX expressions from text
    - Validate LaTeX syntax
    - Preserve LaTeX during text processing
    - Convert between LaTeX formats
    - Clean and normalize LaTeX
    """
    
    # LaTeX delimiters (ordered by priority)
    DELIMITERS = [
        (r'\$\$', r'\$\$', True),      # Display math $$...$$
        (r'\\\[', r'\\\]', True),       # Display math \[...\]
        (r'\\begin\{equation\}', r'\\end\{equation\}', True),
        (r'\\begin\{align\}', r'\\end\{align\}', True),
        (r'\\begin\{gather\}', r'\\end\{gather\}', True),
        (r'\$', r'\$', False),          # Inline math $...$
        (r'\\\(', r'\\\)', False),      # Inline math \(...\)
    ]
    
    # Common LaTeX commands that should be preserved
    LATEX_COMMANDS = [
        # Greek letters
        r'\\alpha', r'\\beta', r'\\gamma', r'\\delta', r'\\epsilon', r'\\zeta',
        r'\\eta', r'\\theta', r'\\iota', r'\\kappa', r'\\lambda', r'\\mu',
        r'\\nu', r'\\xi', r'\\pi', r'\\rho', r'\\sigma', r'\\tau',
        r'\\upsilon', r'\\phi', r'\\chi', r'\\psi', r'\\omega',
        r'\\Gamma', r'\\Delta', r'\\Theta', r'\\Lambda', r'\\Xi',
        r'\\Pi', r'\\Sigma', r'\\Phi', r'\\Psi', r'\\Omega',
        # Math operators
        r'\\frac', r'\\sqrt', r'\\sum', r'\\prod', r'\\int', r'\\oint',
        r'\\lim', r'\\log', r'\\ln', r'\\sin', r'\\cos', r'\\tan',
        r'\\sec', r'\\csc', r'\\cot', r'\\arcsin', r'\\arccos', r'\\arctan',
        r'\\sinh', r'\\cosh', r'\\tanh',
        # Relations
        r'\\leq', r'\\geq', r'\\neq', r'\\approx', r'\\equiv', r'\\sim',
        r'\\propto', r'\\perp', r'\\parallel',
        # Arrows
        r'\\rightarrow', r'\\leftarrow', r'\\Rightarrow', r'\\Leftarrow',
        r'\\leftrightarrow', r'\\Leftrightarrow', r'\\to', r'\\gets',
        # Misc
        r'\\infty', r'\\partial', r'\\nabla', r'\\forall', r'\\exists',
        r'\\in', r'\\notin', r'\\subset', r'\\supset', r'\\cup', r'\\cap',
        r'\\times', r'\\cdot', r'\\div', r'\\pm', r'\\mp',
        r'\\vec', r'\\hat', r'\\bar', r'\\dot', r'\\ddot',
        r'\\overline', r'\\underline', r'\\overbrace', r'\\underbrace',
        # Formatting
        r'\\text', r'\\mathrm', r'\\mathbf', r'\\mathit', r'\\mathsf',
        r'\\left', r'\\right', r'\\big', r'\\Big', r'\\bigg', r'\\Bigg',
        # Environments
        r'\\begin', r'\\end',
    ]
    
    # Patterns that indicate LaTeX content
    LATEX_INDICATORS = [
        r'\\frac\{[^}]+\}\{[^}]+\}',           # Fractions
        r'\\sqrt(?:\[[^\]]+\])?\{[^}]+\}',     # Square roots
        r'\\int(?:_\{[^}]+\})?(?:\^\{[^}]+\})?', # Integrals
        r'\\sum(?:_\{[^}]+\})?(?:\^\{[^}]+\})?', # Summations
        r'\\lim_\{[^}]+\}',                     # Limits
        r'[a-zA-Z]\^[\d\{\}]+',                 # Superscripts
        r'[a-zA-Z]_[\d\{\}]+',                  # Subscripts
        r'\\[a-zA-Z]+\{',                       # Any command with braces
    ]
    
    def __init__(self):
        """Initialize LaTeX processor"""
        self._placeholder_counter = 0
        self._placeholder_map = {}
    
    def extract_latex(self, text: str) -> List[LaTeXExpression]:
        """
        Extract all LaTeX expressions from text
        
        Args:
            text: Input text containing LaTeX
            
        Returns:
            List of LaTeXExpression objects
        """
        expressions = []
        
        # Find display math first ($$...$$ and \[...\])
        display_patterns = [
            (r'\$\$([^\$]+)\$\$', True),
            (r'\\\[([^\]]+)\\\]', True),
            (r'\\begin\{equation\}(.*?)\\end\{equation\}', True),
            (r'\\begin\{align\}(.*?)\\end\{align\}', True),
        ]
        
        for pattern, is_display in display_patterns:
            for match in re.finditer(pattern, text, re.DOTALL):
                expr = LaTeXExpression(
                    original=match.group(0),
                    cleaned=match.group(1).strip(),
                    display_mode=is_display,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    is_valid=self._validate_latex(match.group(1))
                )
                expressions.append(expr)
        
        # Find inline math ($...$)
        # Be careful not to match already found display math
        inline_pattern = r'(?<!\$)\$(?!\$)([^\$]+)\$(?!\$)'
        for match in re.finditer(inline_pattern, text):
            # Check if this overlaps with display math
            overlaps = any(
                e.start_pos <= match.start() < e.end_pos or
                e.start_pos < match.end() <= e.end_pos
                for e in expressions
            )
            if not overlaps:
                expr = LaTeXExpression(
                    original=match.group(0),
                    cleaned=match.group(1).strip(),
                    display_mode=False,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    is_valid=self._validate_latex(match.group(1))
                )
                expressions.append(expr)
        
        # Sort by position
        expressions.sort(key=lambda e: e.start_pos)
        
        return expressions
    
    def _validate_latex(self, latex: str) -> bool:
        """
        Basic validation of LaTeX syntax
        
        Args:
            latex: LaTeX content (without delimiters)
            
        Returns:
            True if syntax appears valid
        """
        if not latex or not latex.strip():
            return False
        
        # Check balanced braces
        brace_count = 0
        for char in latex:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
            if brace_count < 0:
                return False
        
        if brace_count != 0:
            return False
        
        # Check balanced brackets
        bracket_count = 0
        for char in latex:
            if char == '[':
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
            if bracket_count < 0:
                return False
        
        if bracket_count != 0:
            return False
        
        # Check for common invalid patterns
        invalid_patterns = [
            r'\\\\[a-z]',  # Double backslash before command (except \\)
            r'\{\}',       # Empty braces (usually invalid)
        ]
        
        for pattern in invalid_patterns:
            if re.search(pattern, latex):
                return False
        
        return True
    
    def preserve_latex(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Replace LaTeX expressions with placeholders to protect during processing
        
        Args:
            text: Input text with LaTeX
            
        Returns:
            Tuple of (text with placeholders, mapping of placeholder to original)
        """
        self._placeholder_counter = 0
        self._placeholder_map = {}
        
        expressions = self.extract_latex(text)
        
        # Replace from end to start to preserve positions
        result = text
        for expr in reversed(expressions):
            placeholder = f"__LATEX_{self._placeholder_counter}__"
            self._placeholder_map[placeholder] = expr.original
            result = result[:expr.start_pos] + placeholder + result[expr.end_pos:]
            self._placeholder_counter += 1
        
        return result, self._placeholder_map
    
    def restore_latex(self, text: str, placeholder_map: Dict[str, str] = None) -> str:
        """
        Restore LaTeX expressions from placeholders
        
        Args:
            text: Text with placeholders
            placeholder_map: Mapping of placeholders to original LaTeX
            
        Returns:
            Text with LaTeX restored
        """
        if placeholder_map is None:
            placeholder_map = self._placeholder_map
        
        result = text
        for placeholder, original in placeholder_map.items():
            result = result.replace(placeholder, original)
        
        return result
    
    def has_latex(self, text: str) -> bool:
        """
        Check if text contains LaTeX content
        
        Args:
            text: Input text
            
        Returns:
            True if LaTeX is detected
        """
        # Quick check for delimiters
        if '$' in text or '\\[' in text or '\\(' in text:
            return True
        
        # Check for LaTeX commands
        for pattern in self.LATEX_INDICATORS:
            if re.search(pattern, text):
                return True
        
        return False
    
    def clean_latex(self, latex: str) -> str:
        """
        Clean and normalize LaTeX expression
        
        Args:
            latex: Raw LaTeX string
            
        Returns:
            Cleaned LaTeX
        """
        if not latex:
            return latex
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', latex.strip())
        
        # Normalize spacing around operators
        cleaned = re.sub(r'\s*([+\-=<>])\s*', r' \1 ', cleaned)
        
        # Remove space after commands
        cleaned = re.sub(r'(\\[a-zA-Z]+)\s+\{', r'\1{', cleaned)
        
        # Normalize fractions
        cleaned = re.sub(r'\\frac\s*\{', r'\\frac{', cleaned)
        
        return cleaned.strip()
    
    def convert_to_display(self, latex: str) -> str:
        """Convert inline math to display math"""
        if latex.startswith('$') and not latex.startswith('$$'):
            return '$$' + latex[1:-1] + '$$'
        return latex
    
    def convert_to_inline(self, latex: str) -> str:
        """Convert display math to inline math"""
        if latex.startswith('$$'):
            return '$' + latex[2:-2] + '$'
        if latex.startswith('\\['):
            return '$' + latex[2:-2] + '$'
        return latex
    
    def extract_latex_content(self, text: str) -> List[str]:
        """
        Extract just the LaTeX content (without delimiters)
        
        Args:
            text: Input text
            
        Returns:
            List of LaTeX content strings
        """
        expressions = self.extract_latex(text)
        return [e.cleaned for e in expressions]
    
    def get_latex_stats(self, text: str) -> Dict:
        """
        Get statistics about LaTeX content in text
        
        Args:
            text: Input text
            
        Returns:
            Dictionary with LaTeX statistics
        """
        expressions = self.extract_latex(text)
        
        return {
            'total_count': len(expressions),
            'inline_count': sum(1 for e in expressions if not e.display_mode),
            'display_count': sum(1 for e in expressions if e.display_mode),
            'valid_count': sum(1 for e in expressions if e.is_valid),
            'invalid_count': sum(1 for e in expressions if not e.is_valid),
            'expressions': [e.original for e in expressions[:10]],  # Sample
        }
    
    def fix_common_issues(self, text: str) -> str:
        """
        Fix common LaTeX issues in text
        
        Args:
            text: Input text with potentially broken LaTeX
            
        Returns:
            Text with fixed LaTeX
        """
        result = text
        
        # Fix unescaped special characters
        # (but not inside existing LaTeX)
        protected, mapping = self.preserve_latex(result)
        
        # Fix common issues in non-LaTeX text
        # ... (add specific fixes as needed)
        
        result = self.restore_latex(protected, mapping)
        
        # Fix broken delimiters
        # Single $ that should be $$
        result = re.sub(r'(?<!\$)\$\s*\\begin', r'$$\\begin', result)
        result = re.sub(r'\\end\{[^}]+\}\s*\$(?!\$)', r'\\end{\1}$$', result)
        
        # Fix missing closing delimiters
        # Count $ and add if odd
        dollar_count = result.count('$') - 2 * result.count('$$')
        if dollar_count % 2 == 1:
            # Find last unclosed $ and close it
            last_dollar = result.rfind('$')
            if last_dollar > 0 and result[last_dollar-1:last_dollar+1] != '$$':
                # Check if it's an opening $
                before = result[:last_dollar]
                if before.count('$') % 2 == 0:
                    result = result + '$'
        
        return result
    
    def render_preview(self, latex: str) -> str:
        """
        Generate a simple text preview of LaTeX (for non-rendered display)
        
        Args:
            latex: LaTeX expression
            
        Returns:
            Simplified text representation
        """
        preview = latex
        
        # Remove delimiters
        preview = re.sub(r'^\$+|\$+$', '', preview)
        preview = re.sub(r'^\\\[|\\\]$', '', preview)
        
        # Simplify common expressions
        replacements = [
            (r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1)/(\2)'),
            (r'\\sqrt\{([^}]+)\}', r'√(\1)'),
            (r'\\sum', '∑'),
            (r'\\int', '∫'),
            (r'\\infty', '∞'),
            (r'\\alpha', 'α'),
            (r'\\beta', 'β'),
            (r'\\gamma', 'γ'),
            (r'\\delta', 'δ'),
            (r'\\pi', 'π'),
            (r'\\theta', 'θ'),
            (r'\\lambda', 'λ'),
            (r'\\mu', 'μ'),
            (r'\\sigma', 'σ'),
            (r'\\omega', 'ω'),
            (r'\\times', '×'),
            (r'\\cdot', '·'),
            (r'\\pm', '±'),
            (r'\\leq', '≤'),
            (r'\\geq', '≥'),
            (r'\\neq', '≠'),
            (r'\\approx', '≈'),
            (r'\\rightarrow', '→'),
            (r'\\leftarrow', '←'),
            (r'\^(\d)', r'^(\1)'),
            (r'_(\d)', r'_(\1)'),
            (r'\{', ''),
            (r'\}', ''),
        ]
        
        for pattern, replacement in replacements:
            preview = re.sub(pattern, replacement, preview)
        
        return preview.strip()


# Utility functions for easy access
def has_latex(text: str) -> bool:
    """Quick check if text contains LaTeX"""
    processor = LaTeXProcessor()
    return processor.has_latex(text)


def extract_latex(text: str) -> List[str]:
    """Extract LaTeX expressions from text"""
    processor = LaTeXProcessor()
    return processor.extract_latex_content(text)


def preserve_and_restore_latex(text: str, process_func) -> str:
    """
    Preserve LaTeX, apply processing function, then restore
    
    Args:
        text: Input text
        process_func: Function to apply to text (with LaTeX protected)
        
    Returns:
        Processed text with LaTeX restored
    """
    processor = LaTeXProcessor()
    protected, mapping = processor.preserve_latex(text)
    processed = process_func(protected)
    return processor.restore_latex(processed, mapping)
