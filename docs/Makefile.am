docdir = $(datadir)/doc/$(PACKAGE)

dist_doc_DATA = hooks.html hooks.pdf
EXTRA_DIST = hooks.sgml

%.html: %.sgml
	docbook2html --nochunks $<

%.pdf: %.sgml
	docbook2pdf $<
