"""LaTeX rendering: a second PDF target beside headless Chromium.

The structured document stays canonical. ``render.py`` generates ``.tex`` from
it, ``compile.py`` turns that into a PDF, and ``escape.py`` is the boundary
every user string crosses on the way in.
"""

from app.latex.escape import escape_tex

__all__ = ["escape_tex"]
