# Fotogrammetria – ORTODIS

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
