/**
 * Global Industry Code Search - Alpine.js Version
 * Refactored to use Alpine.js for better state management and reduced code duplication
 */

function createGlobalSearchComponent() {
  return {
    // State
    searchQuery: '',
    currentPage: 1,
    resultsPerPage: 10,
    totalPages: 1,
    filteredResults: [],
    allResults: [],
    
    // Filter states
    filters: {
      all: true,
      'US SIC': true,
      'UK SIC': true,
      'EU NACE': true,
      'ISIC': true,
      'Japan SIC': true
    },
    
    filterCounts: {
      all: 0,
      'US SIC': 0,
      'UK SIC': 0,
      'EU NACE': 0,
      'ISIC': 0,
      'Japan SIC': 0
    },
    
    // UI states
    isSearching: false,
    hasResults: false,
    errorMessage: '',
    statusMessage: '',
    showResults: false,
    selectedJsonResult: null,
    showJsonModal: false,
    jumpToPage: '',
    
    /**
     * Initialize the component
     */
    async init() {
      // Add keyboard navigation support
      document.addEventListener('keydown', (e) => this.handleKeyboard(e));
      console.log('[GlobalSearch] Component initialized with Alpine.js');
      console.log('[GlobalSearch] apiService available:', typeof apiService !== 'undefined');
    },
    
    /**
     * Perform global search for industry codes
     */
    async performSearch() {
      console.log('[GlobalSearch] performSearch called with:', this.searchQuery);
      this.searchQuery = this.searchQuery.trim();
      if (!this.searchQuery) {
        console.warn('[GlobalSearch] Empty search query');
        return;
      }
      
      this.isSearching = true;
      this.hasResults = false;
      this.errorMessage = '';
      this.statusMessage = `Searching for "${this.searchQuery}"...`;
      this.showResults = true;
      this.currentPage = 1;
      this.filteredResults = [];
      
      try {
        console.log('[GlobalSearch] Calling apiService.searchIndustryCodes');
        const data = await apiService.searchIndustryCodes(this.searchQuery);
        console.log('[GlobalSearch] API response:', data);
        
        if (data.code !== 200 || !data.data?.results) {
          console.warn('[GlobalSearch] No results in response');
          this.errorMessage = 'No results found.';
          this.statusMessage = '';
          this.isSearching = false;
          return;
        }
        
        console.log('[GlobalSearch] Got results:', data.data.results.length);
        this.allResults = data.data.results;
        this.updateFilterCounts();
        this.applyFilters();
        this.statusMessage = `Found ${this.allResults.length} of ${data.data.total} results`;
        this.hasResults = true;
        console.log('[GlobalSearch] Search complete, hasResults:', this.hasResults);
        
      } catch (error) {
        this.errorMessage = `Error: ${error.message}`;
        this.statusMessage = '';
        console.error('[GlobalSearch] Search error:', error);
        
      } finally {
        this.isSearching = false;
      }
    },
    
    /**
     * Update filter counts based on results
     */
    updateFilterCounts() {
      const counts = {
        all: this.allResults.length,
        'US SIC': 0,
        'UK SIC': 0,
        'EU NACE': 0,
        'ISIC': 0,
        'Japan SIC': 0
      };
      
      this.allResults.forEach(result => {
        if (counts[result.source_type] !== undefined) {
          counts[result.source_type]++;
        }
      });
      
      console.log('[GlobalSearch] Filter counts:', counts);
      this.filterCounts = counts;
    },
    
    /**
     * Apply selected filters to results
     */
    applyFilters() {
      const selectedSources = this.getSelectedSources();
      
      if (selectedSources.length === 0) {
        this.filteredResults = [];
      } else {
        this.filteredResults = this.allResults.filter(result =>
          selectedSources.includes(result.source_type)
        );
      }
      
      // Recalculate pagination
      this.totalPages = Math.max(1, Math.ceil(this.filteredResults.length / this.resultsPerPage));
      if (this.currentPage > this.totalPages) {
        this.currentPage = 1;
      }
      
      if (this.filteredResults.length === 0) {
        this.statusMessage = this.filters.all 
          ? 'No results match the selected filters.'
          : 'Please select at least one filter.';
      } else {
        this.statusMessage = `Showing ${this.getCurrentPageResults().length} of ${this.filteredResults.length} results`;
      }
    },
    
    /**
     * Get selected source filters
     */
    getSelectedSources() {
      return Object.entries(this.filters)
        .filter(([key, checked]) => checked && key !== 'all')
        .map(([key]) => key);
    },
    
    /**
     * Handle filter "All Results" checkbox
     */
    toggleAllFilters(checked) {
      this.filters.all = checked;
      Object.keys(this.filters).forEach(key => {
        if (key !== 'all') {
          this.filters[key] = checked;
        }
      });
      this.currentPage = 1;
      this.applyFilters();
    },
    
    /**
     * Handle individual filter checkbox
     */
    toggleFilter(filterName) {
      // Note: x-model already updates the value, we just need to handle side effects
      
      // Update "all" checkbox state
      const anyChecked = Object.entries(this.filters)
        .some(([key, checked]) => key !== 'all' && checked);
      this.filters.all = anyChecked && Object.entries(this.filters)
        .every(([key, checked]) => key === 'all' || checked);
      
      this.currentPage = 1;
      this.applyFilters();
      console.log('[GlobalSearch] Filter toggled:', filterName, 'New state:', this.filters[filterName]);
    },
    
    /**
     * Get results for current page
     */
    getCurrentPageResults() {
      const startIndex = (this.currentPage - 1) * this.resultsPerPage;
      const endIndex = startIndex + this.resultsPerPage;
      const pageResults = this.filteredResults.slice(startIndex, endIndex);
      console.log('[GlobalSearch] getCurrentPageResults:', {
        filteredResults: this.filteredResults.length,
        currentPage: this.currentPage,
        resultsPerPage: this.resultsPerPage,
        startIndex,
        endIndex,
        pageResults: pageResults.length
      });
      return this.filteredResults.slice(startIndex, endIndex);
    },
    
    /**
     * Change results per page
     */
    changeResultsPerPage(newPageSize) {
      this.resultsPerPage = parseInt(newPageSize);
      this.currentPage = 1;
      this.totalPages = Math.max(1, Math.ceil(this.filteredResults.length / this.resultsPerPage));
    },
    
    /**
     * Navigate to page
     */
    goToPage(pageNum) {
      const num = parseInt(pageNum);
      if (num >= 1 && num <= this.totalPages && num !== this.currentPage) {
        this.currentPage = num;
        this.$nextTick(() => {
          document.getElementById('globalSearchResults')?.scrollIntoView({ behavior: 'smooth' });
        });
      }
    },
    
    /**
     * Go to next page
     */
    nextPage() {
      if (this.currentPage < this.totalPages) {
        this.currentPage++;
        this.scrollToResults();
      }
    },
    
    /**
     * Go to previous page
     */
    previousPage() {
      if (this.currentPage > 1) {
        this.currentPage--;
        this.scrollToResults();
      }
    },
    
    /**
     * Go to first page
     */
    firstPage() {
      if (this.currentPage !== 1) {
        this.currentPage = 1;
        this.scrollToResults();
      }
    },
    
    /**
     * Go to last page
     */
    lastPage() {
      if (this.currentPage !== this.totalPages) {
        this.currentPage = this.totalPages;
        this.scrollToResults();
      }
    },
    
    /**
     * Handle keyboard shortcuts
     */
    handleKeyboard(event) {
      if (!this.showResults || !this.filteredResults.length) return;
      
      if (event.altKey) {
        switch (event.key) {
          case 'ArrowLeft':
            event.preventDefault();
            this.previousPage();
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
    },
    
    /**
     * Scroll results into view
     */
    scrollToResults() {
      this.$nextTick(() => {
        const resultsDiv = document.getElementById('globalSearchResults');
        if (resultsDiv) {
          resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    },
    
    /**
     * Show JSON modal for result
     */
    viewResultJson(result) {
      this.selectedJsonResult = {
        source_type: result.source_type,
        code: result.code,
        description: result.description,
        additional_data: result.additional_data || {}
      };
      this.showJsonModal = true;
    },
    
    /**
     * Close JSON modal
     */
    closeJsonModal() {
      this.showJsonModal = false;
      this.selectedJsonResult = null;
    },
    
    /**
     * Copy JSON to clipboard
     */
    copyJsonToClipboard() {
      const jsonStr = JSON.stringify(this.selectedJsonResult, null, 2);
      navigator.clipboard.writeText(jsonStr).then(() => {
        alert('JSON copied to clipboard');
      }).catch(() => {
        alert('Failed to copy to clipboard');
      });
    },
    
    /**
     * Get pagination button range
     */
    getPaginationRange() {
      const maxButtons = 5;
      let startPage = Math.max(1, this.currentPage - Math.floor(maxButtons / 2));
      let endPage = Math.min(this.totalPages, startPage + maxButtons - 1);
      
      if (endPage - startPage + 1 < maxButtons && startPage > 1) {
        startPage = Math.max(1, endPage - maxButtons + 1);
      }
      
      return { startPage, endPage };
    },
    
    /**
     * Check if page button should show
     */
    showPageButton(pageNum) {
      const { startPage, endPage } = this.getPaginationRange();
      return pageNum === 1 || pageNum === this.totalPages || (pageNum >= startPage && pageNum <= endPage);
    },
    
    /**
     * Check if ellipsis should show before page range
     */
    showEllipsisBefore() {
      const { startPage } = this.getPaginationRange();
      return startPage > 2;
    },
    
    /**
     * Check if ellipsis should show after page range
     */
    showEllipsisAfter() {
      const { endPage } = this.getPaginationRange();
      return endPage < this.totalPages - 1;
    },
    
    /**
     * Get page numbers to display
     */
    getPageNumbers() {
      const pages = [];
      const { startPage, endPage } = this.getPaginationRange();
      
      // First page
      if (startPage > 1) {
        pages.push(1);
        if (this.showEllipsisBefore()) {
          pages.push('...');
        }
      }
      
      // Range pages
      for (let i = startPage; i <= endPage; i++) {
        pages.push(i);
      }
      
      // Last page
      if (endPage < this.totalPages) {
        if (this.showEllipsisAfter()) {
          pages.push('...');
        }
        pages.push(this.totalPages);
      }
      
      return pages;
    }
  };
}

// Initialize the component when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  if (typeof Alpine !== 'undefined') {
    console.log('[GlobalSearch] Alpine.js detected, component ready');
  }
});

// Expose the component factory globally for Alpine.js
window.createGlobalSearchComponent = createGlobalSearchComponent;
console.log('[GlobalSearch] Component registered globally');
