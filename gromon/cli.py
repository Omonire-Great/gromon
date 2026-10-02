"""The gromon command: run a file, restart it when it changes.

    gromon run app.py
    gromon run --port 5000 app.py

In reload mode a supervisor process watches the folder and starts the app in a
child process, so a restart never fights over the port.
"""

import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

USAGE = """gromon - build Python applications with less code

usage:
  gromon new [--template FOLDER] <name>    start a project
  gromon run [options] <file.py|folder>   run it, reloading on changes
  gromon routes <file.py|folder>          print the routes an app has

`new` is also spelled `createapp`.

options:
  --template FOLDER  copy this folder instead of the built-in starter
  --host HOST        address to bind          (default 127.0.0.1)
  --port PORT        port to bind             (default 8000)
  --no-reload        do not watch for changes
  -h, --help         show this message

A template folder is a starter kept in git. Every {name} in a file, or in a
path, becomes the project name. Use . to start from the folder you are in:

    gromon createapp shop --template ./gromon-starter
    gromon createapp shop --template .
"""


def snapshot(folder):
    """Map every .py file under folder to its modification time."""
    return {path: path.stat().st_mtime for path in folder.rglob("*.py")}


def run_file(path, host="127.0.0.1", port=8000, reload=True):
    """Run path as __main__ and block."""
    path = Path(path).resolve()
    if path.is_dir():
        path = path / "app.py"
    if not path.is_file():
        sys.exit(f"gromon: no such file: {path}")

    if reload and not os.environ.get("GROMON_RELOADED"):
        os.environ["GROMON_RELOADED"] = "1"
        return supervise(path, host, port)

    enter(path)
    os.environ["GROMON_HOST"], os.environ["GROMON_PORT"] = host, str(port)
    runpy.run_path(path, run_name="__main__")


def enter(path):
    """Work from the app's folder, with that folder importable.

    runpy does not add it to sys.path the way `python app.py` does, so a
    multi-file app could not `import views`.
    """
    folder = path.parent
    os.chdir(folder)  # ./static and ./templates are relative to the file
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    return folder


def supervise(path, host, port):
    """Run the app in a child process, restarting it when a file changes."""
    while True:
        child = start_child(path, host, port)
        try:
            if not changed(path.parent, child):
                return child.wait()  # the app stopped on its own
            print("Changed, restarting...")
        finally:
            stop(child)


def start_child(path, host, port):
    """Start the app as its own process so a restart can take the port back."""
    return subprocess.Popen(
        [sys.executable, "-m", "gromon", "_serve", str(path), "--host", host, "--port", str(port)],
        env=dict(os.environ, GROMON_RELOADED="1"),
    )


def changed(folder, child):
    """Wait for a changed file or a child that exits. True means a file changed."""
    before = snapshot(folder)
    while child.poll() is None:
        time.sleep(0.4)
        if snapshot(folder) != before:
            return True
    return False


def stop(child):
    """Shut the child down and wait, so its port is free for the next one."""
    if child.poll() is None:
        child.terminate()
    child.wait()


def show_routes(path):
    """Import an app without running it and print its routes."""
    target = resolve(path)
    if not target.is_file():
        sys.exit(f"gromon: no such file: {target}")

    enter(target)
    from .app import app as shared

    namespace = runpy.run_path(str(target), run_name="gromon_routes")
    # a file either builds its own App, or uses the global decorators
    app = namespace.get("app") or namespace.get("application") or shared
    if not app.routes:
        sys.exit("gromon: no routes found; name your app `app` to list them")

    # Mixing `@app.route` with the global `route` splits routes across two apps
    # and half of them are never served, so say so rather than list the short half.
    if app is not shared and shared.routes:
        print(
            f"gromon: warning: {len(shared.routes)} more route(s) were registered on the"
            " global app. Use one style: app.route(...), or the global route, not both.",
            file=sys.stderr,
        )

    print(app.routes_table())


def resolve(path):
    """A folder means the app.py inside it."""
    path = Path(path).resolve()
    return path / "app.py" if path.is_dir() else path


def start_project(arguments):
    """Write a starter project: `gromon new myapp`."""
    from .scaffold import create, next_steps

    template, names, pending = None, [], iter(arguments)
    for argument in pending:
        if argument in ("--template", "--t"):
            template = next(pending, None)
            if template is None:
                sys.exit(f"gromon: --template needs a folder\n\n{USAGE}")
        elif argument.startswith("--template="):
            template = argument.split("=", 1)[1]
        elif argument.startswith("-"):
            sys.exit(f"gromon: unknown option {argument}\n\n{USAGE}")
        else:
            names.append(argument)

    if not names:
        sys.exit(f"gromon: new needs a project name\n\n{USAGE}")
    if len(names) > 1:
        sys.exit(f"gromon: new takes one project name\n\n{USAGE}")

    name = names[0]
    try:
        written = create(name, template)
    except ValueError as problem:
        sys.exit(f"gromon: {problem}")

    from_folder = f" from {template}" if template else ""
    print(f"Created {name}/{from_folder} with {len(written)} files.{next_steps(written)}")


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        print(USAGE)
        return

    command = arguments.pop(0)
    if command in ("new", "createapp"):
        start_project(arguments)
        return
    if command not in ("run", "_serve", "routes"):
        sys.exit(f"gromon: unknown command\n\n{USAGE}")

    options, files, pending = {"host": "127.0.0.1", "port": 8000, "reload": True}, [], iter(arguments)
    for argument in pending:
        if argument == "--no-reload":
            options["reload"] = False
        elif argument == "--host":
            options["host"] = next(pending)
        elif argument == "--port":
            options["port"] = int(next(pending))
        else:
            files.append(argument)

    if not files:
        sys.exit(f"gromon: {command} needs a file\n\n{USAGE}")

    if command == "routes":
        show_routes(files[0])
        return

    options["reload"] = options["reload"] and command == "run"

    try:
        run_file(files[0], **options)
    except KeyboardInterrupt:
        pass
