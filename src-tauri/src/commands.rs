use std::process::Command;

use tauri::State;
use tauri_plugin_dialog::DialogExt;

use crate::sidecar::SidecarState;

/// Open a project directory in Visual Studio Code.
#[tauri::command]
pub fn open_in_vscode(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !p.is_absolute() {
        return Err(format!("Only absolute paths are allowed: {path}"));
    }
    if !p.exists() {
        return Err(format!("Path does not exist: {path}"));
    }
    if !p.is_dir() {
        return Err(format!("Path is not a directory: {path}"));
    }

    Command::new("open")
        .args(["-a", "Visual Studio Code", &path])
        .spawn()
        .map_err(|e| format!("Failed to open VS Code: {e}"))?;

    Ok(())
}

/// Open a project directory in the default Terminal application.
#[tauri::command]
pub fn open_in_terminal(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !p.is_absolute() {
        return Err(format!("Only absolute paths are allowed: {path}"));
    }
    if !p.exists() {
        return Err(format!("Path does not exist: {path}"));
    }
    if !p.is_dir() {
        return Err(format!("Path is not a directory: {path}"));
    }

    Command::new("open")
        .args(["-a", "Terminal", &path])
        .spawn()
        .map_err(|e| format!("Failed to open Terminal: {e}"))?;

    Ok(())
}

/// Open a path in Finder (reveals the folder or file).
#[tauri::command]
pub fn open_in_finder(path: String) -> Result<(), String> {
    let p = std::path::Path::new(&path);
    if !p.is_absolute() {
        return Err(format!("Only absolute paths are allowed: {path}"));
    }
    if !p.exists() {
        return Err(format!("Path does not exist: {path}"));
    }

    Command::new("open")
        .arg(&path)
        .spawn()
        .map_err(|e| format!("Failed to open Finder: {e}"))?;

    Ok(())
}

/// Show a native macOS folder picker dialog.
///
/// Returns `Some(path_string)` if the user selected a folder, or `None` if
/// they cancelled.
#[tauri::command]
pub fn pick_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let folder = app.dialog().file().blocking_pick_folder();

    Ok(folder.map(|p| p.to_string()))
}

/// Return the port the sidecar is listening on.
#[tauri::command]
pub fn get_sidecar_port(state: State<'_, SidecarState>) -> Result<u16, String> {
    Ok(state.port)
}
