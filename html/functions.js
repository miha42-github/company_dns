function openTab(evt, tabName, tabContentClass, tabLinks) {
    console.log(`Tab switch: ${tabName}, content class: ${tabContentClass}`);
    
    // Hide ALL possible content tabs regardless of their class
    const allTabContents = [
        ...document.getElementsByClassName("explorer-pagecontent"),
        ...document.getElementsByClassName("query-pagecontent"),
        ...document.getElementsByClassName("help-pagecontent")
    ];
    
    console.log(`Found ${allTabContents.length} content tabs to hide`);
    
    for (let i = 0; i < allTabContents.length; i++) {
        allTabContents[i].style.display = "none";
        console.log(`Hiding tab: ${allTabContents[i].id}`);
    }
    
    // Remove active class from all tab buttons
    const tablinks = document.getElementsByClassName(tabLinks);
    for (let i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    
    // Show the selected tab and mark button as active
    const selectedTab = document.getElementById(tabName);
    if (selectedTab) {
        selectedTab.style.display = "block";
        console.log(`Showing tab: ${tabName}`);
    } else {
        console.error(`Tab ${tabName} not found!`);
    }
    
    evt.currentTarget.className += " active";
}

function generateTable(endpointsData, version) {
  // Start table
  let table = `<table>
      <tr>
          <th>Endpoint</th>
          <th>Description</th>
      </tr>`;

  // Loop through each endpoint in the version
  for (let endpoint in endpointsData[version]) {
      table += `
          <tr>
              <td>${version}${endpoint}</td>
              <td>${endpointsData[version][endpoint]}</td>
          </tr>`;
  }

  // End table
  table += `</table>`;

  return table;
}

// Function to copy code examples to clipboard
function copyToClipboard(button) {
  // Get the element to copy from
  let targetId = button.getAttribute('data-copy-target');
  let textToCopy = '';
  
  if (targetId) {
    // For URL copying
    const targetElement = document.getElementById(targetId);
    textToCopy = targetElement.textContent;
  } else {
    // For code block copying (existing functionality)
    const codeBlock = button.previousElementSibling;
    textToCopy = codeBlock.textContent;
  }
  
  navigator.clipboard.writeText(textToCopy).then(() => {
    // Change button text temporarily
    const originalText = button.querySelector('.copy-text').textContent;
    button.querySelector('.copy-text').textContent = 'Copied!';
    
    setTimeout(() => {
      button.querySelector('.copy-text').textContent = originalText;
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy text: ', err);
  });
}

// Function to switch between help tabs
function openHelpTab(evt, tabName) {
  // Hide all tab content
  const tabContents = document.getElementsByClassName('help-tab-content');
  for (let i = 0; i < tabContents.length; i++) {
    tabContents[i].classList.remove('active');
  }
  
  // Remove active class from all tab buttons
  const tabButtons = document.getElementsByClassName('help-tab-button');
  for (let i = 0; i < tabButtons.length; i++) {
    tabButtons[i].classList.remove('active');
  }
  
  // Show the selected tab content and mark button as active
  document.getElementById(tabName).classList.add('active');
  evt.currentTarget.classList.add('active');
}

// Initialize the help section on page load
document.addEventListener('DOMContentLoaded', function() {
  // Ensure first help tab is active by default
  const firstHelpTab = document.querySelector('.help-tab-button');
  if (firstHelpTab) {
    firstHelpTab.classList.add('active');
    const firstTabId = firstHelpTab.getAttribute('onclick').match(/openHelpTab\(event, '(.+?)'\)/)[1];
    document.getElementById(firstTabId).classList.add('active');
  }
});

// Add this function to handle copying the response JSON

function copyResponseToClipboard() {
  const responseElement = document.getElementById('queryResults');
  let textToCopy = '';
  
  // Check if the results contain a pre element (formatted JSON)
  const preElement = responseElement.querySelector('pre');
  if (preElement) {
    textToCopy = preElement.textContent;
  } else {
    textToCopy = responseElement.textContent;
  }
  
  // Only copy if there's content
  if (textToCopy.trim() && !textToCopy.includes('Execute a request to see results')) {
    navigator.clipboard.writeText(textToCopy).then(() => {
      const button = document.getElementById('copyResponseButton');
      const originalText = button.querySelector('.copy-text').textContent;
      button.querySelector('.copy-text').textContent = 'Copied!';
      
      setTimeout(() => {
        button.querySelector('.copy-text').textContent = originalText;
      }, 2000);
    }).catch(err => {
      console.error('Failed to copy text: ', err);
    });
  }
}

// Add this new function specifically for inner tabs
function openInnerTab(evt, tabName, tabContentClass, tabLinks) {
    console.log(`Inner tab switch: ${tabName}, content class: ${tabContentClass}`);
    
    // Only hide tabs of the specified content class
    const tabContents = document.getElementsByClassName(tabContentClass);
    for (let i = 0; i < tabContents.length; i++) {
        tabContents[i].style.display = "none";
    }
    
    // Remove active class from specified tab buttons
    const tablinks = document.getElementsByClassName(tabLinks);
    for (let i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    
    // Show the selected tab and mark button as active
    const selectedTab = document.getElementById(tabName);
    if (selectedTab) {
        selectedTab.style.display = "block";
        console.log(`Showing inner tab: ${tabName}`);
    } else {
        console.error(`Inner tab ${tabName} not found!`);
    }
    
    evt.currentTarget.className += " active";
}