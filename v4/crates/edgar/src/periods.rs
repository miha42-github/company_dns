//! Which quarters `ingest-edgar` pulls (`docs/plans/v4-deployment.md` §3.2).
//!
//! The catalog is a rolling window of quarterly SEC filing indexes. The
//! default is the last two years of *completed* quarters (8), counted back
//! from today: a quarter is only complete once it is over, and the SEC's
//! index for the running quarter keeps growing, so including it would give
//! a catalog that changes under the quarterly rebuild. Explicit ranges may
//! include any quarter the SEC has published.
//!
//! Everything here is pure (the date is passed in) so it is unit-tested
//! without a clock or the network.

use chrono::{Datelike, NaiveDate};
use std::fmt;
use std::path::PathBuf;

/// How many years of quarters the default window covers.
pub const DEFAULT_YEARS: u32 = 2;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Quarter {
    pub year: i32,
    /// 1-4
    pub q: u8,
}

impl Quarter {
    pub fn new(year: i32, q: u8) -> anyhow::Result<Self> {
        if !(1..=4).contains(&q) {
            anyhow::bail!("quarter must be 1-4, got {q}");
        }
        if !(1993..=2200).contains(&year) {
            anyhow::bail!("year {year} is outside EDGAR's range");
        }
        Ok(Self { year, q })
    }

    /// The quarter a date falls in.
    pub fn of(date: NaiveDate) -> Self {
        Self { year: date.year(), q: ((date.month() - 1) / 3 + 1) as u8 }
    }

    /// Parses `2025Q2`, `2025q2`, `2025-Q2` or `2025 2`'s joined form `2025-2`.
    pub fn parse(s: &str) -> anyhow::Result<Self> {
        let t = s.trim().to_ascii_uppercase().replace('-', "");
        let (y, q) = t
            .split_once('Q')
            .ok_or_else(|| anyhow::anyhow!("expected a quarter like 2025Q2, got {s:?}"))?;
        Self::new(y.parse()?, q.parse()?)
    }

    pub fn next(self) -> Self {
        if self.q == 4 { Self { year: self.year + 1, q: 1 } } else { Self { year: self.year, q: self.q + 1 } }
    }

    pub fn prev(self) -> Self {
        if self.q == 1 { Self { year: self.year - 1, q: 4 } } else { Self { year: self.year, q: self.q - 1 } }
    }

    /// Steps back `n` quarters.
    pub fn back(self, n: u32) -> Self {
        (0..n).fold(self, |q, _| q.prev())
    }
}

impl fmt::Display for Quarter {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}Q{}", self.year, self.q)
    }
}

/// Every quarter from `from` to `to` inclusive, oldest first.
pub fn quarters_between(from: Quarter, to: Quarter) -> anyhow::Result<Vec<Quarter>> {
    if from > to {
        anyhow::bail!("--from {from} is after --to {to}");
    }
    let mut out = vec![from];
    while *out.last().unwrap() < to {
        out.push(out.last().unwrap().next());
    }
    Ok(out)
}

/// The most recent quarter that is over as of `today`.
pub fn last_completed(today: NaiveDate) -> Quarter {
    Quarter::of(today).prev()
}

/// What to ingest and where to write it.
#[derive(Debug, PartialEq, Eq)]
pub struct Plan {
    pub quarters: Vec<Quarter>,
    /// `None` = the standard file in the data directory.
    pub out: Option<PathBuf>,
}

pub const USAGE: &str = "usage: ingest-edgar [--years N] [--from 2024Q4] [--to 2026Q3] [--out PATH]\n\
       ingest-edgar <year> <quarter 1-4> [out-path]      (one quarter)\n\
\n\
  no arguments   the last 2 years (8 quarters) of completed quarters\n\
  --years N      the last N years of completed quarters\n\
  --from/--to    an explicit range, inclusive (either may be omitted)\n\
  --out PATH     output file (default: <data dir>/edgar_10x_catalog.feather)";

/// Turns the command line into a [`Plan`]. `today` is injected for tests.
pub fn parse_args(args: &[String], today: NaiveDate) -> anyhow::Result<Plan> {
    // Legacy form: `ingest-edgar 2025 2 [out]`.
    if args.len() >= 2 && args[0].parse::<i32>().is_ok() && !args[0].starts_with('-') {
        let q = Quarter::new(args[0].parse()?, args[1].parse()?)?;
        return Ok(Plan { quarters: vec![q], out: args.get(2).map(PathBuf::from) });
    }

    let (mut years, mut from, mut to, mut out) = (None, None, None, None);
    let mut it = args.iter();
    while let Some(flag) = it.next() {
        let mut value = |name: &str| -> anyhow::Result<String> {
            it.next().cloned().ok_or_else(|| anyhow::anyhow!("{name} needs a value\n{USAGE}"))
        };
        match flag.as_str() {
            "--years" => years = Some(value("--years")?.parse::<u32>()?),
            "--from" => from = Some(Quarter::parse(&value("--from")?)?),
            "--to" => to = Some(Quarter::parse(&value("--to")?)?),
            "--out" => out = Some(PathBuf::from(value("--out")?)),
            other => anyhow::bail!("unknown argument {other:?}\n{USAGE}"),
        }
    }
    if years.is_some() && (from.is_some() || to.is_some()) {
        anyhow::bail!("--years cannot be combined with --from/--to\n{USAGE}");
    }
    if years == Some(0) {
        anyhow::bail!("--years must be at least 1");
    }

    let end = to.unwrap_or_else(|| last_completed(today));
    let span = years.unwrap_or(DEFAULT_YEARS) * 4;
    let start = from.unwrap_or_else(|| end.back(span - 1));
    Ok(Plan { quarters: quarters_between(start, end)?, out })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(y: i32, m: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, day).unwrap()
    }
    fn args(s: &[&str]) -> Vec<String> {
        s.iter().map(|x| x.to_string()).collect()
    }
    fn names(p: &Plan) -> Vec<String> {
        p.quarters.iter().map(|q| q.to_string()).collect()
    }

    #[test]
    fn quarters_parse_and_roll_over_year_ends() {
        assert_eq!(Quarter::parse("2025Q2").unwrap(), Quarter { year: 2025, q: 2 });
        assert_eq!(Quarter::parse("2025-q4").unwrap(), Quarter { year: 2025, q: 4 });
        assert!(Quarter::parse("2025").is_err() && Quarter::parse("2025Q5").is_err() && Quarter::parse("Q2").is_err());
        assert_eq!(Quarter { year: 2025, q: 4 }.next(), Quarter { year: 2026, q: 1 });
        assert_eq!(Quarter { year: 2026, q: 1 }.prev(), Quarter { year: 2025, q: 4 });
        assert_eq!(Quarter::of(d(2026, 10, 4)), Quarter { year: 2026, q: 4 });
        assert_eq!(Quarter::of(d(2026, 3, 31)), Quarter { year: 2026, q: 1 });
        assert_eq!(Quarter::of(d(2026, 4, 1)), Quarter { year: 2026, q: 2 });
    }

    #[test]
    fn default_is_the_last_eight_completed_quarters() {
        // Today is in 2026Q4, which is not over: the window ends at 2026Q3.
        let p = parse_args(&[], d(2026, 10, 4)).unwrap();
        assert_eq!(p.quarters.len(), 8);
        assert_eq!(names(&p).first().unwrap(), "2024Q4");
        assert_eq!(names(&p).last().unwrap(), "2026Q3");
        assert_eq!(p.out, None);
        // The quarterly rebuild runs on the first day of a quarter: the quarter
        // just ended is complete and is the newest in the window.
        let p = parse_args(&[], d(2027, 1, 1)).unwrap();
        assert_eq!((names(&p)[0].as_str(), names(&p)[7].as_str()), ("2025Q1", "2026Q4"));
    }

    #[test]
    fn years_from_and_to_choose_the_window() {
        assert_eq!(parse_args(&args(&["--years", "1"]), d(2026, 10, 4)).unwrap().quarters.len(), 4);
        let p = parse_args(&args(&["--from", "2024Q1", "--to", "2024Q4"]), d(2026, 10, 4)).unwrap();
        assert_eq!(names(&p), ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]);
        // --from alone runs to the last completed quarter; --to alone is 8 back.
        let p = parse_args(&args(&["--from", "2026Q2"]), d(2026, 10, 4)).unwrap();
        assert_eq!(names(&p), ["2026Q2", "2026Q3"]);
        let p = parse_args(&args(&["--to", "2025Q4"]), d(2026, 10, 4)).unwrap();
        assert_eq!((p.quarters.len(), names(&p)[0].as_str()), (8, "2024Q1"));
        let p = parse_args(&args(&["--out", "/tmp/x.feather"]), d(2026, 10, 4)).unwrap();
        assert_eq!(p.out, Some(PathBuf::from("/tmp/x.feather")));
    }

    #[test]
    fn the_old_single_quarter_form_still_works() {
        let p = parse_args(&args(&["2025", "2"]), d(2026, 10, 4)).unwrap();
        assert_eq!(names(&p), ["2025Q2"]);
        let p = parse_args(&args(&["2025", "2", "/tmp/o.feather"]), d(2026, 10, 4)).unwrap();
        assert_eq!(p.out, Some(PathBuf::from("/tmp/o.feather")));
    }

    #[test]
    fn nonsense_is_rejected_with_a_reason() {
        let t = d(2026, 10, 4);
        assert!(parse_args(&args(&["--years", "2", "--from", "2024Q1"]), t).is_err());
        assert!(parse_args(&args(&["--years", "0"]), t).is_err());
        assert!(parse_args(&args(&["--from", "2025Q3", "--to", "2024Q1"]), t).is_err());
        assert!(parse_args(&args(&["--bogus"]), t).is_err());
        assert!(parse_args(&args(&["--from"]), t).is_err());
        assert!(parse_args(&args(&["2025", "9"]), t).is_err());
    }
}
