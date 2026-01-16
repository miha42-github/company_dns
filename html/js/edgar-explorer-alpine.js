/**
 * EDGAR Explorer - Alpine.js Component
 */

function createEdgarExplorerComponent() {
  return {
    // Pagination state
    currentPage: 1,
    resultsPerPage: 10,
    totalPages: 1,
    
    // UI state
    isSearching: false,
    hasResults: false,
    errorMessage: '',
    statusMessage: '',
    showResults: false,
    
    // EDGAR-specific state
    searchQuery: '',
    allItems: [],
    filteredResults: [],
    filters: {
      has10K: false,
      recent10Q: false,
      division: '',
      fiscalYearEnd: ''
    },
    availableDivisions: [],
    availableFiscalYearEnds: [],

    async init() {
      createJsonModal();
      this.loadStateFromUrl();
      document.addEventListener('keydown', (e) => this.handleKeyboard(e));
      console.log('[EdgarExplorer] Initialized');
    },

    async performSearch() {
      this.searchQuery = (this.searchQuery || '').trim();
      if (!this.searchQuery) return;
      this.isSearching = true;
      this.errorMessage = '';
      this.statusMessage = `Searching EDGAR for "${this.searchQuery}"...`;
      this.showResults = true;
      this.hasResults = false;
      this.currentPage = 1;
      this.allItems = [];
      this.filteredResults = [];

      try {
        const isCIK = /^\d{1,10}$/.test(this.searchQuery);
        const edgarTimeout = 60000; // 60 seconds - summary endpoint should be much faster (SQLite cache only)

        // Use summary endpoint for faster results (SQLite cache only, no REST calls)
        let summaryData = null;
        if (isCIK) {
          const firmo = await apiService.get(`/V3.0/na/company/edgar/firmographics/${encodeURIComponent(this.searchQuery)}`, { timeout: edgarTimeout });
          const companyName = firmo?.data?.name || '';
          if (companyName) {
            summaryData = await apiService.get(`/V3.0/na/companies/edgar/summary/${encodeURIComponent(companyName)}`, { timeout: edgarTimeout });
          } else {
            // Fall back: show firmographics only (no filings)
            summaryData = null;
            this.allItems = [];
            this.errorMessage = 'No filings found for provided CIK.';
          }
        } else {
          summaryData = await apiService.get(`/V3.0/na/companies/edgar/summary/${encodeURIComponent(this.searchQuery)}`, { timeout: edgarTimeout });
        }

        const items = this.transformSummaryToItems(summaryData);
        this.allItems = items;
        this.applyFilters();
        this.hasResults = this.filteredResults.length > 0;
        this.statusMessage = this.hasResults
          ? `Found ${this.filteredResults.length} companies with filings`
          : 'No companies found in database.';
        // Scroll to results after search
        this.scrollToResults('edgar-search-results');

      } catch (error) {
        console.error('[EdgarExplorer] Search error:', error);
        this.errorMessage = `Error: ${error.message}`;
        this.statusMessage = '';
      } finally {
        this.isSearching = false;
      }
    },

    transformSummaryToItems(summaryData) {
      const items = [];
      const companies = summaryData?.data?.companies || {};

      for (const [companyName, info] of Object.entries(companies)) {
        const cik = info?.cik || '';
        const forms = info?.forms || {};
        
        // Build list of recent forms (10-K and 10-Q)
        const recentForms = [];
        const formsByType = { '10-K': [], '10-Q': [] };
        
        for (const [formKey, form] of Object.entries(forms)) {
          const [y, m, d] = formKey.split('-');
          const filingDate = `${y}-${m}-${d}`;
          const formType = (form?.formType || '').toUpperCase();
          
          if (formType.startsWith('10-K') || formType.startsWith('10-Q')) {
            recentForms.push({
              type: formType,
              date: filingDate,
              url: form?.filingIndex || '',
              key: formKey
            });
            
            // Track by type for quick access
            const baseType = formType.startsWith('10-K') ? '10-K' : '10-Q';
            formsByType[baseType].push({
              type: formType,
              date: filingDate,
              url: form?.filingIndex || '',
              key: formKey
            });
          }
        }
        
        // Sort forms by date descending
        recentForms.sort((a, b) => new Date(b.date) - new Date(a.date));
        
        // Get latest 10-K and 10-Q
        let latest10K = null;
        let latest10Q = null;
        
        if (formsByType['10-K'].length > 0) {
          formsByType['10-K'].sort((a, b) => new Date(b.date) - new Date(a.date));
          latest10K = formsByType['10-K'][0];
        }
        
        if (formsByType['10-Q'].length > 0) {
          formsByType['10-Q'].sort((a, b) => new Date(b.date) - new Date(a.date));
          latest10Q = formsByType['10-Q'][0];
          
          // Check if recent (within 90 days)
          const ninetyDaysAgo = new Date();
          ninetyDaysAgo.setDate(ninetyDaysAgo.getDate() - 90);
          latest10Q.isRecent = new Date(latest10Q.date) >= ninetyDaysAgo;
        }

        // Build EDGAR URLs for this company
        const edgarUrls = this.buildEdgarUrls(cik);
        
        // Create one item per company
        items.push({
          companyName,
          cik,
          latest10K,
          latest10Q,
          recentForms: recentForms.slice(0, 10), // Show up to 10 most recent forms
          totalForms: Object.keys(forms).length,
          edgarUrls, // Add URLs object
          raw: info
        });
      }
      
      // Sort by company name
      items.sort((a, b) => a.companyName.localeCompare(b.companyName));
      return items;
    },

    buildEdgarUrls(cik) {
      // Pad CIK to 10 digits as per SEC format
      const paddedCik = String(cik).padStart(10, '0');
      
      return {
        browse: `https://www.sec.gov/cgi-bin/browse-edgar?CIK=${cik}&action=getcompany`,
        facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK${paddedCik}.json`,
        issuerTransactions: `https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK=${cik}`,
        ownerTransactions: `https://www.sec.gov/cgi-bin/own-disp?action=getowner&CIK=${cik}`
      };
    },

    applyFilters() {
      let results = [...this.allItems];
      
      // For summary data, we filter by presence of filing types
      if (this.filters.has10K) {
        results = results.filter(item => item.latest10K);
      }
      if (this.filters.recent10Q) {
        results = results.filter(item => item.latest10Q && item.latest10Q.isRecent);
      }

      this.filteredResults = results;
      this.updateFilterOptions();
      this.totalPages = Math.max(1, Math.ceil(this.filteredResults.length / this.resultsPerPage));
      if (this.currentPage > this.totalPages) this.currentPage = 1;
    },

    updateFilterOptions() {
      // No additional filter discovery needed for company-level summary data
      this.availableDivisions = [];
      this.availableFiscalYearEnds = [];
    },

    // Pagination helpers
    getCurrentPageResults() {
      const start = (this.currentPage - 1) * this.resultsPerPage;
      const end = start + this.resultsPerPage;
      return this.filteredResults.slice(start, end);
    },
    /**
     * Active filters label (override base class)
     */
    getActiveFiltersLabel() {
      const active = [];
      if (this.filters.has10K) active.push('Has 10-K');
      if (this.filters.recent10Q) active.push('Recent 10-Q');
      return active.length ? `Filters: ${active.join(', ')}` : 'Filters: none selected';
    },

    viewItemJson(item) {
      showJsonModal(item.raw);
    },

    /**
     * Scroll to results container after pagination
     */
    scrollToResults() {
      const resultsDiv = document.getElementById('edgar-search-results');
      if (resultsDiv) {
        resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    },

    /**
     * Sync state to URL for bookmarkable searches
     */
    updateUrlState() {
      try {
        const params = new URLSearchParams();
        if (this.searchQuery) params.set('q', this.searchQuery);
        if (this.currentPage > 1) params.set('page', this.currentPage);
        if (this.resultsPerPage && this.resultsPerPage !== 10) params.set('perPage', this.resultsPerPage);
        
        // Add active filters
        const activeFilters = [];
        if (this.filters.has10K) activeFilters.push('has10K');
        if (this.filters.recent10Q) activeFilters.push('recent10Q');
        if (this.filters.division) activeFilters.push(`division:${this.filters.division}`);
        if (this.filters.fiscalYearEnd) activeFilters.push(`fye:${this.filters.fiscalYearEnd}`);
        
        if (activeFilters.length) params.set('filters', activeFilters.join(','));
        
        const newUrl = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState({}, '', newUrl);
      } catch (err) {
        console.warn('[EdgarExplorer] Failed to update URL state', err);
      }
    },

    /**
     * Load state from URL parameters
     */
    loadStateFromUrl() {
      try {
        const params = new URLSearchParams(window.location.search);
        const q = params.get('q');
        const page = parseInt(params.get('page'));
        const per = parseInt(params.get('perPage'));
        const filtersParam = params.get('filters');

        if (q) this.searchQuery = q;
        if (per && [10, 25, 50, 100].includes(per)) { // Valid page sizes
          this.resultsPerPage = per;
        }
        if (page && page > 0) this.currentPage = page;

        if (filtersParam) {
          const filterParts = filtersParam.split(',').map(f => f.trim());
          filterParts.forEach(filter => {
            if (filter === 'has10K') this.filters.has10K = true;
            else if (filter === 'recent10Q') this.filters.recent10Q = true;
            else if (filter.startsWith('division:')) this.filters.division = filter.substring(9);
            else if (filter.startsWith('fye:')) this.filters.fiscalYearEnd = filter.substring(4);
          });
        }
      } catch (err) {
        console.warn('[EdgarExplorer] Failed to load URL state', err);
      }
    },

    // ========== Pagination Methods ==========
    firstPage() {
      if (this.currentPage !== 1) {
        this.currentPage = 1;
        this.updateUrlState?.();
        this.scrollToResults();
      }
    },
    prevPage() {
      if (this.currentPage > 1) {
        this.currentPage--;
        this.updateUrlState?.();
        this.scrollToResults();
      }
    },
    nextPage() {
      if (this.currentPage < this.totalPages) {
        this.currentPage++;
        this.updateUrlState?.();
        this.scrollToResults();
      }
    },
    lastPage() {
      if (this.currentPage !== this.totalPages) {
        this.currentPage = this.totalPages;
        this.updateUrlState?.();
        this.scrollToResults();
      }
    },
    goToPage(pageNum) {
      if (pageNum >= 1 && pageNum <= this.totalPages) {
        this.currentPage = pageNum;
        this.updateUrlState?.();
        this.scrollToResults();
      }
    },

    // ========== UI Helpers ==========
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
    },

    getResultsHeadline() {
      if (!this.hasResults) {
        return this.statusMessage || 'No results';
      }
      return `${this.filteredResults?.length || 0} results`;
    },

    getResultsRangeLabel() {
      if (!this.hasResults || !this.filteredResults?.length) {
        return 'Showing 0-0 of 0';
      }
      const start = (this.currentPage - 1) * this.resultsPerPage + 1;
      const end = Math.min(this.filteredResults.length, start + this.resultsPerPage - 1);
      return `Showing ${start}-${end} of ${this.filteredResults.length}`;
    },

    getCurrentPageResults() {
      const start = (this.currentPage - 1) * this.resultsPerPage;
      const end = start + this.resultsPerPage;
      return this.filteredResults.slice(start, end);
    },

    // ========== Navigation & Scroll ==========
    handleKeyboard(event) {
      if (!this.showResults || !this.filteredResults?.length) return;
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
    },

    scrollToResults() {
      const resultsDiv = document.getElementById('edgar-search-results');
      if (resultsDiv) {
        resultsDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  };
}

// Expose globally
window.createEdgarExplorerComponent = createEdgarExplorerComponent;
console.log('[EdgarExplorer] Component registered globally');
