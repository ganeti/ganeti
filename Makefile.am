SUBDIRS = man lib scripts daemons doc test tools qa
EXTRA_DIST = NEWS

.PHONY: ganeti
ganeti:
	cd $(top_builddir) && rm -f $@ && $(LN_S) lib $@

pre-check: ganeti
	$(MAKE) -C lib $@

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
	  "$(DESTDIR)${localstatedir}/log/ganeti"
