# KNXGateTool

Un'applicazione desktop moderna per Windows 11 e macOS per i gateway **ESP_KNXGATE / ESP_SCSGATE** di Guido Pagani. Reimplementazione indipendente delle funzioni di **KnxScsGateTCP V6.0 (VB6)**, con protocollo TCP 5045, porta seriale, monitor, archivio dei dispositivi e trasferimento della configurazione.

> **Stato:** progetto nuovo. Non usare i comandi di scrittura su un impianto di produzione prima di avere verificato i telegrammi e fatto un backup. Il software non è affiliato al progetto originale.

## Scaricare l'app già compilata

Aprire [GitHub Actions – Tests and desktop builds](https://github.com/JRcode197/knxgatetool/actions/workflows/build.yml), scegliere **l'ultima esecuzione riuscita** e, nella sezione **Artifacts**, scaricare:

- **KNXGateTool-Windows**: estrarre lo ZIP contenuto nell'artifact e avviare \`KNXGateTool.exe\` dalla cartella estratta su Windows 11.
- **KNXGateTool-macOS**: estrarre lo ZIP contenuto nell'artifact e aprire \`KNXGateTool.app\` su macOS. L'app non è notarizzata da Apple: il primo avvio può richiedere una conferma nelle impostazioni Sicurezza.

Il file ZIP distribuito dall'azione contiene l'app PyInstaller e le dipendenze Qt: **non serve installare Python** per usarla. Se non è disponibile alcun artifact, verificare la conclusione del workflow. Gli artifact GitHub Actions possono scadere.

## Avvio da sorgente

Installare Python 3.11 o successivo:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS: source .venv/bin/activate
python -m pip install -e .
python -m knxgatetool
```

La schermata principale permette di scegliere TCP (IP del gateway, porta predefinita **5045**) o seriale, interrogare il firmware, avviare il monitor e registrare i telegrammi. Le azioni di controllo sono disponibili solo quando un telegramma utilizzabile è stato osservato (o ricostruito secondo la logica VB6, con indicazione esplicita).

## Funzioni

- Connessione TCP/seriale; interrogazione firmware `@q`; apertura monitor tramite la sequenza della versione 6.
- Decodifica telegrammi SCS e KNX Vimar in una tabella modificabile con ID esadecimale, nome, categoria, tipo, stato e maxP.
- Comandi ON, OFF, UP, DOWN, STOP, MORE, LESS attraverso `@W` e telegrammi acquisiti.
- Import/export JSON e import del formato testuale legacy VB6; storico log salvabile.
- Download `#getdevice`, upload `#putdevice` e commit `#setup` sul gateway TCP.
- Procedura di upload con conferma e backup automatico locale; impostazione frequenza 80/160 MHz.
- Impostazioni e catalogo salvati in una cartella dati dell'utente. Nessun servizio cloud.

## Pacchetti Windows/macOS

In **Actions** viene eseguita la suite di test e vengono creati gli artifact PyInstaller per i due sistemi operativi. Le app macOS non sono firmate/notarizzate: se Gatekeeper le blocca, procedere secondo le impostazioni di sicurezza di macOS. I pacchetti non possono essere collaudati sul gateway fisico dalla CI.

## Compatibilità, limiti e sicurezza

Il programma replica il protocollo **specifico** di esp_knxgate/scsgate, **non** è un client KNXnet/IP standard. La versione 6 VB6 è stata analizzata dal repository [papergion/knxscsgateTCP_VB6](https://github.com/papergion/knxscsgateTCP_VB6), principalmente da `Form1.frm`. Non è stato copiato codice VB6 o componenti OCX/ActiveX.

- Il caricamento firmware PIC/ESP, presente nel vecchio software, **non è implementato**: richiede validazione hardware e recovery prima di essere reso disponibile.
- Il riconoscimento automatico KNX segue la convenzione *pari/dispari* del vecchio programma, che può non essere valida su **By-me Plus**. Verificare gli ID scoperti.
- Upload **sostituisce** la tabella dispositivi sul gateway; effettuare prima un download e verificare il backup.
- Il sistema non è stato testato con un gateway reale in questa sessione; le suite di test verificano parsing, conversioni e logica senza hardware.
- Non inoltrare la porta TCP 5045 verso Internet; usare il tool solo in LAN fidata.

## Sviluppo e test

```bash
python -m unittest discover -s tests -v
```

Il codice applicativo si trova in `knxgatetool/`. I workflow in `.github/workflows/` eseguono i test e producono gli eseguibili.

Per la mappatura dei comandi e le precauzioni operative, vedere [docs/PROTOCOL_V6.md](docs/PROTOCOL_V6.md). È disponibile anche [un esempio di archivio JSON](examples/ByMe_Lab_dispositivi.example.json).

## Riferimenti

- [KnxScsGateTCP V6.0 (VB6)](https://github.com/papergion/knxscsgateTCP_VB6)
- [Firmware ESP/KNX/SCS e manuali](https://github.com/papergion/scsknxgate)
- [Guida tecnica dell'autore](https://guidopic.altervista.org/alter/knxgate.html)

### Licenza

Questo repository contiene codice nuovo sviluppato per l'interoperabilità con il gateway. Controllare le condizioni di licenza dei singoli progetti originali prima di distribuire loro firmware o binari insieme a questo tool.
