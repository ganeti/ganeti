Developer notes
===============

.. highlight:: shell-example

Build dependencies
------------------

Most dependencies from :doc:`install-quick`, including ``qemu-img``
(marked there as optional) plus (for Python):

- `GNU make <http://www.gnu.org/software/make/>`_
- `GNU tar <http://www.gnu.org/software/tar/>`_
- `Gzip <http://www.gnu.org/software/gzip/>`_
- `pandoc <http://johnmacfarlane.net/pandoc/>`_
- `python-epydoc <http://epydoc.sourceforge.net/>`_
- `python-sphinx <http://sphinx.pocoo.org/>`_
  (tested with version 1.1.3)
- `python-mock <http://www.voidspace.org.uk/python/mock/>`_
  (tested with version 1.0.1)
- `graphviz <http://www.graphviz.org/>`_
- the `en_US.UTF-8` locale must be enabled on the system
- `pylint <http://www.logilab.org/857>`_ and its associated
  dependencies
- `pep8 <https://github.com/jcrocholl/pep8/>`_
- `PyYAML <http://pyyaml.org/>`_

For older developement (Ganeti < 2.4) ``docbook`` was used instead of
``pandoc``.

Note that for pylint, at the current moment the following versions
must be used::

    $ pylint --version
    pylint 0.26.0,
    astng 0.24.1, common 0.58.3

The same with pep8, other versions may give you errors::

     $ pep8 --version
     1.3.3

Both these versions are the ones shipped with Ubuntu 13.04.

To generate unittest coverage reports (``make coverage``), `coverage
<http://pypi.python.org/pypi/coverage>`_ needs to be installed.

Installation of all dependencies listed here::

     $ apt-get install python-setuptools automake git fakeroot
     $ apt-get install pandoc python-epydoc graphviz python-sphinx
     $ apt-get install python-yaml
     $ cd / && easy_install \
               logilab-astng==0.24.1 \
               logilab-common==0.58.3 \
               pylint==0.26.0 \
               pep8==1.3.3 \
               mock==1.0.1 \
               coverage

For Haskell development, again all things from the quick install
document, plus:

- `haddock <http://www.haskell.org/haddock/>`_, documentation
  generator (equivalent to epydoc for Python)
- `HsColour <http://hackage.haskell.org/package/hscolour>`_, again
  used for documentation (it's source-code pretty-printing)
- `hlint <http://community.haskell.org/~ndm/hlint/>`_, a source code
  linter (equivalent to pylint for Python), recommended version 1.8 or
  above (tested with 1.8.43)
- the `QuickCheck <http://hackage.haskell.org/package/QuickCheck>`_
  library, version 2.x
- the `HUnit <http://hunit.sourceforge.net/>`_ library (tested with
  1.2.x)
- the `test-framework
  <http://batterseapower.github.com/test-framework/>`_ libraries,
  tested versions: ``test-framework``: 0.6, ``test-framework-hunit``:
  0.2.7, ``test-framework-quickcheck2``: 0.2.12.1
- ``hpc``, which comes with the compiler, so you should already have
  it
- `shelltestrunner <http://joyful.com/shelltestrunner>`_, used for
  running shell-based unit-tests
- `temporary <https://github.com/batterseapower/temporary/>`_ library,
  tested with version 1.1.2.3

Under Debian Wheezy or later, these can be installed (on top of the
required ones from the quick install document) via::

  $ apt-get install libghc-quickcheck2-dev libghc-hunit-dev \
        libghc-test-framework-dev \
        libghc-test-framework-quickcheck2-dev \
        libghc-test-framework-hunit-dev \
        libghc-temporary-dev shelltestrunner \
        hscolour hlint

Or alternatively via ``cabal``::

  $ cabal install QuickCheck HUnit \
          test-framework test-framework-quickcheck2 test-framework-hunit \
          temporary hscolour hlint shelltestrunner


Configuring for development
---------------------------

Run the following command (only use ``PYTHON=...`` if you need to use a
different python version)::

  $ ./autogen.sh && \
    ./configure --prefix=/usr/local --sysconfdir=/etc --localstatedir=/var

Note that doing development on a machine which already has Ganeti
installed is problematic, as ``PYTHONPATH`` behaviour can be confusing
(see Issue 170 for a bit of history/details; in general it works if
the installed and developed versions are very similar, and/or if
PYTHONPATH is customised correctly). As such, in general it's
recommended to use a "clean" machine for ganeti development.

Style guide
-----------

Please adhere to the :doc:`dev-codestyle` while writing code for Ganeti.

Haskell development notes
-------------------------

There are a few things which can help writing or debugging the Haskell
code.

You can run the Haskell linter :command:`hlint` via::

  $ make hlint

This is not enabled by default (as the htools component is
optional). The above command will generate both output on the terminal
and, if any warnings are found, also an HTML report at
``doc/hs-lint.html``.

When writing or debugging TemplateHaskell code, it's useful to see
what the splices are converted to. This can be done via::

  $ make HEXTRA="-ddump-splices"

Or, more interactively::

  $ ghci
  λ> :set -ddump-splices
  λ> :l src/Ganeti/Objects.hs

And you will get the spliced code as the module is loaded.

To build profiling code you must install the ``ghc-prof`` (or
``gch6-prof``) package, and all the relevant libraries with their
``-prof`` counterparts. If installing libraries through cabal the config
file should include ``library-profiling: True`` or the ``-p`` flag
should be used. Any library already installed can be updated by passing
``--reinstall`` as well.

Due to the way TemplateHaskell works, it's not straightforward to
build profiling code. The recommended way is to run ``make hs-prof``,
or alternatively the manual sequence is::

  $ make clean
  $ make src/htools HEXTRA="-osuf .o"
  $ rm src/htools
  $ make src/htools HEXTRA="-osuf .prof_o -prof -auto-all"

This will build the binary twice, per the TemplateHaskell
documentation, the second one with profiling enabled.

The binary files generated by compilation and the profiling/coverage
files can "break" tab-completion in the sources; they can be ignored,
for example, in bash via ``.bashrc``::

  FIGNORE='.o:.hi:.prof_o:.tix'

or in emacs via ``completion-ignored-extensions`` (run ``M-x
customize-var completion-ignored-extensions``).

Running individual tests
~~~~~~~~~~~~~~~~~~~~~~~~

When developing code, running the entire test suite can be
slow. Running individual tests is possible. There are different
Makefile targets for running individual Python and Haskell tests.

For Python tests::

  $ export PYTHONPATH=$PWD
  $ python ./test/py/ganeti.%mytest%

For Haskell tests::

  $ make hs-test-%pattern%

Where ``pattern`` can be a simple test pattern (e.g. ``comma``,
matching any test whose name contains ``comma``), a test pattern
denoting a group (ending with a slash, e.g. ``Utils/``), or more
complex glob pattern. For more details, search for glob patterns in
the documentation of `test-framework
<http://batterseapower.github.com/test-framework/>`_).

For individual Haskell shelltests::

  $ make hs-shell-%name%

which runs the test ``test/hs/shelltests/htools-%name%.test``. For
example, to run the test ``test/hs/shelltests/htools-balancing.test``,
use::

  $ make hs-shell-balancing

For combined Haskell shelltests::

  $ make hs-shell-{%name1%,%name2%,...}

for example::

  $ make hs-shell-{balancing,basic}

Checking for the correct style of the NEWS file is also possible, by running::

  $ make check-news

Packaging notes
===============

Ganeti is mostly developed and tested on `Debian
<http://www.debian.org/>`_-based distributions, while still keeping
adaptability to other Linux distributions in mind.

The ``doc/examples/`` directory contains a number of potentially useful
scripts and configuration files. Some of them might need adjustment
before use.

``daemon-util``
---------------

This script, in the source code as ``daemons/daemon-util.in``, is used
to start/stop Ganeti and do a few other things related to system
daemons. It is recommended to use ``daemon-util`` also from the system's
init scripts. That way the code starting and stopping daemons is shared
and future changes have to be made in only one place.

``daemon-util`` reads extra arguments from variables (``*_ARGS``) in
``/etc/default/ganeti``. When modifying ``daemon-util``, keep in mind to
not remove support for the ``EXTRA_*_ARGS`` variables for starting
daemons. Some parts of Ganeti use them to pass additional arguments when
starting a daemon.

The ``reload_ssh_keys`` function can be adjusted to use another command
for reloading the OpenSSH daemon's host keys.

.. vim: set textwidth=72 :
