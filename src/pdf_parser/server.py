from fastmcp import FastMCP
import pymupdf # fitz

mcp = FastMCP("PDFParser")

@mcp.tool()
def extract_pdf_sections(pdf_path: str, max_chars: int = 10000) -> dict:
    """
    Extract abstract, introduction, methods, etc. from a PDF.
    Args:
        pdf_path: Path to the PDF file (can be relative to papers directory or absolute)
        max_chars: Maximum characters to extract (default 10000)
    """
    try:
        # Handle both absolute and relative paths
        import os
        if not os.path.isabs(pdf_path):
            # Try papers directory
            papers_dir = os.path.join(os.path.dirname(__file__), "../../papers")
            pdf_path = os.path.join(papers_dir, os.path.basename(pdf_path))
        
        if not os.path.exists(pdf_path):
            return {"error": f"File not found: {pdf_path}"}
            
        doc = pymupdf.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
            if len(text) > max_chars:
                text = text[:max_chars]
                break
        
        # Basic section detection (simplified)
        sections = {}
        text_lower = text.lower()
        
        # Try to find abstract
        if "abstract" in text_lower:
            start = text_lower.find("abstract")
            end = text_lower.find("introduction", start) or text_lower.find("1.", start) or start + 1500
            sections["abstract"] = text[start:end].strip()
        
        sections["full_text_preview"] = text[:max_chars]
        sections["total_pages"] = doc.page_count
        
        return sections
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def extract_figures(pdf_path: str) -> list:
    """Extract figures and charts as images."""
    return ["figure1.png"] # Placeholder

if __name__ == "__main__":
    mcp.run()
