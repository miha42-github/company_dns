/**
 * Global Industry Code Search - Alpine.js Version
 * Extends ExplorerBase for shared pagination and UI logic
 */

function createGlobalSearchComponent() {
  const base = new ExplorerBase({
    searchContainer: 'industry-initial-search',
    resultsLayout: 'industry-results-layout',
    resultsContainer: 'industry-search-results'
  });
  
  const component = {
    // Industry-specific state (extends ExplorerBase)
    searchQuery: '',
    allResults: [],
    expandedCards: {},
    pageSizes: [10, 25, 50, 100],
    
    // Filter states (Industry-specific)
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
    
    /**
     * Initialize the component
     */
    async init() {
      // Create JSON modal on initialization
      createJsonModal();

      // Load any saved state from URL (query, page, page size, filters)
      this.loadStateFromUrl();

      // Add keyboard navigation support
      document.addEventListener('keydown', (e) => this.handleKeyboard(e));
      console.log('[GlobalSearch] Component initialized with Alpine.js');
      console.log('[GlobalSearch] apiService available:', typeof apiService !== 'undefined');

      // Auto-run search if query present
      if (this.searchQuery) {
        this.performSearch();
      }
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
        this.updateUrlState();
        
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

      this.updateUrlState();
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
      this.updateUrlState();
    },
    
    /**
     * Navigate to page
     */
    /**
     * Change page size (Industry-specific)
     */
    changePageSize(newSize) {
      const size = parseInt(newSize);
      if (!this.pageSizes.includes(size)) return;
      this.resultsPerPage = size;
      this.totalPages = Math.max(1, Math.ceil(this.filteredResults.length / this.resultsPerPage));
      if (this.currentPage > this.totalPages) this.currentPage = this.totalPages;
      this.updateUrlState();
      this.scrollToResults('industry-search-results');
    },
    
    /**
     * Show JSON modal for result
     */
    viewResultJson(result) {
      console.log('[GlobalSearch] viewResultJson called with:', result);
      const resultJson = {
        source_type: result.source_type,
        code: result.code,
        description: result.description,
        additional_data: result.additional_data || {}
      };
      showJsonModal(resultJson);
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
    },

    /**
     * Determine if a description should show a toggle
     */
    shouldShowToggle(result) {
      return (result?.description || '').length > 200;
    },

    /**
     * Get truncated description (collapsible)
     */
    getTruncatedDescription(result) {
      const desc = result?.description || '';
      if (desc.length <= 200) return desc;
      return desc.slice(0, 200) + '...';
    },

    /**
     * Toggle description expansion
     */
    toggleDescription(result) {
      const key = this.getResultKey(result);
      this.expandedCards[key] = !this.expandedCards[key];
    },

    /**
     * Is description expanded
     */
    isExpanded(result) {
      const key = this.getResultKey(result);
      return !!this.expandedCards[key];
    },

    /**
     * Build unique key for a result
     */
    getResultKey(result) {
      return `${result.source_type}-${result.code}`;
    },

    /**
     * Does this result have metadata to show
     */
    hasMetadata(result) {
      const data = result.additional_data || {};
      if (result.source_type === 'UK SIC') {
        return this.hasUkMetadata(result);
      }
      return Object.values(data).some(value => value !== undefined && value !== null && `${value}`.trim() !== '');
    },

    /**
     * UK metadata guard
     */
    hasUkMetadata(result) {
      const data = result.additional_data || {};
      return !!(data.code || data.description || data.section_code || data.division_code || data.group_code || data.class_code);
    },

    /**
     * Source pill class helper
     */
    getSourceClass(source) {
      return {
        'pill-us_sic': source === 'US SIC',
        'pill-uk_sic': source === 'UK SIC',
        'pill-eu_nace': source === 'EU NACE',
        'pill-isic': source === 'ISIC',
        'pill-japan_sic': source === 'Japan SIC'
      };
    },

    /**
     * Results headline (total count)
     */
    /**
     * Active filters label (override base class)
     */
    getActiveFiltersLabel() {
      const active = this.getSelectedSources();
      if (!active.length) return 'Filters: none selected';
      if (active.length === Object.keys(this.filters).length - 1) return 'Filters: all systems';
      return `Filters: ${active.join(', ')}`;
    },

    /**
     * Sync state to URL
     */
    updateUrlState() {
      try {
        const params = new URLSearchParams();
        if (this.searchQuery) params.set('q', this.searchQuery);
        if (this.currentPage > 1) params.set('page', this.currentPage);
        if (this.resultsPerPage && this.resultsPerPage !== 10) params.set('perPage', this.resultsPerPage);
        const active = this.getSelectedSources();
        const allSources = Object.keys(this.filters).filter(f => f !== 'all').length;
        if (active.length && active.length !== allSources) params.set('filters', active.join(','));
        const newUrl = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState({}, '', newUrl);
      } catch (err) {
        console.warn('[GlobalSearch] Failed to update URL state', err);
      }
    },

    /**
     * Load state from URL
     */
    loadStateFromUrl() {
      const params = new URLSearchParams(window.location.search);
      const q = params.get('q');
      const page = parseInt(params.get('page'));
      const per = parseInt(params.get('perPage'));
      const filtersParam = params.get('filters');

      if (q) this.searchQuery = q;
      if (per && this.pageSizes.includes(per)) {
        this.resultsPerPage = per;
      }
      if (page && page > 0) this.currentPage = page;

      if (filtersParam) {
        const active = filtersParam.split(',').map(f => f.trim()).filter(Boolean);
        Object.keys(this.filters).forEach(key => {
          if (key === 'all') return;
          this.filters[key] = active.includes(key);
        });
        this.filters.all = active.length === Object.keys(this.filters).length - 1;
      }
    },

    /**
     * Jump to a page (validated)
     */
    jumpToPageAction() {
      const target = parseInt(this.jumpToPage);
      if (Number.isNaN(target)) return;
      const clamped = Math.min(Math.max(target, 1), this.totalPages);
      this.jumpToPage = clamped;
      this.goToPage(clamped);
    }
  };
  
  // Return the component with base class methods properly merged
  return Object.assign(component, base);
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

/**
 * Create JSON modal for displaying result details
 * Uses vanilla JavaScript - called during Alpine component initialization
 */
function createJsonModal() {
  // Check if modal already exists
  if (document.getElementById('explorerJsonModal')) {
    return;
  }
  
  // Create modal elements
  const modalOverlay = document.createElement('div');
  modalOverlay.className = 'explorer-modal-overlay';
  modalOverlay.id = 'explorerJsonModalOverlay';
  modalOverlay.style.display = 'none'; // Start hidden
  
  const modal = document.createElement('div');
  modal.className = 'explorer-modal';
  modal.id = 'explorerJsonModal';
  
  const modalHeader = document.createElement('div');
  modalHeader.className = 'explorer-modal-header';
  
  const modalTitle = document.createElement('div');
  modalTitle.className = 'explorer-modal-title';
  modalTitle.textContent = 'Result Details (JSON)';
  
  const closeButton = document.createElement('button');
  closeButton.className = 'explorer-modal-close';
  closeButton.innerHTML = '&times;';
  closeButton.addEventListener('click', hideJsonModal);

  modalHeader.appendChild(modalTitle);
  modalHeader.appendChild(closeButton);
  
  const modalContent = document.createElement('div');
  modalContent.className = 'explorer-modal-content';
  
  const jsonDisplay = document.createElement('pre');
  jsonDisplay.className = 'explorer-json-display';
  jsonDisplay.id = 'explorerJsonDisplay';
  
  modalContent.appendChild(jsonDisplay);
  
  const modalFooter = document.createElement('div');
  modalFooter.className = 'explorer-modal-footer';
  
  const copyButton = document.createElement('button');
  copyButton.className = 'explorer-copy-json-btn dns-button';
  copyButton.innerHTML = 'Copy to Clipboard';
  copyButton.addEventListener('click', copyJsonToClipboard);
  
  modalFooter.appendChild(copyButton);
  
  modal.appendChild(modalHeader);
  modal.appendChild(modalContent);
  modal.appendChild(modalFooter);
  
  modalOverlay.appendChild(modal);
  document.body.appendChild(modalOverlay);
  
  // Close modal when clicking outside
  modalOverlay.addEventListener('click', function(event) {
    if (event.target === modalOverlay) {
      hideJsonModal();
    }
  });
  
  console.log('[JSON Modal] Modal created and appended to DOM');
}

/**
 * Show JSON modal with the provided data
 */
function showJsonModal(jsonData) {
  const modalOverlay = document.getElementById('explorerJsonModalOverlay');
  const jsonDisplay = document.getElementById('explorerJsonDisplay');
  
  if (!modalOverlay || !jsonDisplay) {
    createJsonModal();
  }
  
  // Format JSON with indentation
  const formattedJson = JSON.stringify(jsonData, null, 2);
  document.getElementById('explorerJsonDisplay').textContent = formattedJson;
  
  // Show the modal
  document.getElementById('explorerJsonModalOverlay').style.display = 'flex';
  
  // Prevent body scrolling while modal is open
  document.body.style.overflow = 'hidden';
  
  console.log('[JSON Modal] Modal shown with data');
}

/**
 * Hide the JSON modal
 */
function hideJsonModal() {
  const modalOverlay = document.getElementById('explorerJsonModalOverlay');
  if (modalOverlay) {
    modalOverlay.style.display = 'none';
  }
  
  // Restore body scrolling
  document.body.style.overflow = '';
  
  console.log('[JSON Modal] Modal hidden');
}

/**
 * Copy JSON to clipboard
 */
function copyJsonToClipboard() {
  const jsonText = document.getElementById('explorerJsonDisplay').textContent;
  
  navigator.clipboard.writeText(jsonText).then(() => {
    const copyButton = document.querySelector('.explorer-copy-json-btn');
    const originalText = copyButton.textContent;
    copyButton.textContent = 'Copied!';
    copyButton.style.minWidth = '140px';
    copyButton.style.textAlign = 'center';
    setTimeout(() => {
      copyButton.textContent = originalText;
    }, 2000);
    
    console.log('[JSON Modal] JSON copied to clipboard');
  }).catch(err => {
    console.error('[JSON Modal] Failed to copy text:', err);
    alert('Failed to copy to clipboard');
  });
}
