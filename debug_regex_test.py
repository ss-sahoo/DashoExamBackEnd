#!/usr/bin/env python3
"""
Debug script to test regex patterns on specific question formats
"""
import re

def test_regex_patterns():
    """Test regex patterns on different question formats"""
    print("🔍 Testing regex patterns...")
    
    # Sample formats from the debug output
    test_cases = [
        # Working format (Q51-Q63)
        "51. The relation R in the set",
        "52. If $\\mathrm{A}=\\{\\mathrm{a}",
        
        # Non-working format (Q64-Q73)
        "64.\n(1) $\\frac{3 \\mathrm{x}^{2}-5}",
        "65.\n(2) $\\frac{1}{f(x)}$",
        "66.\n(A) 0",
        "67. (A) 1",
        "68.\n(A) 5",
        "69.\n(A) $\\left[\\frac{\\pi}{2}",
        "70. (A) 0",
        "72.\n\nLet $f(x)=\\max",
        "## 73.\n\n74. Let $\\mathrm{f}",
    ]
    
    patterns = [
        (r'(?:^|\n)\s*(\d+)[\.\)]\s+[A-Za-z0-9\\\$]', 'original'),
        (r'(?:^|\n)\s*(\d+)[\.\)]\s*[A-Za-z0-9\\\$\(]', 'modified'),
        (r'(?:^|\n)\s*(\d+)[\.\)]', 'simple'),
        (r'(?:^|\n)\s*(\d+)[\.\)]\s*\(?[A-Za-z0-9\\\$]', 'with_optional_paren'),
    ]
    
    for pattern, name in patterns:
        print(f"\n📋 Testing pattern '{name}': {pattern}")
        
        for test_case in test_cases:
            matches = list(re.finditer(pattern, test_case, re.IGNORECASE | re.MULTILINE))
            if matches:
                numbers = [m.group(1) for m in matches]
                print(f"   ✓ '{test_case[:30]}...' -> {numbers}")
            else:
                print(f"   ❌ '{test_case[:30]}...' -> no match")

if __name__ == "__main__":
    test_regex_patterns()