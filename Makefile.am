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
BUILD_BASH_COMPLETION = $(top_srcdir)/autotools/build-bash-completion
RUN_IN_TEMPDIR = $(top_srcdir)/autotools/run-in-tempdir
CHECK_PYTHON_CODE = $(top_srcdir)/autotools/check-python-code
REPLACE_VARS_SED = autotools/replace_vars.sed

hypervisordir = $(pkgpythondir)/hypervisor
httpdir = $(pkgpythondir)/http
confddir = $(pkgpythondir)/confd
rapidir = $(pkgpythondir)/rapi
toolsdir = $(pkglibdir)/tools
docdir = $(datadir)/doc/$(PACKAGE)

DIRS = \
	autotools \
	daemons \
	devel \
	doc \
	doc/examples \
	doc/examples/hooks \
	lib \
	lib/build \
	lib/http \
	lib/hypervisor \
	lib/rapi \
	lib/confd \
	man \
	qa \
	scripts \
	test \
	test/data \
	tools

MAINTAINERCLEANFILES = \
	$(docpng) \
	$(maninput) \
	doc/install-quick.rst \
	doc/news.rst

maintainer-clean-local:
	rm -rf doc/api doc/html

CLEANFILES = \
	autotools/replace_vars.sed \
	daemons/daemon-util \
	daemons/ganeti-cleaner \
	devel/upload \
	doc/examples/bash_completion \
	doc/examples/ganeti.initd \
	doc/examples/ganeti.cron \
	doc/examples/gnt-config-backup \
	doc/examples/hooks/ipsec \
	lib/*.py[co] \
	lib/build/*.py[co] \
	lib/http/*.py[co] \
	lib/hypervisor/*.py[co] \
	lib/rapi/*.py[co] \
	$(man_MANS) \
	$(manhtml) \
	qa/*.py[co] \
	test/*.py[co] \
	stamp-directories \
	stamp-srclinks \
	$(nodist_pkgpython_PYTHON)

BUILT_SOURCES = \
	ganeti \
	stamp-srclinks \
	stamp-directories \
	lib/_autoconf.py

nodist_pkgpython_PYTHON = \
	lib/_autoconf.py

noinst_PYTHON = \
	lib/build/__init__.py

pkgpython_PYTHON = \
	lib/__init__.py \
	lib/asyncnotifier.py \
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
	lib/storage.py \
	lib/utils.py \
	lib/workerpool.py

hypervisor_PYTHON = \
	lib/hypervisor/__init__.py \
	lib/hypervisor/hv_base.py \
	lib/hypervisor/hv_chroot.py \
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

confd_PYTHON = \
	lib/confd/__init__.py \
	lib/confd/client.py \
	lib/confd/server.py \
	lib/confd/querylib.py

docrst = \
	doc/admin.rst \
	doc/design-2.0.rst \
	doc/design-2.1.rst \
	doc/design-2.2.rst \
	doc/devnotes.rst \
	doc/glossary.rst \
	doc/hooks.rst \
	doc/iallocator.rst \
	doc/index.rst \
	doc/install-quick.rst \
	doc/install.rst \
	doc/locking.rst \
	doc/news.rst \
	doc/rapi.rst \
	doc/security.rst \
	doc/walkthrough.rst

doc/html/.stamp: $(docrst) $(docpng) doc/conf.py configure.ac
	@test -n "$(SPHINX)" || \
	    { echo 'sphinx-build' not found during configure; exit 1; }
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(SPHINX) -q -W -b html \
	    -d . \
	    -D version="$(VERSION_MAJOR).$(VERSION_MINOR)" \
	    -D release="$(PACKAGE_VERSION)" \
	    $(abs_top_srcdir)/doc $(CURDIR)/doc/html
	rm -f doc/html/.buildinfo doc/html/objects.inv
	touch $@

doc/html: doc/html/.stamp

doc/news.rst: NEWS
	set -e; \
	{ echo '.. This file is automatically updated at build time from $<.'; \
	  echo '.. Do not edit.'; \
	  echo; \
	  cat $<; \
	} > $@

doc/install-quick.rst: INSTALL
	set -e; \
	{ echo '.. This file is automatically updated at build time from $<.'; \
	  echo '.. Do not edit.'; \
	  echo; \
	  cat $<; \
	} > $@

docdot = \
	doc/arch-2.0.dot \
	doc/design-2.1-lock-acquire.dot \
	doc/design-2.1-lock-release.dot

docpng = $(patsubst %.dot,%.png,$(docdot))

# Things to build but not to install (add it to EXTRA_DIST if it should be
# distributed)
noinst_DATA = \
	devel/upload \
	doc/html \
	doc/examples/bash_completion \
	doc/examples/ganeti.cron \
	doc/examples/ganeti.initd \
	doc/examples/gnt-config-backup \
	doc/examples/hooks/ipsec \
	$(manhtml)

gnt_scripts = \
	scripts/gnt-backup \
	scripts/gnt-cluster \
	scripts/gnt-debug \
	scripts/gnt-instance \
	scripts/gnt-job \
	scripts/gnt-node \
	scripts/gnt-os

dist_sbin_SCRIPTS = \
	daemons/ganeti-noded \
	daemons/ganeti-watcher \
	daemons/ganeti-masterd \
	daemons/ganeti-confd \
	daemons/ganeti-rapi \
	$(gnt_scripts)

nodist_sbin_SCRIPTS = \
	daemons/ganeti-cleaner

dist_tools_SCRIPTS = \
	tools/burnin \
	tools/cfgshell \
	tools/cfgupgrade \
	tools/lvmstrap

pkglib_SCRIPTS = \
	daemons/daemon-util

EXTRA_DIST = \
	NEWS \
	pylintrc \
	autotools/build-bash-completion \
	autotools/check-python-code \
	autotools/docbook-wrapper \
	$(RUN_IN_TEMPDIR) \
	daemons/daemon-util.in \
	daemons/ganeti-cleaner.in \
	devel/upload.in \
	$(docdot) \
	$(docpng) \
	$(docrst) \
	doc/conf.py \
	doc/html \
	doc/examples/ganeti.initd.in \
	doc/examples/ganeti.cron.in \
	doc/examples/gnt-config-backup.in \
	doc/examples/dumb-allocator \
	doc/examples/hooks/ethers \
	doc/examples/hooks/ipsec.in \
	test/testutils.py \
	test/mocks.py \
	$(dist_TESTS) \
	$(TEST_FILES) \
	man/footer.sgml \
	$(mansgml) \
	$(maninput) \
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
	man/ganeti-cleaner.8 \
	man/ganeti-confd.8 \
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
maninput = \
	$(patsubst %.7,%.7.in,$(patsubst %.8,%.8.in,$(man_MANS))) \
	$(patsubst %.html,%.html.in,$(manhtml))

TEST_FILES = \
	test/data/bdev-both.txt \
	test/data/bdev-8.3-both.txt \
	test/data/bdev-disk.txt \
	test/data/bdev-net.txt \
	test/data/proc_drbd8.txt \
	test/data/proc_drbd80-emptyline.txt \
	test/data/proc_drbd83.txt

dist_TESTS = \
	test/ganeti.bdev_unittest.py \
	test/ganeti.cli_unittest.py \
	test/ganeti.cmdlib_unittest.py \
	test/ganeti.confd_client_unittest.py \
	test/ganeti.config_unittest.py \
	test/ganeti.constants_unittest.py \
	test/ganeti.hooks_unittest.py \
	test/ganeti.http_unittest.py \
	test/ganeti.locking_unittest.py \
	test/ganeti.mcpu_unittest.py \
	test/ganeti.objects_unittest.py \
	test/ganeti.rapi.resources_unittest.py \
	test/ganeti.serializer_unittest.py \
	test/ganeti.ssh_unittest.py \
	test/ganeti.utils_unittest.py \
	test/ganeti.workerpool_unittest.py \
	test/docs_unittest.py

nodist_TESTS =

TESTS = $(dist_TESTS) $(nodist_TESTS)

TESTS_ENVIRONMENT = \
	PYTHONPATH=. TOP_SRCDIR=$(abs_top_srcdir) \
	$(RUN_IN_TEMPDIR) $(PYTHON)

all_python_code = \
	$(dist_sbin_SCRIPTS) \
	$(dist_tools_SCRIPTS) \
	$(dist_TESTS) \
	$(pkgpython_PYTHON) \
	$(hypervisor_PYTHON) \
	$(rapi_PYTHON) \
	$(http_PYTHON) \
	$(confd_PYTHON) \
	$(noinst_PYTHON)

srclink_files = \
	man/footer.sgml \
	$(all_python_code)

check_python_code = \
	autotools/build-bash-completion \
	$(all_python_code)

devel/upload: devel/upload.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod u+x $@

daemons/%: daemons/%.in \
		$(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

doc/examples/%: doc/examples/%.in \
		$(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

doc/examples/hooks/%: doc/examples/hooks/%.in \
		$(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

doc/examples/bash_completion: $(BUILD_BASH_COMPLETION) $(RUN_IN_TEMPDIR) \
	lib/cli.py $(gnt_scripts) tools/burnin
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(BUILD_BASH_COMPLETION) > $@

doc/%.png: doc/%.dot
	@test -n "$(DOT)" || { echo 'dot' not found during configure; exit 1; }
	$(DOT) -Tpng -o $@ $<

man/%.7.in man/%.8.in: man/%.sgml man/footer.sgml $(DOCBOOK_WRAPPER)
	@test -n "$(DOCBOOK2MAN)" || \
	  { echo 'docbook2man' not found during configure; exit 1; }
	$(DOCBOOK_WRAPPER) "$(DOCBOOK2MAN)" $< $(notdir $(@:.in=)) $@

man/%.html.in: man/%.sgml man/footer.sgml $(DOCBOOK_WRAPPER)
	@test -n "$(DOCBOOK2HTML)" || \
	  { echo 'docbook2html' not found during configure; exit 1; }
	$(DOCBOOK_WRAPPER) "$(DOCBOOK2HTML) --nochunks" $< $(notdir $(@:.in=)) $@

man/%.7: man/%.7.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.8: man/%.8.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.html: man/%.html.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

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
	  echo "EXPORT_DIR = '$(EXPORT_DIR)'"; \
	  echo "OS_SEARCH_PATH = [$(OS_SEARCH_PATH)]"; \
	  echo "XEN_BOOTLOADER = '$(XEN_BOOTLOADER)'"; \
	  echo "XEN_KERNEL = '$(XEN_KERNEL)'"; \
	  echo "XEN_INITRD = '$(XEN_INITRD)'"; \
	  echo "FILE_STORAGE_DIR = '$(FILE_STORAGE_DIR)'"; \
	  echo "IALLOCATOR_SEARCH_PATH = [$(IALLOCATOR_SEARCH_PATH)]"; \
	  echo "KVM_PATH = '$(KVM_PATH)'"; \
	  echo "SOCAT_PATH = '$(SOCAT)'"; \
	  echo "SOCAT_USE_ESCAPE = $(SOCAT_USE_ESCAPE)"; \
	  echo "LVM_STRIPECOUNT = $(LVM_STRIPECOUNT)"; \
	  echo "TOOLSDIR = '$(toolsdir)'"; \
	  echo "GNT_SCRIPTS = [$(foreach i,$(notdir $(gnt_scripts)),'$(i)',)]"; \
	  echo "PKGLIBDIR = '$(pkglibdir)'"; \
	} > $@

$(REPLACE_VARS_SED): Makefile
	set -e; \
	{ echo 's#@PREFIX@#$(prefix)#g'; \
	  echo 's#@SYSCONFDIR@#$(sysconfdir)#g'; \
	  echo 's#@LOCALSTATEDIR@#$(localstatedir)#g'; \
	  echo 's#@BINDIR@#$(bindir)#g'; \
	  echo 's#@SBINDIR@#$(sbindir)#g'; \
	  echo 's#@GANETI_VERSION@#$(PACKAGE_VERSION)#g'; \
	  echo 's#@CUSTOM_XEN_BOOTLOADER@#$(XEN_BOOTLOADER)#g'; \
	  echo 's#@CUSTOM_XEN_KERNEL@#$(XEN_KERNEL)#g'; \
	  echo 's#@CUSTOM_XEN_INITRD@#$(XEN_INITRD)#g'; \
	  echo 's#@RPL_FILE_STORAGE_DIR@#$(FILE_STORAGE_DIR)#g'; \
	  echo 's#@RPL_SSH_INITD_SCRIPT@#$(SSH_INITD_SCRIPT)#g'; \
	  echo 's#@PKGLIBDIR@#$(pkglibdir)#g'; \
	} > $@

# We need to create symlinks because "make distcheck" will not install Python
# files when building.
stamp-srclinks: Makefile stamp-directories
	set -e; \
	for i in $(srclink_files); do \
		if test ! -f $$i -a -f $(abs_top_srcdir)/$$i; then \
			$(LN_S) $(abs_top_srcdir)/$$i $$i; \
		fi; \
	done
	touch $@

.PHONY: ganeti
ganeti:
	cd $(top_builddir) && test -h "$@" || { rm -f $@ && $(LN_S) lib $@; }

check-local:
	$(CHECK_PYTHON_CODE) $(check_python_code)

# a dist hook rule for catching revision control directories
distcheck-hook:
	if find $(top_distdir) -name .svn -or -name .git | grep .; then \
		echo "Found revision control files in final archive." 1>&2; \
		exit 1; \
	fi
	if find $(top_distdir) -name '*.py[co]' | grep .; then \
		echo "Found Python byte code in final archive." 1>&2; \
		exit 1; \
	fi
	if find $(top_distdir) -name '*~' | grep .; then \
		echo "Found backup files in final archive." 1>&2; \
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
apidoc: epydoc.conf $(RUN_IN_TEMPDIR)
	test -e doc/api || mkdir doc/api
	$(RUN_IN_TEMPDIR) epydoc -v \
		--conf $(CURDIR)/epydoc.conf \
		--output $(CURDIR)/doc/api

.PHONY: TAGS
TAGS:
	rm -f TAGS
	find . -path './lib/*.py' -o -path 'scripts/gnt-*' -o \
	  -path 'daemons/ganeti-*' -o -path 'tools/*' | \
	  etags -

# vim: set noet :
