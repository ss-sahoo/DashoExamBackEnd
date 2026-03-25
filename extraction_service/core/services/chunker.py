import re
from typing import List, Tuple
from core.state import Chunk

class Chunker:
    def chunk(self, text: str, expected_count: int = 50, smart_chunk: bool = True) -> List[Chunk]:
        """Split text into manageable chunks"""
        chunks = []
        chunk_size = 20  # questions per chunk
        
        # Simple paragraph based splitting for MVP
        # Ideally, use the complex regex logic from gemini_extraction_v2.py
        
        # Regex to find question numbers
        # Matches: "1. ", "1) ", "Q1. ", "Question 1: ", etc.
        q_pattern = r'(?m)^\s*(?:Q\.?\s*|Question\s*)?(\d+)(?:[\.\)]|\s+)'
        matches = list(re.finditer(q_pattern, text))
        
        if not matches:
            # Fallback size based
            part_size = len(text) // max(1, (expected_count // chunk_size))
            for i in range(0, len(text), part_size):
                chunks.append(Chunk(
                    text=text[i:i+part_size],
                    start_q=(i // part_size) * chunk_size + 1,
                    end_q=(i // part_size + 1) * chunk_size
                ))
            return chunks

        # Group by detected question numbers
        current_start_idx = 0
        current_q_start = 1
        
        # split every N questions
        target_count = chunk_size
        count = 0
        
        last_match_end = 0
        
        for i, match in enumerate(matches):
            count += 1
            if count >= target_count:
                # split here
                end_pos = match.start()
                chunk_text = text[current_start_idx:end_pos]
                q_num = int(match.group(1))
                
                chunks.append(Chunk(
                    text=chunk_text,
                    start_q=current_q_start,
                    end_q=q_num
                ))
                
                current_start_idx = end_pos
                current_q_start = q_num
                count = 0
                last_match_end = end_pos
                
        # Last chunk
        if current_start_idx < len(text):
            chunks.append(Chunk(
                text=text[current_start_idx:],
                start_q=current_q_start,
                end_q=expected_count
            ))
            
        return chunks

chunker = Chunker()
