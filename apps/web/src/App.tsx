/*
 * Shell dell'app: prima l'accesso con Authentik (app/auth.tsx), poi le schermate
 * scelte dall'hash (app/route.ts): mazzi, studio, aggiungi, libreria, impostazioni, telecomando.
 */
import { AuthGate } from './app/auth';
import { useRoute, type Route } from './app/route';
import { ToastProvider } from './app/toasts';
import { AddScreen } from './screens/AddScreen';
import { DecksScreen } from './screens/DecksScreen';
import { LibraryScreen } from './screens/LibraryScreen';
import { RemoteScreen } from './screens/RemoteScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { StudyScreen } from './screens/StudyScreen';
import { useSettings } from './settings';
import { RemoteScreenProvider } from './remote/RemoteScreenProvider';
import { SyncProvider } from './sync/SyncProvider';

export function App() {
  // tema e animazioni valgono anche nella schermata di accesso
  useSettings();
  return (
    <ToastProvider>
      <div className="flex h-dvh w-screen flex-col overflow-hidden bg-background text-foreground">
        {/* Striscia opaca sotto la status bar. Su iPadOS 26 la PWA installata disegna comunque
            il contenuto sotto la barra (lo stile "default" non basta) e il sistema ci mette
            sopra una sfumatura. WebKit la sostituisce con un colore pieno solo se in cima c'è un
            elemento fixed, largo quanto la vista e con uno sfondo opaco: questo, in ogni schermata.
            Altezza 0 fuori dalla PWA (nessuna safe area), quindi nel browser non si vede. */}
        <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-[70] h-[env(safe-area-inset-top)] bg-background" />
        <AuthGate>
          <SyncProvider>
            <Connected />
          </SyncProvider>
        </AuthGate>
      </div>
    </ToastProvider>
  );
}

function Connected() {
  const route = useRoute();

  return (
    // Il telecomando vale in ogni schermata: sui mazzi il telefono ne apre uno, nello studio comanda la carta.
    <RemoteScreenProvider route={route}>
      <Screen route={route} />
    </RemoteScreenProvider>
  );
}

function Screen({ route }: { route: Route }) {
  switch (route.name) {
    case 'study':
      return <StudyScreen key={route.deckId} deckId={route.deckId} />;
    case 'add':
      return <AddScreen deckId={route.deckId} />;
    case 'settings':
      return <SettingsScreen />;
    case 'remote':
      return <RemoteScreen />;
    case 'library':
      return <LibraryScreen />;
    default:
      return <DecksScreen />;
  }
}
