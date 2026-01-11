"""
Pydantic models for API validation.
Using a simple BaseAPIResponse that matches actual backend structure.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any


# ============================================================================
# Base Response Model (matches actual backend structure)
# ============================================================================

class BaseAPIResponse(BaseModel):
    """
    Base response model matching actual backend structure.
    All backend endpoints return: code, message, module, data, dependencies
    The 'data' field structure varies by endpoint but is always a dict.
    """
    code: int = Field(..., ge=200, le=599, description="HTTP status code")
    message: Optional[str] = Field(None, description="Response message")
    module: Optional[str] = Field(None, description="Module that processed the request")
    data: Dict[str, Any] = Field(default_factory=dict, description="Response data (structure varies)")
    dependencies: Optional[Dict[str, Any]] = Field(None, description="Data dependencies")
    
    model_config = ConfigDict(
        extra='allow',  # Allow additional fields
        json_schema_extra={
            "example": {
                "code": 200,
                "message": "Success",
                "module": "Module->method",
                "data": {},
                "dependencies": {"modules": {}, "data": {}}
            }
        }
    )


# Use BaseAPIResponse for all endpoints since they follow the same structure
SICResponse = BaseAPIResponse
DivisionResponse = BaseAPIResponse
UKSICResponse = BaseAPIResponse
ISICResponse = BaseAPIResponse
EUSICResponse = BaseAPIResponse
JapanSICResponse = BaseAPIResponse
UnifiedSICResponse = BaseAPIResponse
EdgarCIKResponse = BaseAPIResponse
EdgarDetailResponse = BaseAPIResponse
WikipediaResponse = BaseAPIResponse
MergedFirmographicsResponse = BaseAPIResponse
