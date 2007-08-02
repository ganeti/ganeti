docdir = $(datadir)/doc/$(PACKAGE)

dist_doc_DATA = hooks.html hooks.pdf installing.html installing.pdf admin.html admin.pdf
EXTRA_DIST = hooks.sgml installing.sgml admin.sgml

%.html: %.sgml
	docbook2html --nochunks $<

%.pdf: %.sgml
	docbook2pdf $<
