# -*- coding: utf-8 -*-
#

import os
import sys


def get_version():
    fn = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "objc_asyncio",
        "__init__.py",
    )
    for ln in open(fn):
        if ln.startswith("__version__"):
            version = ln.split("=")[-1].strip().strip('"')
            return version


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# -- General configuration -----------------------------------------------------

# coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.ifconfig",
    "sphinx.ext.napoleon",
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# The suffix of source filenames.
source_suffix = ".rst"

# The encoding of source files.
source_encoding = "utf-8"

# The master toctree document.
master_doc = "index"

# General information about the project.
project = "objc_asyncio"
copyright = "2020, Ronald Oussoren"  # noqa: A001

# The short X.Y version.
version = get_version()
# The full version, including alpha/beta/rc tags.
release = version

# List of directories, relative to source directory, that shouldn't be searched
# for source files.
exclude_trees = ["_build"]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
html_theme = "nature"

# If true, SmartyPants will be used to convert quotes and dashes to
# typographically correct entities.
html_use_smartypants = True

# Custom sidebar templates, maps document names to template names.
html_sidebars = {"**": ["localtoc.html", "links.html", "donate.html", "searchbox.html"]}


# Output file base name for HTML help builder.
htmlhelp_basename = "objc_asyncio_doc"


# -- Options for LaTeX output --------------------------------------------------

# The paper size ('letter' or 'a4').
latex_paper_size = "a4"

# The font size ('10pt', '11pt' or '12pt').
latex_font_size = "12pt"

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
latex_documents = [
    (
        "index",
        "objc_asyncio.tex",
        u"objc_asyncio Documentation",
        u"Ronald Oussoren",
        "manual",
    )
]

# Example configuration for intersphinx: refer to the Python standard library.
intersphinx_mapping = {"python": ("http://docs.python.org/", None)}

todo_include_todos = True
