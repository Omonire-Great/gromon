"""Jinja2 templates, kept optional: pip install gromon[templates]."""

_environments = {}


def globals_for():
    """The names every template can use, as Flask does without asking.

    Imported here rather than at the top because app.py imports this module.
    """
    from .app import url_for
    from .context import request

    return {"url_for": url_for, "request": request}


def render(template, *, folder="templates", **context):
    """Render a template file and return the HTML string.

    `folder` is keyword only so template variables can be called anything.
    """
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape  # optional
    except ImportError as missing:
        raise ImportError(
            "Templates need Jinja2, which is optional: pip install gromon[templates]"
        ) from missing

    if folder not in _environments:
        environment = Environment(
            loader=FileSystemLoader(folder), autoescape=select_autoescape()
        )
        environment.globals.update(globals_for())
        _environments[folder] = environment
    return _environments[folder].get_template(template).render(**context)
