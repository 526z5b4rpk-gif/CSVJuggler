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

    # Status bar
    STATUS_LOADED = "« {alias} » chargé : {count} séries, {points} points"
    STATUS_MISSING_SERIES = "Série introuvable : {series_id}"
