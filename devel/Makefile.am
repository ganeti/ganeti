EXTRA_DIST = upload.in clean-cluster.in
CLEANFILES = upload clean-cluster

all-local: upload clean-cluster
%: %.in
	sed \
	  -e 's#@PREFIX@#$(prefix)#g' \
	  -e 's#@LOCALSTATEDIR@#$(localstatedir)#g' \
	  -e 's#@SYSCONFDIR@#$(sysconfdir)#g' \
	< $< > $@
	chmod u+x $@
