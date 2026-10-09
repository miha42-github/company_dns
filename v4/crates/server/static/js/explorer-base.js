/**
 * ExplorerBase Class
 * Shared pagination, keyboard navigation, and display management logic
 * for all explorer component types (Industry, EDGAR, future explorers)
 * 
 * Provides:
 * - Pagination state and navigation methods
 * - Pagination UI helpers (visible pages, result ranges)
 * - Keyboard navigation (arrow keys, Home, End)
 * - Scroll and display management
 * - Modal integration
 * 
 * Usage: Extend this class in specialized explorer components
 * and override getActiveFiltersLabel() for custom filter labels.
 */

class ExplorerBase {
  /**
   * Initialize base explorer with container references
   * @param {Object} containerIds - HTML element IDs: { searchContainer, resultsLayout, resultsContainer }
   */
  constructor(containerIds = {}) {
    // Pagination state
    this.currentPage = 1;
    this.resultsPerPage = 10;
    this.totalPages = 1;
    this.filteredResults = [];
    
    // UI state
    this.isSearching = false;
    this.hasResults = false;
    this.errorMessage = '';
    this.statusMessage = '';
    this.showResults = false;
    
    // Container references for scroll/display
    this.containerIds = containerIds; // { searchContainer, resultsLayout, resultsContainer }
  }
  
  // ============ Pagination Navigation Methods ============
  
  /**
   * Navigate to first page
   * Calls optional updateUrlState() and scrollToResults() if available
   */
  firstPage() {
    if (this.currentPage !== 1) {
      this.currentPage = 1;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to previous page
   * Calls optional updateUrlState() and scrollToResults() if available
   */
  prevPage() {
    if (this.currentPage > 1) {
      this.currentPage--;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to next page
   * Calls optional updateUrlState() and scrollToResults() if available
   */
  nextPage() {
    if (this.currentPage < this.totalPages) {
      this.currentPage++;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to last page
   * Calls optional updateUrlState() and scrollToResults() if available
   */
  lastPage() {
    if (this.currentPage !== this.totalPages) {
      this.currentPage = this.totalPages;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  /**
   * Navigate to specific page number
   * @param {number} pageNum - Page number to navigate to
   * Calls optional updateUrlState() and scrollToResults() if available
   */
  goToPage(pageNum) {
    if (pageNum >= 1 && pageNum <= this.totalPages) {
      this.currentPage = pageNum;
      this.updateUrlState?.();
      this.scrollToResults?.();
    }
  }
  
  // ============ Pagination UI Helper Methods ============
  
  /**
   * Get visible page numbers for pagination button group
   * Shows up to 5 page buttons centered on current page
   * @returns {Array<number>} Array of page numbers to display
   */
  getVisiblePages() {
    const maxButtons = 5;
    let start = Math.max(1, this.currentPage - Math.floor(maxButtons / 2));
    let end = Math.min(this.totalPages, start + maxButtons - 1);
    if (end - start + 1 < maxButtons) {
      start = Math.max(1, end - maxButtons + 1);
    }
    const pages = [];
    for (let p = start; p <= end; p++) {
      pages.push(p);
    }
    return pages;
  }
  
  /**
   * Get headline summary text
   * @returns {string} e.g., "42 results" or status message
   */
  getResultsHeadline() {
    if (!this.hasResults) {
      return this.statusMessage || 'No results';
    }
    return `${this.filteredResults?.length || 0} results`;
  }
  
  /**
   * Get results range label for current page
   * @returns {string} e.g., "Showing 1-10 of 42"
   */
  getResultsRangeLabel() {
    if (!this.hasResults || !this.filteredResults?.length) {
      return 'Showing 0-0 of 0';
    }
    const start = (this.currentPage - 1) * this.resultsPerPage + 1;
    const end = Math.min(this.filteredResults.length, start + this.resultsPerPage - 1);
    return `Showing ${start}-${end} of ${this.filteredResults.length}`;
  }
  
  /**
   * Get active filters summary label
   * Subclasses override to provide type-specific label
   * @returns {string} Filter summary text, default "Filters: none"
   */
  getActiveFiltersLabel() {
    return 'Filters: none';
  }
  
  // ============ Keyboard Navigation ============
  
  /**
   * Handle keyboard shortcuts for pagination
   * - ArrowLeft/ArrowRight: Previous/Next page
   * - Home/End: First/Last page
   * Ignores input in form fields
   * @param {KeyboardEvent} event - The keyboard event
   */
  handleKeyboard(event) {
    if (!this.showResults || !this.filteredResults?.length) return;
    
    // Don't trigger if user is typing in a form field
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    
    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault();
        this.prevPage();
        break;
      case 'ArrowRight':
        event.preventDefault();
        this.nextPage();
        break;
      case 'Home':
        event.preventDefault();
        this.firstPage();
        break;
      case 'End':
        event.preventDefault();
        this.lastPage();
        break;
    }
  }
  
  // ============ Scroll & Display Management ============
  
  /**
   * Scroll results container into view smoothly
   * Note: In Alpine components, call within $nextTick() for proper rendering
   * @param {string} elementId - HTML ID of results container element
   */
  scrollToResults(elementId) {
    const resultsDiv = document.getElementById(elementId);
    if (resultsDiv) {
      resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
  
  /**
   * Show results layout and hide initial search container
   * @param {string} initialContainerId - ID of initial search container
   * @param {string} resultsLayoutId - ID of results layout container
   */
  showResultsLayout(initialContainerId, resultsLayoutId) {
    const initialContainer = document.getElementById(initialContainerId);
    const resultsLayout = document.getElementById(resultsLayoutId);
    
    if (initialContainer) initialContainer.style.display = 'none';
    if (resultsLayout) resultsLayout.style.display = 'block';
  }
  
  /**
   * Show initial search layout and hide results
   * @param {string} initialContainerId - ID of initial search container
   * @param {string} resultsLayoutId - ID of results layout container
   */
  showSearchLayout(initialContainerId, resultsLayoutId) {
    const initialContainer = document.getElementById(initialContainerId);
    const resultsLayout = document.getElementById(resultsLayoutId);
    
    if (initialContainer) initialContainer.style.display = 'block';
    if (resultsLayout) resultsLayout.style.display = 'none';
  }
  
  // ============ Modal Integration ============
  
  /**
   * Show JSON modal for a result item
   * Uses the global showJsonModal() function
   * @param {Object} resultData - The result data to display
   */
  showJsonModal(resultData) {
    showJsonModal(resultData);
  }
}

// Export for use in Alpine components
window.ExplorerBase = ExplorerBase;
