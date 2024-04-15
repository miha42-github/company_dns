function openTab(evt, tabName, tabContent, tabLinks) {
    var i, tabcontent, tablinks;
    tabcontent = document.getElementsByClassName(tabContent);
    for (i = 0; i < tabcontent.length; i++) {
      tabcontent[i].style.display = "none";
    }
    tablinks = document.getElementsByClassName(tabLinks);
    for (i = 0; i < tablinks.length; i++) {
      tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    document.getElementById(tabName).style.display = "block";
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


const endpointsData = {
  "V2.0": {
      "/companies/edgar/detail/": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
      "/companies/edgar/summary/": "Accepts a company search string, returns summary EDGAR  firmographics data for one or more companies.",
      "/companies/edgar/ciks/": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
      "/company/edgar/firmographics/": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
      "/company/wikipedia/firmographics/": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
      "/company/merged/firmographics/": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail.",
      "/sic/description/": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
      "/sic/code/": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
      "/sic/division/": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
      "/sic/industry/": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
      "/sic/major/": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number."
  },
  "V3.0": {
      "/na/companies/edgar/detail/": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
      "/na/companies/edgar/summary/": "Accepts a company search string, returns summary EDGAR  firmographics data for one or more companies.",
      "/na/companies/edgar/ciks/": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
      "/na/company/edgar/firmographics/": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
      "/global/company/wikipedia/firmographics/": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
      "/global/company/merged/firmographics/": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail.",
      "/na/sic/description/": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
      "/na/sic/code/": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
      "/na/sic/division/": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
      "/na/sic/industry/": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
      "/na/sic/major/": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number."
  }
}