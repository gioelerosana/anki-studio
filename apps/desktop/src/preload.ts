/*
 * Ponte minimo verso la PWA: le dice che gira nell'app desktop (niente «Esci» da
 * Authentik, dove stanno i dati, quale build è installata) e dà i comandi della finestra
 * alla barra del titolo che disegna lei, più lo zoom per le impostazioni. Nessuna API di Node.
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
    getZoom: () => ipcRenderer.invoke('zoom:get') as Promise<number>,
    setZoom: (factor: number) => ipcRenderer.invoke('zoom:set', factor) as Promise<number>,
    onZoomChange: (callback: (factor: number) => void) => {
      const handler = (_: Electron.IpcRendererEvent, factor: number) => callback(factor);
      ipcRenderer.on('zoom:changed', handler);
      return () => {
        ipcRenderer.removeListener('zoom:changed', handler);
      };
    },
  }),
);
