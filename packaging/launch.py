"""Entry script of the packaged application (PyInstaller needs a script, not a module)."""

from csvjuggler.app import main

raise SystemExit(main())
