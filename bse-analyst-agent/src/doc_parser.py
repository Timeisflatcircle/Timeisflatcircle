import fitz  # PyMuPDF
import re
from typing import Dict

class FinancialDocParser:
    def __init__(self, pdf_path: str):
        self.doc = fitz.open(pdf_path)

    def find_section_pages(self, keyword_pattern: str, max_pages: int = 25) -> str:
        """Locates pages matching specific financial section headings and returns combined text."""
        matched_pages = []
        pattern = re.compile(keyword_pattern, re.IGNORECASE)

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text("text")
            
            # Match heading near the top half of the page
            first_500_chars = text[:500]
            if pattern.search(first_500_chars):
                matched_pages.append(page_num)
                if len(matched_pages) >= max_pages:
                    break
        
        extracted_content = ""
        for p in matched_pages:
            extracted_content += f"\n--- [PAGE {p+1}] ---\n" + self.doc[p].get_text("text")
        return extracted_content

    def extract_critical_sections(self) -> Dict[str, str]:
        """Extracts the high-conviction sections for forensic and fundamental screening."""
        print("[*] Parsing Auditor's Report...")
        auditor_report = self.find_section_pages(r"(independent auditor['’]s report)", max_pages=8)
        
        print("[*] Parsing Consolidated Financial Statements...")
        statements = self.find_section_pages(r"consolidated statement of (profit and loss|financial position|balance sheet)", max_pages=10)
        
        print("[*] Parsing Notes on Contingent Liabilities & RPTs...")
        notes = self.find_section_pages(r"(contingent liabilities|related party transactions)", max_pages=6)

        return {
            "auditor_report": auditor_report,
            "financial_statements": statements,
            "notes": notes
        }