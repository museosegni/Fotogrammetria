;;; ===========================================================================
;;; ORTODIS.LSP - Restituzione grafica su ortofoto con quote intere in mm
;;; ---------------------------------------------------------------------------
;;; Disegna sopra un'ortofoto (raster inserito in scala 1 unita' = 1 mm)
;;; SOLO polilinee LWPOLYLINE (nessun blocco), con vertici arrotondati
;;; al passo impostato (default 1 mm): una finestra cliccata a 1734,37
;;; diventa 1734.
;;;
;;; Comandi:
;;;   ORTOSETUP   crea i layer e controlla le unita' del disegno
;;;   ORTOFIN     sagoma finestra (rettangolo da 2 angoli o da dimensioni)
;;;   ORTOMURO    confine muro (polilinea libera)
;;;   ORTOSOGLIA  soglia/davanzale sotto una finestra (automatica o manuale)
;;;   ORTOCOP     copertura (polilinea libera)
;;;   ORTOARR     arrotonda i vertici di polilinee gia' disegnate
;;;   ORTOPASSO   imposta il passo di arrotondamento (1, 5, 10 mm ...)
;;;
;;; Compatibile con AutoCAD e BricsCAD (richiede Visual LISP / vl-load-com).
;;; ===========================================================================

(vl-load-com)

;;; ---------------------------------------------------------------------------
;;; Configurazione (modificabile)
;;; ---------------------------------------------------------------------------
;;; (chiave  nome-layer  colore-ACI)
(setq *orto-layers*
  '(("FINESTRA"  "ORTO_FINESTRA"  4)
    ("MURO"      "ORTO_MURO"      7)
    ("SOGLIA"    "ORTO_SOGLIA"    3)
    ("COPERTURA" "ORTO_COPERTURA" 1)))

(if (not *orto-passo*)     (setq *orto-passo* 1.0))      ; mm
(if (not *orto-sporgenza*) (setq *orto-sporgenza* 30.0)) ; sporgenza laterale soglia, mm
(if (not *orto-spessore*)  (setq *orto-spessore* 40.0))  ; spessore soglia, mm

;;; ---------------------------------------------------------------------------
;;; Arrotondamento
;;; Niente FIX: con coordinate georeferenziate in mm (es. 4.500.000.000)
;;; si supererebbe il limite degli interi a 32 bit. Si lavora sui reali.
;;; ---------------------------------------------------------------------------
(defun orto:tronca (q) (- q (rem q 1.0)))

(defun orto:arr (x / q)
  (setq q (/ (float x) *orto-passo*))
  (* *orto-passo*
     (if (minusp q) (orto:tronca (- q 0.5)) (orto:tronca (+ q 0.5)))))

;; punto UCS arrotondato in XY, Z forzata a 0 (tutto sul piano UCS)
(defun orto:arrpt (p)
  (list (orto:arr (car p)) (orto:arr (cadr p)) 0.0))

;; punto UCS arrotondato in XY, Z conservata
(defun orto:arrxy (p)
  (list (orto:arr (car p)) (orto:arr (cadr p)) (caddr p)))

(defun orto:mm (x) (rtos x 2 (if (< *orto-passo* 1.0) 2 0)))

;;; ---------------------------------------------------------------------------
;;; Gestione errori / annulla
;;; ---------------------------------------------------------------------------
(defun orto:err (msg)
  (if (not (wcmatch (strcase msg) "*CANCEL*,*ANNULL*,*QUIT*,*EXIT*,*BREAK*"))
    (princ (strcat "\nErrore: " msg)))
  (redraw)
  (orto:fine)
  (princ))

(defun orto:inizio ()
  (setq *orto-olderr* *error*
        *error*       orto:err)
  (vla-StartUndoMark (vla-get-ActiveDocument (vlax-get-acad-object)))
  (if (/= (getvar "INSUNITS") 4)
    (princ "\nAttenzione: INSUNITS non e' 4 (millimetri). Verificare la scala dell'ortofoto."))
  (princ))

(defun orto:fine ()
  (vla-EndUndoMark (vla-get-ActiveDocument (vlax-get-acad-object)))
  (setq *error* *orto-olderr*)
  (princ))

;;; ---------------------------------------------------------------------------
;;; Layer
;;; ---------------------------------------------------------------------------
(defun orto:layer (chiave / d)
  (setq d (assoc chiave *orto-layers*))
  (if (not (tblsearch "LAYER" (cadr d)))
    (entmake
      (list '(0 . "LAYER")
            '(100 . "AcDbSymbolTableRecord")
            '(100 . "AcDbLayerTableRecord")
            (cons 2 (cadr d))
            '(70 . 0)
            (cons 62 (caddr d))
            '(6 . "Continuous"))))
  (cadr d))

;;; ---------------------------------------------------------------------------
;;; Creazione LWPOLYLINE da punti UCS (gia' arrotondati)
;;; ---------------------------------------------------------------------------
(defun orto:senzadoppi (pts / out)
  (foreach p pts
    (if (or (null out) (not (equal p (car out) 1e-9)))
      (setq out (cons p out))))
  (reverse out))

(defun orto:pline (pts chiusa chiave / zdir ocs)
  (setq pts (orto:senzadoppi pts))
  (if (and chiusa (> (length pts) 2) (equal (car pts) (last pts) 1e-9))
    (setq pts (reverse (cdr (reverse pts)))))
  (if (< (length pts) 2)
    (progn (princ "\nServono almeno 2 punti distinti.") nil)
    (progn
      (setq zdir (trans '(0.0 0.0 1.0) 1 0 T)
            ocs  (mapcar '(lambda (p) (trans p 1 zdir)) pts))
      (if (entmake
            (append
              (list '(0 . "LWPOLYLINE")
                    '(100 . "AcDbEntity")
                    (cons 8 (orto:layer chiave))
                    '(100 . "AcDbPolyline")
                    (cons 90 (length ocs))
                    (cons 70 (if chiusa 1 0))
                    (cons 38 (caddr (car ocs)))
                    '(43 . 0.0))
              (mapcar '(lambda (p) (cons 10 (list (car p) (cadr p)))) ocs)
              (list (cons 210 zdir))))
        (entlast)
        (progn (princ "\nImpossibile creare la polilinea.") nil)))))

;; rettangolo da due angoli qualsiasi (UCS), primo vertice in basso a sinistra
(defun orto:rett (p1 p2 chiave / x1 y1 x2 y2)
  (setq x1 (min (car p1) (car p2))  x2 (max (car p1) (car p2))
        y1 (min (cadr p1) (cadr p2)) y2 (max (cadr p1) (cadr p2)))
  (if (or (equal x1 x2 1e-9) (equal y1 y2 1e-9))
    (progn (princ "\nDimensione nulla dopo l'arrotondamento: rettangolo non creato.") nil)
    (if (orto:pline (list (list x1 y1 0.0) (list x2 y1 0.0)
                          (list x2 y2 0.0) (list x1 y2 0.0))
                    T chiave)
      (list (- x2 x1) (- y2 y1)))))

;;; ---------------------------------------------------------------------------
;;; Polilinea libera con anteprima (muro, copertura)
;;; ---------------------------------------------------------------------------
(defun orto:anteprima (pts / a)
  (setq a (car pts))
  (foreach b (cdr pts) (grdraw a b 2) (setq a b)))

(defun orto:polilibera (chiave nome / pts p fine chiusa kw ok)
  (if (setq p (getpoint (strcat "\nPrimo punto " nome " <esci>: ")))
    (progn
      (setq ok  T
            pts (list (orto:arrpt p)))
      (while (not fine)
        (setq kw (if (> (length pts) 2) "Chiudi Annulla" "Annulla"))
        (initget kw)
        (setq p (getpoint (last pts)
                          (strcat "\nPunto successivo ["
                                  (if (> (length pts) 2) "Chiudi/" "")
                                  "Annulla] <fine>: ")))
        (cond
          ((null p) (setq fine T))
          ((listp p)
           (setq p (orto:arrpt p))
           (if (equal p (last pts) 1e-9)
             (princ "\nPunto coincidente dopo l'arrotondamento: ignorato.")
             (progn
               (grdraw (last pts) p 2)
               (setq pts (append pts (list p))))))
          ((= p "Chiudi") (setq chiusa T fine T))
          ((= (type p) 'STR)
           (if (> (length pts) 1)
             (setq pts (reverse (cdr (reverse pts))))
             (princ "\nNessun segmento da annullare."))
           (redraw)
           (orto:anteprima pts))))
      (redraw)
      (if (orto:pline pts chiusa chiave)
        (princ (strcat "\n" nome ": " (itoa (length (orto:senzadoppi pts))) " vertici"
                       (if chiusa ", chiusa." ", aperta."))))))
  ok)

;;; ---------------------------------------------------------------------------
;;; COMANDI
;;; ---------------------------------------------------------------------------

(defun c:ORTOSETUP ()
  (foreach d *orto-layers* (orto:layer (car d)))
  (princ "\nLayer creati/verificati:")
  (foreach d *orto-layers* (princ (strcat " " (cadr d))))
  (if (/= (getvar "INSUNITS") 4)
    (progn
      (initget "Si No")
      (if (/= (getkword "\nINSUNITS non e' in millimetri. Impostare INSUNITS=4? [Si/No] <Si>: ") "No")
        (progn (setvar "INSUNITS" 4) (princ "\nINSUNITS = 4 (mm).")))))
  (princ (strcat "\nPasso di arrotondamento: " (rtos *orto-passo* 2 2) " mm."))
  (princ))

(defun c:ORTOPASSO (/ v)
  (initget 6)
  (setq v (getreal (strcat "\nPasso di arrotondamento in mm <" (rtos *orto-passo* 2 2) ">: ")))
  (if v (setq *orto-passo* (float v)))
  (princ (strcat "\nPasso: " (rtos *orto-passo* 2 2) " mm."))
  (princ))

;; --- Finestra ---------------------------------------------------------------
(defun c:ORTOFIN (/ p1 p2 l h r)
  (orto:inizio)
  (while (setq p1 (getpoint "\nPrimo angolo finestra <esci>: "))
    (setq p1 (orto:arrpt p1))
    (initget "Dimensioni")
    (setq p2 (getcorner p1 "\nAngolo opposto o [Dimensioni]: "))
    (cond
      ((= (type p2) 'STR)
       (initget 7)
       (setq l (orto:arr (getdist "\nLarghezza (mm): ")))
       (initget 7)
       (setq h (orto:arr (getdist "\nAltezza (mm): ")))
       (setq p2 (list (+ (car p1) l) (+ (cadr p1) h) 0.0)))
      (p2 (setq p2 (orto:arrpt p2))))
    (if (and p2 (setq r (orto:rett p1 p2 "FINESTRA")))
      (princ (strcat "\nFinestra L=" (orto:mm (car r)) " H=" (orto:mm (cadr r)) " mm"))))
  (orto:fine))

;; --- Muro -------------------------------------------------------------------
(defun c:ORTOMURO ()
  (orto:inizio)
  (while (orto:polilibera "MURO" "confine muro"))
  (orto:fine))

;; --- Copertura --------------------------------------------------------------
(defun c:ORTOCOP ()
  (orto:inizio)
  (while (orto:polilibera "COPERTURA" "copertura"))
  (orto:fine))

;; --- Soglia -----------------------------------------------------------------
(defun orto:vertici-ucs (e / ed el)
  (setq ed (entget e)
        el (cond ((cdr (assoc 38 ed))) (0.0)))
  (mapcar '(lambda (g) (trans (list (cadr g) (caddr g) el) e 1))
          (vl-remove-if-not '(lambda (g) (= (car g) 10)) ed)))

(defun orto:parametri-soglia (/ v)
  (initget 4)
  (setq v (getdist (strcat "\nSporgenza laterale per lato (mm) <" (orto:mm *orto-sporgenza*) ">: ")))
  (if v (setq *orto-sporgenza* (orto:arr v)))
  (initget 6)
  (setq v (getdist (strcat "\nSpessore soglia (mm) <" (orto:mm *orto-spessore*) ">: ")))
  (if v (setq *orto-spessore* (orto:arr v)))
  (if (<= *orto-spessore* 0.0) (setq *orto-spessore* *orto-passo*)))

(defun c:ORTOSOGLIA (/ sel e ed pts xmin xmax ymin p1 p2 r fine)
  (orto:inizio)
  (princ (strcat "\nSoglia: sporgenza " (orto:mm *orto-sporgenza*)
                 " mm, spessore " (orto:mm *orto-spessore*) " mm."))
  (while (not fine)
    (setvar "ERRNO" 0)
    (initget "Parametri Manuale")
    (setq sel (entsel "\nSeleziona sagoma finestra o [Parametri/Manuale] <esci>: "))
    (cond
      ((null sel)
       (if (= (getvar "ERRNO") 7) (princ "\nNessun oggetto selezionato.") (setq fine T)))
      ((= sel "Parametri") (orto:parametri-soglia))
      ((= sel "Manuale")
       (if (and (setq p1 (getpoint "\nPrimo angolo soglia: "))
                (setq p2 (getcorner p1 "\nAngolo opposto: ")))
         (if (setq r (orto:rett (orto:arrpt p1) (orto:arrpt p2) "SOGLIA"))
           (princ (strcat "\nSoglia L=" (orto:mm (car r)) " H=" (orto:mm (cadr r)) " mm")))))
      ((= (type sel) 'LIST)
       (setq e (car sel) ed (entget e))
       (if (/= (cdr (assoc 0 ed)) "LWPOLYLINE")
         (princ "\nL'oggetto non e' una polilinea.")
         (progn
           (setq pts  (orto:vertici-ucs e)
                 xmin (orto:arr (apply 'min (mapcar 'car pts)))
                 xmax (orto:arr (apply 'max (mapcar 'car pts)))
                 ymin (orto:arr (apply 'min (mapcar 'cadr pts))))
           (setq r (orto:rett (list (- xmin *orto-sporgenza*) (- ymin *orto-spessore*) 0.0)
                              (list (+ xmax *orto-sporgenza*) ymin 0.0)
                              "SOGLIA"))
           (if r
             (princ (strcat "\nSoglia L=" (orto:mm (car r)) " H=" (orto:mm (cadr r))
                            " mm (finestra L=" (orto:mm (- xmax xmin)) ")"))))))))
  (orto:fine))

;; --- Arrotonda polilinee esistenti -----------------------------------------
(defun c:ORTOARR (/ ss i e ed el zdir n skip)
  (orto:inizio)
  (setq zdir (trans '(0.0 0.0 1.0) 1 0 T) n 0 skip 0)
  (princ "\nSeleziona le polilinee da arrotondare al passo corrente.")
  (if (setq ss (ssget '((0 . "LWPOLYLINE"))))
    (progn
      (repeat (setq i (sslength ss))
        (setq e  (ssname ss (setq i (1- i)))
              ed (entget e)
              el (cond ((cdr (assoc 38 ed))) (0.0)))
        (if (equal (cdr (assoc 210 ed)) zdir 1e-8)
          (progn
            (setq ed
              (mapcar
                '(lambda (g / q)
                   (if (= (car g) 10)
                     (progn
                       (setq q (trans (orto:arrxy (trans (list (cadr g) (caddr g) el) e 1)) 1 e))
                       (cons 10 (list (car q) (cadr q))))
                     g))
                ed))
            (entmod ed)
            (entupd e)
            (setq n (1+ n)))
          (setq skip (1+ skip))))
      (princ (strcat "\nPolilinee arrotondate: " (itoa n)))
      (if (> skip 0)
        (princ (strcat "\nIgnorate " (itoa skip) " polilinee non parallele all'UCS corrente.")))))
  (orto:fine))

(princ "\nORTODIS caricato. Comandi: ORTOSETUP ORTOFIN ORTOMURO ORTOSOGLIA ORTOCOP ORTOARR ORTOPASSO")
(princ)
