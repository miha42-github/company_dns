pub mod catalog;
pub mod client;
pub mod firmographics;

pub use catalog::{CatalogEntry, EdgarCatalog};
pub use client::EdgarClient;
pub use firmographics::build_firmographics;

/// Matches `lib/edgar.py`'s existing pattern for identifying
/// `company_dns` to SEC.gov, per its fair-access User-Agent
/// requirement.
pub const USER_AGENT: &str = "Mediumroast, Inc. company_dns/4.0.0 hello@mediumroast.io";
