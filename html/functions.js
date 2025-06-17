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