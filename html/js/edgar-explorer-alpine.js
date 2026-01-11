/**
 * EDGAR Explorer - Alpine.js Component
 * List-only results with sidebar filters (Has 10-K, Recent 10-Q ≤90 days)
 */

function createEdgarExplorerComponent() {
  return {
    // State
    searchQuery: '',
    isSearching: false,
    errorMessage: '',
    statusMessage: '',
    showResults: false,
    hasResults: false,

    // Filters
    filters: {
      has10K: false,
      recent10Q: false
    },

    // Results & pagination
    allItems: [],
    filteredItems: [],
    currentPage: 1,
    resultsPerPage: 10,
    totalPages: 1,

    async init() {
      createJsonModal();
      // No query param preloading for now; keep simple like Classification Explorer
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
      this.filteredItems = [];

      try {
        const isCIK = /^\d{1,10}$/.test(this.searchQuery);

        // If CIK, fetch firmographics then fetch detail via company name to get forms
        let detailData = null;
        if (isCIK) {
          const firmo = await apiService.get(`/V3.0/na/company/edgar/firmographics/${encodeURIComponent(this.searchQuery)}`);
          const companyName = firmo?.data?.name || '';
          if (companyName) {
            detailData = await apiService.get(`/V3.0/na/companies/edgar/detail/${encodeURIComponent(companyName)}`);
          } else {
            // Fall back: show firmographics only (no filings)
            detailData = null;
            this.allItems = [];
            this.errorMessage = 'No filings found for provided CIK.';
          }
        } else {
          detailData = await apiService.get(`/V3.0/na/companies/edgar/detail/${encodeURIComponent(this.searchQuery)}`);
        }

        const items = this.transformDetailToItems(detailData);
        this.allItems = items;
        this.applyFilters();
        this.hasResults = this.filteredItems.length > 0;
        this.statusMessage = this.hasResults
          ? `Found ${this.filteredItems.length} filings`
          : 'No filings match the criteria.';

      } catch (error) {
        console.error('[EdgarExplorer] Search error:', error);
        this.errorMessage = `Error: ${error.message}`;
        this.statusMessage = '';
      } finally {
        this.isSearching = false;
      }
    },

    transformDetailToItems(detailData) {
      const items = [];
      const companies = detailData?.data?.companies || {};
      const today = new Date();
      for (const [companyName, info] of Object.entries(companies)) {
        const cik = info?.cik || '';
        const forms = info?.forms || {};
        for (const [accessionKey, form] of Object.entries(forms)) {
          // accessionKey format: YYYY-MM-DD-ACCESSION
          const [y, m, d, acc] = accessionKey.split('-');
          const filingDate = `${y}-${m}-${d}`;
          items.push({
            companyName,
            cik,
            filingType: form?.formType || '',
            filingDate,
            accessionNumber: acc || '',
            documentUrl: form?.filingIndex || '',
            raw: { company: info, form, accessionKey }
          });
        }
      }
      // Sort by date desc
      items.sort((a, b) => new Date(b.filingDate) - new Date(a.filingDate));
      return items;
    },

    applyFilters() {
      let results = [...this.allItems];
      const ninetyDaysAgo = new Date();
      ninetyDaysAgo.setDate(ninetyDaysAgo.getDate() - 90);

      if (this.filters.has10K) {
        results = results.filter(item => (item.filingType || '').toUpperCase().startsWith('10-K'));
      }
      if (this.filters.recent10Q) {
        results = results.filter(item => {
          if (!(item.filingType || '').toUpperCase().startsWith('10-Q')) return false;
          const dt = new Date(item.filingDate);
          return dt >= ninetyDaysAgo;
        });
      }

      this.filteredItems = results;
      this.totalPages = Math.max(1, Math.ceil(this.filteredItems.length / this.resultsPerPage));
      if (this.currentPage > this.totalPages) this.currentPage = 1;
    },

    // Pagination helpers
    getCurrentPageResults() {
      const start = (this.currentPage - 1) * this.resultsPerPage;
      const end = start + this.resultsPerPage;
      return this.filteredItems.slice(start, end);
    },
    getVisiblePages() {
      const maxButtons = 5;
      let start = Math.max(1, this.currentPage - Math.floor(maxButtons / 2));
      let end = Math.min(this.totalPages, start + maxButtons - 1);
      if (end - start + 1 < maxButtons) start = Math.max(1, end - maxButtons + 1);
      const pages = [];
      for (let p = start; p <= end; p++) pages.push(p);
      return pages;
    },
    firstPage() { if (this.currentPage !== 1) this.currentPage = 1; },
    prevPage() { if (this.currentPage > 1) this.currentPage--; },
    nextPage() { if (this.currentPage < this.totalPages) this.currentPage++; },
    lastPage() { if (this.currentPage !== this.totalPages) this.currentPage = this.totalPages; },

    // UI helpers
    getResultsHeadline() {
      if (!this.hasResults || !this.filteredItems.length) return this.statusMessage || 'No results';
      return `${this.filteredItems.length} filings`;
    },
    getResultsRangeLabel() {
      if (!this.hasResults || !this.filteredItems.length) return 'Showing 0-0 of 0';
      const start = (this.currentPage - 1) * this.resultsPerPage + 1;
      const end = Math.min(this.filteredItems.length, start + this.resultsPerPage - 1);
      return `Showing ${start}-${end} of ${this.filteredItems.length}`;
    },
    getActiveFiltersLabel() {
      const active = [];
      if (this.filters.has10K) active.push('Has 10-K');
      if (this.filters.recent10Q) active.push('Recent 10-Q');
      return active.length ? `Filters: ${active.join(', ')}` : 'Filters: none selected';
    },

    viewItemJson(item) {
      showJsonModal(item.raw);
    }
  };
}

// Expose globally
window.createEdgarExplorerComponent = createEdgarExplorerComponent;
console.log('[EdgarExplorer] Component registered globally');
