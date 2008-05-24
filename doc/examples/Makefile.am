EXTRA_DIST = ganeti.initd.in ganeti.cron.in dumb-allocator
CLEANFILES = $(nodist_EXTRA_DATA)

nodist_EXTRA_DATA = ganeti.initd ganeti.cron

all-local: ganeti.initd ganeti.cron
ganeti.%: ganeti.%.in Makefile
	sed \
	  -e "s#@PREFIX@#$(prefix)#g" \
	  -e "s#@SYSCONFDIR@#$(sysconfdir)#g" \
	  -e "s#@LOCALSTATEDIR@#$(localstatedir)#g" \
	  -e "s#@SBINDIR@#$(sbindir)#g" \
	< $< > $@
