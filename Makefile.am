# Ganeti makefile
# - Indent with tabs only.
# - Keep files sorted; one line per file.
# - Directories in lib/ must have their own *dir variable (see hypervisor).
# - All directories must be listed DIRS.
# - Use autogen.sh to generate Makefile.in and configure script.

# Automake doesn't export these variables before version 1.10.
abs_top_builddir = @abs_top_builddir@
abs_top_srcdir = @abs_top_srcdir@

ACLOCAL_AMFLAGS = -I autotools
DOCBOOK_WRAPPER = $(top_srcdir)/autotools/docbook-wrapper
REPLACE_VARS_SED = autotools/replace_vars.sed

hypervisordir = $(pkgpythondir)/hypervisor
httpdir = $(pkgpythondir)/http
rapidir = $(pkgpythondir)/rapi
toolsdir = $(pkglibdir)/tools
docdir = $(datadir)/doc/$(PACKAGE)

DIRS = \
	autotools \
	daemons \
	devel \
	doc \
	doc/examples \
	lib \
	lib/http \
	lib/hypervisor \
	lib/rapi \
	man \
	qa \
	scripts \
	test \
	test/data \
	tools

MAINTAINERCLEANFILES = \
	$(dochtml) \
	$(patsubst %.dot,%.png,$(docdot)) \
	$(maninput)

CLEANFILES = \
	autotools/replace_vars.sed \
	devel/upload \
	doc/examples/bash_completion \
	doc/examples/ganeti.initd \
	doc/examples/ganeti.cron \
	lib/*.py[co] \
	lib/http/*.py[co] \
	lib/hypervisor/*.py[co] \
	lib/rapi/*.py[co] \
	$(man_MANS) \
	$(manhtml) \
	qa/*.py[co] \
	test/*.py[co] \
	stamp-directories \
	$(nodist_pkgpython_PYTHON)

nodist_pkgpython_PYTHON = \
	lib/_autoconf.py

pkgpython_PYTHON = \
	lib/__init__.py \
	lib/backend.py \
	lib/bdev.py \
	lib/bootstrap.py \
	lib/cli.py \
	lib/cmdlib.py \
	lib/config.py \
	lib/constants.py \
	lib/daemon.py \
	lib/errors.py \
	lib/jqueue.py \
	lib/jstore.py \
	lib/locking.py \
	lib/luxi.py \
	lib/mcpu.py \
	lib/objects.py \
	lib/opcodes.py \
	lib/rpc.py \
	lib/serializer.py \
	lib/ssconf.py \
	lib/ssh.py \
	lib/utils.py \
	lib/workerpool.py

hypervisor_PYTHON = \
	lib/hypervisor/__init__.py \
	lib/hypervisor/hv_base.py \
	lib/hypervisor/hv_fake.py \
	lib/hypervisor/hv_kvm.py \
	lib/hypervisor/hv_xen.py

rapi_PYTHON = \
	lib/rapi/__init__.py \
	lib/rapi/baserlib.py \
	lib/rapi/connector.py \
	lib/rapi/rlib2.py

http_PYTHON = \
	lib/http/__init__.py \
	lib/http/auth.py \
	lib/http/client.py \
	lib/http/server.py


docrst = \
	doc/admin.rst \
	doc/design-2.0.rst \
	doc/hooks.rst \
	doc/iallocator.rst \
	doc/install.rst \
	doc/rapi.rst \
	doc/security.rst

dochtml = $(patsubst %.rst,%.html,$(docrst))

docdot = \
	doc/arch-2.0.dot

doc_DATA = $(dochtml)

noinst_DATA = $(manhtml)

dist_sbin_SCRIPTS = \
	daemons/ganeti-noded \
	daemons/ganeti-watcher \
	daemons/ganeti-masterd \
	daemons/ganeti-rapi \
	scripts/gnt-backup \
	scripts/gnt-cluster \
	scripts/gnt-debug \
	scripts/gnt-instance \
	scripts/gnt-job \
	scripts/gnt-node \
	scripts/gnt-os

dist_tools_SCRIPTS = \
	tools/burnin \
	tools/cfgshell \
	tools/cfgupgrade \
	tools/lvmstrap

EXTRA_DIST = \
	$(MAINTAINERCLEANFILES) \
	NEWS \
	DEVNOTES \
	autotools/docbook-wrapper \
	devel/upload.in \
	$(docrst) \
	$(docdot) \
	doc/examples/bash_completion.in \
	doc/examples/ganeti.initd.in \
	doc/examples/ganeti.cron.in \
	doc/examples/dumb-allocator \
	doc/locking.txt \
	test/testutils.py \
	test/mocks.py \
	$(dist_TESTS) \
	$(TEST_FILES) \
	man/footer.sgml \
	$(mansgml) $(maninput) \
	qa/ganeti-qa.py \
	qa/qa-sample.json \
	qa/qa_cluster.py \
	qa/qa_config.py \
	qa/qa_daemon.py \
	qa/qa_env.py \
	qa/qa_error.py \
	qa/qa_instance.py \
	qa/qa_node.py \
	qa/qa_os.py \
	qa/qa_rapi.py \
	qa/qa_tags.py \
	qa/qa_utils.py

man_MANS = \
	man/ganeti.7 \
	man/ganeti-masterd.8 \
	man/ganeti-noded.8 \
	man/ganeti-os-interface.7 \
	man/ganeti-rapi.8 \
	man/ganeti-watcher.8 \
	man/gnt-backup.8 \
	man/gnt-cluster.8 \
	man/gnt-debug.8 \
	man/gnt-instance.8 \
	man/gnt-job.8 \
	man/gnt-node.8 \
	man/gnt-os.8

mansgml = $(patsubst %.7,%.sgml,$(patsubst %.8,%.sgml,$(man_MANS)))
manhtml = $(patsubst %.sgml,%.html,$(mansgml))
maninput = $(patsubst %.7,%.7.in,$(patsubst %.8,%.8.in,$(man_MANS))) $(patsubst %.html,%.html.in,$(manhtml))

TEST_FILES = \
	test/data/bdev-both.txt \
	test/data/bdev-disk.txt \
	test/data/bdev-net.txt \
	test/data/proc_drbd8.txt

dist_TESTS = \
	test/ganeti.bdev_unittest.py \
	test/ganeti.cli_unittest.py \
	test/ganeti.cmdlib_unittest.py \
	test/ganeti.config_unittest.py \
	test/ganeti.constants_unittest.py \
	test/ganeti.hooks_unittest.py \
	test/ganeti.http_unittest.py \
	test/ganeti.locking_unittest.py \
	test/ganeti.rapi.resources_unittest.py \
	test/ganeti.serializer_unittest.py \
	test/ganeti.ssh_unittest.py \
	test/ganeti.utils_unittest.py \
	test/ganeti.workerpool_unittest.py

nodist_TESTS =

TESTS = $(dist_TESTS) $(nodist_TESTS)

TESTS_ENVIRONMENT = PYTHONPATH=.:$(top_builddir)

all-local: stamp-directories lib/_autoconf.py devel/upload \
	doc/examples/bash_completion \
	doc/examples/ganeti.initd doc/examples/ganeti.cron

devel/upload: devel/upload.in stamp-directories $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod u+x $@

doc/examples/%: doc/examples/%.in stamp-directories \
		$(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

doc/%.html: doc/%.rst
	@test -n "$(RST2HTML)" || { echo 'rst2html' not found during configure; exit 1; }
	$(RST2HTML) $< $@

doc/%.png: doc/%.dot
	@test -n "$(DOT)" || { echo 'dot' not found during configure; exit 1; }
	$(DOT) -Tpng -o $@ $<

doc/design-2.0.html: doc/design-2.0.rst doc/arch-2.0.png

man/%.7.in man/%.8.in: man/%.sgml man/footer.sgml $(DOCBOOK_WRAPPER)
	@test -n "$(DOCBOOK2MAN)" || { echo 'docbook2html' not found during configure; exit 1; }
	TMPDIR=`mktemp -d` && { \
	$(DOCBOOK_WRAPPER) "$(DOCBOOK2MAN)" $< $$TMPDIR/$(patsubst man/%.in,%,$@) ; \
	mv $$TMPDIR/$(patsubst man/%.in,%,$@) $@ ; \
	rm -rf "$$TMPDIR" ; \
	}

man/%.html.in: man/%.sgml man/footer.sgml $(DOCBOOK_WRAPPER)
	@test -n "$(DOCBOOK2HTML)" || { echo 'docbook2html' not found during configure; exit 1; }
	TMPDIR=`mktemp -d` && { \
	$(DOCBOOK_WRAPPER) "$(DOCBOOK2HTML) --nochunks" $< $$TMPDIR/$(patsubst man/%.in,%,$@) ; \
	mv $$TMPDIR/$(patsubst man/%.in,%,$@) $@ ; \
	rm -rf "$$TMPDIR" ; \
	}

man/%.7: man/%.7.in stamp-directories $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.8: man/%.8.in stamp-directories $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.html: man/%.html.in stamp-directories $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/footer.sgml $(TESTS): srclinks

$(TESTS): ganeti lib/_autoconf.py

lib/_autoconf.py: Makefile stamp-directories
	set -e; \
	{ echo '# This file is automatically generated, do not edit!'; \
	  echo '#'; \
	  echo ''; \
	  echo '"""Build-time configuration for Ganeti.'; \
	  echo '';\
	  echo 'This file is autogenerated by the build process.'; \
	  echo 'For any changes you need to re-run ./configure (and'; \
	  echo 'not edit by hand).'; \
	  echo ''; \
	  echo '"""'; \
	  echo ''; \
	  echo "PACKAGE_VERSION = '$(PACKAGE_VERSION)'"; \
	  echo "VERSION_MAJOR = '$(VERSION_MAJOR)'"; \
	  echo "VERSION_MINOR = '$(VERSION_MINOR)'"; \
	  echo "VERSION_REVISION = '$(VERSION_REVISION)'"; \
	  echo "VERSION_SUFFIX = '$(VERSION_SUFFIX)'"; \
	  echo "VERSION_FULL = '$(VERSION_FULL)'"; \
	  echo "LOCALSTATEDIR = '$(localstatedir)'"; \
	  echo "SYSCONFDIR = '$(sysconfdir)'"; \
	  echo "SSH_INITD_SCRIPT = '$(SSH_INITD_SCRIPT)'"; \
	  echo "EXPORT_DIR = '$(EXPORT_DIR)'"; \
	  echo "OS_SEARCH_PATH = [$(OS_SEARCH_PATH)]"; \
	  echo "XEN_KERNEL = '$(XEN_KERNEL)'"; \
	  echo "XEN_INITRD = '$(XEN_INITRD)'"; \
	  echo "FILE_STORAGE_DIR = '$(FILE_STORAGE_DIR)'"; \
	  echo "IALLOCATOR_SEARCH_PATH = [$(IALLOCATOR_SEARCH_PATH)]"; \
	  echo "KVM_PATH = '$(KVM_PATH)'"; \
	  echo "KVM_MIGRATION_PORT = '$(KVM_MIGRATION_PORT)'"; \
	  echo "SOCAT_PATH = '$(SOCAT_PATH)'"; \
	} > $@

$(REPLACE_VARS_SED): Makefile stamp-directories
	set -e; \
	{ echo 's#@PREFIX@#$(prefix)#g'; \
	  echo 's#@SYSCONFDIR@#$(sysconfdir)#g'; \
	  echo 's#@LOCALSTATEDIR@#$(localstatedir)#g'; \
	  echo 's#@SBINDIR@#$(sbindir)#g'; \
	  echo 's#@GANETI_VERSION@#$(PACKAGE_VERSION)#g'; \
	  echo 's#@CUSTOM_XEN_KERNEL@#$(XEN_KERNEL)#g'; \
	  echo 's#@CUSTOM_XEN_INITRD@#$(XEN_INITRD)#g'; \
	  echo 's#@RPL_FILE_STORAGE_DIR@#$(FILE_STORAGE_DIR)#g'; \
	} > $@

# We need to create symlinks because "make distcheck" will not install Python
# files when building.
#.PHONY: srclinks
srclinks: stamp-directories
	set -e; \
	for i in man/footer.sgml $(pkgpython_PYTHON) $(hypervisor_PYTHON) \
			$(rapi_PYTHON) $(http_PYTHON); do \
		if test ! -f $$i -a -f $(abs_top_srcdir)/$$i; then \
			$(LN_S) $(abs_top_srcdir)/$$i $$i; \
		fi; \
	done

.PHONY: ganeti
ganeti:
	cd $(top_builddir) && test -h "$@" || { rm -f $@ && $(LN_S) lib $@; }

# a dist hook rule for catching revision control directories
distcheck-hook:
	if find $(top_distdir) | grep -F -e '.svn' -e '.git'; then \
		echo "Found revision control files in final archive" 1>&2 ; \
		exit 1; \
	fi

install-exec-local:
	@mkdir_p@ "$(DESTDIR)${localstatedir}/lib/ganeti" \
	  "$(DESTDIR)${localstatedir}/log/ganeti" \
	  "$(DESTDIR)${localstatedir}/run/ganeti"

stamp-directories: Makefile
	@mkdir_p@ $(DIRS)
	touch $@

.PHONY: apidoc
apidoc:
	test -e doc/api || mkdir doc/api
	TMPDIR=`mktemp -d ` && { \
		cp -r scripts daemons lib $$TMPDIR && \
		( \
			CDIR=`pwd` && \
			cd $$TMPDIR && \
			mv lib ganeti && \
			epydoc -v --conf $$CDIR/epydoc.conf -o $$CDIR/doc/api \
		) ; \
		rm -rf $$TMPDIR ; \
	}

# vim: set noet :
