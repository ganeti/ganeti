docdir = $(datadir)/doc/$(PACKAGE)

SUBDIRS = examples
dist_doc_DATA = hooks.html hooks.pdf install.html install.pdf admin.html \
  admin.pdf
EXTRA_DIST = hooks.sgml install.sgml admin.sgml

%.html: %.sgml
	docbook2html --nochunks $<

%.pdf: %.sgml
	docbook2pdf $<
