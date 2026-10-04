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
from json import dumps
from pathlib import Path

USAGE = """gromon - build Python applications with less code

usage:
  gromon new [--template FOLDER] <name>    start a project
  gromon run [options] <file.py|folder>   run it, reloading on changes
  gromon routes <file.py|folder>          print the routes an app has
  gromon test [folder]                    run the tests in a project
  gromon cls                              clear the screen

`new` is also spelled `createapp`.

options:
  --template FOLDER  copy this starter instead of the built-in one
  --host HOST        address to bind          (default 127.0.0.1)
  --port PORT        port to bind             (default 8000)
  --no-reload        do not watch for changes
  --json             with routes, print them as JSON
  --openapi          with routes, print an OpenAPI document
  -V, --version      show the version
  -h, --help         show this message

A template is a starter kept in git. Every {name} in a file, or in a path,
becomes the project name. Use . for the folder you are in:

    gromon createapp shop --template ./gromon-starter
    gromon createapp shop --template .

It can also be online, so a starter can live anywhere: an archive over http,
https or file, a git repository, or a GitHub owner/repo.

    gromon createapp shop --template https://example.com/starter.zip
    gromon createapp shop --template https://github.com/someone/starter.git
    gromon createapp shop --template someone/starter
"""


def snapshot(folder):
    """Map every .py file under folder to its modification time."""
    return {path: path.stat().st_mtime for path in folder.rglob("*.py")}


def run_file(path, host="127.0.0.1", port=8000, reload=True):
    """Run path as __main__ and block."""
    path = resolve(path)
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


def show_routes(path, machine=False, spec=False):
    """Import an app without running it and print its routes."""
    app = load_app(path)
    if not app.routes:
        sys.exit("gromon: no routes found; name your app `app` to list them")

    if spec:
        print(dumps(app.openapi(), indent=2))
        return

    # Mixing `@app.route` with the global `route` splits routes across two apps
    # and half of them are never served, so say so rather than list the short half.
    from .app import app as shared

    if app is not shared and shared.routes:
        print(
            f"gromon: warning: {len(shared.routes)} more route(s) were registered on the"
            " global app. Use one style: app.route(...), or the global route, not both.",
            file=sys.stderr,
        )

    if machine:
        print(dumps(machine_routes(app), indent=2))
        return

    print(app.routes_table())


def load_app(path):
    """Import an app without serving it, whichever way the file names it."""
    target = resolve(path)
    if not target.is_file():
        sys.exit(f"gromon: no such file: {target}")

    enter(target)
    from .app import app as shared

    namespace = runpy.run_path(str(target), run_name="gromon_routes")
    return namespace.get("app") or namespace.get("application") or shared


def run_tests(folder=None):
    """Run the tests in a project: `gromon test`."""
    import unittest

    root = Path(folder or Path.cwd()).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    found = [str(root / name) for name in ("test", "tests") if (root / name).is_dir()]
    if not found:
        sys.exit(f"gromon: no test folder in {root}\nMake one called test/ or tests/")

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for place in found:
        # No top_level_dir: that would demand an __init__.py in every tests/
        # folder anyone ever writes. The project root is already on sys.path,
        # so `from app import app` works either way.
        suite.addTests(loader.discover(place))

    if loader.errors:
        for problem in loader.errors:
            print(problem, file=sys.stderr)
        sys.exit("gromon: could not load the tests")

    if suite.countTestCases() == 0:
        sys.exit(f"gromon: no tests found in {', '.join(found)}")

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def machine_routes(app):
    """Every route as JSON, for diffing in CI or feeding another tool."""
    return [
        {
            "path": template,
            "endpoint": endpoint,
            "methods": sorted(methods),
            # kind is None on a plain text segment, which is not a parameter
            "parameters": [
                {"name": name, "converter": kind}
                for name, kind in pattern
                if kind is not None
            ],
        }
        for pattern, _handler, methods, endpoint, template in app.routes
    ]


def resolve(path):
    """A folder means the app.py inside it, and says so when there isn't one."""
    path = Path(path).resolve()
    if not path.is_dir():
        return path

    if (path / "app.py").is_file():
        return path / "app.py"

    if (path / "pyproject.toml").is_file() or (path / "setup.py").is_file():
        sys.exit(
            f"gromon: {path} has no app.py\n"
            "That looks like a library rather than an app. A template needs an app.py"
            " to run."
        )

    others = sorted(item.name for item in path.glob("*.py"))
    if others:
        sys.exit(f"gromon: {path} has no app.py\nIt has {', '.join(others)}. Try one of those.")
    sys.exit(f"gromon: {path} has no app.py and no .py files\nNothing here to run.")


def start_project(arguments):
    """Write a starter project: `gromon new myapp`."""
    from .scaffold import create, next_steps

    template, names, pending = None, [], iter(arguments)
    for argument in pending:
        if argument in ("--template", "--t", "-t"):
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
    print(f"Created {name}/{from_folder} with {len(written)} files.{next_steps(Path(name))}")


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        print(USAGE)
        return
    if arguments[0] in ("-V", "--version"):
        from . import __version__

        print(f"gromon {__version__}")
        return

    command = arguments.pop(0)
    if command == "cls":
        os.system("cls" if os.name == "nt" else "clear")
        return
    if command in ("new", "createapp"):
        start_project(arguments)
        return
    if command == "test":
        run_tests(arguments[0] if arguments else None)
        return
    if command not in ("run", "_serve", "routes"):
        sys.exit(f"gromon: unknown command\n\n{USAGE}")

    options, files, pending = (
        {"host": "127.0.0.1", "port": 8000, "reload": True, "json": False, "openapi": False},
        [],
        iter(arguments),
    )
    for argument in pending:
        if argument == "--no-reload":
            options["reload"] = False
        elif argument == "--json":
            options["json"] = True
        elif argument == "--openapi":
            options["openapi"] = True
        elif argument == "--host":
            options["host"] = next(pending)
        elif argument == "--port":
            options["port"] = int(next(pending))
        else:
            files.append(argument)

    if not files:
        # In a project folder, the app is the one called app.py. Having to say
        # `gromon routes .` every time is noise.
        if (Path.cwd() / "app.py").is_file():
            files.append(".")
        else:
            sys.exit(f"gromon: {command} needs a file\n\n{USAGE}")

    if command == "routes":
        show_routes(files[0], machine=options["json"] or options["openapi"], spec=options["openapi"])
        return

    options.pop("json"), options.pop("openapi")
    options["reload"] = options["reload"] and command == "run"

    try:
        run_file(files[0], **options)
    except KeyboardInterrupt:
        pass
