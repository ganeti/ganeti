# standard automake rules

SUBDIRS = man lib scripts daemons docs testing tools
EXTRA_DIST = docs/examples/ganeti.initd

# custom rules
depgraph: depgraph.png

depgraph.png: depgraph.dot
	dot -Tpng -o $@ $<

depgraph.ps: depgraph.dot
	dot -Tps -o $@ $<

depgraph.dot: ganeti/*.py
	pylint.python2.4 --indent-string '  ' --rcfile=/dev/null \
	  --reports y --int-import-graph $@ --persistent n ganeti >/dev/null
