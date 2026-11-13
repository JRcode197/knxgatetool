# Protocollo gateway — analisi V6.0

Fonte primaria: [Form1.frm, repository VB6 originale](https://github.com/papergion/knxscsgateTCP_VB6/blob/master/Form1.frm). **Questo non è KNXnet/IP**: il protocollo è proprietario di ESP_KNXGATE/ESP_SCSGATE. Il riferimento è una fotografia del sorgente V6 e non equivale a certificazione sul firmware installato.

## Trasporto

- **TCP**: gateway ESP sulla porta **5045**. Comandi ASCII del tipo `#setup {...}`, `#getdevice {...}`, `#putdevice {...}`; la risposta non è necessariamente delimitata da newline. Il tool accumula dati fino a una pausa e non suppone che un pacchetto TCP corrisponda a un comando.
- **Seriale**: porta selezionabile dall'utente; 115200 baud, 8N1 di default; prevista alternativa 19200 baud.
- `@q`: interrogazione; il programma VB6 interpreta un ACK `k` seguito da informazioni firmware. I firmware che iniziano con `KNX` identificano la modalità KNX; altri identificano SCS.

## Abilitazione e monitoraggio

1. Solo TCP: `#setup {"uart":"tcp"}`
2. `@q`, risposta `k...` (oppure echo `qk...`)
3. Sequenza monitor telegrammi V6: `@\\x16`, `@MX`, `@F0`, `@b`, `@Y0`, `@l`; ACK `k` per ciascun comando.
4. Nel monitor bus i messaggi ricevuti sono **lunghezza (1 byte) + telegramma**. La lunghezza non fa parte del telegramma.
5. Invio telegramma di controllo: `@W` + lunghezza (1 byte) + telegramma (massimo 16 byte nel codice V6).
6. Monitor seriale ASCII: `@MA`. Il monitor viene terminato riaprendo la connessione perché V6 non documenta un comando di uscita.

## Dispositivi sul gateway

Il download della griglia nella versione VB6 chiede i numeri progressivi:

```text
#getdevice {"devnum":"1"}
#getdevice {"devnum":"2"}
...
#eof
```

Un dispositivo può essere restituito così:

```text
#ok {"device":"0EA1","type":"1","maxp":"0","descr":"Luce Ingresso"}
```

L'upload è **distruttivo** e richiede conferma:

```text
#putdevice {"coverpct":"false","devclear":"true"}
#putdevice {"device":"0EA1","type":"1","maxp":"0","descr":"Luce Ingresso"}
#setup {"commit":"true"}
```

Il programma richiede risposte `#ok` a ogni passo, scarica la tabella remota completa e la archivia in JSON prima di autorizzare la cancellazione. Se la lettura remota fallisce, non procede con l'upload.

| Tipo UI | Tipo firmware V6 |
| --- | --- |
| LUCE | 1 |
| GEN | 11 |
| DIM | 4 (KNX), 3 (SCS) |
| D+- | 24 |
| TAP / STO | 8, oppure 9 con percentuale |
| UPD | 18, oppure 19 con percentuale |

Per un firmware KNX, il campo `device` include quattro caratteri esadecimali (due byte). Per SCS il VB6 trasmette solo il byte indirizzo.

## Interpretazione monitor

**SCS**: telegrammi di 7 byte, prefisso `A8`, suffisso `A3`. Origine zero indica comando, destinazione `B8` indica stato. L'ID è composto da byte rete e indirizzo. Azioni più comuni sono 00=ON, 01=OFF, 03=MORE, 04=LESS.

**KNX Vimar**: prefissi `B4`, `B8`, `BC`. La destinazione è il byte indice 4 (partendo da 0), rete indice 3, payload dalla posizione 7, lunghezza payload nel nibble basso del byte 5. Il programma originale usa indirizzo dispari come pressione breve e indirizzo pari ricondotto al dispari precedente come pressione lunga. Il payload `80`/`81` distingue le azioni luce/tapparella e il contesto del dispositivo. Esempio nel VB6: `B4 10 0E 0B 1D E1 00 81 23`.

La V6 crea la controparte ON/OFF o UP/DOWN modificando il byte del comando e l'ultimo byte di verifica con XOR 1; SCS MORE/LESS usa XOR 7. La ricostruzione richiede un frame osservato, e il software indica e conferma i comandi inferiti.

## Non coperto dalla prima release

- Aggiornamento firmware: il codice VB6 implementa un bootloader con pacchetti specifici, ma una riscrittura senza validazione sul dispositivo rischierebbe di renderlo inutilizzabile.
- KNXnet/IP, ETS e specifiche KNX generiche, non presenti nel programma VB6.
- Interpretazione specifica dei cronotermostati Vimar 14514 o di payload non riconosciuti.
- Verifica live con gateway reale (necessaria prima dell'uso su impianti).

## Test

I test verificano framing frammentato, decodifica KNX/SCS, generazione delle controparti, conversioni, import/export e comunicazione con un mock TCP. La suite non sostituisce una prova hardware del firmware specifico.
