"""
Structured logging configuration for FastAPI application.
Provides request/response logging with appropriate severity levels.
"""

import logging
import time
import os
from fastapi import Request, Response
from typing import Callable

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:\t%(asctime)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create logger for company_dns
logger = logging.getLogger("company_dns")

# Set logging level from environment variable
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Suppress uvicorn access logs if we're doing our own logging
uvicorn_access_logger = logging.getLogger("uvicorn.access")


async def logging_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware to log all HTTP requests with appropriate severity levels.
    
    - DEBUG: Blocked requests (403, 404)
    - INFO: Successful requests (2xx, 3xx)
    - WARNING: Client errors (4xx, except 403/404)
    - ERROR: Server errors (5xx)
    
    Also logs request timing for performance monitoring.
    """
    start_time = time.time()
    
    # Get client info
    client_ip = request.client.host if request.client else "unknown"
    
    # Check for forwarded IP (Azure/AWS load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(',')[0].strip()
    
    # Process request
    try:
        response = await call_next(request)
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(
            f"Exception: {request.method} {request.url.path} "
            f"from {client_ip} - {str(e)} ({process_time:.3f}s)",
            exc_info=True
        )
        raise
    
    process_time = time.time() - start_time
    status_code = response.status_code
    
    # Build log message
    log_msg = (
        f"{request.method} {request.url.path} "
        f"from {client_ip} - {status_code} ({process_time:.3f}s)"
    )
    
    # Log based on response status
    if status_code in [403, 404]:
        # DEBUG level for blocked/not found (reduces log noise)
        logger.debug(f"Blocked: {log_msg}")
    elif status_code >= 500:
        # ERROR level for server errors
        logger.error(f"Error: {log_msg}")
    elif status_code >= 400:
        # WARNING level for client errors
        logger.warning(f"Client Error: {log_msg}")
    else:
        # INFO level for successful requests
        logger.info(f"Success: {log_msg}")
    
    # Add custom headers for debugging (optional, can disable in production)
    if os.environ.get("DEBUG_HEADERS", "false").lower() == "true":
        response.headers["X-Process-Time"] = f"{process_time:.3f}s"
    
    return response


def configure_logging(log_level: str = "INFO", log_file: str | None = None):
    """
    Configure logging with optional file output.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional path to log file
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    
    if log_file:
        # Add file handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        formatter = logging.Formatter(
            '%(levelname)s:\t%(asctime)s [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {log_file}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__ of the module)
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
