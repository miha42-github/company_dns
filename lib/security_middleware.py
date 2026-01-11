"""
Security middleware for FastAPI application.
Blocks malicious requests, validates paths, and implements security best practices.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class SecurityConfig:
    """Security configuration with blocked patterns and validation rules"""
    
    # Known malicious patterns to block immediately (403 response)
    BLOCKED_PATTERNS = [
        # WordPress and CMS vulnerabilities
        'wp-', 'wordpress', 'wp_', 'xmlrpc',
        'wp-admin', 'wp-login', 'wp-content', 'wp-includes',
        'wp-trackback', 'wp-cron', 'wp-json',
        
        # Admin panels
        'admin', 'administrator', 'phpmyadmin', 'pma',
        'cpanel', 'webmail', 'plesk',
        
        # File extensions (we only serve JSON/HTML)
        '.php', '.asp', '.aspx', '.jsp', '.cgi', '.pl', '.py',
        '.sh', '.bat', '.cmd', '.exe',
        
        # Configuration and sensitive files
        'config', '.env', '.git', '.svn', '.hg', '.bzr',
        'web.config', '.htaccess', '.htpasswd',
        'passwd', 'shadow', 'etc/passwd',
        
        # Common exploit paths
        'shell', 'upload', 'eval', 'exec', 'system',
        'phpinfo', 'info.php', 'test.php',
        'backup', 'old', 'temp', 'tmp',
        
        # Database
        'sql', 'mysql', 'mssql', 'oracle', 'postgres',
        'database', 'db_', 'backup.sql',
        
        # Debugging and development
        'debug', 'trace', 'console', 'phperror',
        '.log', 'error_log', 'access_log',
    ]
    
    # Suspicious query parameters (SQL injection, XSS attempts)
    BLOCKED_QUERY_PARAMS = [
        # SQL injection
        'union', 'select', 'insert', 'delete', 'drop',
        'update', 'exec', 'execute', 'declare',
        '1=1', '1\'=\'1', 'or 1=1', 'and 1=1',
        
        # XSS attempts
        'script', 'javascript:', 'onerror=', 'onload=',
        '<script', '</script>', 'alert(', 'eval(',
        
        # Command injection
        '&&', '||', ';', '|', '`',
        '../', '..\\', '/etc/', 'c:\\',
    ]
    
    # Valid API path prefixes (whitelist)
    VALID_PREFIXES = [
        '/V2.0/',
        '/V3.0/',
        '/help',
        '/static',
        '/docs',
        '/redoc',
        '/openapi.json',
        '/health',
    ]
    
    # Paths that are always allowed (root, favicon, etc.)
    ALWAYS_ALLOWED = {
        '/',
        '/favicon.ico',
        '/robots.txt',
        '/health',
    }


async def security_middleware(request: Request, call_next):
    """
    FastAPI middleware to block malicious requests before they reach endpoints.
    
    This middleware provides defense-in-depth by:
    1. Blocking known attack patterns in URL paths
    2. Detecting SQL injection and XSS in query parameters
    3. Validating paths against whitelist of valid prefixes
    4. Logging security events for monitoring
    
    Returns:
        - 403 Forbidden for known attack patterns
        - 404 Not Found for invalid paths (outside whitelist)
        - Normal response for legitimate requests
    """
    path = request.url.path.lower()
    original_path = request.url.path
    query = str(request.url.query).lower()
    client_ip = request.client.host if request.client else "unknown"
    
    # Allow always-allowed paths immediately
    if original_path in SecurityConfig.ALWAYS_ALLOWED:
        return await call_next(request)
    
    # Check for blocked path patterns
    for pattern in SecurityConfig.BLOCKED_PATTERNS:
        if pattern in path:
            logger.warning(
                f"Blocked malicious path: {original_path} from {client_ip} "
                f"(matched pattern: '{pattern}')"
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "Forbidden",
                    "code": 403,
                    "path": original_path
                }
            )
    
    # Check for SQL injection or XSS in query parameters
    if query:
        for pattern in SecurityConfig.BLOCKED_QUERY_PARAMS:
            if pattern in query:
                logger.warning(
                    f"Blocked suspicious query: {request.url.query} from {client_ip} "
                    f"(matched pattern: '{pattern}')"
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "detail": "Invalid query parameters",
                        "code": 403,
                        "reason": "Potential SQL injection or XSS attempt detected"
                    }
                )
    
    # Validate path starts with known prefix (unless it's allowed above)
    is_valid = any(original_path.startswith(prefix) for prefix in SecurityConfig.VALID_PREFIXES)
    
    if not is_valid:
        logger.debug(f"Invalid path: {original_path} from {client_ip}")
        # Return 404 instead of 403 to avoid leaking information about security rules
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": "Not Found",
                "code": 404,
                "path": original_path,
                "help": "Visit /docs for API documentation"
            }
        )
    
    # Process legitimate requests
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(f"Error processing request {original_path}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal Server Error",
                "code": 500
            }
        )


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request, accounting for proxies.
    
    Checks X-Forwarded-For header (Azure/AWS/GCP load balancers) first,
    falls back to direct client connection.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, use the first (client)
        return forwarded_for.split(',')[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    if request.client:
        return request.client.host
    
    return "unknown"
