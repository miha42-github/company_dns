const companyDnsServers = {
  "localhost:8000": "http://localhost:8000",
  "company-dns.mediumroast.io": "https://company-dns.mediumroast.io"
}

let url = null

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



// Create a new XMLHttpRequest outside the event listener
var xhr = new XMLHttpRequest();

document.getElementById('endpointForm').addEventListener('submit', function(event) {
  // Prevent the form from submitting normally
  event.preventDefault();

  // Clear the queryResults div
  document.getElementById('queryResults').textContent = '';

  // Get the form values
  const host = document.getElementById('hostSelect').value;
  const endpoint = document.getElementById('endpointSelect').value;
  const query = document.getElementById('queryInput').value;

  // Check if the query field is filled in
  if (query.trim() !== '') {
      // Construct the URL
      const url = companyDnsServers[host] + '/' + endpoint + encodeURIComponent(query);

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

  // Reset the form
  event.target.reset();
});