# Fotogrammetria

Due strumenti per restituire prospetti da ortofoto, in mm interi e solo con polilinee (nessun blocco):

1. **`ortoanalisi`** (Python): **analizza l'ortofoto in automatico** e genera il DXF con muro, copertura, finestre e soglie.
2. **`ortodis.lsp`** (AutoLISP): disegno o correzione manuale in AutoCAD/BricsCAD, sempre al mm intero.

## 1. Analisi automatica – `ortoanalisi`

### Installazione
```
pip install -r requirements.txt
```

### Uso
```
python -m ortoanalisi prospetto.tif                  # scala dal world file (.tfw) o GeoTIFF
python -m ortoanalisi prospetto.jpg --mm-pixel 2     # scala esplicita: 1 px = 2 mm
```
Produce, accanto all'immagine:
- `prospetto_rilievo.dxf`: LWPOLYLINE chiuse, unità mm, ortofoto inserita sotto come riferimento
- `prospetto_rilievo.csv`: elenco degli elementi con larghezza e altezza
- `prospetto_rilievo_controllo.png`: ortofoto con il riconoscimento sovrapposto (verde muro, rosso copertura, azzurro aperture, giallo soglie rilevate, arancio soglie stimate)

| Layer | Contenuto |
|---|---|
| `ORTO_MURO` | confine del muro |
| `ORTO_COPERTURA` | copertura in vista |
| `ORTO_FINESTRA` | sagome delle aperture (finestre e porte, telaio compreso) |
| `ORTO_SOGLIA` | soglie e davanzali rilevati |
| `ORTO_SOGLIA_STIMATA` | soglie non visibili, disegnate con le misure di default: da verificare |
| `ORTO_IMMAGINE`, `ORTO_TESTI` | ortofoto ed etichette L×H (`--etichette`) |

### Scala: obbligatoria
Lo strumento misura in pixel e converte in mm, quindi deve conoscere la dimensione del pixel. In ordine di priorità:
1. `--mm-pixel N`
2. un world file accanto all'immagine (`.tfw` / `.jgw` / `.pgw`). Metashape e Pix4D lo esportano con l'opzione "write world file". L'unità predefinita è il metro; si cambia con `--unita-world cm|mm`.
3. la georeferenziazione interna del GeoTIFF (richiede `tifffile`).

### Come riconosce gli elementi
1. **Sagoma della facciata**: usa la trasparenza (alpha), altrimenti uno sfondo uniforme ai bordi, altrimenti GrabCut.
2. **Aperture**: cerca zone più scure del contorno (soglia adattiva) che siano rettangolari, abbiano dimensioni plausibili e un colore diverso dal muro. Ogni zona viene poi allargata finché il bordo raggiunge il colore del muro, così telaio e mazzetta restano dentro la sagoma.
3. **Copertura**: è la zona di colore diverso dal muro attaccata al profilo superiore della sagoma. Il confine con il muro è ricavato pixel per pixel, assegnando ciascuno alla classe di colore più vicina.
4. **Muro**: è la facciata meno la copertura. Il contorno viene semplificato e i lati quasi orizzontali o verticali vengono resi esattamente orizzontali o verticali.
5. **Soglie**: cerca sotto ogni apertura una fascia di colore diverso dal muro. Se non la trova, la disegna con le misure di default sul layer `_STIMATA`. Le porte a terra non hanno soglia.
6. **Allineamento**: le quote delle aperture che differiscono meno di `--allinea` (20 mm) vengono unificate (stesso piano, stessa colonna).
7. **Arrotondamento**: tutte le coordinate finali vengono arrotondate al mm intero (`--passo`).

### Opzioni utili
`--contrasto` (abbassalo se non trova le finestre), `--finestra-min` / `--finestra-max`, `--gronda-mm Y` (forza il limite muro/copertura se i colori sono simili), `--soglie rilevate|nessuna`, `--risoluzione-max`, `--allinea 0` (disattiva l'allineamento).

### Limiti
- Il riconoscimento si basa su colore e contrasto, non è un modello di intelligenza artificiale addestrato. Funziona bene con aperture scure e copertura di colore diverso dal muro. Ombre forti, persiane chiuse dello stesso colore del muro, vegetazione o ponteggi possono creare errori. **Controlla sempre il PNG di controllo** e correggi in CAD, anche con `ortodis.lsp`.
- La precisione è di circa ±1 pixel dell'ortofoto. Con 4 mm/px significa circa ±4 mm: il mm intero è un arrotondamento, non la precisione reale del rilievo.
- World file ruotati (come quelli di RealityScan per i prospetti): si usa solo la dimensione del pixel e il disegno parte da 0,0 in basso a sinistra.

### Test
```
python -m pytest tests
```
I test usano facciate sintetiche di misure note: una con la falda in vista e una a capanna su sfondo trasparente. Su entrambe le finestre risultano esatte al mm; la porta a terra ha uno scarto di circa 4 mm in larghezza e 12 mm alla base, dovuto al bordo con lo sfondo.

## 2. Disegno manuale – `ortodis.lsp`

Routine AutoLISP (AutoCAD / BricsCAD) per ridisegnare un prospetto sopra un'ortofoto.
Disegna sagome di finestre, confini dei muri, soglie e coperture.

- Crea **solo LWPOLYLINE**, nessun blocco.
- Ogni vertice viene **arrotondato al mm intero** (passo configurabile). Se clicchi una finestra larga 1734,37 mm, la routine disegna 1734.

## Installazione

1. `APPLOAD`, poi carica `ortodis.lsp`. Per caricarlo a ogni avvio aggiungilo alla *Startup Suite* (Gruppo di avvio).
2. Esegui `ORTOSETUP`: crea i layer e porta `INSUNITS` a 4 (mm).

## Prerequisiti dell'ortofoto

- L'ortofoto deve essere inserita in scala reale **1 unità = 1 mm**. Per verificarla, misura con `DIST` una quota nota. Se non torna, usa `SCALA` con l'opzione *Riferimento*.
- I rettangoli vengono costruiti allineati agli assi dell'**UCS corrente**. Se il prospetto è ruotato, imposta prima un UCS allineato alla facciata con `UCS` → *Oggetto* oppure *3 punti*.

## Comandi

| Comando | Cosa fa | Layer |
|---|---|---|
| `ORTOSETUP` | Crea i layer e imposta le unità in mm | – |
| `ORTOFIN` | Sagoma della finestra: 2 angoli, oppure il primo angolo e poi *Dimensioni* (L × H). Il comando si ripete finché non premi Invio | `ORTO_FINESTRA` |
| `ORTOMURO` | Confine del muro: polilinea libera con opzioni *Chiudi* e *Annulla* | `ORTO_MURO` |
| `ORTOSOGLIA` | Soglia o davanzale: selezioni la finestra e la soglia viene creata sotto il lato inferiore, con sporgenza laterale e spessore. Le opzioni *Parametri* e *Manuale* permettono di cambiare i valori o disegnarla a mano | `ORTO_SOGLIA` |
| `ORTOCOP` | Copertura: polilinea libera aperta o chiusa | `ORTO_COPERTURA` |
| `ORTOARR` | Arrotonda al passo corrente i vertici di polilinee già disegnate | – |
| `ORTOPASSO` | Cambia il passo di arrotondamento (1, 5, 10 mm…) | – |

Default della soglia: sporgenza 30 mm per lato, spessore 40 mm. Si modificano con `ORTOSOGLIA` → *Parametri*.
Nomi e colori dei layer si cambiano in testa al file, nella variabile `*orto-layers*`.

Per tracciare segmenti orizzontali o verticali usa Orto (F8). Gli snap ad oggetto funzionano normalmente: il punto agganciato viene comunque arrotondato.

## Come funziona l'arrotondamento

- L'arrotondamento si fa sulle **coordinate X,Y nell'UCS corrente**, al mm più vicino (0,5 va verso l'unità superiore in valore assoluto).
- Se tutti i vertici hanno coordinate intere:
  - i lati orizzontali e verticali hanno lunghezze intere, quindi larghezza e altezza di finestre e soglie sono sempre intere;
  - un lato inclinato, per esempio la falda di una copertura, ha proiezioni ΔX e ΔY intere. La sua lunghezza reale √(ΔX²+ΔY²) in generale non lo è, ed è un limite geometrico che non si può evitare.
- Con un UCS ruotato le coordinate sono intere nell'UCS, non nel WCS. Le dimensioni restano comunque intere.
- Il calcolo usa numeri reali e non `fix`, quindi funziona anche con coordinate georeferenziate grandi, per esempio UTM in mm, senza superare il limite degli interi a 32 bit.
- Tutte le polilinee vengono create con Z = 0 nell'UCS corrente.
