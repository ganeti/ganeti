# Build man pages

man_MANS = ganeti.7 ganeti-os-interface.7 gnt-cluster.8 gnt-node.8 gnt-os.8 \
	   gnt-instance.8 ganeti-noded.8 ganeti-watcher.8 gnt-backup.8 \
	   ganeti-master.8

maninput = $(patsubst %.7,%.in,$(patsubst %.8,%.in,$(man_MANS)))

EXTRA_DIST = ganeti-os-interface.sgml gnt-cluster.sgml gnt-node.sgml \
	     ganeti-watcher.sgml ganeti.sgml gnt-instance.sgml gnt-os.sgml \
	     gnt-backup.sgml ganeti-noded.sgml ganeti-master.sgml \
	     footer.sgml $(maninput)
CLEANFILES = *.[78]
MAINTAINERCLEANFILES = $(maninput)

# Wrapper around docbook2man to control the output's filename
%.in: %.sgml footer.sgml
	tmpdir=`mktemp -d "./manbuildXXXXXX"` && \
	docbook2man -o "$$tmpdir" $< && \
	ok= && \
	for check in `basename $< .sgml`.{7,8}; do \
		if test -f "$$tmpdir/$$check"; then \
			mv "$$tmpdir/$$check" $@ && \
			ok=1 && \
			break; \
		fi; \
	done; \
	if test -z "$$ok"; then \
		echo "Building $@ failed."; \
		exit 1; \
	fi; \
	rm -rf "$$tmpdir"

%.7 %.8: %.in Makefile
	sed -e 's#@LOCALSTATEDIR@#$(localstatedir)#g' \
	    -e 's#@CUSTOM_XEN_KERNEL@#$(XEN_KERNEL)#g' \
	    -e 's#@CUSTOM_XEN_INITRD@#$(XEN_INITRD)#g' \
	    < $< > $@
