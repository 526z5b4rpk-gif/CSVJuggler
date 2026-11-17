"""User-facing texts (French), centralised and routed through Qt's translation system.

Every string shown to the user must be declared in :class:`Msg` and displayed via :func:`tr`,
so that a ``QTranslator`` can later provide other languages.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

CONTEXT = "CsvJuggler"


def tr(text: str) -> str:
    """Translate a source text from :class:`Msg`."""
    return QCoreApplication.translate(CONTEXT, text)


class Msg:
    """French source texts."""

    APP_NAME = "CsvJuggler"

    # Menus / actions
    MENU_FILE = "&Fichier"
    MENU_WINDOW = "Fe&nêtre"
    ACTION_OPEN = "&Ouvrir un CSV…"
    ACTION_QUIT = "&Quitter"
    ACTION_RELOAD = "&Recharger les fichiers"
    CANCEL = "Annuler"
    PROGRESS_IMPORT = "Import de « {name} »…"
    PROGRESS_RELOAD = "Rechargement de « {name} »…"
    ACTION_AUTO_RANGE = "Ajuster la vue"
    ACTION_CLEAR_PLOT = "Effacer le graphe"
    ACTION_SPLIT = "Diviser"
    ACTION_UNSPLIT = "Retirer un sous-graphe"
    ACTION_RENAME = "Renommer…"
    ACTION_NEW_PLOT = "&Nouveau graphe"
    ACTION_TILE = "&Mosaïque automatique"
    ACTION_CLOSE_ALL = "&Tout fermer"

    # Docks
    DOCK_SERIES = "Séries"
    DOCK_PLOT = "Graphe {index}"
    FILTER_PLACEHOLDER = "Filtrer les séries…"

    # Dialogs
    RENAME_PLOT_TITLE = "Renommer le graphe"
    RENAME_PLOT_LABEL = "Nom du graphe :"
    OPEN_DIALOG_TITLE = "Ouvrir des fichiers CSV"
    OPEN_DIALOG_FILTER = "Fichiers CSV (*.csv *.tsv *.txt);;Tous les fichiers (*)"
    IMPORT_ERROR_TITLE = "Erreur d'import"
    IMPORT_ERROR_TEXT = "Impossible d'importer « {path} » :\n{error}"

    IMPORT_TITLE = "Importer « {name} »"
    IMPORT_ALIAS = "Alias du fichier :"
    IMPORT_ENCODING = "Encodage :"
    IMPORT_DELIMITER = "Séparateur de colonnes :"
    IMPORT_DECIMAL = "Séparateur décimal :"
    IMPORT_HEADER_ROW = "Ligne des noms :"
    IMPORT_UNIT_ROW = "Ligne des unités :"
    IMPORT_DATA_START = "Début des données (ligne) :"
    IMPORT_TIME_MODE = "Temps :"
    IMPORT_TIME_COLUMN = "Colonne de temps :"
    IMPORT_TIME_UNIT = "Unité de temps :"
    IMPORT_DATETIME_FORMAT = "Format date/heure :"
    IMPORT_DATETIME_HINT = "auto (ex. %d/%m/%Y %H:%M:%S)"
    IMPORT_NONE = "Aucune"
    IMPORT_SCOPE_DETECTED = "Export TwinCAT Scope détecté"
    IMPORT_FILE_PREVIEW = "Début du fichier"
    IMPORT_SERIES = "Séries"
    IMPORT_COL_NAME = "Colonne"
    IMPORT_COL_UNIT = "Unité"
    IMPORT_COL_ALIAS = "Alias"
    DELIM_COMMA = "Virgule (,)"
    DELIM_SEMICOLON = "Point-virgule (;)"
    DELIM_TAB = "Tabulation"
    DECIMAL_DOT = "Point (.)"
    DECIMAL_COMMA = "Virgule (,)"
    TIME_MODE_COLUMN = "Une colonne de temps"
    TIME_MODE_PAIRS = "Paires temps/valeur (une colonne de temps par canal)"
    TIME_MODE_INDEX = "Index de ligne"
    TIME_UNIT_S = "secondes"
    TIME_UNIT_MS = "millisecondes"
    TIME_UNIT_US = "microsecondes"
    TIME_UNIT_DATETIME = "date/heure"

    # Status bar
    STATUS_LOADED = "« {alias} » chargé : {count} séries, {points} points"
    STATUS_MISSING_SERIES = "Série introuvable : {series_id}"
    STATUS_RELOADED = "{count} fichier(s) rechargé(s)"
