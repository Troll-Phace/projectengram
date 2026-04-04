import { invoke } from "@tauri-apps/api/core";

export interface TauriCommands {
  openInVscode: (path: string) => Promise<void>;
  openInTerminal: (path: string) => Promise<void>;
  openInFinder: (path: string) => Promise<void>;
  pickFolder: () => Promise<string | null>;
  getSidecarPort: () => Promise<number>;
}

const openInVscode = async (path: string): Promise<void> => {
  await invoke("open_in_vscode", { path });
};

const openInTerminal = async (path: string): Promise<void> => {
  await invoke("open_in_terminal", { path });
};

const openInFinder = async (path: string): Promise<void> => {
  await invoke("open_in_finder", { path });
};

const pickFolder = async (): Promise<string | null> => {
  return await invoke<string | null>("pick_folder");
};

const getSidecarPort = async (): Promise<number> => {
  return await invoke<number>("get_sidecar_port");
};

const commands: TauriCommands = {
  openInVscode,
  openInTerminal,
  openInFinder,
  pickFolder,
  getSidecarPort,
};

export function useTauriCommands(): TauriCommands {
  return commands;
}
