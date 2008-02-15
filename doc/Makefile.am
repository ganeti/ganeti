docdir = $(datadir)/doc/$(PACKAGE)

SUBDIRS = examples
dist_doc_DATA = \
  hooks.html hooks.pdf \
  install.html install.pdf \
  admin.html admin.pdf
EXTRA_DIST = hooks.sgml install.sgml admin.sgml
MAINTAINERCLEANFILES = *.html *.pdf

%.sgmltmp: %.sgml
	sed -e 's#@GANETI_VERSION@#$(PACKAGE_VERSION)#g' < $< > $@

%.html: %.sgmltmp
	docbook2html --nochunks $<

%.pdf: %.sgmltmp
	docbook2pdf $<
