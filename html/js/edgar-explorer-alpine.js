/**
 * EDGAR Explorer - Alpine.js Component
 * Extends ExplorerBase for shared pagination and UI logic
 */

function createEdgarExplorerComponent() {
  const base = new ExplorerBase({
    searchContainer: 'edgar-initial-search',
    resultsLayout: 'edgar-results-layout',
    resultsContainer: 'edgar-search-results'
  });
  
  return {
    ...base,
    // EDGAR-specific state (extends ExplorerBase)
    searchQuery: '',
    hasResults: false,
    filteredResults: [],

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
      this.filteredResults = [];

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
        this.hasResults = this.filteredResults.length > 0;
        this.statusMessage = this.hasResults
          ? `Found ${this.filteredResults.length} filings`
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

      const computeLatest = (forms) => {
        let latest10K = null;
        let latest10Q = null;
        const ninetyDaysAgo = new Date();
        ninetyDaysAgo.setDate(ninetyDaysAgo.getDate() - 90);
        for (const [key, f] of Object.entries(forms || {})) {
          const [y, m, d] = key.split('-');
          const dt = new Date(`${y}-${m}-${d}`);
          const type = (f?.formType || '').toUpperCase();
          if (type.startsWith('10-K')) {
            if (!latest10K || dt > new Date(latest10K.date)) {
              latest10K = { date: `${y}-${m}-${d}`, url: f?.filingIndex || '', accessionNumber: key.split('-')[3] || '' };
            }
          }
          if (type.startsWith('10-Q')) {
            const candidate = { date: `${y}-${m}-${d}`, url: f?.filingIndex || '', accessionNumber: key.split('-')[3] || '' };
            if (!latest10Q || dt > new Date(latest10Q.date)) {
              latest10Q = candidate;
            }
          }
        }
        if (latest10Q) {
          latest10Q.isRecent = new Date(latest10Q.date) >= ninetyDaysAgo;
        }
        return { latest10K, latest10Q };
      };

      for (const [companyName, info] of Object.entries(companies)) {
        const firmo = info?.data || info; // unwrap if wrapped
        const cik = firmo?.cik || '';
        const forms = info?.forms || {};
        const { latest10K, latest10Q } = computeLatest(forms);

        for (const [accessionKey, form] of Object.entries(forms)) {
          const [y, m, d, acc] = accessionKey.split('-');
          const filingDate = `${y}-${m}-${d}`;
          items.push({
            companyName,
            cik,
            filingType: form?.formType || '',
            filingDate,
            accessionNumber: acc || '',
            documentUrl: form?.filingIndex || '',
            raw: { company: info, form, accessionKey },
            latest10K,
            latest10Q,
            sic: {
              code: firmo?.sic || '',
              description: firmo?.sicDescription || '',
              division: firmo?.division || '',
              divisionDescription: firmo?.divisionDescription || '',
              majorGroup: firmo?.majorGroup || '',
              majorGroupDescription: firmo?.majorGroupDescription || '',
              industryGroup: firmo?.industryGroup || '',
              industryGroupDescription: firmo?.industryGroupDescription || ''
            },
            filerCategory: firmo?.category || '',
            fiscalYearEnd: firmo?.fiscalYearEnd || '',
            location: {
              city: firmo?.city || '',
              stateProvince: firmo?.stateProvince || '',
              zipPostal: firmo?.zipPostal || '',
              address: firmo?.address || ''
            },
            ticker: Array.isArray(firmo?.tickers) ? firmo.tickers[1] || '' : '',
            exchange: Array.isArray(firmo?.exchanges) ? firmo.exchanges[0] || '' : ''
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
      if (this.filters.division) {
        results = results.filter(item => item.sic.division === this.filters.division);
      }
      if (this.filters.fiscalYearEnd) {
        results = results.filter(item => this.formatFYE(item.fiscalYearEnd) === this.filters.fiscalYearEnd);
      }

      this.filteredResults = results;
      this.updateFilterOptions();
      this.totalPages = Math.max(1, Math.ceil(this.filteredResults.length / this.resultsPerPage));
      if (this.currentPage > this.totalPages) this.currentPage = 1;
    },

    updateFilterOptions() {
      // Discover unique divisions and FYE from filtered results
      const divisionSet = new Set();
      const fyeSet = new Set();
      this.filteredResults.forEach(item => {
        if (item.sic.division) divisionSet.add(item.sic.division);
        if (item.fiscalYearEnd) fyeSet.add(this.formatFYE(item.fiscalYearEnd));
      });
      this.availableDivisions = Array.from(divisionSet).sort();
      this.availableFiscalYearEnds = Array.from(fyeSet).sort();
    },

    formatFYE(fyeString) {
      // Convert "MMDD" or "MM/DD" to "MM/YY" format with current year
      if (!fyeString) return '';
      const cleaned = fyeString.replace(/\D/g, '');
      if (cleaned.length < 4) return fyeString;
      const mm = cleaned.substring(0, 2);
      const dd = cleaned.substring(2, 4);
      const yy = new Date().getFullYear().toString().slice(-2);
      return `${mm}/${yy}`;
    },

    displayFYE(fyeString) {
      // For display in the UI, use MM/DD format
      if (!fyeString) return '';
      const cleaned = fyeString.replace(/\D/g, '');
      if (cleaned.length < 4) return fyeString;
      const mm = cleaned.substring(0, 2);
      const dd = cleaned.substring(2, 4);
      return `${mm}/${dd}`;
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
    }
  };
}

// Expose globally
window.createEdgarExplorerComponent = createEdgarExplorerComponent;
console.log('[EdgarExplorer] Component registered globally');
