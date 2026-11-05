/*
 * Shell dell'app. Per ora due schermate:
 *  - Connect: inserimento del token del backend (salvato sul dispositivo)
 *  - Decks:   elenco dei mazzi con i conteggi di oggi
 * Lo studio, l'aggiunta di carte e le impostazioni arrivano dopo (vedi AGENTS.md, "Roadmap").
 */
import { useSettings } from './settings';
import { ConnectScreen } from './screens/ConnectScreen';
import { DecksScreen } from './screens/DecksScreen';

export function App() {
  const { settings } = useSettings();
  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      {settings.apiToken ? <DecksScreen /> : <ConnectScreen />}
    </div>
  );
}
