const companyDnsServers = {
  "localhost:8000": "http://localhost:8000",
  "company-dns.mediumroast.io": "https://company-dns.mediumroast.io"
}

let url = null

// Save form state to localStorage
function saveFormState() {
  const host = document.getElementById('hostSelect').value;
  const endpoint = document.getElementById('endpointSelect').value;
  const query = document.getElementById('queryInput').value;
  
  localStorage.setItem('savedHost', host);
  localStorage.setItem('savedEndpoint', endpoint);
  localStorage.setItem('savedQuery', query);
}

// Load form state from localStorage
function loadFormState() {
  const hostSelect = document.getElementById('hostSelect');
  const endpointSelect = document.getElementById('endpointSelect');
  const queryInput = document.getElementById('queryInput');
  
  // Set values from localStorage if they exist
  if (localStorage.getItem('savedHost')) {
    hostSelect.value = localStorage.getItem('savedHost');
  }
  
  // Populate endpoints first before trying to select one
  populateEndpoints();
  
  if (localStorage.getItem('savedEndpoint')) {
    endpointSelect.value = localStorage.getItem('savedEndpoint');
  }
  
  if (localStorage.getItem('savedQuery')) {
    queryInput.value = localStorage.getItem('savedQuery');
  }
}

function populateEndpoints() {
  // Get the select element
  const endpointSelect = document.getElementById('endpointSelect');
  
  // Clear any existing options
  endpointSelect.innerHTML = '';

  // Iterate over the endpoints object
  for (const version in endpoints) {
    if (endpoints.hasOwnProperty(version)) {
      for (const friendlyName in endpoints[version]) {
        if (endpoints[version].hasOwnProperty(friendlyName)) {
          // Create a new option element
          const option = document.createElement('option');
          const endpoint = endpoints[version][friendlyName];

          // Set the value and text of the option
          option.value = version + endpoint;
          option.text = version + ' - ' + friendlyName;

          // Add the option to the select element
          endpointSelect.appendChild(option);
        }
      }
    }
  }
}

// Add event listeners to form fields to save state on change
function setupFormStateListeners() {
  document.getElementById('hostSelect').addEventListener('change', saveFormState);
  document.getElementById('endpointSelect').addEventListener('change', saveFormState);
  document.getElementById('queryInput').addEventListener('input', saveFormState);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
  // First populate endpoints
  populateEndpoints();
  
  // Then load saved state
  loadFormState();
  
  // Set up listeners for form changes
  setupFormStateListeners();
});

document.getElementById('endpointForm').addEventListener('submit', function(event) {
  // Prevent the form from submitting normally
  event.preventDefault();

  // Clear the queryResults div
  document.getElementById('queryResults').textContent = '';

  // Get the form values
  const host = document.getElementById('hostSelect').value;
  const endpoint = document.getElementById('endpointSelect').value;
  const query = document.getElementById('queryInput').value;

  // Save form state
  saveFormState();

  // Check if the query field is filled in
  if (query.trim() !== '') {
    // Find the parameter pattern like {class_desc} or {sic_desc}
    const paramPattern = /{[^}]+}/;
    
    // Replace the parameter placeholder with the actual query value
    // This completely removes the {param} and puts the query in its place
    const cleanEndpoint = endpoint.replace(paramPattern, query);
    
    // Construct the URL
    const url = `${companyDnsServers[host]}/${cleanEndpoint}`;
    
    // Update the div with the URL
    document.getElementById('queryUrl').textContent = url;

    // Send the request over the network
    fetch(url)
      .then(response => {
        if (!response.ok) { // analyze HTTP response status
          throw new Error(`HTTP error! status: ${response.status}`);
        } else { // show the result
          return response.json();
        }
      })
      .then(data => {
        const formattedJson = JSON.stringify(data, null, 3); // format JSON
        document.getElementById('queryResults').innerHTML = `<pre>${formattedJson}</pre>`; // display in div
      })
      .catch(e => {
        console.error('Fetch failed', e);
        document.getElementById('queryResults').textContent = 'Fetch failed: ' + e.message;
      });
  }
});