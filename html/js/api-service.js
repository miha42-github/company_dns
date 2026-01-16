/**
 * API Service Module for company_dns
 * Centralized API call handling with consistent error handling and response formatting
 */

class APIService {
  constructor() {
    this.baseUrl = this.getBaseUrl();
    this.timeout = 30000; // 30 seconds
    this.cache = new Map();
    this.cacheExpiry = new Map();
  }

  /**
   * Get the base URL for API calls
   * Handles different deployment scenarios (localhost, production, custom host)
   */
  getBaseUrl() {
    if (window.companyDnsServers && window.companyDnsServers[window.location.hostname]) {
      return window.companyDnsServers[window.location.hostname];
    }

    const protocol = window.location.protocol;
    const host = window.location.host; // includes port
    return `${protocol}//${host}`;
  }

  /**
   * Perform a generic GET request with timeout and error handling
   * @param {string} endpoint - API endpoint path (e.g., '/V3.0/global/sic/description/...')
   * @param {Object} options - Request options
   * @returns {Promise<Object>} Response data
   */
  async get(endpoint, options = {}) {
    const {
      useCache = false,
      cacheDuration = 5 * 60 * 1000, // 5 minutes default
      signal = null,
      timeout = null // Allow custom timeout per request
    } = options;

    // Check cache first
    if (useCache && this.cache.has(endpoint)) {
      const expiry = this.cacheExpiry.get(endpoint);
      if (expiry && Date.now() < expiry) {
        console.log(`[APIService] Cache hit for: ${endpoint}`);
        return this.cache.get(endpoint);
      }
      // Cache expired, remove it
      this.cache.delete(endpoint);
      this.cacheExpiry.delete(endpoint);
    }

    const url = `${this.baseUrl}${endpoint}`;
    const effectiveTimeout = timeout !== null ? timeout : this.timeout;
    
    try {
      const controller = signal ? null : new AbortController();
      const timeoutId = signal ? null : setTimeout(
        () => controller?.abort(),
        effectiveTimeout
      );

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
        signal: signal || controller?.signal
      });

      if (timeoutId) clearTimeout(timeoutId);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({
          detail: `HTTP ${response.status}`,
          code: response.status
        }));
        throw new APIError(
          errorData.detail || 'API Error',
          response.status,
          errorData
        );
      }

      const data = await response.json();

      // Cache successful responses if requested
      if (useCache) {
        this.cache.set(endpoint, data);
        this.cacheExpiry.set(endpoint, Date.now() + cacheDuration);
        console.log(`[APIService] Cached response for: ${endpoint}`);
      }

      return data;

    } catch (error) {
      if (error instanceof APIError) {
        throw error;
      }
      
      if (error.name === 'AbortError') {
        throw new APIError(
          'Request timeout',
          408,
          { detail: 'Request exceeded 30 second timeout' }
        );
      }

      throw new APIError(
        error.message || 'Network error',
        0,
        { detail: error.message }
      );
    }
  }

  /**
   * Search for industry codes by description
   * @param {string} query - Search query
   * @param {Object} options - Additional options
   * @returns {Promise<Object>} Search results
   */
  async searchIndustryCodes(query, options = {}) {
    console.log('[APIService] searchIndustryCodes called with:', query);
    
    if (!query || query.trim().length === 0) {
      throw new APIError('Query cannot be empty', 400, {
        detail: 'Please enter a search term'
      });
    }

    const endpoint = `/V3.0/global/sic/description/${encodeURIComponent(query)}`;
    console.log('[APIService] Calling endpoint:', endpoint);
    console.log('[APIService] Base URL:', this.baseUrl);
    
    try {
      const result = await this.get(endpoint, {
        useCache: true,
        cacheDuration: 10 * 60 * 1000, // 10 minutes for search results
        ...options
      });
      console.log('[APIService] Search results received:', result);
      return result;
    } catch (error) {
      console.error('[APIService] Search error:', error);
      throw error;
    }
  }

  /**
   * Get SIC code details
   * @param {string} code - SIC code
   * @returns {Promise<Object>} Code details
   */
  async getSICDetails(code) {
    const endpoint = `/V2.0/sic/description/${encodeURIComponent(code)}`;
    return this.get(endpoint, {
      useCache: true,
      cacheDuration: 24 * 60 * 60 * 1000 // 24 hours for static data
    });
  }

  /**
   * Get health status
   * @returns {Promise<Object>} Health status
   */
  async getHealth() {
    return this.get('/health', {
      useCache: false // Don't cache health checks
    });
  }

  /**
   * Clear all cached data
   */
  clearCache() {
    this.cache.clear();
    this.cacheExpiry.clear();
    console.log('[APIService] Cache cleared');
  }

  /**
   * Clear cache for specific endpoint
   * @param {string} endpoint - Endpoint to clear
   */
  clearCacheFor(endpoint) {
    this.cache.delete(endpoint);
    this.cacheExpiry.delete(endpoint);
    console.log(`[APIService] Cache cleared for: ${endpoint}`);
  }
}

/**
 * Custom error class for API errors
 */
class APIError extends Error {
  constructor(message, statusCode, data) {
    super(message);
    this.name = 'APIError';
    this.statusCode = statusCode;
    this.data = data;
  }
}

// Create and export singleton instance
const apiService = new APIService();
