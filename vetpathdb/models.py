from datetime import datetime
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any

# Filter / QueryRequest used by /api/query are defined locally inside
# vetpathdb/app.py and vetpathdb/search/query.py — only the classes that
# other modules actually import live in this file.

class Filter(BaseModel):
    """Filter criteria for case searches"""
    category: str
    term: str
    operator: Optional[str] = "eq"  # eq, gt, lt, contains, etc.

class SearchQuery(BaseModel):
    """Search query parameters"""
    term: str
    limit: Optional[int] = 20
    offset: Optional[int] = 0
    sort_by: Optional[str] = None
    sort_order: Optional[str] = "desc"

class StatsResponse(BaseModel):
    """Response model for basic statistics"""
    total_cases: int
    unique_species: int
    avg_age: Optional[float] = None
    last_updated: datetime = Field(default_factory=datetime.now)

class Case(BaseModel):
    """Core case model"""
    case_id: str
    date: datetime
    species: str
    age: Optional[float]
    diagnosis: str
    findings: List[str] = []
    metadata: Optional[Dict[str, Any]] = None

    @validator('case_id')
    def validate_case_id(cls, v):
        from vetpathdb.pipeline._utils import is_valid_case_id
        if not is_valid_case_id(v):
            raise ValueError(
                f'Case ID {v!r} does not match any registered case-ID pattern '
                f'(see vetpathdb/prompts/case_id_patterns.yaml; override via '
                f'VETPATHDB_CASE_ID_PATTERNS)'
            )
        return v

    @validator('date', pre=True)
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v
