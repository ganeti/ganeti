Developer notes
===============

Build dependencies
------------------

Most dependencies from :doc:`install-quick`, plus:

- `GNU make <http://www.gnu.org/software/make/>`_
- `GNU tar <http://www.gnu.org/software/tar/>`_
- `Gzip <http://www.gnu.org/software/gzip/>`_
- `Docbook tools <http://sources.redhat.com/docbook-tools/>`_
  (docbook2html and docbook2man)
- `python-sphinx <http://sphinx.pocoo.org/>`_
  (tested with version 0.6.1)
- `graphviz <http://www.graphviz.org/>`_


Configuring for development
---------------------------

.. highlight:: sh

Run the following command (only use ``PYTHON=...`` if you need to use a
different python version)::

  ./autogen.sh && \
  ./configure PYTHON=python2.4 \
    --prefix=/usr/local --sysconfdir=/etc --localstatedir=/var

.. vim: set textwidth=72 :
