import fitz  # PyMuPDF
import re
from typing import Dict


class FinancialDocParser:
    def __init__(self, pdf_path: str):
        self.doc = fitz.open(pdf_path)

    def find_section_pages(self, keyword_pattern: str, max_pages: int = 25) -> str:
        """Locate pages whose headings match a pattern and return their text."""
        matched_pages = []
        pattern = re.compile(keyword_pattern, re.IGNORECASE)

        for page_num in range(len(self.doc)):
            text = self.doc[page_num].get_text("text")
            if pattern.search(text[:700]):
                matched_pages.append(page_num)
                if len(matched_pages) >= max_pages:
                    break

        extracted_content = ""
        for p in matched_pages:
            extracted_content += f"\n--- [PAGE {p + 1}] ---\n" + self.doc[p].get_text("text")
        return extracted_content

    def extract_critical_sections(self) -> Dict[str, str]:
        """Extract high-conviction audit, statements, cash-flow and notes sections."""
        print("[*] Parsing Auditor's Report...")
        auditor_report = self.find_section_pages(
            r"(independent auditor['’]s report|auditor['’]s report)", max_pages=10
        )

        print("[*] Parsing Consolidated Financial Statements...")
        statements = self.find_section_pages(
            r"(consolidated statement of (profit and loss|financial position|balance sheet)|consolidated balance sheet|consolidated statement of cash flows?|cash flow statement)",
            max_pages=25,
        )

        print("[*] Parsing Notes on Contingent Liabilities & RPTs...")
        notes = self.find_section_pages(
            r"(contingent liabilities|related party transactions|related parties|commitments)", max_pages=10
        )

        return {
            "auditor_report": auditor_report,
            "financial_statements": statements,
            "notes": notes,
        }
