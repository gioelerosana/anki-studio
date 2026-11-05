/*
 * Shell dell'app: senza token la schermata di collegamento, altrimenti le
 * schermate scelte dall'hash (app/route.ts): mazzi, studio, aggiungi, impostazioni.
 */
import { useEffect } from 'react';
import { api } from './api/client';
import { useRoute } from './app/route';
import { ToastProvider } from './app/toasts';
import { AddScreen } from './screens/AddScreen';
import { ConnectScreen } from './screens/ConnectScreen';
import { DecksScreen } from './screens/DecksScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { StudyScreen } from './screens/StudyScreen';
import { useSettings } from './settings';
import { SyncProvider } from './sync/SyncProvider';

export function App() {
  const { settings } = useSettings();
  return (
    <ToastProvider>
      <div className="flex h-full flex-col bg-background text-foreground">
        {settings.apiToken ? (
          <SyncProvider>
            <Connected />
          </SyncProvider>
        ) : (
          <ConnectScreen />
        )}
      </div>
    </ToastProvider>
  );
}

function Connected() {
  const route = useRoute();

  // Il cookie dei media dura un anno, ma iPadOS può svuotare i dati di una PWA poco usata:
  // lo si rinnova a ogni avvio, così le immagini delle carte non spariscono.
  useEffect(() => {
    api.createSession().catch(() => {});
  }, []);

  switch (route.name) {
    case 'study':
      return <StudyScreen key={route.deckId} deckId={route.deckId} />;
    case 'add':
      return <AddScreen deckId={route.deckId} />;
    case 'settings':
      return <SettingsScreen />;
    default:
      return <DecksScreen />;
  }
}
