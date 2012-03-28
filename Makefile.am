# Ganeti makefile
# - Indent with tabs only.
# - Keep files sorted; one line per file.
# - Directories in lib/ must have their own *dir variable (see hypervisor).
# - All directories must be listed DIRS.
# - Use autogen.sh to generate Makefile.in and configure script.

# Automake doesn't export these variables before version 1.10.
abs_top_builddir = @abs_top_builddir@
abs_top_srcdir = @abs_top_srcdir@

# Helper values for calling builtin functions
empty :=
space := $(empty) $(empty)
comma := ,

# Use bash in order to be able to use pipefail
SHELL=/bin/bash

ACLOCAL_AMFLAGS = -I autotools
BUILD_BASH_COMPLETION = $(top_srcdir)/autotools/build-bash-completion
RUN_IN_TEMPDIR = $(top_srcdir)/autotools/run-in-tempdir
CHECK_PYTHON_CODE = $(top_srcdir)/autotools/check-python-code
CHECK_HEADER = $(top_srcdir)/autotools/check-header
CHECK_MAN_DASHES = $(top_srcdir)/autotools/check-man-dashes
CHECK_MAN_WARNINGS = $(top_srcdir)/autotools/check-man-warnings
CHECK_VERSION = $(top_srcdir)/autotools/check-version
CHECK_NEWS = $(top_srcdir)/autotools/check-news
CHECK_IMPORTS = $(top_srcdir)/autotools/check-imports
DOCPP = $(top_srcdir)/autotools/docpp
REPLACE_VARS_SED = autotools/replace_vars.sed
CONVERT_CONSTANTS = $(top_srcdir)/autotools/convert-constants
BUILD_RPC = $(top_srcdir)/autotools/build-rpc

# Note: these are automake-specific variables, and must be named after
# the directory + 'dir' suffix
clientdir = $(pkgpythondir)/client
hypervisordir = $(pkgpythondir)/hypervisor
httpdir = $(pkgpythondir)/http
masterddir = $(pkgpythondir)/masterd
confddir = $(pkgpythondir)/confd
rapidir = $(pkgpythondir)/rapi
serverdir = $(pkgpythondir)/server
watcherdir = $(pkgpythondir)/watcher
impexpddir = $(pkgpythondir)/impexpd
utilsdir = $(pkgpythondir)/utils
toolsdir = $(pkglibdir)/tools
iallocatorsdir = $(pkglibdir)/iallocators
pytoolsdir = $(pkgpythondir)/tools
docdir = $(datadir)/doc/$(PACKAGE)
myexeclibdir = $(pkglibdir)

# Delete output file if an error occurred while building it
.DELETE_ON_ERROR:

HTOOLS_DIRS = \
	htools \
	htools/Ganeti \
	htools/Ganeti/Confd \
	htools/Ganeti/HTools \
	htools/Ganeti/HTools/Program

DIRS = \
	autotools \
	daemons \
	devel \
	doc \
	doc/examples \
	doc/examples/hooks \
	doc/examples/gnt-debug \
	$(HTOOLS_DIRS) \
	lib \
	lib/client \
	lib/build \
	lib/confd \
	lib/http \
	lib/hypervisor \
	lib/impexpd \
	lib/masterd \
	lib/rapi \
	lib/server \
	lib/tools \
	lib/utils \
	lib/watcher \
	man \
	qa \
	test \
	test/data \
	test/data/htools \
	test/data/htools/rapi \
	test/data/ovfdata \
	test/data/ovfdata/other \
	tools

BUILDTIME_DIR_AUTOCREATE = \
	scripts \
	$(APIDOC_DIR) \
	$(APIDOC_PY_DIR) \
	$(APIDOC_HS_DIR) \
	$(APIDOC_HS_DIR)/Ganeti \
	$(APIDOC_HS_DIR)/Ganeti/Confd \
	$(APIDOC_HS_DIR)/Ganeti/HTools \
	$(APIDOC_HS_DIR)/Ganeti/HTools/Program \
	$(COVERAGE_DIR) \
	$(COVERAGE_PY_DIR) \
	$(COVERAGE_HS_DIR) \
	.hpc

BUILDTIME_DIRS = \
	$(BUILDTIME_DIR_AUTOCREATE) \
	doc/html

DIRCHECK_EXCLUDE = \
	$(BUILDTIME_DIRS) \
	ganeti-[0-9]*.[0-9]*.[0-9]* \
	doc/html/_*

all_dirfiles = $(addsuffix /.dir,$(DIRS) $(BUILDTIME_DIR_AUTOCREATE))

# some helper vars
COVERAGE_DIR = doc/coverage
COVERAGE_PY_DIR = $(COVERAGE_DIR)/py
COVERAGE_HS_DIR = $(COVERAGE_DIR)/hs
APIDOC_DIR = doc/api
APIDOC_PY_DIR = $(APIDOC_DIR)/py
APIDOC_HS_DIR = $(APIDOC_DIR)/hs

MAINTAINERCLEANFILES = \
	$(docpng) \
	$(maninput) \
	doc/install-quick.rst \
	doc/news.rst \
	doc/upgrade.rst \
	vcs-version

maintainer-clean-local:
	rm -rf $(BUILDTIME_DIRS)

CLEANFILES = \
	$(addsuffix /*.py[co],$(DIRS)) \
	$(addsuffix /*.hi,$(HTOOLS_DIRS)) \
	$(addsuffix /*.o,$(HTOOLS_DIRS)) \
	$(all_dirfiles) \
	$(PYTHON_BOOTSTRAP) \
	epydoc.conf \
	autotools/replace_vars.sed \
	daemons/daemon-util \
	daemons/ganeti-cleaner \
	devel/upload \
	$(BUILT_EXAMPLES) \
	doc/examples/bash_completion \
	lib/_generated_rpc.py \
	$(man_MANS) \
	$(manhtml) \
	tools/kvm-ifup \
	stamp-srclinks \
	$(nodist_pkgpython_PYTHON) \
	$(HS_ALL_PROGS) $(HS_BUILT_SRCS) \
	$(HS_BUILT_TEST_HELPERS) \
	.hpc/*.mix htools/*.tix \
	doc/hs-lint.html

# BUILT_SOURCES should only be used as a dependency on phony targets. Otherwise
# it'll cause the target to rebuild every time.
BUILT_SOURCES = \
  $(built_base_sources) \
	$(BUILT_PYTHON_SOURCES) \
	$(PYTHON_BOOTSTRAP)

built_base_sources = \
	ganeti \
	stamp-srclinks \
	$(all_dirfiles)

built_python_base_sources = \
	lib/_autoconf.py \
	lib/_vcsversion.py

BUILT_PYTHON_SOURCES = \
	$(built_python_base_sources) \
	lib/_generated_rpc.py

# Generating the RPC wrappers depends on many things, so make sure it's built at
# the end of the built sources
lib/_generated_rpc.py: | $(built_base_sources) $(built_python_base_sources)

# these are all built from the underlying %.in sources
BUILT_EXAMPLES = \
	doc/examples/ganeti-kvm-poweroff.initd \
	doc/examples/ganeti.cron \
	doc/examples/ganeti.initd \
	doc/examples/gnt-config-backup \
	doc/examples/hooks/ipsec

nodist_pkgpython_PYTHON = \
	$(BUILT_PYTHON_SOURCES)

noinst_PYTHON = \
	lib/build/__init__.py \
	lib/build/sphinx_ext.py \
	lib/build/shell_example_lexer.py

pkgpython_PYTHON = \
	lib/__init__.py \
	lib/asyncnotifier.py \
	lib/backend.py \
	lib/bdev.py \
	lib/bootstrap.py \
	lib/cli.py \
	lib/cmdlib.py \
	lib/compat.py \
	lib/config.py \
	lib/constants.py \
	lib/daemon.py \
	lib/errors.py \
	lib/ht.py \
	lib/jqueue.py \
	lib/jstore.py \
	lib/locking.py \
	lib/luxi.py \
	lib/mcpu.py \
	lib/netutils.py \
	lib/objects.py \
	lib/opcodes.py \
	lib/ovf.py \
	lib/qlang.py \
	lib/query.py \
	lib/rpc.py \
	lib/rpc_defs.py \
	lib/runtime.py \
	lib/serializer.py \
	lib/ssconf.py \
	lib/ssh.py \
	lib/storage.py \
	lib/uidpool.py \
	lib/workerpool.py

client_PYTHON = \
	lib/client/__init__.py \
	lib/client/gnt_backup.py \
	lib/client/gnt_cluster.py \
	lib/client/gnt_debug.py \
	lib/client/gnt_group.py \
	lib/client/gnt_instance.py \
	lib/client/gnt_job.py \
	lib/client/gnt_node.py \
	lib/client/gnt_os.py

hypervisor_PYTHON = \
	lib/hypervisor/__init__.py \
	lib/hypervisor/hv_base.py \
	lib/hypervisor/hv_chroot.py \
	lib/hypervisor/hv_fake.py \
	lib/hypervisor/hv_kvm.py \
	lib/hypervisor/hv_lxc.py \
	lib/hypervisor/hv_xen.py

rapi_PYTHON = \
	lib/rapi/__init__.py \
	lib/rapi/baserlib.py \
	lib/rapi/client.py \
	lib/rapi/client_utils.py \
	lib/rapi/connector.py \
	lib/rapi/rlib2.py \
	lib/rapi/testutils.py

http_PYTHON = \
	lib/http/__init__.py \
	lib/http/auth.py \
	lib/http/client.py \
	lib/http/server.py

confd_PYTHON = \
	lib/confd/__init__.py \
	lib/confd/client.py \
	lib/confd/querylib.py \
	lib/confd/server.py

masterd_PYTHON = \
	lib/masterd/__init__.py \
	lib/masterd/instance.py

impexpd_PYTHON = \
	lib/impexpd/__init__.py

watcher_PYTHON = \
	lib/watcher/__init__.py \
	lib/watcher/nodemaint.py \
	lib/watcher/state.py

server_PYTHON = \
	lib/server/__init__.py \
	lib/server/confd.py \
	lib/server/masterd.py \
	lib/server/noded.py \
	lib/server/rapi.py

pytools_PYTHON = \
	lib/tools/__init__.py \
	lib/tools/ensure_dirs.py

utils_PYTHON = \
	lib/utils/__init__.py \
	lib/utils/algo.py \
	lib/utils/filelock.py \
	lib/utils/hash.py \
	lib/utils/io.py \
	lib/utils/log.py \
	lib/utils/mlock.py \
	lib/utils/nodesetup.py \
	lib/utils/process.py \
	lib/utils/retry.py \
	lib/utils/text.py \
	lib/utils/wrapper.py \
	lib/utils/x509.py

docrst = \
	doc/admin.rst \
	doc/design-2.0.rst \
	doc/design-2.1.rst \
	doc/design-2.2.rst \
	doc/design-2.3.rst \
	doc/design-htools-2.3.rst \
	doc/design-2.4.rst \
	doc/design-2.5.rst \
	doc/design-draft.rst \
	doc/design-oob.rst \
	doc/design-cpu-pinning.rst \
	doc/design-query2.rst \
	doc/design-x509-ca.rst \
	doc/design-http-server.rst \
	doc/design-impexp2.rst \
	doc/design-lu-generated-jobs.rst \
	doc/design-multi-reloc.rst \
	doc/design-network.rst \
	doc/design-chained-jobs.rst \
	doc/design-ovf-support.rst \
	doc/design-resource-model.rst \
	doc/cluster-merge.rst \
	doc/design-shared-storage.rst \
	doc/design-node-state-cache.rst \
	doc/design-virtual-clusters.rst \
	doc/devnotes.rst \
	doc/glossary.rst \
	doc/hooks.rst \
	doc/iallocator.rst \
	doc/index.rst \
	doc/install-quick.rst \
	doc/install.rst \
	doc/locking.rst \
	doc/move-instance.rst \
	doc/news.rst \
	doc/rapi.rst \
	doc/security.rst \
	doc/upgrade.rst \
	doc/walkthrough.rst

HS_PROGS = htools/htools
HS_BIN_ROLES = hbal hscan hspace hinfo

HS_ALL_PROGS = $(HS_PROGS) htools/test htools/hpc-htools htools/hconfd
HS_PROG_SRCS = $(patsubst %,%.hs,$(HS_ALL_PROGS))
HS_BUILT_TEST_HELPERS = $(HS_BIN_ROLES:%=test/%) test/hail

HFLAGS = -O -Wall -Werror -fwarn-monomorphism-restriction -fwarn-tabs -ihtools
# extra flags that can be overriden on the command line (e.g. -Wwarn, etc.)
HEXTRA =
# internal extra flags (used for htools/test mainly)
HEXTRA_INT =
# exclude options for coverage reports
HPCEXCL = --exclude Main \
	--exclude Ganeti.Constants \
	--exclude Ganeti.THH \
	--exclude Ganeti.HTools.QC \
	--exclude Ganeti.HTools.QCHelper \
	--exclude Ganeti.HTools.Version

HS_LIB_SRCS = \
	htools/Ganeti/HTools/CLI.hs \
	htools/Ganeti/HTools/Cluster.hs \
	htools/Ganeti/HTools/Compat.hs \
	htools/Ganeti/HTools/Container.hs \
	htools/Ganeti/HTools/ExtLoader.hs \
	htools/Ganeti/HTools/Group.hs \
	htools/Ganeti/HTools/IAlloc.hs \
	htools/Ganeti/HTools/Instance.hs \
	htools/Ganeti/HTools/JSON.hs \
	htools/Ganeti/HTools/Loader.hs \
	htools/Ganeti/HTools/Luxi.hs \
	htools/Ganeti/HTools/Node.hs \
	htools/Ganeti/HTools/PeerMap.hs \
	htools/Ganeti/HTools/QC.hs \
	htools/Ganeti/HTools/QCHelper.hs \
	htools/Ganeti/HTools/Rapi.hs \
	htools/Ganeti/HTools/Simu.hs \
	htools/Ganeti/HTools/Text.hs \
	htools/Ganeti/HTools/Types.hs \
	htools/Ganeti/HTools/Utils.hs \
	htools/Ganeti/HTools/Program.hs \
	htools/Ganeti/HTools/Program/Hail.hs \
	htools/Ganeti/HTools/Program/Hbal.hs \
	htools/Ganeti/HTools/Program/Hinfo.hs \
	htools/Ganeti/HTools/Program/Hscan.hs \
	htools/Ganeti/HTools/Program/Hspace.hs \
	htools/Ganeti/BasicTypes.hs \
	htools/Ganeti/Confd.hs \
	htools/Ganeti/Confd/Server.hs \
	htools/Ganeti/Config.hs \
	htools/Ganeti/Daemon.hs \
	htools/Ganeti/Hash.hs \
	htools/Ganeti/Jobs.hs \
	htools/Ganeti/Logging.hs \
	htools/Ganeti/Luxi.hs \
	htools/Ganeti/Objects.hs \
	htools/Ganeti/OpCodes.hs \
	htools/Ganeti/Runtime.hs \
	htools/Ganeti/Ssconf.hs \
	htools/Ganeti/THH.hs

HS_BUILT_SRCS = htools/Ganeti/HTools/Version.hs htools/Ganeti/Constants.hs
HS_BUILT_SRCS_IN = $(patsubst %,%.in,$(HS_BUILT_SRCS))

$(RUN_IN_TEMPDIR): | $(all_dirfiles)

# Note: we use here an order-only prerequisite, as the contents of
# _autoconf.py are not actually influencing the html build output: it
# has to exist in order for the sphinx module to be loaded
# successfully, but we certainly don't want the docs to be rebuilt if
# it changes
doc/html/index.html: $(docrst) $(docpng) doc/conf.py configure.ac \
	$(RUN_IN_TEMPDIR) lib/build/sphinx_ext.py \
	lib/build/shell_example_lexer.py lib/opcodes.py lib/ht.py \
	| $(BUILT_PYTHON_SOURCES)
	@test -n "$(SPHINX)" || \
	    { echo 'sphinx-build' not found during configure; exit 1; }
	@mkdir_p@ $(dir $@)
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(SPHINX) -q -W -b html \
	    -d . \
	    -D version="$(VERSION_MAJOR).$(VERSION_MINOR)" \
	    -D release="$(PACKAGE_VERSION)" \
	    $(abs_top_srcdir)/doc $(CURDIR)/doc/html
	rm -f doc/html/.buildinfo doc/html/objects.inv
	touch $@

doc/html: doc/html/index.html

doc/install-quick.rst: INSTALL
doc/news.rst: NEWS
doc/upgrade.rst: UPGRADE

doc/install-quick.rst doc/news.rst doc/upgrade.rst:
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
	$(BUILT_EXAMPLES) \
	doc/examples/bash_completion \
	$(manhtml)

gnt_scripts = \
	scripts/gnt-backup \
	scripts/gnt-cluster \
	scripts/gnt-debug \
	scripts/gnt-group \
	scripts/gnt-instance \
	scripts/gnt-job \
	scripts/gnt-node \
	scripts/gnt-os

PYTHON_BOOTSTRAP_SBIN = \
	daemons/ganeti-masterd \
	daemons/ganeti-noded \
	daemons/ganeti-watcher \
	daemons/ganeti-rapi \
	$(gnt_scripts)

if PY_CONFD
PYTHON_BOOTSTRAP_SBIN += daemons/ganeti-confd
endif

PYTHON_BOOTSTRAP = \
	$(PYTHON_BOOTSTRAP_SBIN) \
	tools/ensure-dirs

qa_scripts = \
	qa/ganeti-qa.py \
	qa/qa_cluster.py \
	qa/qa_config.py \
	qa/qa_daemon.py \
	qa/qa_env.py \
	qa/qa_error.py \
	qa/qa_group.py \
	qa/qa_instance.py \
	qa/qa_job.py \
	qa/qa_node.py \
	qa/qa_os.py \
	qa/qa_rapi.py \
	qa/qa_tags.py \
	qa/qa_utils.py

bin_SCRIPTS =
if WANT_HTOOLS
bin_SCRIPTS += $(filter-out htools/hail,$(HS_PROGS))
install-exec-hook:
	@mkdir_p@ $(DESTDIR)$(iallocatorsdir)
# FIXME: this is a hardcoded logic, instead of auto-resolving
	$(LN_S) -f ../../../bin/htools \
		   $(DESTDIR)$(iallocatorsdir)/hail
	for role in $(HS_BIN_ROLES); do \
		$(LN_S) -f htools \
			   $(DESTDIR)$(bindir)/$$role ; \
	done
if HS_CONFD
	mv $(DESTDIR)$(sbindir)/hconfd $(DESTDIR)$(sbindir)/ganeti-confd
endif
endif

$(HS_ALL_PROGS): %: %.hs $(HS_LIB_SRCS) $(HS_BUILT_SRCS) Makefile
	@if [ -z "$(HTOOLS)" ]; then \
	  echo "Error: htools compilation disabled at configure time" 1>&2 ;\
	  exit 1; \
	fi
	@BINARY=$(@:htools/%=%); \
	if [ "$BINARY" = "test" ] && [ -z "$(GHC_PKG_QUICKCHECK)" ]; then \
	  echo "Error: cannot run unittests without the QuickCheck library (see devnotes.rst)" 1>&2; \
	  exit 1; \
	fi
	rm -f $(@:htools/%=%).tix
	BINARY=$(@:htools/%=%); $(GHC) --make \
	  $(HFLAGS) \
	  $(HTOOLS_NOCURL) $(HTOOLS_PARALLEL3) \
	  -osuf $$BINARY.o -hisuf $$BINARY.hi \
	  $(HEXTRA) $(HEXTRA_INT) $@
# for the htools/test binary, we need to enable profiling/coverage
htools/test: HEXTRA_INT=-fhpc -Wwarn -fno-warn-missing-signatures \
	-fno-warn-monomorphism-restriction -fno-warn-orphans \
	-fno-warn-missing-methods -fno-warn-unused-imports

# we compile the hpc-htools binary with the program coverage
htools/hpc-htools: HEXTRA_INT=-fhpc

# test dependency
htools/offline-tests.sh: htools/hpc-htools

# rules for building profiling-enabled versions of the haskell
# programs: hs-prof does the full two-step build, whereas
# hs-prof-quick does only the final rebuild (hs-prof must have been
# run before)
.PHONY: hs-prof hs-prof-quick
hs-prof:
	$(MAKE) clean
	$(MAKE) $(HS_ALL_PROGS) HEXTRA="-osuf .o"
	rm -f $(HS_ALL_PROGS)
	$(MAKE) hs-prof-quick

hs-prof-quick:
	$(MAKE) $(HS_ALL_PROGS) HEXTRA="-osuf .prof_o -prof -auto-all"

dist_sbin_SCRIPTS = \
	tools/ganeti-listrunner

nodist_sbin_SCRIPTS = \
	$(PYTHON_BOOTSTRAP_SBIN) \
	daemons/ganeti-cleaner

if HS_CONFD
nodist_sbin_SCRIPTS += htools/hconfd
endif

python_scripts = \
	tools/burnin \
	tools/cfgshell \
	tools/cfgupgrade \
	tools/cfgupgrade12 \
	tools/cluster-merge \
	tools/confd-client \
	tools/fmtjson \
	tools/lvmstrap \
	tools/move-instance \
	tools/ovfconverter \
	tools/setup-ssh \
	tools/sanitize-config

dist_tools_SCRIPTS = \
	$(python_scripts) \
	tools/kvm-console-wrapper \
	tools/xm-console-wrapper \
	tools/master-ip-setup

pkglib_python_scripts = \
	daemons/import-export \
	tools/check-cert-expired

nodist_pkglib_python_scripts = \
	tools/ensure-dirs

myexeclib_SCRIPTS = \
	daemons/daemon-util \
	tools/kvm-ifup \
	$(pkglib_python_scripts)

nodist_myexeclib_SCRIPTS = \
	$(nodist_pkglib_python_scripts)

EXTRA_DIST = \
	NEWS \
	UPGRADE \
	epydoc.conf.in \
	pylintrc \
	autotools/build-bash-completion \
	autotools/build-rpc \
	autotools/check-header \
	autotools/check-python-code \
	autotools/check-imports \
	autotools/check-man-dashes \
	autotools/check-man-warnings \
	autotools/check-news \
	autotools/check-tar \
	autotools/check-version \
	autotools/convert-constants \
	autotools/docpp \
	autotools/gen-coverage \
	autotools/testrunner \
	$(RUN_IN_TEMPDIR) \
	daemons/daemon-util.in \
	daemons/ganeti-cleaner.in \
	$(pkglib_python_scripts) \
	devel/upload.in \
	tools/kvm-ifup.in \
	$(docdot) \
	$(docpng) \
	$(docrst) \
	doc/conf.py \
	doc/html \
	$(BUILT_EXAMPLES:%=%.in) \
	doc/examples/ganeti.default \
	doc/examples/ganeti.default-debug \
	doc/examples/hooks/ethers \
	doc/examples/gnt-debug/README \
	doc/examples/gnt-debug/delay0.json \
	doc/examples/gnt-debug/delay50.json \
	test/lockperf.py \
	test/testutils.py \
	test/mocks.py \
	$(dist_TESTS) \
	$(TEST_FILES) \
	man/footer.rst \
	$(manrst) \
	$(maninput) \
	qa/qa-sample.json \
	$(qa_scripts) \
	$(HS_LIB_SRCS) $(HS_BUILT_SRCS_IN) \
	$(HS_PROG_SRCS) \
	htools/lint-hints.hs \
	htools/cli-tests-defs.sh \
	htools/offline-test.sh

man_MANS = \
	man/ganeti.7 \
	man/ganeti-cleaner.8 \
	man/ganeti-confd.8 \
	man/ganeti-listrunner.8 \
	man/ganeti-masterd.8 \
	man/ganeti-noded.8 \
	man/ganeti-os-interface.7 \
	man/ganeti-rapi.8 \
	man/ganeti-watcher.8 \
	man/gnt-backup.8 \
	man/gnt-cluster.8 \
	man/gnt-debug.8 \
	man/gnt-group.8 \
	man/gnt-instance.8 \
	man/gnt-job.8 \
	man/gnt-node.8 \
	man/gnt-os.8 \
	man/hail.1 \
	man/hbal.1 \
	man/hinfo.1 \
	man/hscan.1 \
	man/hspace.1 \
	man/htools.1

manrst = $(patsubst %.1,%.rst,$(patsubst %.7,%.rst,$(patsubst %.8,%.rst,$(man_MANS))))
manhtml = $(patsubst %.rst,%.html,$(manrst))
mangen = $(patsubst %.rst,%.gen,$(manrst))
maninput = \
	$(patsubst %.1,%.1.in,$(patsubst %.7,%.7.in,$(patsubst %.8,%.8.in,$(man_MANS)))) \
	$(patsubst %.html,%.html.in,$(manhtml)) \
	man/footer.man man/footer.html $(mangen)

TEST_FILES = \
	test/data/bdev-drbd-8.0.txt \
	test/data/bdev-drbd-8.3.txt \
	test/data/bdev-drbd-disk.txt \
	test/data/bdev-drbd-net-ip4.txt \
	test/data/bdev-drbd-net-ip6.txt \
	test/data/cert1.pem \
	test/data/ip-addr-show-dummy0.txt \
	test/data/ip-addr-show-lo-ipv4.txt \
	test/data/ip-addr-show-lo-ipv6.txt \
	test/data/ip-addr-show-lo-oneline-ipv4.txt \
	test/data/ip-addr-show-lo-oneline-ipv6.txt \
	test/data/ip-addr-show-lo-oneline.txt \
	test/data/ip-addr-show-lo.txt \
	test/data/proc_drbd8.txt \
	test/data/proc_drbd80-emptyline.txt \
	test/data/proc_drbd83.txt \
	test/data/proc_drbd83_sync.txt \
	test/data/proc_drbd83_sync_krnl2.6.39.txt \
	test/data/kvm_1.0_help.txt \
	test/data/kvm_0.15.90_help.txt \
	test/data/kvm_0.12.5_help.txt \
	test/data/kvm_0.9.1_help.txt \
	test/data/sys_drbd_usermode_helper.txt \
	test/data/htools/hail-alloc-drbd.json \
	test/data/htools/hail-change-group.json \
	test/data/htools/hail-invalid-reloc.json \
	test/data/htools/hail-node-evac.json \
	test/data/htools/hail-reloc-drbd.json \
	test/data/htools/common-suffix.data \
	test/data/htools/invalid-node.data \
	test/data/htools/missing-resources.data \
	test/data/htools/rapi/groups.json \
	test/data/htools/rapi/info.json \
	test/data/htools/rapi/instances.json \
	test/data/htools/rapi/nodes.json \
	test/data/ovfdata/compr_disk.vmdk.gz \
	test/data/ovfdata/config.ini \
	test/data/ovfdata/corrupted_resources.ovf \
	test/data/ovfdata/empty.ini \
	test/data/ovfdata/empty.ovf \
	test/data/ovfdata/ganeti.mf \
	test/data/ovfdata/ganeti.ovf \
	test/data/ovfdata/gzip_disk.ovf \
	test/data/ovfdata/new_disk.vmdk \
	test/data/ovfdata/no_disk.ini \
	test/data/ovfdata/no_disk_in_ref.ovf \
	test/data/ovfdata/no_os.ini \
	test/data/ovfdata/no_ovf.ova \
	test/data/ovfdata/ova.ova \
	test/data/ovfdata/second_disk.vmdk \
	test/data/ovfdata/rawdisk.raw \
	test/data/ovfdata/unsafe_path.ini \
	test/data/ovfdata/virtualbox.ovf \
	test/data/ovfdata/wrong_extension.ovd \
	test/data/ovfdata/wrong_config.ini \
	test/data/ovfdata/wrong_manifest.mf \
	test/data/ovfdata/wrong_manifest.ovf \
	test/data/ovfdata/wrong_ova.ova \
	test/data/ovfdata/wrong_xml.ovf \
	test/data/ovfdata/other/rawdisk.raw \
	test/data/vgreduce-removemissing-2.02.02.txt \
	test/data/vgreduce-removemissing-2.02.66-fail.txt \
	test/data/vgreduce-removemissing-2.02.66-ok.txt \
	test/data/vgs-missing-pvs-2.02.02.txt \
	test/data/vgs-missing-pvs-2.02.66.txt \
	test/import-export_unittest-helper \
	test/gnt-cli.test \
	test/ganeti-cli.test \
	test/htools-balancing.test \
	test/htools-basic.test \
	test/htools-dynutil.test \
	test/htools-excl.test \
	test/htools-hail.test \
	test/htools-hspace.test \
	test/htools-invalid.test \
	test/htools-multi-group.test \
	test/htools-no-backend.test \
	test/htools-rapi.test \
	test/htools-single-group.test \
	test/htools-text-backend.test

python_tests = \
	test/ganeti.asyncnotifier_unittest.py \
	test/ganeti.backend_unittest.py \
	test/ganeti.bdev_unittest.py \
	test/ganeti.cli_unittest.py \
	test/ganeti.client.gnt_cluster_unittest.py \
	test/ganeti.client.gnt_instance_unittest.py \
	test/ganeti.daemon_unittest.py \
	test/ganeti.cmdlib_unittest.py \
	test/ganeti.compat_unittest.py \
	test/ganeti.confd.client_unittest.py \
	test/ganeti.config_unittest.py \
	test/ganeti.constants_unittest.py \
	test/ganeti.errors_unittest.py \
	test/ganeti.hooks_unittest.py \
	test/ganeti.ht_unittest.py \
	test/ganeti.http_unittest.py \
	test/ganeti.hypervisor_unittest.py \
	test/ganeti.hypervisor.hv_chroot_unittest.py \
	test/ganeti.hypervisor.hv_fake_unittest.py \
	test/ganeti.hypervisor.hv_kvm_unittest.py \
	test/ganeti.hypervisor.hv_lxc_unittest.py \
	test/ganeti.hypervisor.hv_xen_unittest.py \
	test/ganeti.impexpd_unittest.py \
	test/ganeti.jqueue_unittest.py \
	test/ganeti.locking_unittest.py \
	test/ganeti.luxi_unittest.py \
	test/ganeti.masterd.instance_unittest.py \
	test/ganeti.mcpu_unittest.py \
	test/ganeti.netutils_unittest.py \
	test/ganeti.objects_unittest.py \
	test/ganeti.opcodes_unittest.py \
	test/ganeti.ovf_unittest.py \
	test/ganeti.qlang_unittest.py \
	test/ganeti.query_unittest.py \
	test/ganeti.rapi.baserlib_unittest.py \
	test/ganeti.rapi.client_unittest.py \
	test/ganeti.rapi.resources_unittest.py \
	test/ganeti.rapi.rlib2_unittest.py \
	test/ganeti.rapi.testutils_unittest.py \
	test/ganeti.rpc_unittest.py \
	test/ganeti.runtime_unittest.py \
	test/ganeti.serializer_unittest.py \
	test/ganeti.ssh_unittest.py \
	test/ganeti.storage_unittest.py \
	test/ganeti.tools.ensure_dirs_unittest.py \
	test/ganeti.uidpool_unittest.py \
	test/ganeti.utils.algo_unittest.py \
	test/ganeti.utils.filelock_unittest.py \
	test/ganeti.utils.hash_unittest.py \
	test/ganeti.utils.io_unittest.py \
	test/ganeti.utils.log_unittest.py \
	test/ganeti.utils.mlock_unittest.py \
	test/ganeti.utils.nodesetup_unittest.py \
	test/ganeti.utils.process_unittest.py \
	test/ganeti.utils.retry_unittest.py \
	test/ganeti.utils.text_unittest.py \
	test/ganeti.utils.wrapper_unittest.py \
	test/ganeti.utils.x509_unittest.py \
	test/ganeti.utils_unittest.py \
	test/ganeti.workerpool_unittest.py \
	test/cfgupgrade_unittest.py \
	test/docs_unittest.py \
	test/pycurl_reset_unittest.py \
	test/tempfile_fork_unittest.py
if HAS_FAKEROOT
python_tests += test/ganeti.utils.io_unittest-runasroot.py
endif

haskell_tests = htools/test

dist_TESTS = \
	test/check-cert-expired_unittest.bash \
	test/daemon-util_unittest.bash \
	test/ganeti-cleaner_unittest.bash \
	test/import-export_unittest.bash \
	test/cli-test.bash \
	$(python_tests)

nodist_TESTS =
check_SCRIPTS =

if WANT_HTOOLSTESTS
nodist_TESTS += $(haskell_tests)
dist_TESTS += htools/offline-test.sh
check_SCRIPTS += htools/hpc-htools $(HS_BUILT_TEST_HELPERS)
endif

TESTS = $(dist_TESTS) $(nodist_TESTS)

# Environment for all tests
PLAIN_TESTS_ENVIRONMENT = \
	PYTHONPATH=. \
	TOP_SRCDIR=$(abs_top_srcdir) TOP_BUILDDIR=$(abs_top_builddir) \
	PYTHON=$(PYTHON) FAKEROOT=$(FAKEROOT_PATH) \
	$(RUN_IN_TEMPDIR)

# Environment for tests run by automake
TESTS_ENVIRONMENT = \
	$(PLAIN_TESTS_ENVIRONMENT) $(abs_top_srcdir)/autotools/testrunner

all_python_code = \
	$(dist_sbin_SCRIPTS) \
	$(python_scripts) \
	$(pkglib_python_scripts) \
	$(nodist_pkglib_python_scripts) \
	$(python_tests) \
	$(pkgpython_PYTHON) \
	$(client_PYTHON) \
	$(hypervisor_PYTHON) \
	$(rapi_PYTHON) \
	$(server_PYTHON) \
	$(pytools_PYTHON) \
	$(http_PYTHON) \
	$(confd_PYTHON) \
	$(masterd_PYTHON) \
	$(impexpd_PYTHON) \
	$(utils_PYTHON) \
	$(watcher_PYTHON) \
	$(noinst_PYTHON) \
	$(qa_scripts)

srclink_files = \
	man/footer.rst \
	test/check-cert-expired_unittest.bash \
	test/daemon-util_unittest.bash \
	test/ganeti-cleaner_unittest.bash \
	test/import-export_unittest.bash \
	test/cli-test.bash \
	htools/offline-test.sh \
	htools/cli-tests-defs.sh \
	$(all_python_code) \
	$(HS_LIB_SRCS) $(HS_PROG_SRCS)

check_python_code = \
	$(BUILD_BASH_COMPLETION) \
	$(CHECK_IMPORTS) \
	$(CHECK_HEADER) \
	$(DOCPP) \
	$(all_python_code)

lint_python_code = \
	ganeti \
	ganeti/http/server.py \
	$(dist_sbin_SCRIPTS) \
	$(python_scripts) \
	$(pkglib_python_scripts) \
	$(BUILD_BASH_COMPLETION) \
	$(CHECK_IMPORTS) \
	$(CHECK_HEADER) \
	$(DOCPP) \
	$(PYTHON_BOOTSTRAP)

standalone_python_modules = \
	lib/rapi/client.py \
	tools/ganeti-listrunner

pep8_python_code = \
	ganeti \
	ganeti/http/server.py \
	$(dist_sbin_SCRIPTS) \
	$(python_scripts) \
	$(pkglib_python_scripts) \
	$(BUILD_BASH_COMPLETION) \
	$(CHECK_HEADER) \
	$(DOCPP) \
	$(PYTHON_BOOTSTRAP) \
	qa

test/daemon-util_unittest.bash: daemons/daemon-util

test/ganeti-cleaner_unittest.bash: daemons/ganeti-cleaner

tools/kvm-ifup: tools/kvm-ifup.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

devel/upload: devel/upload.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod u+x $@

daemons/%: daemons/%.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

doc/examples/%: doc/examples/%.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

doc/examples/hooks/%: doc/examples/hooks/%.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

doc/examples/bash_completion: $(BUILD_BASH_COMPLETION) $(RUN_IN_TEMPDIR) \
	lib/cli.py $(gnt_scripts) $(client_PYTHON) tools/burnin
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(BUILD_BASH_COMPLETION) > $@

doc/%.png: doc/%.dot
	@test -n "$(DOT)" || { echo 'dot' not found during configure; exit 1; }
	$(DOT) -Tpng -o $@ $<

man/footer.man: man/footer.rst
	@test -n "$(PANDOC)" || \
	  { echo 'pandoc' not found during configure; exit 1; }
	$(PANDOC) -f rst -t man -o $@ $<

man/footer.html: man/footer.rst
	@test -n "$(PANDOC)" || \
	  { echo 'pandoc' not found during configure; exit 1; }
	$(PANDOC) -f rst -t html -o $@ $<

man/%.gen: man/%.rst lib/query.py lib/build/sphinx_ext.py \
	lib/build/shell_example_lexer.py
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(DOCPP) < $< > $@

man/%.7.in man/%.8.in man/%.1.in: man/%.gen man/footer.man
	@test -n "$(PANDOC)" || \
	  { echo 'pandoc' not found during configure; exit 1; }
	set -o pipefail ; \
	trap 'echo auto-removing $@; rm $@' EXIT; \
	$(PANDOC) -s -f rst -t man -A man/footer.man $< | \
	  sed -e 's/\\@/@/g' > $@; \
	if test -n "$(MAN_HAS_WARNINGS)"; then $(CHECK_MAN_WARNINGS) $@; fi; \
	$(CHECK_MAN_DASHES) $@; \
	trap - EXIT


man/%.html.in: man/%.gen man/footer.html
	@test -n "$(PANDOC)" || \
	  { echo 'pandoc' not found during configure; exit 1; }
	set -o pipefail ; \
	$(PANDOC) -s -f rst -t html -A man/footer.html $< | \
	  sed -e 's/\\@/@/g' > $@

man/%.1: man/%.1.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.7: man/%.7.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.8: man/%.8.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

man/%.html: man/%.html.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

epydoc.conf: epydoc.conf.in Makefile
	sed -e 's#@MODULES@#$(strip $(lint_python_code))#g' < $< > $@

vcs-version:
	if test -d .git; then \
	  git describe > $@; \
	elif test ! -f $@ ; then \
	  echo "Cannot auto-generate $@ file"; exit 1; \
	fi

.PHONY: regen-vcs-version
regen-vcs-version:
	set -e; \
	cd $(srcdir); \
	if test -d .git; then \
	  rm -f vcs-version; \
	  $(MAKE) vcs-version; \
	fi

htools/Ganeti/HTools/Version.hs: htools/Ganeti/HTools/Version.hs.in vcs-version
	set -e; \
	VCSVER=`cat $(abs_top_srcdir)/vcs-version`; \
	sed -e "s/%ver%/$$VCSVER/" < $< > $@

htools/Ganeti/Constants.hs: htools/Ganeti/Constants.hs.in \
	lib/constants.py lib/_autoconf.py $(CONVERT_CONSTANTS) \
	| lib/_vcsversion.py
	set -e; \
	{ cat $< ; PYTHONPATH=. $(CONVERT_CONSTANTS); } > $@

lib/_autoconf.py: Makefile | lib/.dir
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
	  echo '# pylint: disable=C0301,C0324'; \
	  echo '# because this is autogenerated, we do not want'; \
	  echo '# style warnings' ; \
	  echo ''; \
	  echo "PACKAGE_VERSION = '$(PACKAGE_VERSION)'"; \
	  echo "VERSION_MAJOR = '$(VERSION_MAJOR)'"; \
	  echo "VERSION_MINOR = '$(VERSION_MINOR)'"; \
	  echo "VERSION_REVISION = '$(VERSION_REVISION)'"; \
	  echo "VERSION_SUFFIX = '$(VERSION_SUFFIX)'"; \
	  echo "VERSION_FULL = '$(VERSION_FULL)'"; \
	  echo "LOCALSTATEDIR = '$(localstatedir)'"; \
	  echo "SYSCONFDIR = '$(sysconfdir)'"; \
	  echo "SSH_CONFIG_DIR = '$(SSH_CONFIG_DIR)'"; \
	  echo "EXPORT_DIR = '$(EXPORT_DIR)'"; \
	  echo "OS_SEARCH_PATH = [$(OS_SEARCH_PATH)]"; \
	  echo "XEN_BOOTLOADER = '$(XEN_BOOTLOADER)'"; \
	  echo "XEN_KERNEL = '$(XEN_KERNEL)'"; \
	  echo "XEN_INITRD = '$(XEN_INITRD)'"; \
	  echo "KVM_KERNEL = '$(KVM_KERNEL)'"; \
	  echo "FILE_STORAGE_DIR = '$(FILE_STORAGE_DIR)'"; \
	  echo "ENABLE_FILE_STORAGE = $(ENABLE_FILE_STORAGE)"; \
	  echo "SHARED_FILE_STORAGE_DIR = '$(SHARED_FILE_STORAGE_DIR)'"; \
	  echo "ENABLE_SHARED_FILE_STORAGE = $(ENABLE_SHARED_FILE_STORAGE)"; \
	  echo "IALLOCATOR_SEARCH_PATH = [$(IALLOCATOR_SEARCH_PATH)]"; \
	  echo "KVM_PATH = '$(KVM_PATH)'"; \
	  echo "IP_PATH = '$(IP_PATH)'"; \
	  echo "SOCAT_PATH = '$(SOCAT)'"; \
	  echo "SOCAT_USE_ESCAPE = $(SOCAT_USE_ESCAPE)"; \
	  echo "SOCAT_USE_COMPRESS = $(SOCAT_USE_COMPRESS)"; \
	  echo "LVM_STRIPECOUNT = $(LVM_STRIPECOUNT)"; \
	  echo "TOOLSDIR = '$(toolsdir)'"; \
	  echo "GNT_SCRIPTS = [$(foreach i,$(notdir $(gnt_scripts)),'$(i)',)]"; \
	  echo "PKGLIBDIR = '$(pkglibdir)'"; \
	  echo "DRBD_BARRIERS = '$(DRBD_BARRIERS)'"; \
	  echo "DRBD_NO_META_FLUSH = $(DRBD_NO_META_FLUSH)"; \
	  echo "SYSLOG_USAGE = '$(SYSLOG_USAGE)'"; \
	  echo "DAEMONS_GROUP = '$(DAEMONS_GROUP)'"; \
	  echo "ADMIN_GROUP = '$(ADMIN_GROUP)'"; \
	  echo "MASTERD_USER = '$(MASTERD_USER)'"; \
	  echo "MASTERD_GROUP = '$(MASTERD_GROUP)'"; \
	  echo "RAPI_USER = '$(RAPI_USER)'"; \
	  echo "RAPI_GROUP = '$(RAPI_GROUP)'"; \
	  echo "CONFD_USER = '$(CONFD_USER)'"; \
	  echo "CONFD_GROUP = '$(CONFD_GROUP)'"; \
	  echo "NODED_USER = '$(NODED_USER)'"; \
	  echo "NODED_GROUP = '$(NODED_GROUP)'"; \
	  echo "DISK_SEPARATOR = '$(DISK_SEPARATOR)'"; \
	  echo "QEMUIMG_PATH = '$(QEMUIMG_PATH)'"; \
	  if [ "$(HTOOLS)" ]; then \
	    echo "HTOOLS = True"; \
	  else \
	    echo "HTOOLS = False"; \
	  fi; \
	  echo "ENABLE_CONFD = $(ENABLE_CONFD)"; \
	  echo "PY_CONFD = $(PY_CONFD)"; \
	  echo "HS_CONFD = $(HS_CONFD)"; \
	} > $@

lib/_vcsversion.py: Makefile vcs-version | lib/.dir
	set -e; \
	VCSVER=`cat $(abs_top_srcdir)/vcs-version`; \
	{ echo '# This file is automatically generated, do not edit!'; \
	  echo '#'; \
	  echo ''; \
	  echo '"""Build-time VCS version number for Ganeti.'; \
	  echo '';\
	  echo 'This file is autogenerated by the build process.'; \
	  echo 'For any changes you need to re-run ./configure (and'; \
	  echo 'not edit by hand).'; \
	  echo ''; \
	  echo '"""'; \
	  echo ''; \
	  echo '# pylint: disable=C0301,C0324'; \
	  echo '# because this is autogenerated, we do not want'; \
	  echo '# style warnings' ; \
	  echo ''; \
	  echo "VCS_VERSION = '$$VCSVER'"; \
	} > $@

lib/_generated_rpc.py: lib/rpc_defs.py $(BUILD_RPC)
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(BUILD_RPC) lib/rpc_defs.py > $@

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
	  echo 's#@CUSTOM_IALLOCATOR_SEARCH_PATH@#$(IALLOCATOR_SEARCH_PATH)#g'; \
	  echo 's#@CUSTOM_EXPORT_DIR@#$(EXPORT_DIR)#g'; \
	  echo 's#@RPL_FILE_STORAGE_DIR@#$(FILE_STORAGE_DIR)#g'; \
	  echo 's#@RPL_SSH_INITD_SCRIPT@#$(SSH_INITD_SCRIPT)#g'; \
	  echo 's#@PKGLIBDIR@#$(pkglibdir)#g'; \
	  echo 's#@GNTMASTERUSER@#$(MASTERD_USER)#g'; \
	  echo 's#@GNTRAPIUSER@#$(RAPI_USER)#g'; \
	  echo 's#@GNTCONFDUSER@#$(CONFD_USER)#g'; \
	  echo 's#@GNTNODEDUSER@#$(NODED_USER)#g'; \
	  echo 's#@GNTRAPIGROUP@#$(RAPI_GROUP)#g'; \
	  echo 's#@GNTADMINGROUP@#$(ADMIN_GROUP)#g'; \
	  echo 's#@GNTCONFDGROUP@#$(CONFD_GROUP)#g'; \
	  echo 's#@GNTMASTERDGROUP@#$(MASTERD_GROUP)#g'; \
	  echo 's#@GNTDAEMONSGROUP@#$(DAEMONS_GROUP)#g'; \
	  echo 's#@CUSTOM_ENABLE_CONFD@#$(ENABLE_CONFD)#g'; \
	} > $@

# Using deferred evaluation
daemons/ganeti-%: MODULE = ganeti.server.$(patsubst ganeti-%,%,$(notdir $@))
daemons/ganeti-watcher: MODULE = ganeti.watcher
scripts/%: MODULE = ganeti.client.$(subst -,_,$(notdir $@))
tools/ensure-dirs: MODULE = ganeti.tools.ensure_dirs
$(HS_BUILT_TEST_HELPERS): TESTROLE = $(patsubst test/%,%,$@)

$(PYTHON_BOOTSTRAP): Makefile | $(all_dirfiles)
	test -n "$(MODULE)" || { echo Missing module; exit 1; }
	set -e; \
	{ echo '#!/usr/bin/python'; \
	  echo '# This file is automatically generated, do not edit!'; \
	  echo "# Edit $(MODULE) instead."; \
	  echo; \
	  echo '"""Bootstrap script for L{$(MODULE)}"""'; \
	  echo; \
	  echo '# pylint: disable=C0103'; \
	  echo '# C0103: Invalid name'; \
	  echo; \
	  echo 'import sys'; \
	  echo 'import $(MODULE) as main'; \
	  echo; \
	  echo '# Temporarily alias commands until bash completion'; \
	  echo '# generator is changed'; \
	  echo 'if hasattr(main, "commands"):'; \
	  echo '  commands = main.commands # pylint: disable=E1101'; \
	  echo 'if hasattr(main, "aliases"):'; \
	  echo '  aliases = main.aliases # pylint: disable=E1101'; \
	  echo; \
	  echo 'if __name__ == "__main__":'; \
	  echo '  sys.exit(main.Main())'; \
	} > $@
	chmod u+x $@

$(HS_BUILT_TEST_HELPERS): Makefile
	@test -n "$(TESTROLE)" || { echo Missing TESTROLE; exit 1; }
	set -e; \
	{ echo '#!/bin/sh'; \
	  echo '# This file is automatically generated, do not edit!'; \
	  echo "# Edit Makefile.am instead."; \
	  echo; \
	  echo "HTOOLS=$(TESTROLE) exec ./htools/hpc-htools \"\$$@\""; \
	} > $@
	chmod u+x $@

# We need to create symlinks because "make distcheck" will not install Python
# files when building.
stamp-srclinks: Makefile | $(all_dirfiles)
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

.PHONY: check-dirs
check-dirs: $(BUILT_SOURCES)
	@set -e; \
	find . -type d \( \( -name . \) -o \( \
		-name .git -o \
		-name autom4te.cache \
		\) -prune -o -print \) | { \
		error=; \
		while read dir; do \
			case "$$dir" in \
				$(strip $(patsubst %,(./%) ;;,$(DIRCHECK_EXCLUDE) $(DIRS))) \
				*) error=1; echo "Directory $$dir not listed in Makefile" >&2 ;; \
			esac; \
		done; \
		for dir in $(DIRS); do \
			if ! test -d "$$dir"; then \
				echo "Directory $$dir listed in DIRS does not exist" >&2; \
				error=1; \
			fi \
		done; \
		if test -n "$$error"; then exit 1; else exit 0; fi; \
	}

.PHONY: check-local
check-local: check-dirs $(BUILT_SOURCES)
	$(CHECK_PYTHON_CODE) $(check_python_code)
	PYTHONPATH=. $(CHECK_HEADER) $(check_python_code)
	$(CHECK_VERSION) $(VERSION) $(top_srcdir)/NEWS
	$(CHECK_NEWS) < $(top_srcdir)/NEWS
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(CHECK_IMPORTS) . $(standalone_python_modules)
	expver=$(VERSION_MAJOR).$(VERSION_MINOR); \
	if test "`head -n 1 $(top_srcdir)/README`" != "Ganeti $$expver"; then \
		echo "Incorrect version in README, expected $$expver"; \
		exit 1; \
	fi; \
	for file in doc/iallocator.rst doc/hooks.rst; do \
		if test "`sed -ne '4 p' $(top_srcdir)/$$file`" != \
			"Documents Ganeti version $$expver"; then \
			echo "Incorrect version in $$file, expected $$expver"; \
			exit 1; \
		fi; \
	done

.PHONY: hs-check
hs-check: htools/test htools/hpc-htools $(HS_BUILT_TEST_HELPERS)
	@rm -f test.tix
	./htools/test
	HBINARY="./htools/hpc-htools" ./htools/offline-test.sh

# E111: indentation is not a multiple of four
# E261: at least two spaces before inline comment
# E501: line too long (80 characters)
PEP8_IGNORE = E111,E261,E501

# For excluding pep8 expects filenames only, not whole paths
PEP8_EXCLUDE = $(subst $(space),$(comma),$(strip $(notdir $(BUILT_PYTHON_SOURCES))))

.PHONY: lint
lint: $(BUILT_SOURCES)
	@test -n "$(PYLINT)" || { echo 'pylint' not found during configure; exit 1; }
	if test -z "$(PEP8)"; then \
		echo '"pep8" not found during configure' >&2; \
	else \
		$(PEP8) --repeat --ignore='$(PEP8_IGNORE)' --exclude='$(PEP8_EXCLUDE)' \
			$(pep8_python_code); \
	fi
	$(PYLINT) $(LINT_OPTS) $(lint_python_code)
	cd $(top_srcdir)/qa && \
	  PYTHONPATH=$(abs_top_srcdir) $(PYLINT) $(LINT_OPTS) \
	  --rcfile  ../pylintrc $(patsubst qa/%.py,%,$(qa_scripts))

.PHONY: hlint
hlint: $(HS_BUILT_SRCS) htools/lint-hints.hs
	if tty -s; then C="-c"; else C=""; fi; \
	hlint --report=doc/hs-lint.html --cross $$C \
	  --ignore "Use first" \
	  --ignore "Use comparing" \
	  --ignore "Use on" \
	  --ignore "Use Control.Exception.catch" \
	  --ignore "Reduce duplication" \
	  --hint htools/lint-hints \
	  $(filter-out htools/Ganeti/THH.hs,$(HS_LIB_SRCS))

# a dist hook rule for updating the vcs-version file; this is
# hardcoded due to where it needs to build the file...
dist-hook:
	$(MAKE) regen-vcs-version && \
	rm -f $(top_distdir)/vcs-version && \
	cp -p $(srcdir)/vcs-version $(top_distdir)

# a distcheck hook rule for catching revision control directories
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
# Empty files or directories should not be distributed. They can cause
# unnecessary warnings for packagers. Directories used by automake during
# distcheck must be excluded.
	if find $(top_distdir) -empty -and -not \( \
			-path $(top_distdir)/_build -or \
			-path $(top_distdir)/_inst \) | grep .; then \
		echo "Found empty files or directories in final archive." 1>&2; \
		exit 1; \
	fi
	if test -n "$(BUILD_RELEASE)" && \
	   grep -n -H -E '^\*.*unreleased' $(top_distdir)/NEWS; then \
		echo "Found unreleased version in NEWS." >&2; \
		exit 1; \
	fi

# When building a release, stricter checks should be used
distcheck-release dist-release: export BUILD_RELEASE = 1
distcheck-release: distcheck

dist-release: dist
	set -e; \
	for i in $(DIST_ARCHIVES); do \
		echo -n "Checking $$i ... "; \
		autotools/check-tar < $$i; \
		echo OK; \
	done

install-exec-local:
	@mkdir_p@ "$(DESTDIR)${localstatedir}/lib/ganeti" \
	  "$(DESTDIR)${localstatedir}/log/ganeti" \
	  "$(DESTDIR)${localstatedir}/run/ganeti"

# To avoid conflicts between directory names and other targets, a file inside
# the directory is used to ensure its existence.
%.dir:
	@mkdir_p@ $* && touch $@

.PHONY: apidoc
if WANT_HTOOLSAPIDOC
apidoc: py-apidoc hs-apidoc
else
apidoc: py-apidoc
endif

.PHONY: py-apidoc
py-apidoc: epydoc.conf $(RUN_IN_TEMPDIR) $(BUILT_SOURCES)
	$(RUN_IN_TEMPDIR) epydoc -v \
		--conf $(CURDIR)/epydoc.conf \
		--output $(CURDIR)/$(APIDOC_PY_DIR)

.PHONY: hs-apidoc
hs-apidoc: $(HS_BUILT_SRCS)
	@test -n "$(HSCOLOUR)" || \
	    { echo 'HsColour' not found during configure; exit 1; }
	@test -n "$(HADDOCK)" || \
	    { echo 'haddock' not found during configure; exit 1; }
	rm -rf $(APIDOC_HS_DIR)/*
	@mkdir_p@ $(APIDOC_HS_DIR)/Ganeti/HTools/Program
	@mkdir_p@ $(APIDOC_HS_DIR)/Ganeti/Confd
	$(HSCOLOUR) -print-css > $(APIDOC_HS_DIR)/Ganeti/hscolour.css
	$(LN_S) ../hscolour.css $(APIDOC_HS_DIR)/Ganeti/HTools/hscolour.css
	$(LN_S) ../hscolour.css $(APIDOC_HS_DIR)/Ganeti/Confd/hscolour.css
	set -e ; \
	cd htools; \
	if [ "$(HTOOLS_NOCURL)" ]; \
	then OPTGHC="--optghc=$(HTOOLS_NOCURL)"; \
	else OPTGHC=""; \
	fi; \
	if [ "$(HTOOLS_PARALLEL3)" ]; \
	then OPTGHC="$$OPTGHC --optghc=$(HTOOLS_PARALLEL3)"; \
	fi; \
	RELSRCS="$(HS_LIB_SRCS:htools/%=%)  $(HS_BUILT_SRCS:htools/%=%)"; \
	for file in $$RELSRCS; do \
		hfile=`echo $$file|sed 's/\\.hs$$//'`.html; \
		$(HSCOLOUR) -css -anchor $$file > ../$(APIDOC_HS_DIR)/$$hfile ; \
	done ; \
	$(HADDOCK) --odir ../$(APIDOC_HS_DIR) --html --ignore-all-exports -w \
		-t ganeti-htools -p haddock-prologue \
		--source-module="%{MODULE/.//}.html" \
		--source-entity="%{MODULE/.//}.html#%{NAME}" \
		$$OPTGHC \
		$(filter-out Ganeti/HTools/ExtLoader.hs,$(HS_LIB_SRCS:htools/%=%))

.PHONY: TAGS
TAGS: $(BUILT_SOURCES)
	rm -f TAGS
	find . -path './lib/*.py' -o -path './scripts/gnt-*' -o \
	  -path './daemons/ganeti-*' -o -path './tools/*' -o \
	  -path './qa/*.py' | \
	  etags -l python -

.PHONY: coverage
if WANT_HTOOLS
coverage: py-coverage hs-coverage
else
coverage: py-coverage
endif

.PHONY: py-coverage
py-coverage: $(BUILT_SOURCES) $(python_tests)
	set -e; \
	COVERAGE_FILE=$(CURDIR)/$(COVERAGE_PY_DIR)/data \
	TEXT_COVERAGE=$(CURDIR)/$(COVERAGE_PY_DIR)/report.txt \
	HTML_COVERAGE=$(CURDIR)/$(COVERAGE_PY_DIR) \
	$(PLAIN_TESTS_ENVIRONMENT) $(abs_top_srcdir)/autotools/gen-coverage \
	$(python_tests)

.PHONY: hs-coverage
hs-coverage: $(haskell_tests) htools/hpc-htools
	rm -f *.tix && $(MAKE) hs-check
	@mkdir_p@ $(COVERAGE_HS_DIR)
	hpc combine $(HPCEXCL) test.tix hpc-htools.tix > coverage-htools.tix
	hpc markup --destdir=$(COVERAGE_HS_DIR) coverage-htools.tix
	hpc report coverage-htools.tix
	$(LN_S) -f hpc_index.html $(COVERAGE_HS_DIR)/index.html

# Special "kind-of-QA" target for htools, needs special setup (all
# tools compiled with -fhpc)
.PHONY: live-test
live-test: all
	set -e ; \
	cd htools; \
	rm -f .hpc; $(LN_S) ../.hpc .hpc; \
	rm -f *.tix *.mix; \
	./live-test.sh; \
	hpc sum --union $(HPCEXCL) $(addsuffix .tix,$(HS_PROGS:htools/%=%)) \
	  --output=live-test.tix ; \
	@mkdir_p@ ../$(COVERAGE_HS_DIR) ; \
	hpc markup --destdir=../$(COVERAGE_HS_DIR) live-test \
		--srcdir=.. $(HPCEXCL) ; \
	hpc report --srcdir=.. live-test $(HPCEXCL)

commit-check: distcheck lint apidoc

-include ./Makefile.local

# vim: set noet :
