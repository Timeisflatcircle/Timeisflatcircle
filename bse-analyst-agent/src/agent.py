"""
src/agent.py
Autonomous financial analysis agent using Google Gemini.
"""

import os
import json
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from src.financial_tools import CompanyFinancialInputs
from src.prompts import (
    FORENSIC_AUDITOR_SYSTEM,
    FINANCIAL_EXTRACTION_SYSTEM,
    INVESTMENT_COMMITTEE_SYSTEM,
)


# ==========================================
# 1. Pydantic Structured Output Schemas
# ==========================================

class ForensicAuditOutput(BaseModel):
    audit_opinion_type: str = Field(
        description="Must be 'Unmodified/Clean', 'Qualified', 'Adverse', or 'Disclaimer'"
    )
    key_audit_matters: List[str] = Field(
        description="Primary areas of focus, complex estimates, or disputes noted by the auditor"
    )
    contingent_liability_risk: str = Field(
        description="'Low', 'Medium', or 'High' with explicit reasoning relative to net worth"
    )
    related_party_risk: str = Field(
        description="'Low', 'Medium', or 'High' based on loans, guarantees, or non-operating advances to affiliates"
    )
    forensic_red_flags: List[str] = Field(
        description="Specific accounting red flags, CARO remarks, or corporate governance breaches found"
    )


class InvestmentMemo(BaseModel):
    verdict: str = Field(
        description="Final decision: strictly 'INVESTIBLE', 'WATCHLIST', or 'AVOID'"
    )
    conviction_score: int = Field(
        description="Numerical confidence rating from 1 (Extreme Risk / Avoid) to 10 (Highest Conviction Compounder)"
    )
    executive_summary: str = Field(
        description="Comprehensive narrative thesis explaining the verdict, accounting quality, and financial trends"
    )
    financial_strengths: List[str] = Field(
        description="Key balance sheet and operational strengths identified"
    )
    critical_risks: List[str] = Field(
        description="Structural risks, macro headwinds, or financial fragilities"
    )
    governance_clearance: bool = Field(
        description="True if corporate governance and audit reports are clean; False if compromised"
    )


# ==========================================
# 2. Agent Orchestration Engine (Gemini)
# ==========================================

class AnalysisOrchestrator:
    def __init__(self, model_name: str = "gemini-3.6-flash", temperature: float = 0.0):
        """
        Initializes the Gemini LLM orchestrator.
        'gemini-3.6-flash' provides fast inference and structured outputs.
        """
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY or GOOGLE_API_KEY environment variable not detected. "
                "Please set it in your .env file."
            )
            
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key
        )

    def audit_forensics(self, auditor_text: str, notes_text: str) -> ForensicAuditOutput:
        prompt = ChatPromptTemplate.from_messages([
            ("system", FORENSIC_AUDITOR_SYSTEM),
            (
                "human",
                "Please perform a thorough forensic governance audit on the following annual report excerpts:\n\n"
                "=== INDEPENDENT AUDITOR'S REPORT & CARO ===\n{auditor_text}\n\n"
                "=== NOTES TO ACCOUNTS (CONTINGENT LIABILITIES & RPT) ===\n{notes_text}"
            )
        ])
        
        chain = prompt | self.llm.with_structured_output(ForensicAuditOutput)
        return chain.invoke({
            "auditor_text": auditor_text if auditor_text else "No auditor text extracted.",
            "notes_text": notes_text if notes_text else "No notes text extracted."
        })

    def extract_metrics_payload(self, financial_statements_text: str) -> CompanyFinancialInputs:
        prompt = ChatPromptTemplate.from_messages([
            ("system", FINANCIAL_EXTRACTION_SYSTEM),
            (
                "human",
                "Extract the financial statement values into the required schema. "
                "Ensure figures are normalized to INR Crores:\n\n{statements}"
            )
        ])
        
        chain = prompt | self.llm.with_structured_output(CompanyFinancialInputs)
        return chain.invoke({
            "statements": financial_statements_text if financial_statements_text else "No financial statements text extracted."
        })

    def run_investment_committee(
        self, 
        forensic: ForensicAuditOutput, 
        calculated_ratios: Dict[str, Any]
    ) -> InvestmentMemo:
        prompt = ChatPromptTemplate.from_messages([
            ("system", INVESTMENT_COMMITTEE_SYSTEM),
            (
                "human",
                "Synthesize the following forensic audit results and calculated fundamental ratios to render an investment verdict:\n\n"
                "=== FORENSIC & GOVERNANCE REPORT ===\n{forensics}\n\n"
                "=== CALCULATED FINANCIAL RATIOS & HURDLES ===\n{ratios}"
            )
        ])
        
        chain = prompt | self.llm.with_structured_output(InvestmentMemo)
        return chain.invoke({
            "forensics": forensic.model_dump_json(indent=2),
            "ratios": json.dumps(calculated_ratios, indent=2)
        })