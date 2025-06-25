# Query Explorer

## Overview
The Query Explorer is an interactive tool within company_dns that provides a user-friendly interface for testing API endpoints without writing code. It allows researchers, analysts, and developers to quickly query company and industry data through a simple form interface.

## Key Features

### Endpoint Selection
- Access all available company_dns API endpoints through a dropdown menu
- Choose between local and remote hosts
- Test both V2.0 and V3.0 API versions

### Query Construction
- Build proper API requests with the correct parameter formatting
- See the constructed request URL before execution
- Maintain persistent form state between sessions

### Response Visualization
- View formatted JSON responses
- Copy results to clipboard with a single click
- Receive clear error messages when requests fail

### User-Friendly Interface
- Simple, intuitive form layout
- Saved query history between sessions
- Compact design to maximize screen real estate

## How to Use

1. **Select Host**
   - Choose between a local instance (`localhost:8000`) or the Mediumroast hosted instance (`company-dns.mediumroast.io`)

   <!-- Screenshot: Host selection dropdown -->

2. **Select Endpoint**
   - Browse the available API endpoints organized by version and function
   - Endpoints show the parameter pattern that will be replaced by your query

   <!-- Screenshot: Endpoint selection dropdown -->

3. **Enter Query Term**
   - Type your search term, company name, or industry code
   - The query will replace the parameter placeholder in the selected endpoint

   <!-- Screenshot: Query input field -->

4. **Execute Request**
   - Click the "Execute Request" button to send the API request
   - The constructed URL appears in the "Request URL" section

   <!-- Screenshot: Execute button and URL display -->

5. **View Results**
   - JSON response data is displayed in the "Response Data" section
   - Use the "Copy JSON" button to copy the entire response to clipboard

   <!-- Screenshot: Response data area with JSON -->

## Example Queries

### Company Information
- **Query**: `IBM`, `Apple`, `Microsoft`
- **Endpoint**: `/V3.0/global/company/merged/firmographics/{company_name}`
- **Result**: Returns comprehensive firmographic information about the company

### Industry Code Search
- **Query**: `oil`, `retail`, `manufacturing`
- **Endpoint**: `/V3.0/global/sic/description/{sic_desc}`
- **Result**: Returns matching industry codes across all classification systems

### Specific SIC Code Lookup
- **Query**: `7371`, `2911`, `5331`
- **Endpoint**: `/V3.0/na/sic/code/{sic_code}`
- **Result**: Returns detailed information about the specific Standard Industrial Classification code

## Technical Implementation

The Query Explorer is implemented using:
- Vanilla JavaScript for dynamic form handling and API interactions
- Fetch API for making HTTP requests
- LocalStorage for maintaining form state between sessions
- JSON formatting for readable response display

## Usage Tips

- **Parameter Replacement**: Your query term automatically replaces the placeholder (like `{company_name}` or `{sic_desc}`) in the endpoint URL
- **Persistent Queries**: Your last query is saved and will be restored when you return to the page
- **Cross-Origin Requests**: When using the Explorer with remote hosts, be aware of potential CORS limitations
- **URL Encoding**: Special characters and spaces are automatically encoded in your query

The Query Explorer makes API testing accessible to both technical and non-technical users, allowing quick exploration of the company_dns data without writing code.