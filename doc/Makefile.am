docdir = $(datadir)/doc/$(PACKAGE)

SUBDIRS = examples
dist_doc_DATA = \
  hooks.html hooks.pdf \
  install.html install.pdf \
  admin.html admin.pdf \
  iallocator.html iallocator.pdf \
  rapi.html rapi.pdf

EXTRA_DIST = hooks.sgml install.sgml admin.sgml iallocator.sgml \
  rapi.sgml build-rapi-resources-doc
CLEANFILES = *.sgmltmp
MAINTAINERCLEANFILES = *.html *.pdf rapi-resources.sgml

%.sgmltmp: %.sgml
	sed -e 's#@GANETI_VERSION@#$(PACKAGE_VERSION)#g' < $< > $@

%.html: %.sgmltmp
	docbook2html --nochunks $<

%.pdf: %.sgmltmp
	docbook2pdf $<

rapi.pdf rapi.html: rapi-resources.sgml

rapi-resources.sgml: build-rapi-resources-doc ../lib/rapi/resources.py
	$(MAKE) -C $(top_builddir) ganeti
	PYTHONPATH=.:$(top_builddir) ./build-rapi-resources-doc > $@ || rm -f $@

.INTERMEDIATE: rapi-resources.sgml
