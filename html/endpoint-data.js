/**
 * Endpoint definitions for company_dns API
 * Auto-generated from company_dns.py - DO NOT EDIT MANUALLY
 */

const endpointsData = {
  "V2.0": {
    "/sic/description/{sic_desc}": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
    "/sic/code/{sic_code}": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
    "/sic/division/{division_code}": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
    "/sic/industry/{industry_code}": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
    "/sic/major/{major_code}": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number.",
    "/companies/edgar/detail/{company_name}": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
    "/companies/edgar/summary/{company_name}": "Accepts a company search string, returns summary EDGAR firmographics data for one or more companies.",
    "/companies/edgar/ciks/{company_name}": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
    "/company/edgar/firmographics/{cik_no}": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
    "/company/wikipedia/firmographics/{company_name}": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
    "/company/merged/firmographics/{company_name}": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail."
  },
  "V3.0": {
    "/na/sic/description/{sic_desc}": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string.",
    "/na/sic/code/{sic_code}": "Accepts a string containing a SIC of interest, returns all SICs that matched the full or partial string.",
    "/na/sic/division/{division_code}": "Accepts a string containing a division id of interest, returns the SIC division description that matches the id.",
    "/na/sic/industry/{industry_code}": "Accepts a string containing an industry group number of interest, returns the SIC industry group information that matches the number.",
    "/na/sic/major/{major_code}": "Accepts a string containing a major group number of interest, returns the SIC major group information that matches the number.",
    "/na/companies/edgar/detail/{company_name}": "Accepts a company search string, returns detailed EDGAR firmographics data for one or more companies.",
    "/na/companies/edgar/summary/{company_name}": "Accepts a company search string, returns summary EDGAR firmographics data for one or more companies.",
    "/na/companies/edgar/ciks/{company_name}": "Accepts a company search string of interest, returns a pairing of company names to CIKs.",
    "/na/company/edgar/firmographics/{cik_no}": "Accepts a string with a CIK (Central Index Key) for a company, returns EDGAR firmographics detail for that company.",
    "/global/company/wikipedia/firmographics/{company_name}": "Accepts a string with a company name of interest, returns Wikipedia firmographics detail.",
    "/global/company/merged/firmographics/{company_name}": "Accepts a string containing a company name of interest, returns merged EDGAR and Wikipedia firmographics detail.",
    "/uk/sic/description/{uk_sic_desc}": "Accepts a string containing a UK SIC description of interest, returns all UK SIC descriptions that matched the full or partial string.",
    "/uk/sic/code/{uk_sic_code}": "Accepts a string containing a UK SIC code of interest, returns all UK SICs that matched the full or partial string.",
    "/international/sic/section/{section_code}": "Accepts a string containing a section code, returns data about the matching ISIC section.",
    "/international/sic/division/{division_code}": "Accepts a string containing a division code, returns data about the matching ISIC division.",
    "/international/sic/group/{group_code}": "Accepts a string containing a group code, returns data about the matching ISIC group.",
    "/international/sic/class/{class_code}": "Accepts a string containing a class code, returns data about the matching ISIC class.",
    "/international/sic/description/{class_desc}": "Accepts a string containing a description, returns ISIC classes matching the description.",
    "/eu/sic/section/{section_code}": "Accepts a string containing a section code, returns data about the matching EU SIC (NACE) section.",
    "/eu/sic/division/{division_code}": "Accepts a string containing a division code, returns data about the matching EU SIC (NACE) division.",
    "/eu/sic/group/{group_code}": "Accepts a string containing a group code, returns data about the matching EU SIC (NACE) group.",
    "/eu/sic/class/{class_code}": "Accepts a string containing a class code, returns data about the matching EU SIC (NACE) class.",
    "/eu/sic/description/{class_desc}": "Accepts a string containing a description, returns EU SIC (NACE) classes matching the description.",
    "/japan/sic/division/{division_code}": "Accepts a string containing a division code, returns data about the matching Japan SIC division.",
    "/japan/sic/major_group/{major_group_code}": "Accepts a string containing a major group code, returns data about the matching Japan SIC major group.",
    "/japan/sic/group/{group_code}": "Accepts a string containing a group code, returns data about the matching Japan SIC group.",
    "/japan/sic/industry_group/{industry_code}": "Accepts a string containing an industry code, returns data about the matching Japan SIC industry group.",
    "/japan/sic/description/{industry_desc}": "Accepts a string containing a description, returns Japan SIC industry groups matching the description.",
    "/global/sic/description/{query_string}": "Accepts a string containing a SIC description of interest, returns all SIC descriptions that matched the full or partial string across all SIC systems."
  }
};

const endpoints = {
  "V2.0": {
    "/sic/description/{sic_desc}": "/sic/description/{sic_desc}",
    "/sic/code/{sic_code}": "/sic/code/{sic_code}",
    "/sic/division/{division_code}": "/sic/division/{division_code}",
    "/sic/industry/{industry_code}": "/sic/industry/{industry_code}",
    "/sic/major/{major_code}": "/sic/major/{major_code}",
    "/companies/edgar/detail/{company_name}": "/companies/edgar/detail/{company_name}",
    "/companies/edgar/summary/{company_name}": "/companies/edgar/summary/{company_name}",
    "/companies/edgar/ciks/{company_name}": "/companies/edgar/ciks/{company_name}",
    "/company/edgar/firmographics/{cik_no}": "/company/edgar/firmographics/{cik_no}",
    "/company/wikipedia/firmographics/{company_name}": "/company/wikipedia/firmographics/{company_name}",
    "/company/merged/firmographics/{company_name}": "/company/merged/firmographics/{company_name}"
  },
  "V3.0": {
    "/na/sic/description/{sic_desc}": "/na/sic/description/{sic_desc}",
    "/na/sic/code/{sic_code}": "/na/sic/code/{sic_code}",
    "/na/sic/division/{division_code}": "/na/sic/division/{division_code}",
    "/na/sic/industry/{industry_code}": "/na/sic/industry/{industry_code}",
    "/na/sic/major/{major_code}": "/na/sic/major/{major_code}",
    "/na/companies/edgar/detail/{company_name}": "/na/companies/edgar/detail/{company_name}",
    "/na/companies/edgar/summary/{company_name}": "/na/companies/edgar/summary/{company_name}",
    "/na/companies/edgar/ciks/{company_name}": "/na/companies/edgar/ciks/{company_name}",
    "/na/company/edgar/firmographics/{cik_no}": "/na/company/edgar/firmographics/{cik_no}",
    "/global/company/wikipedia/firmographics/{company_name}": "/global/company/wikipedia/firmographics/{company_name}",
    "/global/company/merged/firmographics/{company_name}": "/global/company/merged/firmographics/{company_name}",
    "/uk/sic/description/{uk_sic_desc}": "/uk/sic/description/{uk_sic_desc}",
    "/uk/sic/code/{uk_sic_code}": "/uk/sic/code/{uk_sic_code}",
    "/international/sic/section/{section_code}": "/international/sic/section/{section_code}",
    "/international/sic/division/{division_code}": "/international/sic/division/{division_code}",
    "/international/sic/group/{group_code}": "/international/sic/group/{group_code}",
    "/international/sic/class/{class_code}": "/international/sic/class/{class_code}",
    "/international/sic/description/{class_desc}": "/international/sic/description/{class_desc}",
    "/eu/sic/section/{section_code}": "/eu/sic/section/{section_code}",
    "/eu/sic/division/{division_code}": "/eu/sic/division/{division_code}",
    "/eu/sic/group/{group_code}": "/eu/sic/group/{group_code}",
    "/eu/sic/class/{class_code}": "/eu/sic/class/{class_code}",
    "/eu/sic/description/{class_desc}": "/eu/sic/description/{class_desc}",
    "/japan/sic/division/{division_code}": "/japan/sic/division/{division_code}",
    "/japan/sic/major_group/{major_group_code}": "/japan/sic/major_group/{major_group_code}",
    "/japan/sic/group/{group_code}": "/japan/sic/group/{group_code}",
    "/japan/sic/industry_group/{industry_code}": "/japan/sic/industry_group/{industry_code}",
    "/japan/sic/description/{industry_desc}": "/japan/sic/description/{industry_desc}",
    "/global/sic/description/{query_string}": "/global/sic/description/{query_string}"
  }
};
