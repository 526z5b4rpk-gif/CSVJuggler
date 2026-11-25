# DOC.md — CsvJuggler

Visualiseur de séries temporelles issues de fichiers CSV, inspiré de PlotJuggler, écrit en Python.
Cible principale : exports TwinCAT Scope et acquisitions de mesures industrielles.

Ce fichier fait référence pour toute la durée du projet. Respecte la stack, l'architecture et l'ordre des phases.
En cas de doute sur un choix non couvert ici, pose la question au lieu de deviner.

## 1. Stack imposée

| Rôle | Choix | Remarques |
|---|---|---|
| Langage | Python ≥ 3.11 | Typage partout (`from __future__ import annotations`) |
| GUI | PySide6 (widgets, pas QML) | Pas de PyQt5/6 |
| Tracé | pyqtgraph | Pas de matplotlib dans l'interface interactive |
| Données | pandas (+ numpy) | polars possible plus tard, derrière une interface |
| Sérialisation | JSON (layouts, annotations), via dataclasses | Pas de pickle pour les fichiers utilisateur |
| Tests | pytest + pytest-qt | |
| Qualité | ruff (lint + format), mypy en mode non strict | |
| Packaging | pyproject.toml, point d'entrée `csvjuggler` | |

Aucune nouvelle dépendance sans justification dans le commit.

## 2. Architecture

Séparation stricte données / modèle de vue / widgets. Les widgets ne lisent jamais un CSV directement.

```
csvjuggler/
├── app.py                 # QApplication, point d'entrée, arguments CLI
├── main_window.py         # QMainWindow : menus, barre d'outils, dock area
├── i18n.py                # Textes de l'interface (français), centralisés, via tr()
├── data/
│   ├── importer.py        # Lecture CSV → Dataset (détection séparateurs, en-têtes, temps)
│   ├── scope_importer.py  # Spécificités des exports TwinCAT Scope
│   ├── dataset.py         # Dataset : temps + séries, métadonnées, rechargement
│   ├── series.py          # Series : nom, unité, np.ndarray x/y, source
│   ├── derived.py         # Séries calculées (formules, évaluation sans eval)
│   ├── export.py          # Export CSV d'une plage
│   └── analysis.py        # Valeur à x, statistiques, TSV (fonctions pures)
├── model/
│   ├── plot_config.py     # Dataclasses : PlotConfig, AxisConfig, CurveConfig...
│   ├── annotation.py      # Dataclasses : Annotation (texte, ligne V/H, région)
│   ├── layout.py          # Layout complet (docks + plots + annotations), (dé)sérialisation JSON
│   └── session.py         # État courant : datasets chargés + layout
├── ui/
│   ├── series_tree.py     # Arbre des séries (QTreeView), filtre, drag source
│   ├── plot_dock.py       # Un dock = un PlotWidget + barre d'outils locale
│   ├── plot_widget.py     # Wrapper pyqtgraph : courbes, axes multiples, annotations
│   ├── plot_items.py      # ViewBox et AxisItem personnalisés (menus, format des graduations)
│   ├── plot_menus.py      # Menus contextuels + ouverture des dialogues d'un graphe
│   ├── widgets.py         # Petits widgets réutilisables (ColorButton, DisposableDialog)
│   ├── theme.py           # Style (Fusion + palette claire), feuille de style, icône
│   ├── assets/            # SVG du thème (interrupteurs, chevrons)
│   ├── x_sync.py          # Synchronisation X entre graphes (groupes)
│   ├── progress.py        # Tâche en QThread + barre de progression
│   ├── multi_axis.py      # Gestion des axes Y secondaires (ViewBox liées)
│   ├── cursors.py         # Curseurs de mesure (ValueCursor, tracker, A/B)
│   ├── time_slider.py     # Barre « Lecture X » (timeline, lecture/pause)
│   ├── timeline.py        # Timeline : une ligne par fichier CSV sur un axe X commun
│   ├── annotation_panel.py# Panneau latéral listant les annotations
│   ├── measure_panel.py   # Panneau « Mesures » (curseurs A/B, statistiques, TSV)
│   ├── toolbox.py         # Panneau « Boîte à outils » (graphe, courbes, annotations, en direct)
│   ├── annotation_items.py# Items graphiques d'annotation (éditables, déplaçables)
│   └── dialogs/
│       ├── import_dialog.py
│       ├── plot_settings_dialog.py
│       ├── curve_settings_dialog.py
│       ├── annotation_dialog.py
│       ├── derived_dialog.py
│       └── export_dialog.py
└── utils/
    └── colors.py          # Palette par défaut, cycle de couleurs
tests/
```

Règles :

- **Un modèle sérialisable pour chaque élément personnalisable.** Toute personnalisation passe par une dataclass dans `model/`. Le widget s'applique à partir de la config (`apply_config`) et remonte les changements (signal `config_changed`). Ainsi, ce qui est à l'écran est toujours ce qui est sauvegardé.
- Les séries sont référencées par identifiant stable `"<alias_dataset>/<nom_colonne>"`, jamais par index.
- Pas d'état global caché : la `Session` est passée explicitement.

## 3. Import CSV

### 3.1 Détection automatique (modifiable dans ImportDialog)

- Encodage : UTF-8, avec repli sur cp1252.
- Séparateur de colonnes : `,` `;` `\t`.
- Séparateur décimal : `.` ou `,`. Avec `;` comme séparateur de colonnes, tester `,` décimal.
- Lignes d'en-tête multiples (exports Scope : Name, SymbolName, DataType, SampleTime, Unit...) :
  - détecter le bloc de métadonnées avant les données numériques ;
  - laisser l'utilisateur choisir la ligne qui donne le nom des colonnes ;
  - récupérer l'unité si une ligne Unit existe.
- Colonne de temps : proposer les candidates (monotones croissantes). Options : secondes, millisecondes, date/heure (format personnalisable), ou index de ligne.
- Paires temps/valeur multiples (Scope : une colonne de temps par canal) : les gérer. Chaque série garde son propre vecteur X.

### 3.2 Comportement

- Plusieurs fichiers chargés simultanément, chacun avec un alias (par défaut, le nom du fichier).
- Renommage des séries à l'import et après coup (alias d'affichage, sans modifier le CSV).
- Recharger (Ctrl+R) : relit le fichier avec les mêmes paramètres et conserve les graphes.
- Les paramètres d'import sont mémorisés par fichier dans le layout.
- Glisser-déposer d'un CSV sur la fenêtre = import.
- CLI : `csvjuggler fichier.csv [-l layout.json]`.

## 4. Fenêtres et disposition

- Zone de docks : `pyqtgraph.dockarea` ou `QDockWidget`. Choisis en phase 1 et documente le choix ici. → **QDockWidget** (voir « Décisions prises »).
- Chaque dock contient un graphe. Un graphe peut être divisé en sous-graphes empilés verticalement (axe X partagé).
- Les docks peuvent être déplacés, empilés en onglets, détachés en fenêtre flottante, renommés et fermés.
- Synchronisation de l'axe X : globale par défaut, désactivable par graphe (groupes de synchro nommés).
- Menu « Fenêtre » : nouveau graphe, mosaïque automatique, tout fermer.

## 5. Personnalisation des graphes

Toute personnalisation est accessible :

1. par clic droit sur l'élément (graphe, axe, courbe, annotation) → menu contextuel ;
2. par le dialogue Paramètres du graphe (double-clic sur le fond) ;
3. et elle est sauvegardée dans le layout.

### 5.1 Graphe (PlotConfig)

- Titre (texte, taille, affiché ou non).
- Fond, grille X/Y (on/off, opacité), position de la légende (ou masquée).
- Ratio des sous-graphes empilés.

### 5.2 Axes (AxisConfig)

Pour l'axe X et chaque axe Y :

- Libellé et unité (affichée `Libellé [unité]`).
- Plage : auto ou manuelle (min/max). Bouton « auto une fois ».
- Échelle linéaire / logarithmique.
- Inversion de l'axe.
- Format des graduations (nombre de décimales, notation scientifique, préfixes SI).
- Couleur de l'axe (par défaut : celle de la première courbe attachée, pour les axes secondaires).
- Axe X : temps relatif (s), absolu (date/heure) ou une série (mode XY).

### 5.3 Axes Y secondaires

- Nombre d'axes Y illimité par graphe : un axe principal à gauche, les axes secondaires à droite (puis à gauche si besoin).
- Implémentation pyqtgraph : une ViewBox supplémentaire par axe, liée en X (`setXLink`), géométrie synchronisée sur `sigResized` de la ViewBox principale, AxisItem ajouté au layout du PlotItem. Encapsuler tout ça dans `ui/multi_axis.py`.
- Chaque courbe est affectée à un axe (menu clic droit « Déplacer vers l'axe → … » ou « Nouvel axe »).
- Glisser une série sur la marge droite du graphe = création d'un nouvel axe secondaire.
- Le zoom à la molette sur un axe n'agit que sur cet axe. Le zoom dans la zone de tracé agit sur X et sur l'axe principal.
- Un axe sans courbe est supprimé automatiquement.

### 5.4 Courbes (CurveConfig)

- Nom affiché (alias), couleur, épaisseur, style (plein, tirets, pointillés).
- Marqueurs (aucun, rond, carré, croix), taille.
- Mode : ligne, escalier (stepMode), points seuls.
- Gain et offset d'affichage (`y_affiché = gain * y + offset`), sans modifier la donnée.
- Visible / masquée (clic sur la légende).

### 5.5 Annotations (Annotation)

Types :

- Texte ancré en coordonnées données (x, y, sur un axe donné), avec flèche optionnelle vers le point.
- Écart Δ entre deux points de courbes (A, B) : cotes horizontale (Δx) et verticale (Δy) fléchées, étiquette Δx, 1/Δx, Δy (ou y(A), y(B) si les unités diffèrent).
- Bulle accrochée à une courbe : le point suit la courbe (y = valeur affichée à x), la bulle se déplace autour du point, le point glisse le long de la courbe.
- Ligne verticale (événement) avec étiquette, optionnellement liée à tous les graphes synchronisés.
- Ligne horizontale (seuil) avec étiquette, sur un axe Y donné.
- Région X (début/fin) colorée semi-transparente, avec étiquette (ex. « palier 1 »).

Propriétés communes : texte, couleur, police/taille, fond du texte, opacité, verrouillage (non déplaçable).

Interaction :

- Création par clic droit → « Ajouter une annotation → type », à la position du clic.
- Déplacement à la souris, édition par double-clic, suppression avec Suppr ou par menu.
- Liste de toutes les annotations dans un panneau latéral (clic = centrer la vue dessus).

Persistance :

- Les annotations sont liées au dataset (par alias et chemin du fichier) et sauvegardées :
  - dans le layout ;
  - et dans un fichier compagnon `<fichier>.annotations.json` à côté du CSV, rechargé automatiquement à l'ouverture.
- Les coordonnées X sont stockées dans l'unité de temps de la série (pas en pixels).

## 6. Mesure et analyse

- Tracker (touche T) : ligne verticale qui suit la souris et affiche la valeur de toutes les courbes visibles (interpolation linéaire ou point le plus proche, au choix).
- Deux curseurs A/B : affichent Δt, 1/Δt, ΔY par courbe.
- Statistiques sur la région entre A et B ou sur une région sélectionnée : min, max, moyenne, écart-type, RMS, pic-pic, par courbe. Résultats copiables (presse-papiers en TSV).
- Séries calculées : formule Python restreinte sur les séries existantes (`a / b`, `derivative(a)`, `lowpass(a, fc)`, `integral(a)`), évaluée avec un espace de noms contrôlé (pas d'eval libre). Elles sont sauvegardées dans le layout.

## 7. Layout et session

- Layout (`*.cjl.json`) : docks et disposition, graphes, axes, courbes (par identifiant de série), annotations, séries calculées, paramètres d'import, synchronisation.
- Le chargement d'un layout sur un autre CSV de même structure doit fonctionner. Les séries manquantes sont signalées, sans erreur bloquante.
- Champ `version` dans le JSON, avec migration si le format évolue.
- Fichiers récents et dernier layout restaurés au démarrage (QSettings).

## 8. Export

- Export PNG/SVG d'un graphe ou de toute la fenêtre (`pyqtgraph.exporters`), annotations comprises.
- Export CSV de la plage visible ou de la région sélectionnée (séries choisies).
- Copie de l'image dans le presse-papiers.

## 9. Performances

- Objectif : 10 millions de points cumulés fluides en pan/zoom.
- `setDownsampling(auto=True, method='peak')` et `setClipToView(True)` sur toutes les courbes.
- Ne jamais recréer les PlotDataItem lors d'un zoom ou d'un changement de style : utiliser `setData` / `setPen`.
- Import lourd dans un QThread avec barre de progression. L'interface ne doit jamais geler plus de 200 ms.

## 10. Phases de développement

Valide chaque phase (démo et tests verts) avant de passer à la suivante. Une phase = une branche ou une série de commits cohérente.

1. **Squelette** : fenêtre principale, import CSV simple (une colonne de temps), arbre des séries, un graphe, glisser-déposer d'une série vers le graphe.
2. **Multi-fenêtres** : docks multiples, synchronisation X, division d'un graphe, légende, visibilité des courbes.
3. **Import avancé** : dialogue d'import, exports Scope (multi-en-têtes, virgule décimale, paires temps/valeur), plusieurs fichiers, alias, rechargement.
4. **Personnalisation** : PlotConfig, AxisConfig, CurveConfig, dialogues, menus contextuels.
5. **Axes secondaires** : `multi_axis.py`, affectation des courbes aux axes, dépôt sur la marge droite.
6. **Annotations** : les 4 types, édition, panneau latéral, fichier compagnon.
7. **Layouts** : sauvegarde et chargement, réapplication sur un autre CSV, fichiers récents.
8. **Mesure** : tracker, curseurs A/B, statistiques.
9. **Séries calculées et export.**

## 11. Conventions

- Code et identifiants en anglais. Interface et messages utilisateur en français, centralisés (prêts pour QTranslator).
- Signaux Qt nommés `quelquechose_changed`. Pas de logique métier dans les slots d'UI.
- Pas de `print` : module `logging`, niveau réglable par `--debug`.
- Tests :
  - importeurs testés sur des CSV d'exemple dans `tests/data/` (dont un export Scope multi-en-têtes en virgule décimale) ;
  - aller-retour JSON de chaque dataclass de `model/` ;
  - tests pytest-qt pour le glisser-déposer et les axes secondaires.
- Après chaque phase, mets à jour la section « État d'avancement » ci-dessous.

## 12. Hors périmètre (pour l'instant)

- Flux temps réel (ADS, MQTT, ZMQ). Prévoir l'abstraction Dataset pour l'ajouter plus tard sans refonte.
- Formats autres que CSV/TSV.
- 3D.

## État d'avancement

- [x] Phase 1 — Squelette (18 tests verts ; smoke test : 10 M points, pire frame pan/zoom ≈ 46 ms en offscreen)
- [x] Phase 2 — Multi-fenêtres (docks, sous-graphes, synchro X par groupe, légende cliquable, mosaïque)
- [x] Phase 3 — Import avancé (dialogue, Scope multi-en-têtes, paires temps/valeur, unités, date/heure, alias, renommage, Ctrl+R, QThread)
- [x] Phase 4 — Personnalisation (PlotConfig/AxisConfig/CurveConfig, dialogues, menus contextuels, double-clics)
- [x] Phase 5 — Axes secondaires (ViewBox liées, molette par axe, déplacement de courbe, dépôt sur la marge droite, suppression auto)
- [x] Phase 6 — Annotations (4 types, déplacement, édition, Suppr, panneau, lignes liées, fichier compagnon)
- [x] Phase 7 — Layouts (*.cjl.json versionné, réapplication sur un autre CSV, séries manquantes signalées, récents, dernier layout)
- [x] Phase 8 — Mesure (tracker T synchronisé, interpolation/plus proche, curseurs A/B, statistiques A–B ou région, copie TSV)
- [x] Phase 9 — Séries calculées et export (formules sûres via ast, lowpass vectorisé, PNG/SVG graphe et fenêtre, presse-papiers, CSV)

### Décisions prises

- **Docks : `QDockWidget`** (pas `pyqtgraph.dockarea`). Raisons : onglets, détachement en fenêtre flottante et fenêtres natives gérés par Qt ; `QMainWindow.saveState/restoreState` pour la géométrie (stockée en base64 dans le layout JSON) ; meilleure intégration macOS/Windows. Les graphes vivent dans un `QMainWindow` interne (`MainWindow.plot_area`, widget central) pour ne jamais se mélanger aux panneaux latéraux (arbre des séries, annotations, mesures). Chaque `PlotDock` a un `objectName` stable (`plot_N`).
- **Textes UI** : centralisés dans `csvjuggler/i18n.py` (classe `Msg`, accès via `tr()` → `QCoreApplication.translate`).
- **Glisser-déposer** : type MIME `application/x-csvjuggler-series-ids`, liste d'identifiants séparés par `\n`. Glisser un nœud dataset = toutes ses séries.
- **Alias de dataset** : nom du fichier sans extension, `/` interdit (remplacé par `_`), suffixe `_2`, `_3`… si doublon. Les noms de colonne peuvent contenir `/` (on coupe au premier `/`).
- **pyqtgraph 0.14** : l'API réelle est `setDownsampling(auto=True, method='peak')` (et non `mode=`). `setDownsampling`/`setClipToView` doivent être appelés **après** `plotItem.addItem(item)`, sinon pyqtgraph interroge le QGraphicsView au lieu de la ViewBox et lève une exception.
- **Session** est un `QObject` (signal `datasets_changed`) : le modèle de l'arbre s'y abonne.
- **Sous-graphes** : `PlotWidget` est un `pg.GraphicsLayoutWidget` ; chaque sous-graphe (`SubPlot`) est un `PlotItem` dont l'axe X est lié (`setXLink`) au premier. Seul le dernier affiche les graduations X. `PlotConfig.subplots: list[SubplotConfig]` porte les courbes et le ratio.
- **Synchro X** : `ui/x_sync.py` (`XSyncManager`). `PlotConfig.sync_group` = `"global"` par défaut, `""` = non synchronisé, tout autre nom = groupe nommé. `PlotWidget.set_x_range` n'émet pas `x_range_changed` (pas de boucle).
- **Division de la zone** : « Diviser ↔ » / « Diviser ↕ » (barre d'outils du graphe et menu contextuel) crée un nouveau graphe à droite / en dessous du graphe courant (`MainWindow.split_plot`, `splitDockWidget`), dans le **même groupe de synchro X** et sur la même plage X. Si le graphe source n'était pas synchronisé, les deux rejoignent un nouveau groupe nommé « groupe N » (les autres graphes ne sont pas affectés). « + Sous-graphe » / « - Sous-graphe » gèrent les sous-graphes empilés d'un même graphe.
- **Barre « Lecture X »** (`ui/time_slider.py`, barre d'outils en bas, masquable via Fenêtre) : curseur sur l'étendue X de toutes les séries (`Session.x_extent()`), champ numérique, lecture/pause (vitesse x0.1 à x50 en unités de X par seconde, arrêt en fin de données) et « Suivre » (les graphes défilent pour garder le curseur visible). Elle pilote un `ValueCursor` par graphe (`PlotDock.playhead`, ligne orange, étiquette en bas) affiché sur **tous** les graphes, synchronisés ou non. `ValueCursor` est la base commune du tracker (`Tracker` = `ValueCursor` qui suit la souris, étiquette en haut). L'état de lecture n'est pas sauvegardé dans le layout.
- **Timeline multi-fichiers** (`ui/timeline.py`, dans la barre « Lecture X », remplace l'ancien curseur) : une ligne par fichier (`Session.dataset_extents()`, couleur `color_for_index`) sur l'étendue X de toutes les séries ; les fichiers enregistrés avec la même horloge absolue (colonne date/heure → secondes epoch, ou compteur commun) se placent donc les uns par rapport aux autres. Clic/glisser = position de lecture ; double-clic sur une ligne = cadrer le graphe courant (et son groupe de synchro) sur ce fichier (`MainWindow.frame_x`, marge 2 %) ; bande bleue = plage X visible du graphe courant (suivie via `sigXRangeChanged`). `Session.absolute_time()` (tous les fichiers en `time_unit="datetime"`) → graduations en heure (UTC, comme `DateAxis`) et étiquette date/heure complète à côté du champ numérique ; les étiquettes des curseurs affichent l'heure quand l'axe X est en mode absolu (`timeline.format_x`).
- **Thème** (`ui/theme.py`, appliqué dans `app.main`, **sur toutes les plateformes**) : style Fusion + palette claire **forcée** (le mode sombre de Windows donnerait des panneaux sombres autour de graphes blancs) + feuille de style « plate » (`STYLE_SHEET_TEMPLATE`, `@ASSETS`/`@ACCENT` remplacés par `style_sheet()`) : cases à cocher dessinées en **interrupteurs** (`QCheckBox::indicator` → SVG), champs et boutons arrondis, chevrons, barres de défilement fines, menus et infobulles arrondis. Dessins SVG dans `csvjuggler/ui/assets/` (package-data dans `pyproject.toml`). Police Segoe UI 9 pt et AppUserModelID sous Windows. Icône dessinée au démarrage (`app_icon`). Les tests n'appliquent pas le thème. Les boutons de couleur (`ColorButton`) ont leur propre style (couleur + arrondi). Dans la boîte à outils, libellés au-dessus des champs (`_stack_labels`, panneau étroit).
- **Barre d'outils d'un graphe** : Ajuster la vue, Curseurs A/B, puis trois menus : « Diviser ▾ » (↔, ↕, ± sous-graphe), « Fenêtre ▾ » (détacher/rattacher, plein écran, agrandir, moitié gauche/droite, déplacer vers l'écran N si plusieurs écrans) et « Graphe ▾ » (paramètres, renommer, effacer, fermer).
- **Graphe détaché** (`PlotDock.detach`) : dock flottant transformé en **vraie fenêtre** (`Qt.Window` + boutons min/max/fermer) → agrandissable, accrochage Windows (Win+←/→), entrée dans la barre des tâches. F11 = plein écran, Échap = sortie (raccourcis du dock, contexte `WidgetWithChildrenShortcut`). Moitié d'écran = `availableGeometry()` de l'écran courant, cadre de la fenêtre compensé. Le bouton fermer d'une fenêtre détachée **rattache** le graphe ; « Graphe ▾ → Fermer le graphe » (`close_plot`) le détruit — tout code qui ferme un dock doit appeler `close_plot()`. Fermer la fenêtre principale masque les graphes détachés (sinon l'application resterait ouverte). `saveState` ne mémorise pas ces fenêtres : `DockConfig.detached` + `window_geometry` (base64 de `saveGeometry()`, exclu du suivi des modifications) dans le projet.
- **Panneau Mesures** : se rafraîchit sur `sigXRangeChanged` de la ViewBox (qui couvre aussi les changements imposés par la synchro), avec un délai de 80 ms ; curseurs, config et sélection d'annotation → rafraîchissement immédiat.
- **Grille** : les axes pyqtgraph dessinent la grille au-dessus des courbes ; on leur donne `zValue = -1000`.
- **Fermeture d'un dock** = destruction (pas seulement masquage) ; « Tout fermer » laisse la zone vide, « Nouveau graphe » (Ctrl+N) en recrée un.
- **Import** : analyse ligne à ligne de la tête du fichier (200 lignes) → `data_start`, `header_row`, `unit_row` (indices de lignes physiques, 0-based ; affichés 1-based dans le dialogue), puis lecture pandas par blocs de 200 000 lignes (`header=None`, noms fournis) avec progression et annulation. `ImportSettings.time_mode` ∈ `column | pairs | index`, `time_unit` ∈ `s | ms | us | datetime` (date/heure → secondes epoch, heure naïve). Unités : ligne d'unités, sinon `Nom [unité]` / `Nom (unité)`.
- **TwinCAT Scope** (`scope_importer.py`) : reconnu par ≥ 2 lignes d'attributs (`SymbolName`, `SampleTime`, `DataType`…). Ligne des noms = dernière ligne commençant par `Name`, unités = ligne `Unit`. Les données sont en paires temps/valeur (le premier champ de la ligne `Name` est la clé, au-dessus de la 1re colonne de temps) ; temps par défaut en ms. Les valeurs NaN (canaux plus courts) sont retirées par série.
- **Tâches longues** : `ui/progress.py` (`run_with_progress`) exécute la fonction dans un `QThread` et attend dans un `QEventLoop` local avec un `QProgressDialog` : le code appelant reste séquentiel et l'UI ne gèle pas.
- **Dialogue d'import** : affiché pour Ctrl+O et le glisser-déposer de fichiers ; la CLI importe directement avec la détection automatique.
- **Renommage** : alias d'affichage `Series.display_name`, édité dans l'arbre (double-clic/F2), mémorisé dans `ImportSettings.renames` (donc dans le layout). L'alias de dataset n'est modifiable qu'à l'import (il fait partie des identifiants de séries).
- **Rechargement** (Ctrl+R) : `Session.replace_data` remplace les séries et émet `series_data_changed` ; les graphes font `setData` sur les items existants.
- **Personnalisation** : `ui/plot_items.py` fournit `PlotViewBox` (clic droit / double-clic remontés en signaux, menu pyqtgraph remplacé), `FormattedAxis` (format des graduations : décimales, scientifique, préfixes SI ; clic droit / double-clic) et `DateAxis` (axe X absolu, secondes epoch, `utcOffset=0`). `ui/plot_menus.py` (`PlotController`) transforme ces demandes en menus/dialogues ; les phases suivantes ajoutent leurs entrées via `menu_extensions` / `curve_menu_extensions`. Couleur : `ui/widgets.py` (`ColorButton`).
- **Plages d'axes** : `apply_config` ne retouche la plage d'un axe que si `(auto_range, min, max, log, inverted)` a changé ; un changement de style conserve donc le zoom de l'utilisateur. « Auto une fois » = ajuster puis mémoriser en plage manuelle.
- **Mode XY et sous-échantillonnage** (`plot_widget._set_sampling`) : le « peak » automatique et `clipToView` supposent un X croissant (blocs découpés selon X, pas déduit de `x[-1] - x[0]`) ; en mode XY ils appairent des x et y d'échantillons différents (courbe en zigzag). En mode XY : pas de `clipToView`, et `subsample` (1 point sur k, paires conservées) seulement au-delà de `XY_MAX_POINTS` = 500 000 points. Le mode temps garde `peak` + `clipToView` ; `_move_to_view` restaure l'état de clip de l'item au lieu de le forcer.
- **Données affichées** : `setData` seulement si la série, le gain/offset, le mode ou la série X (mode XY) ont changé. Mode escalier = `stepMode="left"` (maintien). Mode XY : la série X est interpolée sur le vecteur X de chaque courbe si besoin.
- **Axes secondaires** (`ui/multi_axis.py`) : ViewBox de premier niveau dans la scène, `zValue` sous le PlotItem → la zone de tracé (glisser, molette) ne pilote que X et l'axe principal ; la molette/le glisser sur un axe secondaire n'agit que sur lui (`SecondaryViewBox` ignore les événements sans `axis`). Géométrie = position de la ViewBox principale + `size()` (pas `sceneBoundingRect()`, qui ajoute 0,5 px). `PlotViewBox.childrenBounds` agrège l'étendue X des vues secondaires pour l'auto-range X. Axes secondaires placés **à droite** uniquement (colonnes 3, 4… du layout du PlotItem) ; `AxisConfig.side` est réservé pour un placement à gauche ultérieur.
- **Axe sans courbe** : `SubplotConfig.prune_axes()` est appelé à chaque `_commit` (l'axe principal est toujours conservé).
- **Piège pyqtgraph** : désactiver `clipToView` pendant qu'un item change de ViewBox (`_move_to_view`, `MultiAxis._remove`), sinon exception (même cause que pour `addItem`).
- **Dépôt sur la marge droite** : à moins de 40 px du bord droit de la zone de tracé, ou au-delà (zone des axes secondaires) → nouvel axe.
- **Annotations** : `AnnotationStore` (dans `Session.annotations`) est la seule source de vérité ; il stocke et renvoie des **copies** (toute modification passe par `update`, qui émet le signal). `ui/annotation_items.py` : `AnnotationManager` (placement + opérations), `AnnotationLayer` (items d'un graphe, reconstruits quand l'annotation change), items pyqtgraph sous-classés pour les clics (droit = menu, double = édition). Placement : graphe/sous-graphe d'origine (`plot_id` = id de dock) ; ligne verticale `link_all` → tous les sous-graphes des graphes du même groupe de synchro ; si le graphe d'origine n'existe pas (fichier compagnon rouvert seul) → premier sous-graphe de chaque graphe montrant une série du dataset. Annotations ajoutées avec `ignoreBounds=True` (n'influencent pas l'auto-range).
- **Annotation texte = bulle** : `TextAnnotationItem` est un `GraphicsObject` dessiné à la main (rectangle arrondi, bordure de la couleur de l'annotation, fond = `text_background` ou transparent, ombre légère). Taille en pixels obtenue comme `pg.TextItem` : l'item annule l'échelle de la vue par sa propre transformation (`_update_transform`). **Ne pas utiliser `ItemIgnoresTransformations`** : pyqtgraph ne trouve alors plus l'item sous la souris (glisser impossible). Avec `arrow`, la bulle est décalée en haut à droite et une pointe désigne le point (petit disque) ; sans, le coin bas-gauche de la bulle est le point. `Annotation.show_coords` (défaut : oui) ajoute une ligne `x = … s   y = … unité` (unité de l'axe, sinon de sa première courbe ; date/heure si X absolu), mise à jour pendant le glisser.
- **Fichier compagnon** : `<nom complet du CSV>.annotations.json` (ex. `essai.csv.annotations.json`), écrit 500 ms après la dernière modification (et à la fermeture), écriture atomique (fichier `.tmp` + `replace`). Créé seulement si le dataset a des annotations (ou mis à jour s'il existe déjà). Rechargé dans `Session.add_dataset` ; l'alias et le chemin sont réécrits avec ceux du dataset courant.
- **Panneau d'annotations** : `ui/annotation_panel.py`, dock à gauche sous l'arbre des séries ; clic = centrer la vue (largeur de zoom conservée), double-clic = éditer, Suppr = supprimer.
- **Layout** (`model/layout.py`) : `Layout{version, datasets[DatasetRef(alias, path, import_settings)], docks[DockConfig(dock_id, title, plot)], dock_state, window_state, annotations, derived}`. Disposition des docks = `QMainWindow.saveState()` (zone des graphes et fenêtre principale) en base64 ; les `dock_id` sont conservés (référencés par `saveState` et par `Annotation.plot_id`). `migrate()` gère la v0 (liste `curves` à plat). Écriture atomique.
- **Chargement d'un layout** : pour chaque dataset du layout, dans l'ordre : fichier de remplacement (`-l` + fichiers en CLI, ou `file_overrides`) → dataset déjà chargé sous le même alias → chemin enregistré → fichier de même nom à côté du layout → (interactif) demande d'un fichier de remplacement. Le fichier est relu avec les `import_settings` du layout et **l'alias du layout** (les identifiants de séries restent valides). Les séries manquantes restent dans la config (elles réapparaissent si un fichier complet est chargé) et sont signalées (barre d'état + boîte d'info en interactif), jamais bloquantes. Les annotations : `reload_companions()` puis fusion de celles du layout (par id, le layout gagne).
- **Mesure** : calculs purs dans `data/analysis.py` (`value_at`, `interval_stats`, `to_tsv`). `ui/cursors.py` : `Tracker` (un par graphe, activé globalement par T ; la position est propagée aux graphes du même groupe de synchro) et `ABCursors` (par graphe, bouton « Curseurs A/B » ou Ctrl+B ; lignes recopiées dans chaque sous-graphe). Les valeurs sont celles **affichées** (gain/offset appliqués ; en mode XY → point le plus proche). Panneau `ui/measure_panel.py` (dock en bas) pour le graphe courant : Δt, 1/Δt, Y(A), Y(B), ΔY, et statistiques sur [A, B] si les curseurs sont actifs, sinon sur la région d'annotation sélectionnée, sinon sur la plage X visible. « Copier (TSV) » → presse-papiers.
- **Tests** : ne jamais créer d'annotation sur un CSV de `tests/data/` (fichier compagnon écrit à côté) — copier le CSV dans `tmp_path`. Une fixture autouse de `conftest.py` échoue sinon.
- **Séries calculées** (`data/derived.py`) : la formule est analysée par `ast` puis validée (liste blanche : nombres, variables, `+ - * / ** %`, comparaisons, constantes `pi`/`e`, fonctions `derivative`, `integral`, `lowpass(a, fc)`, `abs`, `sqrt`, `exp`, `log`, `log10`, `sin`, `cos`, `tan`, `minimum`, `maximum`, `clip`) et évaluée par un interpréteur d'arbre maison — **aucun `eval`**. Les variables sont rééchantillonnées sur le X de la première variable. `lowpass` = 1er ordre causal, calcul vectorisé par blocs (exact à 1e-13 près face à la récurrence). Les séries vivent dans le dataset virtuel réservé `calc` (`calc/<nom>`), recalculées à chaque ajout/rechargement de fichier ; une formule devenue invalide est signalée (`Session.derived_errors`), sans exception. Sauvegardées dans `Layout.derived`.
- **Export** : PNG d'un graphe = `pyqtgraph.exporters.ImageExporter(scene)` (toute la scène : les ViewBox secondaires sont des items de premier niveau). SVG = `QSvgGenerator(SvgVersion.Svg11)` + `setResolution(widget.logicalDpiX())` — le `SVGExporter` de pyqtgraph 0.14 plante sur les chemins SVG de Qt 6.12, SVG Tiny perd le clipping et 72 dpi décale la mise en page. Fenêtre entière = rendu de la zone des graphes. CSV (`data/export.py`) : valeurs brutes des séries (sans gain/offset), une colonne de temps si X commun, sinon paires temps/valeur ; plage visible, A–B ou région sélectionnée.
- **Bulle sur une courbe** (`kind="bubble"`) : `Annotation.series_id` (courbe), `offset_x/offset_y` (coin bas-gauche de la bulle par rapport au point, en pixels, y vers le bas). Le y du point n'est pas une donnée : il est recalculé à l'affichage (`_curve_y` = valeur **affichée**, NaN hors des données → bulle masquée ; masquée aussi si la courbe l'est ; pas d'item si la courbe n'est plus dans le sous-graphe). `BubbleAnnotationItem` : glisser à moins de 8 px du point = glisser le long de la courbe (`hub.moved`), ailleurs = déplacer la bulle (`hub.offset_changed`). L'item vit **toujours dans la ViewBox principale** : les ViewBox secondaires sont sous le PlotItem, la grille et les autres courbes passeraient dessus. Pour une courbe sur un axe secondaire, `attach(data_view)` convertit le y via la scène et re-place le point sur `sigRangeChanged`/`sigResized` des deux vues (`detach` au retrait). `AnnotationLayer` mémorise un « contexte » par bulle (config de la courbe, identité de la série, mode X) et reconstruit l'item s'il change ; `series_data_changed` déclenche aussi `refresh`. Placement : sous-graphe d'origine s'il montre encore la courbe, sinon chaque graphe qui la montre. Menu : « Ajouter une annotation → Bulle sur « courbe » » (courbe sous la souris) ou « Bulle sur une courbe → … » (une entrée par courbe visible). Forme de clic = contour **uni** (`united`) avec le disque du point : avec `addEllipse`, la règle pair-impair crée un trou au recouvrement.
- **Écart Δ** (`kind="delta"`) : point A = (`series_id`, `x`), point B = (`series_id_b`, `x2`). `DeltaAnnotationItem` est enfant **direct de la ViewBox principale** (pas de son `childGroup`) : ses coordonnées sont des pixels, recalculées (`relayout`) sur `sigRangeChanged`/`sigResized` de la vue principale et des vues des deux courbes. Glisser un point le fait glisser le long de sa courbe ; près d'une autre courbe du sous-graphe (`curve_near`), il s'y accroche ; hors des données, il reste en place. Un glisser ailleurs que sur un point est ignoré (la vue se déplace). Fin du glisser → `hub.delta_moved` → `set_delta_points`. Créé par le menu (« Écart Δ sur « courbe » », B à +15 % de la largeur de vue, sans dialogue). Valeurs de l'étiquette au choix : `show_dx`, `show_inv_dx` (1/Δx en Hz si X en s, sinon `1/unité`), `show_dy` (dialogue et cases du menu clic droit, `AnnotationManager.toggle_flag`) ; sans valeur ni texte, pas d'étiquette (les cotes restent). Style des cotes `line_style` (`solid`/`dash`/`dot`, `LINE_STYLES`). Étiquette déplaçable : glisser dessus → `label_dx/label_dy` (pixels, via `hub.offset_changed` ; `set_offset` écrit `label_*` pour un écart, `offset_*` pour une bulle), trait de rappel pointillé vers le milieu de la cote verticale, « Replacer l'étiquette » dans le menu ; position par défaut basculée de l'autre côté de la cote si elle sortait de la zone de tracé. Glisser un trait de cote déplace toujours la vue. Placement/contexte comme la bulle.
- **Boîte à outils** (`ui/toolbox.py`, dock à droite, Fenêtre → Boîte à outils) : suit le graphe courant (`MainWindow._set_current` → `set_dock`), comme le panneau Mesures. Sections (`QToolBox`) : Graphe (`PlotGeneralWidget` + boutons Axe X/Axe Y/Tous les paramètres), Courbes (liste + `CurveSettingsWidget`, Axe Y de la courbe, Retirer), Annotations (un bouton par type, placé au centre de la vue ; bulle/écart sur la courbe sélectionnée dans « Courbes », sinon la première visible ; modifier/supprimer l'annotation sélectionnée). Application **en direct** par `update_config` / `set_curve_config` (pas de bouton OK) ; rafraîchi sur `config_changed`. Les formulaires sont partagés avec les dialogues : `PlotGeneralWidget` (onglet Général de `PlotSettingsDialog`) et `CurveSettingsWidget` (`CurveSettingsDialog.editor`) ; signal `changed` à chaque modification (champs texte : fin d'édition), `set_config`/`set_curve` sous `QSignalBlocker`.
- **Signaux du hub d'annotations en connexion différée** (`QueuedConnection`) : déplacer/éditer/supprimer reconstruit l'item qui a émis la demande depuis son gestionnaire souris ; le détruire pendant son propre événement fait planter Qt (« shared QObject was deleted directly », segfault). Dans les tests, attendre (`qtbot.waitUntil`) après une action souris ou clavier sur une annotation.
- **Piège PySide (plantage à la sortie)** : un widget créé **sans parent** puis ajouté à un layout lui-même sans parent reste « possédé par Python » ; Qt le détruit avec son dialogue, puis PySide le détruit encore en quittant (`QPushButtonWrapper::~` dans `destroyQCoreApplication`, « shared QObject was deleted directly », segfault 139). Les boutons créés en Python reçoivent donc leur parent dès la construction (`QPushButton(texte, self)`), et tous les dialogues dérivent de `ui/widgets.py:DisposableDialog` (détruit par `deleteLater` à la fin de `exec()`, au lieu de s'accumuler sous la fenêtre principale).
- **Projet = layout** : dans l'interface, le layout s'appelle « projet » (Ouvrir / Enregistrer / Enregistrer sous / Projets récents) ; le format reste `*.cjl.json`. Suivi des modifications : instantané JSON du layout **sans** `dock_state`/`window_state` (déplacer/zoomer n'est pas une modification), comparé à celui du dernier enregistrement/chargement (`MainWindow.mark_saved`, `is_modified`), vérifié 200 ms après un signal (session, annotations, config ou titre d'un graphe, ajout/fermeture de dock). Titre `nom.cjl.json[*] — CsvJuggler` (`setWindowModified`). Fermeture, ouverture d'un projet ou d'un projet récent → `maybe_save()` (Enregistrer / Ne pas enregistrer / Annuler). `MainWindow.confirm_unsaved` est mis à `False` par une fixture autouse des tests (sinon la boîte bloque).
- **QSettings** : `recent_files`, `recent_layouts` (10 max), `last_layout` (dernier layout enregistré/ouvert, rechargé au démarrage sans argument). `MainWindow` reçoit un `QSettings` (fichier ini temporaire dans les tests).
- **CLI** : `csvjuggler fichier.csv` importe directement ; `csvjuggler fichier.csv -l layout.cjl.json` applique le layout en remplaçant ses fichiers dans l'ordre ; sans argument, restaure le dernier layout.
- Environnement de dev : `python -m venv .venv && .venv/bin/pip install -e '.[dev]'` ; tests en `QT_QPA_PLATFORM=offscreen` (forcé dans `tests/conftest.py`).
