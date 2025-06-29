// Global Industry Code Search functionality with refinements

// Pagination settings
const RESULTS_PER_PAGE = 10;
let currentPage = 1;
let totalPages = 1;

// Initialize the global search form
function initGlobalSearch() {
  // Main search form handler
  document.getElementById('globalSearchForm').addEventListener('submit', function(event) {
    event.preventDefault();
    
    const searchQuery = document.getElementById('globalSearchInput').value.trim();
    if (!searchQuery) return;
    
    // Switch to results layout
    switchToResultsLayout(searchQuery);
    
    // Get selected filters
    const selectedSources = getSelectedSources();
    
    performGlobalSearch(searchQuery, selectedSources);
  });
  
  // Top search form handler (when already in results view)
  document.getElementById('globalSearchFormTop').addEventListener('submit', function(event) {
    event.preventDefault();
    
    const searchQuery = document.getElementById('globalSearchInputTop').value.trim();
    if (!searchQuery) return;
    
    // Get selected filters
    const selectedSources = getSelectedSources();
    
    // Reset to first page when performing new search
    currentPage = 1;
    
    performGlobalSearch(searchQuery, selectedSources);
  });
  
  // Set up "All Results" filter behavior
  document.getElementById('filterAll').addEventListener('change', function() {
    const isChecked = this.checked;
    
    // Set all other checkboxes to match the "All Results" state
    document.querySelectorAll('input[name="sourceFilter"]:not([value="All"])').forEach(checkbox => {
      checkbox.checked = isChecked;
    });
    
    // Only refilter if we have results
    if (window.lastSearchResults) {
      const searchQuery = document.getElementById('globalSearchInputTop').value.trim();
      const selectedSources = getSelectedSources();
      
      // Reset to first page when changing filters
      currentPage = 1;
      
      displaySearchResults(window.lastSearchResults, selectedSources);
    }
  });
  
  // Keep "All Results" checkbox in sync with individual filters
  document.querySelectorAll('input[name="sourceFilter"]:not([value="All"])').forEach(checkbox => {
    checkbox.addEventListener('change', function() {
      const allCheckboxes = document.querySelectorAll('input[name="sourceFilter"]:not([value="All"])');
      const allChecked = Array.from(allCheckboxes).every(cb => cb.checked);
      const anyChecked = Array.from(allCheckboxes).some(cb => cb.checked);
      
      // Set "All Results" checkbox state
      document.getElementById('filterAll').checked = allChecked;
      
      // Only refilter if we have results
      if (window.lastSearchResults) {
        const searchQuery = document.getElementById('globalSearchInputTop').value.trim();
        const selectedSources = anyChecked ? getSelectedSources() : ["none"];
        
        // Reset to first page when changing filters
        currentPage = 1;
        
        displaySearchResults(window.lastSearchResults, selectedSources);
      }
    });
  });
}

// Get selected source filters
function getSelectedSources() {
  const allCheckboxes = document.querySelectorAll('input[name="sourceFilter"]:not([value="All"])');
  return Array.from(allCheckboxes)
    .filter(input => input.checked)
    .map(input => input.value);
}

// Switch from centered search to results layout
function switchToResultsLayout(searchQuery) {
  // Hide the centered search
  document.getElementById('initialSearchContainer').style.display = 'none';
  
  // Show the results layout
  document.getElementById('searchResultsLayout').style.display = 'block';
  
  // Copy the search query to the top search input
  document.getElementById('globalSearchInputTop').value = searchQuery;
}

// Perform the search using the unified SIC endpoint
function performGlobalSearch(query, selectedSources) {
  console.log("Starting search for:", query);
  console.log("Selected filters:", selectedSources);
  
  // Get host and construct URL
  const host = getActiveHost();
  
  // Get the full URL with proper protocol from companyDnsServers
  let baseUrl = companyDnsServers[host] || 
                (host.includes("localhost") ? `http://${host}` : `https://${host}`);
  
  let url = `${baseUrl}/V3.0/global/sic/description/${encodeURIComponent(query)}`;
  
  // Ensure we don't have double slashes in the URL
  url = url.replace(/([^:]\/)\/+/g, "$1");
  
  console.log(`Fetching from URL: ${url}`);
  
  // Update status
  const statusDiv = document.getElementById('globalSearchStatus');
  statusDiv.textContent = `Searching for "${query}"...`;
  
  // Clear previous results
  const resultsDiv = document.getElementById('globalSearchResults');
  resultsDiv.innerHTML = '';
  
  // Reset pagination
  currentPage = 1;
  
  // Perform the fetch with explicit error handling
  try {
    fetch(url)
      .then(response => {
        console.log("Received response:", response.status);
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        console.log("Received data:", data);
        // Store the full results for filtering
        window.lastSearchResults = data;
        
        // Display filtered results
        displaySearchResults(data, selectedSources);
      })
      .catch(error => {
        console.error('Fetch error:', error);
        statusDiv.textContent = `Error: ${error.message}`;
        resultsDiv.innerHTML = '<div class="no-results">Search failed. Please try again.</div>';
      });
  } catch (error) {
    console.error('Try-catch error:', error);
    statusDiv.textContent = `Error: ${error.message}`;
    resultsDiv.innerHTML = '<div class="no-results">Search failed. Please try again.</div>';
  }
}

// Update filter counts based on data
function updateFilterCounts(data) {
  if (!data || !data.data || !data.data.results) return;
  
  const results = data.data.results;
  const counts = {
    'US SIC': 0,
    'UK SIC': 0,
    'EU NACE': 0,
    'ISIC': 0,
    'Japan SIC': 0
  };
  
  // Count results by source type
  results.forEach(result => {
    if (counts[result.source_type] !== undefined) {
      counts[result.source_type]++;
    }
  });
  
  // Update the count elements
  document.getElementById('countAll').textContent = results.length;
  document.getElementById('countUSSIC').textContent = counts['US SIC'];
  document.getElementById('countUKSIC').textContent = counts['UK SIC'];
  document.getElementById('countEUNACE').textContent = counts['EU NACE'];
  document.getElementById('countISIC').textContent = counts['ISIC'];
  document.getElementById('countJapanSIC').textContent = counts['Japan SIC'];
}

// Update the displaySearchResults function to use the new pagination container

// Display search results with filtering and pagination
function displaySearchResults(data, selectedSources) {
  const statusDiv = document.getElementById('globalSearchStatus');
  const resultsDiv = document.getElementById('globalSearchResults');
  const paginationContainer = document.getElementById('paginationContainer');
  
  // Clear any existing pagination
  paginationContainer.innerHTML = '';
  
  // Update filter counts regardless of filtering
  updateFilterCounts(data);
  
  if (data.code !== 200 || !data.data.results || data.data.results.length === 0) {
    statusDiv.innerHTML = '<h3>No results found.</h3>';
    resultsDiv.innerHTML = '<div class="no-results">No matching industry codes found.</div>';
    return;
  }
  
  // Filter results by selected sources
  const filteredResults = data.data.results.filter(result => 
    selectedSources.includes(result.source_type)
  );
  
  if (filteredResults.length === 0) {
    statusDiv.innerHTML = '<h3>No results match the selected filters.</h3>';
    resultsDiv.innerHTML = '<div class="no-results">No results match the selected filters.</div>';
    return;
  }
  
  // Calculate pagination
  totalPages = Math.ceil(filteredResults.length / RESULTS_PER_PAGE);
  if (currentPage > totalPages) currentPage = 1;
  
  // Get current page results
  const startIndex = (currentPage - 1) * RESULTS_PER_PAGE;
  const endIndex = Math.min(startIndex + RESULTS_PER_PAGE, filteredResults.length);
  const currentPageResults = filteredResults.slice(startIndex, endIndex);
  
  // Update status
  statusDiv.innerHTML = `<h3>Found ${filteredResults.length} of ${data.data.total} results</h3>`;
  
  // Clear and populate results
  resultsDiv.innerHTML = '';
  
  // Create a results fragment to minimize DOM operations
  const fragment = document.createDocumentFragment();
  
  // Add each result to the fragment
  currentPageResults.forEach(result => {
    const card = document.createElement('div');
    card.className = 'explorer-result-card'; // Add explorer- prefix
    
    const header = document.createElement('div');
    header.className = 'explorer-result-header'; // Add explorer- prefix
    
    const titleContainer = document.createElement('div');
    titleContainer.className = 'explorer-result-title-container'; // Add explorer- prefix
    titleContainer.style.display = 'flex';
    titleContainer.style.alignItems = 'center';
    
    const title = document.createElement('div');
    title.className = 'explorer-result-title'; // Add explorer- prefix
    title.textContent = result.description;
    
    const sourceBadge = document.createElement('span');
    sourceBadge.className = 'explorer-source-badge'; // Add explorer- prefix
    sourceBadge.textContent = result.source_type;
    
    // Ensure source badge comes first, then title
    titleContainer.appendChild(sourceBadge);
    titleContainer.appendChild(title);
    
    const codeLabel = document.createElement('div');
    codeLabel.className = 'explorer-result-source'; // Add explorer- prefix
    codeLabel.textContent = `Code: ${result.code}`;
    
    header.appendChild(titleContainer);
    header.appendChild(codeLabel);
    card.appendChild(header);
    
    const details = document.createElement('div');
    details.className = 'explorer-result-details'; // Add explorer- prefix
    
    // Add additional data
    if (result.additional_data) {
      for (const [key, value] of Object.entries(result.additional_data)) {
        if (value) {
          const detailItem = document.createElement('div');
          detailItem.className = 'explorer-detail-item';
          
          const label = document.createElement('span');
          label.className = 'explorer-detail-label';
          label.textContent = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) + ':';
          
          const valueSpan = document.createElement('span');
          valueSpan.className = 'explorer-detail-value'; // Add the new class
          valueSpan.textContent = value;
          valueSpan.title = value; // Add full text as tooltip on hover
          
          detailItem.appendChild(label);
          detailItem.appendChild(valueSpan);
          details.appendChild(detailItem);
        }
      }
    }
    
    card.appendChild(details);
    
    // Add a "View JSON" button to the card
    const viewJsonBtn = document.createElement('button');
    viewJsonBtn.className = 'explorer-view-json-btn';
    viewJsonBtn.textContent = 'View JSON';
    viewJsonBtn.addEventListener('click', () => {
      // Create a JSON object for this result
      const resultJson = {
        source_type: result.source_type,
        code: result.code,
        description: result.description,
        additional_data: result.additional_data || {}
      };
      
      showJsonModal(resultJson);
    });
    
    card.appendChild(viewJsonBtn);
    fragment.appendChild(card);
  });
  
  resultsDiv.appendChild(fragment);
  
  // Add pagination controls if needed - now to the pagination container
  if (totalPages > 1) {
    console.log("Creating pagination controls, total pages:", totalPages);
    const paginationControls = createPaginationControls();
    paginationContainer.innerHTML = ''; // Clear it first
    paginationContainer.appendChild(paginationControls);
    console.log("Pagination container now has", paginationContainer.childNodes.length, "children");
  } else {
    console.log("Not enough results for pagination");
    paginationContainer.innerHTML = ''; // Clear pagination when not needed
  }
}

// Add debugging for pagination issues
function createPaginationControls() {
  console.log("Building pagination UI, current page:", currentPage, "total pages:", totalPages);
  const paginationDiv = document.createElement('div');
  paginationDiv.className = 'explorer-pagination-controls'; // Add explorer- prefix
  
  // Previous button with arrow
  const prevButton = document.createElement('button');
  prevButton.innerHTML = '&larr;'; // Left arrow
  prevButton.disabled = currentPage === 1;
  prevButton.addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage--;
      const selectedSources = getSelectedSources();
      displaySearchResults(window.lastSearchResults, selectedSources);
      
      // Scroll to top of results when changing pages
      document.getElementById('globalSearchResults').scrollTop = 0;
    }
  });
  
  // Add page number buttons
  const maxPageButtons = 5; // Maximum number of page buttons to show
  let startPage = Math.max(1, currentPage - Math.floor(maxPageButtons / 2));
  let endPage = Math.min(totalPages, startPage + maxPageButtons - 1);
  
  // Adjust if we're near the end
  if (endPage - startPage + 1 < maxPageButtons && startPage > 1) {
    startPage = Math.max(1, endPage - maxPageButtons + 1);
  }
  
  paginationDiv.appendChild(prevButton);
  
  // Add first page button if not included in the range
  if (startPage > 1) {
    const firstPageButton = document.createElement('button');
    firstPageButton.textContent = '1';
    firstPageButton.addEventListener('click', () => {
      currentPage = 1;
      const selectedSources = getSelectedSources();
      displaySearchResults(window.lastSearchResults, selectedSources);
      document.getElementById('globalSearchResults').scrollTop = 0;
    });
    paginationDiv.appendChild(firstPageButton);
    
    // Add ellipsis if there's a gap
    if (startPage > 2) {
      const ellipsis = document.createElement('span');
      ellipsis.textContent = '...';
      paginationDiv.appendChild(ellipsis);
    }
  }
  
  // Add page number buttons
  for (let i = startPage; i <= endPage; i++) {
    const pageButton = document.createElement('button');
    pageButton.textContent = i;
    if (i === currentPage) {
      pageButton.classList.add('active');
    }
    pageButton.addEventListener('click', () => {
      currentPage = i;
      const selectedSources = getSelectedSources();
      displaySearchResults(window.lastSearchResults, selectedSources);
      document.getElementById('globalSearchResults').scrollTop = 0;
    });
    paginationDiv.appendChild(pageButton);
  }
  
  // Add last page button if not included in the range
  if (endPage < totalPages) {
    // Add ellipsis if there's a gap
    if (endPage < totalPages - 1) {
      const ellipsis = document.createElement('span');
      ellipsis.textContent = '...';
      paginationDiv.appendChild(ellipsis);
    }
    
    const lastPageButton = document.createElement('button');
    lastPageButton.textContent = totalPages;
    lastPageButton.addEventListener('click', () => {
      currentPage = totalPages;
      const selectedSources = getSelectedSources();
      displaySearchResults(window.lastSearchResults, selectedSources);
      document.getElementById('globalSearchResults').scrollTop = 0;
    });
    paginationDiv.appendChild(lastPageButton);
  }
  
  // Next button with arrow
  const nextButton = document.createElement('button');
  nextButton.innerHTML = '&rarr;'; // Right arrow
  nextButton.disabled = currentPage === totalPages;
  nextButton.addEventListener('click', () => {
    if (currentPage < totalPages) {
      currentPage++;
      const selectedSources = getSelectedSources();
      displaySearchResults(window.lastSearchResults, selectedSources);
      document.getElementById('globalSearchResults').scrollTop = 0;
    }
  });
  
  paginationDiv.appendChild(nextButton);
  
  console.log("Returning pagination controls with", paginationDiv.childNodes.length, "child elements");
  return paginationDiv;
}

// Create modal for JSON preview
function createJsonModal() {
  // Check if modal already exists
  if (document.getElementById('explorerJsonModal')) {
    return;
  }
  
  // Create modal elements
  const modalOverlay = document.createElement('div');
  modalOverlay.className = 'explorer-modal-overlay';
  modalOverlay.id = 'explorerJsonModalOverlay';
  
  const modal = document.createElement('div');
  modal.className = 'explorer-modal';
  modal.id = 'explorerJsonModal';
  
  const modalHeader = document.createElement('div');
  modalHeader.className = 'explorer-modal-header';
  
  const modalTitle = document.createElement('div');
  modalTitle.className = 'explorer-modal-title';
  modalTitle.textContent = 'JSON Data';
  
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
  copyButton.className = 'explorer-copy-json-btn';
  copyButton.innerHTML = 'Copy JSON';
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
}

// Show the JSON modal with the provided data
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
}

// Hide the JSON modal
function hideJsonModal() {
  const modalOverlay = document.getElementById('explorerJsonModalOverlay');
  if (modalOverlay) {
    modalOverlay.style.display = 'none';
  }
  
  // Restore body scrolling
  document.body.style.overflow = '';
}

// Copy JSON to clipboard
function copyJsonToClipboard() {
  const jsonText = document.getElementById('explorerJsonDisplay').textContent;
  
  navigator.clipboard.writeText(jsonText).then(() => {
    const copyButton = document.querySelector('.explorer-copy-json-btn');
    const originalText = copyButton.innerHTML;
    
    copyButton.innerHTML = 'Copied!';
    
    setTimeout(() => {
      copyButton.innerHTML = originalText;
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy text: ', err);
  });
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  console.log("DOM loaded, initializing global search...");
  initGlobalSearch();
});