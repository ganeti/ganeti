Developer notes
===============

Build dependencies
------------------

Most dependencies from INSTALL, plus:
 - docbook2html, docbook2man from Docbook tools
   http://sources.redhat.com/docbook-tools/
 - python-sphinx (tested with version 0.6.1) from
   http://sphinx.pocoo.org/
 - graphviz
   http://www.graphviz.org/


Configuring for development
---------------------------

Run the following command (only use ``PYTHON=...`` if you need to use a
different python version)::

  ./autogen.sh && \
  ./configure PYTHON=python2.4 \
    --prefix=/usr/local --sysconfdir=/etc --localstatedir=/var
