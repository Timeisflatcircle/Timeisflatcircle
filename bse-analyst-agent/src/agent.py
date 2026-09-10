"""
src/agent.py
Autonomous financial analysis agent using Google Gemini.
Gemini extracts and interprets evidence; Python owns the numeric calculations.
"""

import os
import json
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from src.financial_tools import CompanyFinancialHistory
from src.prompts import (
    FORENSIC_AUDITOR_SYSTEM,
    FINANCIAL_EXTRACTION_SYSTEM,
    INVESTMENT_COMMITTEE_SYSTEM,
)


class ForensicAuditOutput(BaseModel):
    audit_opinion_type: str = Field(description="Unmodified/Clean, Qualified, Adverse, or Disclaimer")
    key_audit_matters: List[str] = Field(description="Material KAMs and accounting judgement areas")
    contingent_liability_risk: str = Field(description="Low, Medium, or High with reasoning")
    related_party_risk: str = Field(description="Low, Medium, or High with reasoning")
    forensic_red_flags: List[str] = Field(description="Specific accounting, audit, or governance red flags")


class InvestmentMemo(BaseModel):
    verdict: str = Field(description="INVESTIBLE, WATCHLIST, or AVOID")
    conviction_score: int = Field(description="1-10 confidence in the conclusion")
    executive_summary: str = Field(description="Clear investment thesis and business-quality interpretation")
    financial_strengths: List[str] = Field(description="Key financial and competitive strengths")
    critical_risks: List[str] = Field(description="Structural risks and thesis-breakers")
    governance_clearance: bool = Field(description="True only when governance evidence is clean enough to pass")


class AnalysisOrchestrator:
    def __init__(self, model_name: str | None = None, temperature: float = 0.0):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not detected. Set it in .env.")

        selected_model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.llm = ChatGoogleGenerativeAI(
            model=selected_model,
            temperature=temperature,
            google_api_key=api_key,
        )

    def audit_forensics(self, auditor_text: str, notes_text: str) -> ForensicAuditOutput:
        prompt = ChatPromptTemplate.from_messages([
            ("system", FORENSIC_AUDITOR_SYSTEM),
            ("human", "Perform the forensic governance audit.\n\n=== AUDITOR REPORT / CARO ===\n{auditor_text}\n\n=== NOTES ===\n{notes_text}"),
        ])
        chain = prompt | self.llm.with_structured_output(ForensicAuditOutput)
        return chain.invoke({
            "auditor_text": auditor_text or "No auditor text extracted.",
            "notes_text": notes_text or "No notes text extracted.",
        })

    def extract_metrics_payload(self, financial_statements_text: str) -> CompanyFinancialHistory:
        prompt = ChatPromptTemplate.from_messages([
            ("system", FINANCIAL_EXTRACTION_SYSTEM),
            ("human", "Extract the chronological financial history into the required schema. Normalize all values to INR Crores.\n\n{statements}"),
        ])
        chain = prompt | self.llm.with_structured_output(CompanyFinancialHistory)
        return chain.invoke({
            "statements": financial_statements_text or "No financial statements text extracted.",
        })

    def run_investment_committee(
        self,
        forensic: ForensicAuditOutput,
        calculated_ratios: Dict[str, Any],
        quality_score: Dict[str, Any],
        valuation: Dict[str, Any] | None = None,
    ) -> InvestmentMemo:
        prompt = ChatPromptTemplate.from_messages([
            ("system", INVESTMENT_COMMITTEE_SYSTEM),
            ("human", "Interpret the following evidence. The Python engine owns the numeric score and valuation; explain rather than override them.\n\n=== FORENSIC ===\n{forensics}\n\n=== FUNDAMENTALS ===\n{ratios}\n\n=== DETERMINISTIC QUALITY SCORE ===\n{quality}\n\n=== VALUATION ===\n{valuation}"),
        ])
        chain = prompt | self.llm.with_structured_output(InvestmentMemo)
        return chain.invoke({
            "forensics": forensic.model_dump_json(indent=2),
            "ratios": json.dumps(calculated_ratios, indent=2),
            "quality": json.dumps(quality_score, indent=2),
            "valuation": json.dumps(valuation or {"available": False}, indent=2),
        })
