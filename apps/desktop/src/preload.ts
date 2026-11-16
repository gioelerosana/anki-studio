/*
 * Ponte minimo verso la PWA: le dice che gira nell'app desktop (niente «Esci» da
 * Authentik, dove stanno i dati, quale build è installata) e dà i comandi della finestra
 * alla barra del titolo che disegna lei. Nessuna API di Node.
 */
import { contextBridge, ipcRenderer } from 'electron';

export interface DesktopInfo {
  version: string;
  revision: string;
  dataDir: string;
}

const info = ipcRenderer.sendSync('desktop:info') as DesktopInfo;
contextBridge.exposeInMainWorld(
  'ankiDesktop',
  Object.freeze({
    ...info,
    minimize: () => ipcRenderer.send('window:minimize'),
    maximize: () => ipcRenderer.send('window:maximize'),
    close: () => ipcRenderer.send('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized') as Promise<boolean>,
    onMaximizedChange: (callback: (maximized: boolean) => void) => {
      const handler = (_: Electron.IpcRendererEvent, maximized: boolean) => callback(maximized);
      ipcRenderer.on('window:maximizedChanged', handler);
      return () => {
        ipcRenderer.removeListener('window:maximizedChanged', handler);
      };
    },
  }),
);
