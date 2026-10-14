//! Graceful shutdown: on the stop signal (SIGTERM, which is what Kubernetes sends, or Ctrl-C) keep serving for a short delay so the load balancer can
//! learn the pod is leaving, then stop accepting, close idle connections, let the requests still running finish, and exit. A watchdog ends the wait after
//! a grace time so one stuck request cannot hold a pod up until it is killed.
//!
//! Before this, the server ignored the signal (it is the container's first process, which has no default action for it), so every stopped pod stayed in
//! `Terminating` for the whole grace period (30 s) and was then killed. Two settings, in seconds: `COMPANY_DNS_SHUTDOWN_DELAY_SECS` (default 5, 0 to 60)
//! and `COMPANY_DNS_SHUTDOWN_GRACE_SECS` (default 15, 1 to 120). Their sum must stay under the pod's `terminationGracePeriodSeconds`.

use std::future::Future;
use std::net::SocketAddr;
use std::time::Duration;

use axum::Router;
use tokio::net::TcpListener;
use tokio::sync::oneshot;

pub const DEFAULT_DELAY_SECS: u64 = 5;
pub const DEFAULT_GRACE_SECS: u64 = 15;
const MAX_DELAY_SECS: u64 = 60;
const MAX_GRACE_SECS: u64 = 120;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ShutdownTimes {
    /// How long to keep serving normally after the signal.
    pub delay: Duration,
    /// How long to wait for running requests once draining has begun.
    pub grace: Duration,
}

impl Default for ShutdownTimes {
    fn default() -> Self {
        Self { delay: Duration::from_secs(DEFAULT_DELAY_SECS), grace: Duration::from_secs(DEFAULT_GRACE_SECS) }
    }
}

fn parse_secs(name: &str, value: Option<String>, default: u64, min: u64, max: u64) -> Result<u64, String> {
    let Some(v) = value.map(|v| v.trim().to_string()).filter(|v| !v.is_empty()) else {
        return Ok(default);
    };
    match v.parse::<u64>() {
        Ok(n) if (min..=max).contains(&n) => Ok(n),
        _ => Err(format!("{name} must be a whole number of seconds from {min} to {max}, got {v:?}")),
    }
}

impl ShutdownTimes {
    pub fn parse(get: impl Fn(&str) -> Option<String>) -> Result<Self, String> {
        Ok(Self {
            delay: Duration::from_secs(parse_secs("COMPANY_DNS_SHUTDOWN_DELAY_SECS", get("COMPANY_DNS_SHUTDOWN_DELAY_SECS"), DEFAULT_DELAY_SECS, 0, MAX_DELAY_SECS)?),
            grace: Duration::from_secs(parse_secs("COMPANY_DNS_SHUTDOWN_GRACE_SECS", get("COMPANY_DNS_SHUTDOWN_GRACE_SECS"), DEFAULT_GRACE_SECS, 1, MAX_GRACE_SECS)?),
        })
    }

    pub fn from_env() -> Result<Self, String> {
        Self::parse(|k| std::env::var(k).ok())
    }
}

/// Completes when the process is asked to stop: SIGTERM (Kubernetes, `docker stop`) or SIGINT (Ctrl-C).
pub async fn stop_signal() {
    #[cfg(unix)]
    {
        use tokio::signal::unix::{signal, SignalKind};
        let mut term = signal(SignalKind::terminate()).expect("install the SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {}
            _ = term.recv() => {}
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}

/// Serve `app` on `listener` until `signal` completes, then wait `times.delay`, drain, and return. `Ok(())` both when everything finished and when the grace time ran out.
pub async fn serve<F>(listener: TcpListener, app: Router, times: ShutdownTimes, signal: F) -> std::io::Result<()>
where
    F: Future<Output = ()> + Send + 'static,
{
    let (drain_tx, drain_rx) = oneshot::channel::<()>();
    let (timer_tx, timer_rx) = oneshot::channel::<()>();
    tokio::spawn(async move {
        signal.await;
        tracing::info!("stop signal received: still serving for {} s so the load balancer can drop this pod", times.delay.as_secs());
        tokio::time::sleep(times.delay).await;
        tracing::info!("draining: no new connections; finishing the requests in flight (at most {} s)", times.grace.as_secs());
        let _ = timer_tx.send(());
        let _ = drain_tx.send(());
    });
    let server = async move {
        axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
            .with_graceful_shutdown(async move {
                let _ = drain_rx.await;
            })
            .await
    };
    let watchdog = async move {
        if timer_rx.await.is_ok() {
            tokio::time::sleep(times.grace).await;
        } else {
            std::future::pending::<()>().await;
        }
    };
    tokio::select! {
        result = server => {
            tracing::info!("all requests finished: exiting");
            result
        }
        _ = watchdog => {
            tracing::warn!("requests were still running after {} s: exiting anyway", times.grace.as_secs());
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::routing::get;
    use std::time::Instant;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;

    fn times(delay_ms: u64, grace_ms: u64) -> ShutdownTimes {
        ShutdownTimes { delay: Duration::from_millis(delay_ms), grace: Duration::from_millis(grace_ms) }
    }

    fn router() -> Router {
        Router::new()
            .route("/fast", get(|| async { "ok" }))
            .route("/slow", get(|| async {
                tokio::time::sleep(Duration::from_millis(500)).await;
                "slow done"
            }))
            .route("/stuck", get(|| async {
                tokio::time::sleep(Duration::from_secs(30)).await;
                "never"
            }))
    }

    /// Start the server; returns its address, the signal sender and the join handle of `serve`.
    async fn start(t: ShutdownTimes) -> (SocketAddr, oneshot::Sender<()>, tokio::task::JoinHandle<std::io::Result<()>>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let addr = listener.local_addr().unwrap();
        let (tx, rx) = oneshot::channel::<()>();
        let handle = tokio::spawn(serve(listener, router(), t, async move {
            let _ = rx.await;
        }));
        (addr, tx, handle)
    }

    /// One request on its own connection; the status code, or None if the connection failed.
    async fn get_status(addr: SocketAddr, path: &str) -> Option<u16> {
        let mut s = TcpStream::connect(addr).await.ok()?;
        s.write_all(format!("GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").as_bytes()).await.ok()?;
        let mut buf = String::new();
        s.read_to_string(&mut buf).await.ok()?;
        buf.split_whitespace().nth(1)?.parse().ok()
    }

    #[test]
    fn the_times_default_and_refuse_nonsense() {
        assert_eq!(ShutdownTimes::parse(|_| None), Ok(ShutdownTimes::default()));
        let t = ShutdownTimes::parse(|k| (k == "COMPANY_DNS_SHUTDOWN_DELAY_SECS").then(|| " 0 ".to_string())).unwrap();
        assert_eq!((t.delay.as_secs(), t.grace.as_secs()), (0, 15));
        for (name, bad) in [("COMPANY_DNS_SHUTDOWN_DELAY_SECS", "61"), ("COMPANY_DNS_SHUTDOWN_DELAY_SECS", "-1"), ("COMPANY_DNS_SHUTDOWN_GRACE_SECS", "0"), ("COMPANY_DNS_SHUTDOWN_GRACE_SECS", "soon")] {
            let e = ShutdownTimes::parse(|k| (k == name).then(|| bad.to_string())).unwrap_err();
            assert!(e.contains(name) && e.contains(bad), "{e}");
        }
    }

    #[tokio::test]
    async fn a_request_in_flight_finishes_and_then_the_server_exits() {
        let (addr, tx, handle) = start(times(0, 5000)).await;
        let slow = tokio::spawn(async move { get_status(addr, "/slow").await });
        tokio::time::sleep(Duration::from_millis(100)).await;
        let started = Instant::now();
        tx.send(()).unwrap();
        assert_eq!(slow.await.unwrap(), Some(200), "the running request was finished, not cut");
        handle.await.unwrap().unwrap();
        assert!(started.elapsed() < Duration::from_secs(3), "{:?}", started.elapsed());
        assert_eq!(get_status(addr, "/fast").await, None, "nothing listens any more");
    }

    #[tokio::test]
    async fn it_keeps_serving_during_the_delay_then_stops() {
        let (addr, tx, handle) = start(times(600, 5000)).await;
        tx.send(()).unwrap();
        tokio::time::sleep(Duration::from_millis(150)).await;
        assert_eq!(get_status(addr, "/fast").await, Some(200), "still serving while the load balancer catches up");
        handle.await.unwrap().unwrap();
        assert_eq!(get_status(addr, "/fast").await, None);
    }

    #[tokio::test]
    async fn a_stuck_request_does_not_hold_the_server_past_the_grace_time() {
        let (addr, tx, handle) = start(times(0, 400)).await;
        let _stuck = tokio::spawn(async move { get_status(addr, "/stuck").await });
        tokio::time::sleep(Duration::from_millis(100)).await;
        let started = Instant::now();
        tx.send(()).unwrap();
        handle.await.unwrap().unwrap();
        assert!(started.elapsed() < Duration::from_secs(3), "gave up after the grace time, not after the request: {:?}", started.elapsed());
    }

    #[tokio::test]
    async fn an_idle_keep_alive_connection_does_not_delay_the_exit() {
        let (addr, tx, handle) = start(times(0, 5000)).await;
        let mut s = TcpStream::connect(addr).await.unwrap();
        s.write_all(b"GET /fast HTTP/1.1\r\nHost: x\r\n\r\n").await.unwrap();
        let mut buf = [0u8; 512];
        let n = s.read(&mut buf).await.unwrap();
        assert!(String::from_utf8_lossy(&buf[..n]).starts_with("HTTP/1.1 200"));
        // the connection is now idle but open (keep-alive), as a proxy leaves it
        let started = Instant::now();
        tx.send(()).unwrap();
        handle.await.unwrap().unwrap();
        assert!(started.elapsed() < Duration::from_secs(2), "{:?}", started.elapsed());
    }
}
