# CsvJuggler

Visualiseur de séries temporelles issues de fichiers CSV, inspiré de PlotJuggler.
Il est pensé pour les exports TwinCAT Scope et les acquisitions de mesures industrielles.

Fonctions principales :

- graphes multiples en docks, avec synchronisation de l'axe X ;
- axes Y secondaires et annotations ;
- curseurs de mesure et statistiques ;
- séries calculées ;
- export PNG, SVG et CSV.

## Installation sur un nouveau PC

### 1. Prérequis

| Outil | Version | Vérification |
|---|---|---|
| Python | 3.11 ou plus récent | `python3 --version` (Windows : `py --version`) |
| Git | toute version récente | `git --version` |

Si Python ou Git manquent, installe-les selon ton système.

**Windows**

Télécharge Python sur <https://www.python.org/downloads/>. Pendant l'installation, coche « Add python.exe to PATH ».
Télécharge Git sur <https://git-scm.com/download/win>.

**macOS**

Installe d'abord [Homebrew](https://brew.sh), puis lance :

```bash
brew install python@3.12 git
```

**Linux (Debian / Ubuntu)**

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git libxcb-cursor0 libegl1
```

Les paquets `libxcb-cursor0` et `libegl1` sont nécessaires à Qt (PySide6) pour ouvrir une fenêtre.

### 2. Récupérer le code

```bash
git clone https://github.com/526z5b4rpk-gif/CSVJuggler.git
cd CSVJuggler
```

### 3. Créer l'environnement virtuel et installer

L'environnement virtuel `.venv` isole les dépendances du projet (PySide6, pyqtgraph, pandas, numpy) du reste du système.

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

> Si PowerShell refuse d'exécuter le script d'activation, lance une fois
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis recommence.

### 4. Lancer

L'environnement virtuel doit être activé (voir l'étape 3).

```bash
csvjuggler                              # rouvre le dernier projet utilisé
csvjuggler mon_fichier.csv              # ouvre un CSV (détection automatique)
csvjuggler mon_fichier.csv -l essai.cjl.json   # applique un projet à ce CSV
csvjuggler --debug mon_fichier.csv      # journal détaillé dans le terminal
```

Tu peux aussi lancer le logiciel sans activer l'environnement :

- macOS / Linux : `.venv/bin/csvjuggler`
- Windows : `.venv\Scripts\csvjuggler.exe`

### 5. Mettre à jour

```bash
cd CSVJuggler
git pull
pip install -e .        # avec l'environnement activé, au cas où les dépendances ont changé
```

## Installation pour le développement

Pour lancer les tests et les outils qualité (pytest, pytest-qt, ruff, mypy), installe les dépendances de développement :

```bash
pip install -e '.[dev]'
```

Puis lance les commandes suivantes :

```bash
pytest                  # tests
ruff check . && ruff format --check .
mypy csvjuggler
```

Sous Linux sans écran (CI, SSH), les tests passent en mode `offscreen` : il est forcé dans `tests/conftest.py`.

Les règles du projet (architecture, conventions, décisions techniques) sont dans [CLAUDE.md](CLAUDE.md).

## Utilisation rapide

- **Ouvrir un CSV** : `Ctrl+O`, ou glisser-déposer le fichier sur la fenêtre.
- **Tracer une série** : glisser-la depuis l'arbre de gauche vers un graphe.
  La déposer sur la marge droite du graphe crée un axe Y secondaire.
- **Recharger le fichier** : `Ctrl+R`.
- **Projet** : `Ctrl+S` pour enregistrer, `Ctrl+L` pour ouvrir (fichiers `*.cjl.json`).
  Un projet contient les fichiers CSV utilisés, les graphes, les annotations et les séries calculées.
  Une `*` dans le titre signale des modifications non enregistrées ; à la fermeture, le logiciel propose de les enregistrer.
- **Nouveau graphe** : `Ctrl+N`. Les boutons « Diviser ↔ / ↕ » partagent la zone en gardant la synchro X.
- **Mesure** :
  - `T` active le tracker ;
  - `Ctrl+B` affiche les curseurs A/B ;
  - le panneau « Mesures » affiche les statistiques, copiables en TSV.
- **Lecture X** : la barre en bas de la fenêtre déplace un curseur sur tous les graphes, avec lecture/pause.
- **Annotations** : clic droit sur le graphe → « Ajouter une annotation ».
  « Bulle sur une courbe » accroche le point à la courbe et affiche ses coordonnées.
  Glisser la bulle la déplace (le point reste accroché), glisser le point le fait glisser le long de la courbe.
- **Boîte à outils** (panneau de droite, menu Fenêtre) : réglages du graphe courant et de ses courbes appliqués en direct, et un bouton par type d'annotation.
  L'« Écart Δ » mesure Δx, 1/Δx et Δy entre deux points accrochés à des courbes.
- **Personnaliser** : clic droit sur un graphe, un axe, une courbe ou une annotation. Double-clic sur le fond pour les paramètres du graphe.

## Dépannage

| Problème | Solution |
|---|---|
| `csvjuggler: command not found` | L'environnement virtuel n'est pas activé (étape 3) ou l'installation `pip install -e .` n'a pas été faite. |
| Linux : `Could not load the Qt platform plugin "xcb"` | Installer `libxcb-cursor0` (voir les prérequis). |
| `requires a different Python` | La version de Python est trop ancienne : il faut 3.11 ou plus. |
| Accents illisibles dans un CSV | Dans le dialogue d'import, choisir l'encodage `cp1252` au lieu d'UTF-8. |
