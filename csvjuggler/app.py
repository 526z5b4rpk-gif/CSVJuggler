"""Entry point: ``csvjuggler [fichier.csv ...] [-l layout.json] [--debug]``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from csvjuggler.i18n import Msg
from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui.theme import apply_theme

log = logging.getLogger("csvjuggler")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="csvjuggler", description="Visualiseur de CSV")
    parser.add_argument("files", nargs="*", help="fichiers CSV à ouvrir")
    parser.add_argument(
        "-l",
        "--layout",
        help="layout à charger (*.cjl.json) ; les fichiers donnés remplacent ceux du layout",
    )
    parser.add_argument("--debug", action="store_true", help="journalisation détaillée")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    app.setApplicationName(Msg.APP_NAME)
    app.setOrganizationName(Msg.APP_NAME)
    pg.setConfigOptions(antialias=False, background="w", foreground="k")
    apply_theme(app)

    session = Session()
    window = MainWindow(session)
    window.show()
    if args.layout:
        window.load_layout(args.layout, file_overrides=args.files, interactive=False)
    elif args.files:
        window.open_files(args.files, interactive=False)
    else:
        window.restore_last_layout()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
