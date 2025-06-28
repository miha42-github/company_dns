// Host configuration - managed by entrypoint.sh
const companyDnsServers = {
  "localhost:8000": "http://localhost:8000",
  "company-dns.mediumroast.io": "https://company-dns.mediumroast.io"
};

// Default primary host - will be set by entrypoint.sh
const primaryHost = "company-dns.mediumroast.io";

// Helper function to get the correct host
function getActiveHost() {
  // When running in a browser, use the current hostname if it matches one of our servers
  if (typeof window !== 'undefined' && window.location && window.location.hostname) {
    const currentHost = window.location.hostname;
    if (currentHost === "company-dns.mediumroast.io") {
      return "company-dns.mediumroast.io";
    } else if (currentHost === "localhost" || currentHost === "127.0.0.1") {
      return "localhost:8000";
    }
  }
  
  // Otherwise use stored value or default to primary
  return localStorage.getItem('savedHost') || primaryHost;
}

// Initialize the host select dropdown
function initializeHostSelect() {
  const hostSelect = document.getElementById('hostSelect');
  if (!hostSelect) return;
  
  // Clear existing options
  hostSelect.innerHTML = '';
  
  // Add options for each host
  for (const [host, url] of Object.entries(companyDnsServers)) {
    const option = document.createElement('option');
    option.value = host;
    option.text = host;
    option.selected = (host === primaryHost);
    hostSelect.appendChild(option);
  }
  
  // Save to localStorage
  localStorage.setItem('savedHost', primaryHost);
}