# Industry Code Explorer

## Overview
The Industry Code Explorer is a tool within company_dns that allows users to search across multiple industry classification systems simultaneously. This unified search experience helps researchers, analysts, and developers identify and compare industrial classifications across different global standards.

## Supported Classification Systems

The Industry Code Explorer supports five major industry classification systems:

| System | Description | Origin |
|--------|-------------|--------|
| US SIC | Standard Industrial Classification | United States |
| UK SIC | Standard Industrial Classification | United Kingdom |
| EU NACE | Statistical Classification of Economic Activities | European Union |
| ISIC | International Standard Industrial Classification | United Nations |
| Japan SIC | Japan Standard Industrial Classification | Japan |

## Key Features

### Unified Search
- Search across all five classification systems simultaneously
- Find matching industry codes based on keywords or descriptions
- Compare equivalent classifications across different systems

### Advanced Results Display
- View results in an organized card layout
- See source system, code, and detailed descriptions
- View additional metadata in a structured grid format

### Filtering Capabilities
- Filter results by classification system
- See counts of matches in each system
- Quickly narrow down results to relevant systems

### JSON Data Access
- View complete JSON data for any result
- Copy JSON to clipboard with one click
- Access all available metadata for each industry code

### User-Friendly Interface
- Pagination controls for large result sets
- Clear visual identification of source systems
- Intuitive filtering options
- Responsive design works on various screen sizes

## How to Use

1. **Enter a Search Term**
   - Type an industry keyword in the search box (e.g., "manufacturing", "oil", "retail")
   - Click the "Search" button or press Enter

   <!-- Screenshot: Initial search interface -->

2. **Review Results**
   - Browse through the matching industry codes across all systems
   - Each result card shows the classification system, code, and description

   <!-- Screenshot: Search results with multiple classification systems -->

3. **Filter if Needed**
   - Use checkboxes on the left to filter by classification system
   - See how many matches exist in each system

   <!-- Screenshot: Filter panel with selected options -->

4. **Examine Details**
   - Each result includes additional metadata like division, group, or class information
   - Click "View JSON" to see the complete structured data

   <!-- Screenshot: JSON viewer modal with data -->

5. **Navigate Large Result Sets**
   - Use pagination controls at the bottom to move through pages of results
   - Results are displayed with 10 items per page for easy browsing

   <!-- Screenshot: Pagination controls -->

## Use Cases

- **Cross-Border Business Analysis**: Compare how a business activity is classified in different countries
- **Market Research**: Identify all relevant industry codes for a particular business domain
- **Regulatory Compliance**: Find the appropriate industry classifications for regulatory filings
- **Economic Research**: Study how different classification systems categorize similar economic activities

## Technical Implementation

The Industry Code Explorer is implemented using modern web technologies:
- Frontend: HTML, CSS, and vanilla JavaScript
- Data retrieval: Fetch API to query the company_dns backend
- Results rendering: Dynamic DOM manipulation for efficient display

## Example Search Terms

For best results, try searching for:
- Broad categories: "retail", "manufacturing", "technology"
- Specific activities: "oil extraction", "software publishing", "financial services"
- Industry jargon: "SaaS", "fintech", "biotech"

The Industry Code Explorer is continuously improved to enhance search functionality and user experience across browsers and devices.