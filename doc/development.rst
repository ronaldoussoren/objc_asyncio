Development
===========

Pre-Commit
----------

The `pre-commit <https://pre-commit.com>` project is used to enforce
coding standards before committing. The pre-commit hooks are used for
CI as well.

Tox
---

All testing is automated using tox.

Coding style
------------

This package uses PEP8 to guide the coding style, and in particular
uses the "black" code formatter to format all code.

Flake8 is used with a number of plugins to enforce code quality, in
general issues found by flake8 and its plugins are fixed, not silenced.

Type checking
-------------

The public interfaces contain type annotations for mypy
and all production code must be without warnings from mypy. The testsuite
is not verified using mypy.


Testing
-------

The production code (package "objc_asyncio") should have full
test coverage. Take care to verify that new code is actually tested
and not just accidently covered.

CI
--

.. note:: GitHub Actions is not yet configured.

The project uses GitHub Actions as its CI platform. All pushes
to the master branch, as well as pull requests, are checked using
the testsuite and pre-commit hooks.
