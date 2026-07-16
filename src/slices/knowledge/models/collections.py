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


COLLECTION_LABELS: dict[str, str] = {
    KnowledgeCollection.CODE_PATTERNS: "Code Patterns Repository",
    KnowledgeCollection.SOLUTIONS: "Solution Database",
    KnowledgeCollection.ERROR_PATTERNS: "Error Patterns",
    KnowledgeCollection.BEST_PRACTICES: "Best Practices",
    KnowledgeCollection.HISTORICAL_CONTEXT: "Historical Context",
    KnowledgeCollection.API_REFERENCE: "API Reference (UL/Docs)",
    KnowledgeCollection.ADR: "Architecture Decision Records",
    KnowledgeCollection.ARCHITECTURE_SPEC: "Architecture Specs (Dizi)",
}

ALL_COLLECTIONS = list(KnowledgeCollection)
