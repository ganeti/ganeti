nodist_bin_SCRIPTS = ganeti.initd

EXTRA_DIST = ganeti.initd.in ganeti.cron
CLEANFILES = $(nodist_bin_SCRIPTS)

ganeti.initd: ganeti.initd.in
	sed \
	  -e "s#@PREFIX@#$(prefix)#g" \
	  -e "s#@SYSCONFDIR@#$(sysconfdir)#g" \
	  -e "s#@LOCALSTATEDIR@#$(localstatedir)#g" \
	< $< > $@
