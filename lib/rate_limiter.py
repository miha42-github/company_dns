"""
Rate limiting configuration using slowapi.
Protects against DDoS and excessive API usage.
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import os

# Initialize rate limiter with IP-based key function
# This tracks requests per IP address
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500/minute"],  # Global default
    storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,  # Include rate limit info in response headers
)

# Rate limit configurations for different endpoint types
RATE_LIMITS = {
    # Public documentation endpoints - higher limits
    "docs": "1000/minute",
    
    # SIC lookup endpoints - moderate limits
    "sic": "200/minute",
    
    # Company/firmographics endpoints - lower limits (more expensive queries)
    "firmographics": "100/minute",
    
    # EDGAR detail endpoints - stricter limits (database intensive)
    "edgar_detail": "50/minute",
    
    # Search/query endpoints - moderate limits
    "search": "150/minute",
}


def get_rate_limit_for_path(path: str) -> str:
    """
    Determine appropriate rate limit based on request path.
    
    Args:
        path: Request URL path
        
    Returns:
        Rate limit string (e.g., "100/minute")
    """
    path_lower = path.lower()
    
    # Documentation paths
    if any(doc_path in path_lower for doc_path in ['/docs', '/redoc', '/help']):
        return RATE_LIMITS["docs"]
    
    # Firmographics endpoints (most expensive)
    if 'firmographics' in path_lower or 'merged' in path_lower:
        return RATE_LIMITS["firmographics"]
    
    # Detailed EDGAR endpoints
    if '/edgar/detail' in path_lower or '/edgar/ciks' in path_lower:
        return RATE_LIMITS["edgar_detail"]
    
    # SIC endpoints
    if '/sic/' in path_lower:
        return RATE_LIMITS["sic"]
    
    # Default for all other endpoints
    return "150/minute"


# Custom error handler for rate limit exceeded
async def rate_limit_error_handler(request, exc):
    """
    Custom handler for rate limit exceeded errors.
    Returns JSON response with helpful information.
    """
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "code": 429,
            "detail": str(exc.detail),
            "retry_after": getattr(exc, 'retry_after', 'unknown'),
            "help": "Please wait before making more requests"
        }
    )
