# xdg-types

Pick which app opens each file type (the XDG `mimeapps.list` defaults), from a
Quickshell overlay instead of digging through KDE/Settings panels.

Two files:

| file | role |
|------|------|
| `xdgtypes.py` | Python 3 stdlib only. Scans the shared-mime-info DB, every `.desktop` file and every `mimeapps.list`/`defaults.list`/`mimeinfo.cache` into a SQLite index, answers queries as one line of JSON, and writes changes with `xdg-mime`. |
| `shell.qml` | Quickshell 0.3 layer-shell overlay: search + filter chips (all / have a default / no default), green dot marks a type that already has one, and an app picker listing every installed app (click = set default, "Remove default" = unset). |

The UI is Qt (Quickshell), not GTK — this machine has no PyGObject/gjs/Vala, and
Quickshell is the GUI runtime already installed. What it *edits* is the XDG
database GTK, Qt and KDE all read, so the change applies everywhere.

## Run

```
qs -p ~/External/Data/Projects/xdg-types          # or: --no-duplicate to keep one instance
```

Escape or a click outside the card closes it. Hyprland hotkey:

```
bind = $mainMod, M, exec, qs -p ~/External/Data/Projects/xdg-types -n
```

Index cache: `~/.local/state/xdg-types/index.db` (rebuilt on each start, ~0.5 s).

## CLI

```
python3 xdgtypes.py build              # rescan (runs automatically)
python3 xdgtypes.py types [QUERY] [all|set|unset]   # id, description or extension search
python3 xdgtypes.py apps <MIME> [QUERY]            # every installed app, handles/current flags
python3 xdgtypes.py set <MIME> <APP>   # xdg-mime default
python3 xdgtypes.py unset <MIME>       # drop the user default; the system default comes back
python3 xdgtypes.py test [N]           # assert the index agrees with `xdg-mime query default`
```

## Not included

App icons in the picker (text names only), and adding an app to a type's
association list without making it the default — `set` writes the default.
Types that are configured come first, but the list is still capped at 200 rows
per query; narrow it with the search box.
