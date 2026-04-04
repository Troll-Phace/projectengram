use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Instant;

use tauri::async_runtime::Receiver;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Default port the Python sidecar listens on.
pub const SIDECAR_PORT: u16 = 9721;

/// Number of health-check attempts before giving up.
const HEALTH_RETRIES: u32 = 10;

/// Milliseconds between each health-check attempt.
const HEALTH_INTERVAL_MS: u64 = 500;

/// Maximum automatic restarts within the restart window before giving up.
const MAX_RESTARTS: u32 = 3;

/// Time window (seconds) in which restart count is tracked.
const RESTART_WINDOW_SECS: u64 = 30;

/// Managed state that holds the sidecar child process handle and lifecycle flags.
pub struct SidecarState {
    pub child: Mutex<Option<CommandChild>>,
    pub port: u16,
    pub shutting_down: AtomicBool,
}

impl Default for SidecarState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            port: SIDECAR_PORT,
            shutting_down: AtomicBool::new(false),
        }
    }
}

/// Spawn the engram-sidecar binary as a child process.
///
/// Returns the event receiver (for stdout/stderr/termination) and the child handle.
pub fn spawn_sidecar(
    app: &AppHandle,
    port: u16,
) -> Result<(Receiver<CommandEvent>, CommandChild), String> {
    let sidecar_command = app
        .shell()
        .sidecar("binaries/engram-sidecar")
        .map_err(|e| format!("Failed to create sidecar command: {e}"))?;

    sidecar_command
        .args(["--port", &port.to_string()])
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar process: {e}"))
}

/// Poll the sidecar health endpoint with retries.
///
/// Attempts up to `HEALTH_RETRIES` times, sleeping `HEALTH_INTERVAL_MS` between
/// each attempt. Returns `Ok(())` once a 2xx response is received, or `Err` with
/// a descriptive message after all retries are exhausted.
pub async fn health_check(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/api/health");

    for attempt in 1..=HEALTH_RETRIES {
        match reqwest::get(&url).await {
            Ok(resp) if resp.status().is_success() => {
                log::info!("Sidecar health check passed on attempt {attempt}");
                return Ok(());
            }
            Ok(resp) => {
                log::warn!(
                    "Sidecar health check attempt {attempt}/{HEALTH_RETRIES}: unexpected status {}",
                    resp.status()
                );
            }
            Err(e) => {
                log::warn!("Sidecar health check attempt {attempt}/{HEALTH_RETRIES}: {e}");
            }
        }

        if attempt < HEALTH_RETRIES {
            tokio::time::sleep(std::time::Duration::from_millis(HEALTH_INTERVAL_MS)).await;
        }
    }

    Err(format!(
        "Sidecar health check failed after {HEALTH_RETRIES} attempts on port {port}"
    ))
}

/// Monitor the sidecar process for stdout, stderr, errors, and unexpected termination.
///
/// On unexpected termination, attempts automatic restart up to `MAX_RESTARTS` times
/// within a rolling `RESTART_WINDOW_SECS` window. If the restart budget is exhausted,
/// emits a `sidecar-crash` event to the frontend and stops monitoring.
///
/// Uses a loop instead of recursion so that `restart_timestamps` is preserved across
/// restarts and the restart budget is enforced correctly.
pub async fn monitor_sidecar(mut rx: Receiver<CommandEvent>, app: AppHandle) {
    let mut restart_timestamps: Vec<Instant> = Vec::new();

    loop {
        let mut restarting = false;

        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    log::info!("[sidecar] {}", line.trim_end());
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    log::warn!("[sidecar] {}", line.trim_end());
                }
                CommandEvent::Error(err) => {
                    log::error!("[sidecar] process error: {err}");
                }
                CommandEvent::Terminated(payload) => {
                    let state = app.state::<SidecarState>();

                    if state.shutting_down.load(Ordering::SeqCst) {
                        log::info!("[sidecar] expected termination during shutdown");
                        return;
                    }

                    log::error!(
                        "[sidecar] unexpected termination — code: {:?}, signal: {:?}",
                        payload.code,
                        payload.signal
                    );

                    // Prune restart timestamps outside the rolling window.
                    let now = Instant::now();
                    let window = std::time::Duration::from_secs(RESTART_WINDOW_SECS);
                    restart_timestamps.retain(|ts| now.duration_since(*ts) < window);

                    if restart_timestamps.len() as u32 >= MAX_RESTARTS {
                        log::error!(
                            "[sidecar] exceeded {MAX_RESTARTS} restarts in {RESTART_WINDOW_SECS}s — giving up"
                        );
                        let _ =
                            app.emit("sidecar-crash", "Sidecar exceeded maximum restart attempts");
                        return;
                    }

                    restart_timestamps.push(now);
                    let attempt = restart_timestamps.len();
                    log::info!("[sidecar] restart attempt {attempt}/{MAX_RESTARTS}");

                    match spawn_sidecar(&app, state.port) {
                        Ok((new_rx, new_child)) => {
                            // Update the managed child handle.
                            if let Ok(mut guard) = state.child.lock() {
                                *guard = Some(new_child);
                            }

                            // Run health check before resuming monitoring.
                            if let Err(e) = health_check(state.port).await {
                                log::error!("[sidecar] health check failed after restart: {e}");
                            } else {
                                log::info!("[sidecar] restarted and healthy");
                            }

                            // Replace receiver and break inner loop to continue
                            // monitoring with the new process.
                            rx = new_rx;
                            restarting = true;
                            break;
                        }
                        Err(e) => {
                            log::error!("[sidecar] failed to restart: {e}");
                            let _ =
                                app.emit("sidecar-crash", &format!("Sidecar restart failed: {e}"));
                            return;
                        }
                    }
                }
                _ => {
                    log::warn!("[sidecar] unhandled command event variant");
                }
            }
        }

        if !restarting {
            log::info!("[sidecar] event stream ended");
            return;
        }
    }
}
