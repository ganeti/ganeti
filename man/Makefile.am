# Build man pages

man_MANS = ganeti.7 ganeti-os-interface.7 gnt-cluster.8 gnt-node.8 gnt-os.8 \
	   gnt-instance.8 ganeti-noded.8 ganeti-watcher.8 gnt-backup.8

EXTRA_DIST = ganeti-os-interface.sgml gnt-cluster.sgml gnt-node.sgml \
	     ganeti-watcher.sgml ganeti.sgml gnt-instance.sgml gnt-os.sgml \
	     gnt-backup.sgml ganeti-noded.sgml \
	     footer.sgml $(man_MANS)
MAINTAINERCLEANFILES = *.[78]

%.7 %.8: %.sgml footer.sgml
	docbook2man $<
	rm -f manpage.links manpage.refs
