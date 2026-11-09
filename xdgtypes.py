#!/usr/bin/env python3
"""XDG file-type -> default app store, indexed in SQLite.

    xdgtypes.py build                 rebuild the index (scan mime db + .desktop files)
    xdgtypes.py types [QUERY] [all|set|unset]  -> [{id, descr, default, defaultName}]
    xdgtypes.py apps <MIME> [QUERY]           -> [{id, name, handles, isDefault}] all apps
    xdgtypes.py set <MIME> <APP>    -> xdg-mime default, then update the index
    xdgtypes.py unset <MIME>        -> drop the default from the user's mimeapps.list
    xdgtypes.py test [N]            -> assert the index matches `xdg-mime query default`

All queries print a single line of JSON.
"""
import json
import os
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

STATE = Path(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")))
DB = STATE / "xdg-types" / "index.db"
LIMIT = 200
SECTION = "Default Applications"


def data_dirs():
    dirs = [os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))]
    dirs += (os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")).split(":")
    return [Path(d) for d in dirs if d]


def config_dirs():
    out = [os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))]
    out += (os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg")).split(":")
    return [Path(d) for d in out if d]


def menu_prefix():
    """xdg-utils looks for `<XDG_MENU_PREFIX>defaults.list` before the plain one."""
    return os.environ.get("XDG_MENU_PREFIX", "")


def read_desktop(path):
    """Flat key/value of the [Desktop Entry] section; first value wins."""
    out, section = {}, None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif section == "Desktop Entry" and "=" in line:
            key, value = line.split("=", 1)
            out.setdefault(key.split("[")[0], value)
    return out


def entries(path, section):
    """`mime=first-app` lines of a mimeapps.list (section filtered) or a cache file."""
    if not path.is_file():
        return
    current = None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("["):
            current = line.strip("[]")
            continue
        if section and current != section:
            continue
        mime, _, apps = line.partition("=")
        if apps:
            yield mime, apps.split(";")[0]


def read_defaults(con):
    """Current defaults, in the same order and files as `xdg-mime query default`."""
    prefix = menu_prefix()

    def keep(files, section=None):
        for path in files:
            for mime, app in entries(path, section):
                con.execute(
                    "INSERT OR IGNORE INTO prefs(mime_id, app_id) VALUES(?,?)",
                    (mime, app),
                )

    for home in config_dirs():
        keep([home / f"{prefix}mimeapps.list", home / "mimeapps.list"], SECTION)
    for d in data_dirs():
        a = d / "applications"
        keep([a / f"{prefix}mimeapps.list", a / "mimeapps.list"], SECTION)
    for d in data_dirs():
        a = d / "applications"
        for p in (prefix, ""):
            keep([a / f"{p}defaults.list", a / f"{p}mimeinfo.cache"])


def tag(node):
    """Local name of an XML element, ignoring its namespace."""
    return node.tag.rsplit("}", 1)[-1]


def read_globs(path, prioritized):
    """`globs`/`globs2` lines: [priority,]mime,pattern (separator varies by version)."""
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("#"):
            continue
        parts = line.split(",", 2)
        if len(parts) < 3:
            parts = line.split(":", 2)
        if prioritized and len(parts) == 3:
            yield parts[1], parts[2]
        elif not prioritized and len(parts) == 2:
            yield parts[0], parts[1]


def build():
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE mime(id TEXT PRIMARY KEY, descr TEXT, parent TEXT);
        CREATE TABLE glob(mime_id TEXT, pat TEXT);
        CREATE TABLE alias(id TEXT PRIMARY KEY, mime_id TEXT);
        CREATE TABLE app(id TEXT PRIMARY KEY, name TEXT, path TEXT);
        CREATE TABLE supports(app_id TEXT, mime_id TEXT);
        CREATE TABLE prefs(mime_id TEXT PRIMARY KEY, app_id TEXT);
        """
    )

    for d in (p / "mime" for p in data_dirs()):
        for name, prioritized in (("globs2", True), ("globs", False)):
            path = d / name
            if path.is_file():
                for mime, pat in read_globs(path, prioritized):
                    con.execute("INSERT OR IGNORE INTO mime(id) VALUES(?)", (mime,))
                    con.execute(
                        "INSERT INTO glob(mime_id, pat) VALUES(?,?)", (mime, pat)
                    )
                break
        aliases = d / "aliases"
        if aliases.is_file():
            for line in aliases.read_text(errors="replace").splitlines():
                if "=" in line and not line.startswith("#"):
                    alias, mime = line.split("=", 1)
                    con.execute(
                        "INSERT OR IGNORE INTO alias(id, mime_id) VALUES(?, ?)",
                        (alias.strip(), mime.strip()),
                    )
        for xml in (d.rglob("*.xml") if d.is_dir() else []):
            try:
                root = ET.parse(xml).getroot()
            except (ET.ParseError, OSError):
                continue
            for node in root.iter():
                if tag(node) != "mime-type" or not node.get("type"):
                    continue
                mime = node.get("type")
                descr = next((c.text for c in node if tag(c) == "comment" and not c.attrib), None)
                parent = next((c.get("type") for c in node if tag(c) == "parent"), None)
                con.execute(
                    """INSERT INTO mime(id, descr, parent) VALUES(?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         descr = COALESCE(descr, excluded.descr),
                         parent = COALESCE(parent, excluded.parent)""",
                    (mime, descr, parent),
                )

    for d in (p / "applications" for p in data_dirs()):
        if not d.is_dir():
            continue
        for path in d.rglob("*.desktop"):
            entry = read_desktop(path)
            name = entry.get("Name")
            if not name:
                continue
            con.execute(
                "INSERT OR IGNORE INTO app(id, name, path) VALUES(?,?,?)",
                (path.name, name, str(path)),
            )
            for mime in entry.get("MimeType", "").split(";"):
                if mime:
                    con.execute(
                        "INSERT INTO supports(app_id, mime_id) VALUES(?,?)",
                        (path.name, mime),
                    )

    read_defaults(con)
    con.commit()
    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("mime", "app", "supports", "prefs")
    }
    print(json.dumps(counts))


def chain(con, mime):
    """The mime and its parents, aliases resolved; used for app inheritance."""
    out = []
    cur = con.execute("SELECT mime_id FROM alias WHERE id=?", (mime,)).fetchone()
    cur = cur[0] if cur else mime
    while cur and cur not in out:
        out.append(cur)
        cur = con.execute("SELECT parent FROM mime WHERE id=?", (cur,)).fetchone()
        cur = cur[0] if cur else None
    return out


def types(con, query, only="all"):
    q = f"%{query.strip().lstrip('.')}%"
    # all/set/unset; configured types are listed first so the real state comes before the empty half of the registry
    extra = {"set": " AND p.app_id IS NOT NULL", "unset": " AND p.app_id IS NULL"}.get(
        only, ""
    )
    rows = con.execute(
        """SELECT m.id, COALESCE(m.descr,''), COALESCE(p.app_id,''), COALESCE(a.name,'')
           FROM mime m
           LEFT JOIN prefs p ON p.mime_id = m.id
           LEFT JOIN app a ON a.id = p.app_id
           WHERE (m.id LIKE ? OR COALESCE(m.descr,'') LIKE ?
                  OR EXISTS(SELECT 1 FROM glob g WHERE g.mime_id = m.id AND g.pat LIKE ?))"""
        + extra
        + " ORDER BY p.app_id IS NULL, m.id LIMIT ?",
        (q, q, q, LIMIT),
    ).fetchall()
    return [
        {"id": r[0], "descr": r[1], "default": r[2], "defaultName": r[3]} for r in rows
    ]


def apps(con, mime, query=""):
    """Every installed app, marked with whether it handles this type; current default first."""
    mimes = chain(con, mime)
    handles = set()
    for app_id, declared in con.execute(
        f"""SELECT app_id, mime_id FROM supports
            WHERE mime_id IN ({','.join('?' * len(mimes))}) OR mime_id LIKE '%/*'""",
        mimes,
    ):
        # an app declaring image/* handles every image type in the chain
        if "*" not in declared or any(
            declared[:-1] == m[: len(declared) - 1] for m in mimes
        ):
            handles.add(app_id)
    default = con.execute(
        "SELECT app_id FROM prefs WHERE mime_id=?", (mimes[0],)
    ).fetchone()
    default = default[0] if default else ""
    handles.add(default)  # whatever is set now is always a listed choice
    q = f"%{query}%"
    return sorted(
        (
            {
                "id": app_id,
                "name": name,
                "handles": app_id in handles,
                "isDefault": app_id == default,
            }
            for app_id, name in con.execute(
                "SELECT id, name FROM app WHERE id LIKE ? OR name LIKE ?", (q, q)
            )
        ),
        key=lambda r: (not r["isDefault"], not r["handles"], r["name"].lower()),
    )


def drop_default(path, mime):
    """Remove one type's default from a mimeapps.list, leaving Added Associations alone."""
    if not path.is_file():
        return
    out, section = [], None
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("["):
            section = line.strip("[]")
        elif section == SECTION and line.split("=")[0].strip() == mime:
            continue
        out.append(line)
    path.write_text("\n".join(out) + "\n")


def refresh_defaults(con):
    """Re-read what xdg-mime now considers the default for every type."""
    con.execute("DELETE FROM prefs")
    read_defaults(con)
    con.commit()


def test(con, n):
    """The parsing/precedence rules must agree with xdg-mime itself."""
    import random

    mine = dict(con.execute("SELECT mime_id, app_id FROM prefs"))
    all_types = [r[0] for r in con.execute("SELECT id FROM mime")]
    sample = random.sample(all_types, min(n, len(all_types)))
    sample += [m for m in ("application/pdf", "text/plain", "audio/mpeg") if m not in sample]
    bad = []
    for mime in sample:
        real = subprocess.run(
            ["xdg-mime", "query", "default", mime],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if real != mine.get(mime, ""):
            bad.append(f"{mime}: xdg-mime={real!r} index={mine.get(mime, '')!r}")
    print(json.dumps({"checked": len(sample), "mismatches": bad}))
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "build"
    if cmd == "build":
        return build()
    if not DB.is_file():
        subprocess.run([sys.executable, __file__, "build"], check=True)
    con = sqlite3.connect(DB)
    if cmd == "types":
        query = args[1] if len(args) > 1 else ""
        only = args[2] if len(args) > 2 else "all"
        print(json.dumps(types(con, query, only)))
    elif cmd == "apps":
        print(json.dumps(apps(con, args[1], args[2] if len(args) > 2 else "")))
    elif cmd == "set":
        subprocess.run(["xdg-mime", "default", args[2], args[1]], check=True)
        refresh_defaults(con)
        print(json.dumps({"ok": True}))
    elif cmd == "unset":
        for path in [
            Path(
                os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            )
            / "mimeapps.list",
            Path(
                os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            )
            / "applications"
            / "mimeapps.list",
        ]:
            drop_default(path, args[1])
        refresh_defaults(con)
        print(json.dumps({"ok": True}))
    elif cmd == "test":
        raise SystemExit(test(con, int(args[1]) if len(args) > 1 else 20))
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
