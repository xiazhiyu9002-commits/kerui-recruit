use std::io;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Manager, RunEvent, State};

/// Per-launch runtime values handed to the React frontend so it can reach the
/// Python sidecar on loopback with a short-lived session token.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeConfig {
    pub api_base_url: String,
    pub session_token: String,
}

impl RuntimeConfig {
    /// Bind a loopback ephemeral port and generate a fresh 256-bit session token.
    pub fn allocate() -> io::Result<Self> {
        let (port, session_token) = allocate_runtime()?;
        Ok(Self {
            api_base_url: format!("http://127.0.0.1:{port}"),
            session_token,
        })
    }
}

/// The running sidecar process, kept so it can be terminated on application exit.
pub struct SidecarProcess(Mutex<Option<Child>>);

fn allocate_runtime() -> io::Result<(u16, String)> {
    Ok((allocate_loopback_port()?, generate_session_token()))
}

fn allocate_loopback_port() -> io::Result<u16> {
    // Bind to 127.0.0.1:0 and ask the OS for an ephemeral port. The sidecar
    // re-binds it; the tiny window is inherent to any port reservation scheme.
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

fn generate_session_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("operating system randomness must be available");
    hex::encode(bytes)
}

/// Forward only the scoped runtime values the sidecar accepts; never leak any
/// other process environment into the child.
pub fn sidecar_arguments(port: u16, token: String, data_root: PathBuf) -> Vec<String> {
    vec![
        "--port".to_string(),
        port.to_string(),
        "--token".to_string(),
        token,
        "--data-root".to_string(),
        data_root.to_string_lossy().into_owned(),
    ]
}

fn default_data_root() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        std::env::var("LOCALAPPDATA")
            .map(|dir| PathBuf::from(dir).join("KeRuiRecruit"))
            .unwrap_or_else(|_| PathBuf::from(".").join("KeRuiRecruit"))
    }
    #[cfg(target_os = "macos")]
    {
        std::env::var("HOME")
            .map(|home| PathBuf::from(home).join("Library/Application Support/KeRuiRecruit"))
            .unwrap_or_else(|_| PathBuf::from(".").join("KeRuiRecruit"))
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        PathBuf::from(".").join("KeRuiRecruit")
    }
}

fn resolve_sidecar_binary() -> PathBuf {
    if let Ok(path) = std::env::var("KERUI_SIDECAR_BIN") {
        return PathBuf::from(path);
    }
    let name = if cfg!(windows) {
        "kerui-recruit-sidecar.exe"
    } else {
        "kerui-recruit-sidecar"
    };
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(name)))
        .unwrap_or_else(|| PathBuf::from(name))
}

fn wait_until_ready(config: &RuntimeConfig, timeout: Duration) -> io::Result<()> {
    let deadline = Instant::now() + timeout;
    let url = format!(
        "{}/health/ready",
        config.api_base_url.trim_end_matches('/')
    );
    while Instant::now() < deadline {
        let ready = tauri::async_runtime::block_on(async {
            reqwest::Client::new()
                .get(&url)
                .send()
                .await
                .map(|response| response.status().is_success())
                .unwrap_or(false)
        });
        if ready {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        "sidecar did not become ready in time",
    ))
}

#[tauri::command]
fn runtime_config(state: State<'_, RuntimeConfig>) -> RuntimeConfig {
    state.inner().clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let config = RuntimeConfig::allocate()?;
            let sidecar = resolve_sidecar_binary();
            let arguments = sidecar_arguments(
                parse_port(&config.api_base_url)?,
                config.session_token.clone(),
                default_data_root(),
            );
            let child = Command::new(&sidecar)
                .args(&arguments)
                .spawn()
                .map_err(|error| {
                    io::Error::new(
                        error.kind(),
                        format!("failed to start sidecar {}: {error}", sidecar.display()),
                    )
                })?;
            wait_until_ready(&config, Duration::from_secs(15))?;

            app.manage(SidecarProcess(Mutex::new(Some(child))));
            app.manage(config);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![runtime_config])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(process) = app_handle.try_state::<SidecarProcess>() {
                    if let Some(mut child) = process.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}

fn parse_port(api_base_url: &str) -> io::Result<u16> {
    let suffix = api_base_url
        .strip_prefix("http://127.0.0.1:")
        .or_else(|| api_base_url.strip_prefix("http://localhost:"))
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "unexpected API base URL"))?;
    suffix
        .trim_end_matches('/')
        .parse::<u16>()
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "invalid API port"))
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::{RuntimeConfig, sidecar_arguments};

    #[test]
    fn runtime_config_uses_loopback_and_a_256_bit_launch_token() {
        let config = RuntimeConfig::allocate().expect("runtime config");

        assert!(config.api_base_url.starts_with("http://127.0.0.1:"));
        assert_eq!(config.session_token.len(), 64);
        assert!(config.session_token.chars().all(|character| character.is_ascii_hexdigit()));
    }

    #[test]
    fn sidecar_arguments_forward_only_scoped_runtime_values() {
        let args = sidecar_arguments(
            43127,
            "a".repeat(64),
            PathBuf::from("C:/Users/example/AppData/Local/KeRuiRecruit"),
        );

        assert_eq!(args, vec![
            "--port", "43127",
            "--token", &"a".repeat(64),
            "--data-root", "C:/Users/example/AppData/Local/KeRuiRecruit",
        ]);
    }
}