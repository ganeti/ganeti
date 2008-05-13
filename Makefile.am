ACLOCAL_AMFLAGS = -I autotools

SUBDIRS = man lib scripts daemons doc test tools qa devel
EXTRA_DIST = NEWS DEVNOTES

.PHONY: ganeti
ganeti:
	cd $(top_builddir) && rm -f $@ && $(LN_S) lib $@

pre-check: ganeti
	$(MAKE) -C lib $@
	$(MAKE) -C lib/rapi $@

# a dist hook rule for catching revision control directories
distcheck-hook:
	if find $(top_distdir) | grep -F -e '.svn' -e '.git'; then \
		echo "Found revision control files in final archive" 1>&2 ; \
		exit 1; \
	fi

# custom rules
depgraph: depgraph.png

depgraph.png: depgraph.dot
	dot -Tpng -o $@ $<

depgraph.ps: depgraph.dot
	dot -Tps -o $@ $<

depgraph.dot: ganeti/*.py
	pylint.python2.4 --indent-string '  ' --rcfile=/dev/null \
	  --reports y --int-import-graph $@ --persistent n ganeti >/dev/null

install-exec-local:
	@mkdir_p@ "$(DESTDIR)${localstatedir}/lib/ganeti" \
	  "$(DESTDIR)${localstatedir}/log/ganeti" \
	  "$(DESTDIR)${localstatedir}/run/ganeti"
