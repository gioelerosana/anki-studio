/*
 * Ponte minimo verso la PWA: le dice che gira nell'app desktop (niente «Esci» da
 * Authentik, dove stanno i dati, quale build è installata). Nessuna API di Node.
 */
import { contextBridge, ipcRenderer } from 'electron';

export interface DesktopInfo {
  version: string;
  revision: string;
  dataDir: string;
}

const info = ipcRenderer.sendSync('desktop:info') as DesktopInfo;
contextBridge.exposeInMainWorld('ankiDesktop', Object.freeze({ ...info }));
