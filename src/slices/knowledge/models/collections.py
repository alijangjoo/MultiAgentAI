from enum import StrEnum


class KnowledgeCollection(StrEnum):
    CODE_PATTERNS = "code_patterns"
    SOLUTIONS = "solutions"
    ERROR_PATTERNS = "error_patterns"
    BEST_PRACTICES = "best_practices"
    HISTORICAL_CONTEXT = "historical_context"
    API_REFERENCE = "api_reference"
    ADR = "adr"
    ARCHITECTURE_SPEC = "architecture_spec"
    REVIEW_RULES = "review_rules"
    CODE_SPECS = "code_specs"
    REVIEW_PROMPT = "review_prompt"
    AGENT_DOCUMENTS = "agent_documents"
    UBIQUITOUS_LANGUAGE = "ubiquitous_language"
    DATABASE_SCHEMA = "database_schema"


COLLECTION_LABELS: dict[str, str] = {
    KnowledgeCollection.CODE_PATTERNS: "Code Patterns Repository",
    KnowledgeCollection.SOLUTIONS: "Solution Database",
    KnowledgeCollection.ERROR_PATTERNS: "Error Patterns",
    KnowledgeCollection.BEST_PRACTICES: "Best Practices",
    KnowledgeCollection.HISTORICAL_CONTEXT: "Historical Context",
    KnowledgeCollection.API_REFERENCE: "API Reference (UL/Docs)",
    KnowledgeCollection.ADR: "Architecture Decision Records",
    KnowledgeCollection.ARCHITECTURE_SPEC: "Architecture Specs (Dizi)",
    KnowledgeCollection.REVIEW_RULES: "Sentinel Review Rules",
    KnowledgeCollection.CODE_SPECS: "Code Specs",
    KnowledgeCollection.REVIEW_PROMPT: "Review Prompt Template",
    KnowledgeCollection.AGENT_DOCUMENTS: "Agent Document Catalog",
    KnowledgeCollection.UBIQUITOUS_LANGUAGE: "Ubiquitous Language (*_UL.md)",
    KnowledgeCollection.DATABASE_SCHEMA: "Dizi MySQL Schema (Dev / Stage)",
}

ALL_COLLECTIONS = list(KnowledgeCollection)
