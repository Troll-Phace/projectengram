mod sidecar;

use sidecar::{SidecarState, SIDECAR_PORT};
use std::sync::atomic::Ordering;
use std::sync::Mutex;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let handle = app.handle().clone();

            match sidecar::spawn_sidecar(&handle, SIDECAR_PORT) {
                Ok((rx, child)) => {
                    let state = SidecarState {
                        child: Mutex::new(Some(child)),
                        port: SIDECAR_PORT,
                        shutting_down: Default::default(),
                    };
                    app.manage(state);

                    // Spawn async health check.
                    tauri::async_runtime::spawn(async move {
                        match sidecar::health_check(SIDECAR_PORT).await {
                            Ok(()) => log::info!("Sidecar is ready on port {SIDECAR_PORT}"),
                            Err(e) => log::error!("Sidecar health check failed: {e}"),
                        }
                    });

                    // Spawn async monitor for crash detection and auto-restart.
                    tauri::async_runtime::spawn(sidecar::monitor_sidecar(rx, handle));
                }
                Err(e) => {
                    log::error!("Failed to spawn sidecar: {e}");
                    // Manage a default (empty) state so downstream code
                    // that accesses SidecarState does not panic.
                    app.manage(SidecarState::default());
                }
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                let state = app.state::<SidecarState>();
                state.shutting_down.store(true, Ordering::SeqCst);
                // Block scopes the MutexGuard temporary so it drops before `state`.
                let child = { state.child.lock().ok().and_then(|mut g| g.take()) };
                if let Some(child) = child {
                    let _ = child.kill();
                    log::info!("Sidecar process killed on app exit");
                }
            }
        });
}
