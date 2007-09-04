# standard automake rules

SUBDIRS = man lib scripts daemons doc testing tools

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
