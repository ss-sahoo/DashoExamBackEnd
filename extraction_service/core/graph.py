from langgraph.graph import StateGraph, END
from core.state import ExtractionState
from core.nodes import process_document_node, split_sections_node, extract_questions_node, validate_extraction_node

def create_extraction_graph():
    """Build the extraction pipeline graph"""
    graph = StateGraph(ExtractionState)
    
    # Add nodes
    graph.add_node("process_document", process_document_node)
    graph.add_node("split_sections", split_sections_node)
    graph.add_node("extract_questions", extract_questions_node)
    graph.add_node("validate_extraction", validate_extraction_node)
    
    # Set entry point
    graph.set_entry_point("process_document")
    
    # Add simple linear edges for now
    # Ideally should branch on error
    graph.add_edge("process_document", "split_sections")
    graph.add_edge("split_sections", "extract_questions")
    graph.add_edge("extract_questions", "validate_extraction")
    graph.add_edge("validate_extraction", END)
    
    return graph.compile()
