# Changelog

All notable changes to this project are documented here.

The format is based on Keep a Changelog and this project adheres to Semantic Versioning.

## [3.1.0]
The V3.1.0 release of `company_dns` brings significant UI improvements to enhance usability and functionality:

1. Renamed sections to "Industry Code Explorer" and "Query Explorer" for consistent terminology
2. Fixed cross-browser compatibility issues affecting Chrome and Safari
3. Improved search results display with horizontal detail layout
4. Added JSON viewer modal for search results with copy capability
5. More compact layout for the Query Explorer to maximize screen real estate
6. Enhanced pagination controls and scroll behavior
7. Added proper DOCTYPE declaration to ensure modern rendering mode

## [3.0.0]
The V3.0.0 release of `company_dns` is a significant update to the service. The primary changes are:

1. Shift from Flask to Starlette with Uvicorn
2. Automated monthly container builds from the main branch using GitHub Actions
3. Simplification of code structure with streamlined Docker and service control script
4. Vastly improved embedded help with a query console to test queries
