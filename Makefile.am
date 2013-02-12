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
CHECK_MAN_REFERENCES = $(top_srcdir)/autotools/check-man-references
CHECK_MAN_WARNINGS = $(top_srcdir)/autotools/check-man-warnings
CHECK_VERSION = $(top_srcdir)/autotools/check-version
CHECK_NEWS = $(top_srcdir)/autotools/check-news
CHECK_IMPORTS = $(top_srcdir)/autotools/check-imports
DOCPP = $(top_srcdir)/autotools/docpp
REPLACE_VARS_SED = autotools/replace_vars.sed
CONVERT_CONSTANTS = $(top_srcdir)/autotools/convert-constants
BUILD_RPC = $(top_srcdir)/autotools/build-rpc
SHELL_ENV_INIT = autotools/shell-env-init

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

HS_DIRS = \
	src \
	src/Ganeti \
	src/Ganeti/Block \
	src/Ganeti/Block/Drbd \
	src/Ganeti/Confd \
	src/Ganeti/DataCollectors \
	src/Ganeti/HTools \
	src/Ganeti/HTools/Backend \
	src/Ganeti/HTools/Program \
	src/Ganeti/Query \
	test/hs \
	test/hs/Test \
	test/hs/Test/Ganeti \
	test/hs/Test/Ganeti/Block \
	test/hs/Test/Ganeti/Block/Drbd \
	test/hs/Test/Ganeti/Confd \
	test/hs/Test/Ganeti/HTools \
	test/hs/Test/Ganeti/HTools/Backend \
	test/hs/Test/Ganeti/Query

DIRS = \
	$(HS_DIRS) \
	autotools \
	daemons \
	devel \
	doc \
	doc/css \
	doc/examples \
	doc/examples/gnt-debug \
	doc/examples/hooks \
	test/data/htools \
	test/data/htools/rapi \
	test/hs/shelltests \
	lib \
	lib/build \
	lib/client \
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
	test/data/ovfdata \
	test/data/ovfdata/other \
	test/py \
	tools

ALL_APIDOC_HS_DIRS = \
	$(APIDOC_HS_DIR) \
	$(APIDOC_HS_DIR)/Ganeti \
	$(APIDOC_HS_DIR)/Ganeti/Block \
	$(APIDOC_HS_DIR)/Ganeti/Block/Drbd \
	$(APIDOC_HS_DIR)/Ganeti/Confd \
	$(APIDOC_HS_DIR)/Ganeti/DataCollectors \
	$(APIDOC_HS_DIR)/Ganeti/HTools \
	$(APIDOC_HS_DIR)/Ganeti/HTools/Backend \
	$(APIDOC_HS_DIR)/Ganeti/HTools/Program \
	$(APIDOC_HS_DIR)/Ganeti/Query

BUILDTIME_DIR_AUTOCREATE = \
	scripts \
	$(APIDOC_DIR) \
	$(ALL_APIDOC_HS_DIRS) \
	$(APIDOC_PY_DIR) \
	$(COVERAGE_DIR) \
	$(COVERAGE_HS_DIR) \
	$(COVERAGE_PY_DIR) \
	.hpc

BUILDTIME_DIRS = \
	$(BUILDTIME_DIR_AUTOCREATE) \
	doc/html \
	doc/man-html

DIRCHECK_EXCLUDE = \
	$(BUILDTIME_DIRS) \
	ganeti-[0-9]*.[0-9]*.[0-9]* \
	doc/html/_* \
	doc/man-html/_* \
	autom4te.cache

# some helper vars
COVERAGE_DIR = doc/coverage
COVERAGE_PY_DIR = $(COVERAGE_DIR)/py
COVERAGE_HS_DIR = $(COVERAGE_DIR)/hs
APIDOC_DIR = doc/api
APIDOC_PY_DIR = $(APIDOC_DIR)/py
APIDOC_HS_DIR = $(APIDOC_DIR)/hs

MAINTAINERCLEANFILES = \
	$(maninput) \
	doc/install-quick.rst \
	doc/news.rst \
	doc/upgrade.rst \
	vcs-version

maintainer-clean-local:
	rm -rf $(BUILDTIME_DIRS)

CLEANFILES = \
	$(addsuffix /*.py[co],$(DIRS)) \
	$(addsuffix /*.hi,$(HS_DIRS)) \
	$(addsuffix /*.o,$(HS_DIRS)) \
	$(PYTHON_BOOTSTRAP) \
	epydoc.conf \
	$(REPLACE_VARS_SED) \
	$(SHELL_ENV_INIT) \
	daemons/daemon-util \
	daemons/ganeti-cleaner \
	$(mandocrst) \
	doc/manpages-enabled.rst \
	$(BUILT_EXAMPLES) \
	doc/examples/bash_completion \
	doc/examples/bash_completion-debug \
	lib/_generated_rpc.py \
	$(man_MANS) \
	$(manhtml) \
	tools/kvm-ifup \
	tools/vcluster-setup \
	stamp-directories \
	stamp-srclinks \
	$(nodist_pkgpython_PYTHON) \
	$(HS_ALL_PROGS) $(HS_BUILT_SRCS) \
	$(HS_BUILT_TEST_HELPERS) \
	src/ganeti-confd \
	.hpc/*.mix src/*.tix test/hs/*.tix \
	doc/hs-lint.html

GENERATED_FILES = \
	$(built_base_sources) \
	$(BUILT_PYTHON_SOURCES) \
	$(PYTHON_BOOTSTRAP)

HS_GENERATED_FILES =
if WANT_HTOOLS
HS_GENERATED_FILES += $(HS_PROGS)
if ENABLE_CONFD
HS_GENERATED_FILES += src/hconfd src/ganeti-confd
endif
endif

built_base_sources = \
	stamp-directories \
	stamp-srclinks

built_python_base_sources = \
	lib/_autoconf.py \
	lib/_vcsversion.py

BUILT_PYTHON_SOURCES = \
	$(built_python_base_sources) \
	lib/_generated_rpc.py

# Generating the RPC wrappers depends on many things, so make sure
# it's built at the end of the built sources
lib/_generated_rpc.py: | $(built_base_sources) $(built_python_base_sources)

# these are all built from the underlying %.in sources
BUILT_EXAMPLES = \
	doc/examples/ganeti-kvm-poweroff.initd \
	doc/examples/ganeti.cron \
	doc/examples/ganeti.initd \
	doc/examples/ganeti-master-role.ocf \
	doc/examples/ganeti-node-role.ocf \
	doc/examples/gnt-config-backup \
	doc/examples/hooks/ipsec

nodist_pkgpython_PYTHON = \
	$(BUILT_PYTHON_SOURCES)

noinst_PYTHON = \
	lib/build/__init__.py \
	lib/build/shell_example_lexer.py \
	lib/build/sphinx_ext.py

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
	lib/objectutils.py \
	lib/opcodes.py \
	lib/ovf.py \
	lib/pathutils.py \
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
	lib/vcluster.py \
	lib/network.py \
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
	lib/client/gnt_network.py \
	lib/client/gnt_os.py \
	lib/client/gnt_storage.py

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
	lib/confd/client.py

masterd_PYTHON = \
	lib/masterd/__init__.py \
	lib/masterd/iallocator.py \
	lib/masterd/instance.py

impexpd_PYTHON = \
	lib/impexpd/__init__.py

watcher_PYTHON = \
	lib/watcher/__init__.py \
	lib/watcher/nodemaint.py \
	lib/watcher/state.py

server_PYTHON = \
	lib/server/__init__.py \
	lib/server/masterd.py \
	lib/server/noded.py \
	lib/server/rapi.py

pytools_PYTHON = \
	lib/tools/__init__.py \
	lib/tools/burnin.py \
	lib/tools/ensure_dirs.py \
	lib/tools/node_cleanup.py \
	lib/tools/node_daemon_setup.py \
	lib/tools/prepare_node_join.py

utils_PYTHON = \
	lib/utils/__init__.py \
	lib/utils/algo.py \
	lib/utils/filelock.py \
	lib/utils/hash.py \
	lib/utils/io.py \
	lib/utils/log.py \
	lib/utils/lvm.py \
	lib/utils/mlock.py \
	lib/utils/nodesetup.py \
	lib/utils/process.py \
	lib/utils/retry.py \
	lib/utils/text.py \
	lib/utils/wrapper.py \
	lib/utils/x509.py

docinput = \
	doc/conf.py \
	doc/css/style.css \
	doc/admin.rst \
	doc/cluster-merge.rst \
	doc/design-2.0.rst \
	doc/design-2.1.rst \
	doc/design-2.2.rst \
	doc/design-2.3.rst \
	doc/design-2.4.rst \
	doc/design-2.5.rst \
	doc/design-2.6.rst \
	doc/design-2.7.rst \
	doc/design-autorepair.rst \
	doc/design-bulk-create.rst \
	doc/design-chained-jobs.rst \
	doc/design-cpu-pinning.rst \
	doc/design-draft.rst \
	doc/design-htools-2.3.rst \
	doc/design-http-server.rst \
	doc/design-impexp2.rst \
	doc/design-lu-generated-jobs.rst \
	doc/design-linuxha.rst \
	doc/design-multi-reloc.rst \
	doc/design-network.rst \
	doc/design-node-add.rst \
	doc/design-oob.rst \
	doc/design-ovf-support.rst \
	doc/design-opportunistic-locking.rst \
	doc/design-partitioned.rst \
	doc/design-query-splitting.rst \
	doc/design-query2.rst \
	doc/design-remote-commands.rst \
	doc/design-resource-model.rst \
	doc/design-shared-storage.rst \
	doc/design-monitoring-agent.rst \
	doc/design-virtual-clusters.rst \
	doc/design-x509-ca.rst \
	doc/devnotes.rst \
	doc/glossary.rst \
	doc/hooks.rst \
	doc/iallocator.rst \
	doc/index.rst \
	doc/install-quick.rst \
	doc/install.rst \
	doc/locking.rst \
	doc/manpages-disabled.rst \
	doc/move-instance.rst \
	doc/news.rst \
	doc/ovfconverter.rst \
	doc/rapi.rst \
	doc/security.rst \
	doc/upgrade.rst \
	doc/virtual-cluster.rst \
	doc/walkthrough.rst

# Generates file names such as "doc/man-gnt-instance.rst"
mandocrst = $(addprefix doc/man-,$(notdir $(manrst)))

# Haskell programs to be installed in $PREFIX/bin
HS_BIN_PROGS=src/htools

# Haskell programs to be installed in the MYEXECLIB dir
HS_MYEXECLIB_PROGS=src/mon-collector

# Haskell programs to compiled but not installed automatically
# Usually they have their own specific installation rules
HS_COMPILE_PROGS= \
	src/hconfd \
	src/rpc-test

# All Haskell non-test programs to be compiled but not automatically installed
HS_PROGS = $(HS_BIN_PROGS) $(HS_MYEXECLIB_PROGS)

HS_BIN_ROLES = harep hbal hscan hspace hinfo hcheck hroller
HS_HTOOLS_PROGS = $(HS_BIN_ROLES) hail

HS_ALL_PROGS = \
	$(HS_PROGS) \
	test/hs/hpc-htools \
	test/hs/hpc-mon-collector \
	test/hs/htest \
	$(HS_COMPILE_PROGS)

HS_PROG_SRCS = $(patsubst %,%.hs,$(HS_ALL_PROGS))
HS_BUILT_TEST_HELPERS = $(HS_BIN_ROLES:%=test/hs/%) test/hs/hail

HFLAGS = \
	-O -Wall -Werror -isrc \
	-fwarn-monomorphism-restriction \
	-fwarn-tabs \
	$(GHC_BYVERSION_FLAGS)

# extra flags that can be overriden on the command line (e.g. -Wwarn, etc.)
HEXTRA =
# internal extra flags (used for test/hs/htest mainly)
HEXTRA_INT =
# exclude options for coverage reports
HPCEXCL = --exclude Main \
	--exclude Ganeti.Constants \
	--exclude Ganeti.HTools.QC \
	--exclude Ganeti.THH \
	--exclude Ganeti.Version \
	--exclude Test.Ganeti.Attoparsec \
	--exclude Test.Ganeti.TestCommon \
	--exclude Test.Ganeti.TestHTools \
	--exclude Test.Ganeti.TestHelper \
	--exclude Test.Ganeti.TestImports \
	$(patsubst src.%,--exclude Test.%,$(subst /,.,$(patsubst %.hs,%, $(HS_LIB_SRCS))))

HS_LIB_SRCS = \
	src/Ganeti/Block/Drbd/Types.hs \
	src/Ganeti/Block/Drbd/Parser.hs \
	src/Ganeti/BasicTypes.hs \
	src/Ganeti/Common.hs \
	src/Ganeti/Compat.hs \
	src/Ganeti/Confd/Client.hs \
	src/Ganeti/Confd/Server.hs \
	src/Ganeti/Confd/Types.hs \
	src/Ganeti/Confd/Utils.hs \
	src/Ganeti/Config.hs \
	src/Ganeti/Daemon.hs \
	src/Ganeti/DataCollectors/CLI.hs \
	src/Ganeti/DataCollectors/Drbd.hs \
	src/Ganeti/DataCollectors/Program.hs \
	src/Ganeti/DataCollectors/Types.hs \
	src/Ganeti/Errors.hs \
	src/Ganeti/HTools/Backend/IAlloc.hs \
	src/Ganeti/HTools/Backend/Luxi.hs \
	src/Ganeti/HTools/Backend/Rapi.hs \
	src/Ganeti/HTools/Backend/Simu.hs \
	src/Ganeti/HTools/Backend/Text.hs \
	src/Ganeti/HTools/CLI.hs \
	src/Ganeti/HTools/Cluster.hs \
	src/Ganeti/HTools/Container.hs \
	src/Ganeti/HTools/ExtLoader.hs \
	src/Ganeti/HTools/Graph.hs \
	src/Ganeti/HTools/Group.hs \
	src/Ganeti/HTools/Instance.hs \
	src/Ganeti/HTools/Loader.hs \
	src/Ganeti/HTools/Node.hs \
	src/Ganeti/HTools/PeerMap.hs \
	src/Ganeti/HTools/Program/Hail.hs \
	src/Ganeti/HTools/Program/Harep.hs \
	src/Ganeti/HTools/Program/Hbal.hs \
	src/Ganeti/HTools/Program/Hcheck.hs \
	src/Ganeti/HTools/Program/Hinfo.hs \
	src/Ganeti/HTools/Program/Hscan.hs \
	src/Ganeti/HTools/Program/Hspace.hs \
	src/Ganeti/HTools/Program/Hroller.hs \
	src/Ganeti/HTools/Program/Main.hs \
	src/Ganeti/HTools/Types.hs \
	src/Ganeti/Hash.hs \
	src/Ganeti/JQueue.hs \
	src/Ganeti/JSON.hs \
	src/Ganeti/Jobs.hs \
	src/Ganeti/Logging.hs \
	src/Ganeti/Luxi.hs \
	src/Ganeti/Network.hs \
	src/Ganeti/Objects.hs \
	src/Ganeti/OpCodes.hs \
	src/Ganeti/OpParams.hs \
	src/Ganeti/Path.hs \
	src/Ganeti/Query/Common.hs \
	src/Ganeti/Query/Filter.hs \
	src/Ganeti/Query/Group.hs \
	src/Ganeti/Query/Job.hs \
	src/Ganeti/Query/Language.hs \
	src/Ganeti/Query/Network.hs \
	src/Ganeti/Query/Node.hs \
	src/Ganeti/Query/Query.hs \
	src/Ganeti/Query/Server.hs \
	src/Ganeti/Query/Types.hs \
	src/Ganeti/Rpc.hs \
	src/Ganeti/Runtime.hs \
	src/Ganeti/Ssconf.hs \
	src/Ganeti/THH.hs \
	src/Ganeti/Types.hs \
	src/Ganeti/Utils.hs

HS_TEST_SRCS = \
	test/hs/Test/Ganeti/Attoparsec.hs \
	test/hs/Test/Ganeti/BasicTypes.hs \
	test/hs/Test/Ganeti/Block/Drbd/Parser.hs \
	test/hs/Test/Ganeti/Block/Drbd/Types.hs \
	test/hs/Test/Ganeti/Common.hs \
	test/hs/Test/Ganeti/Confd/Types.hs \
	test/hs/Test/Ganeti/Confd/Utils.hs \
	test/hs/Test/Ganeti/Daemon.hs \
	test/hs/Test/Ganeti/Errors.hs \
	test/hs/Test/Ganeti/HTools/Backend/Simu.hs \
	test/hs/Test/Ganeti/HTools/Backend/Text.hs \
	test/hs/Test/Ganeti/HTools/CLI.hs \
	test/hs/Test/Ganeti/HTools/Cluster.hs \
	test/hs/Test/Ganeti/HTools/Container.hs \
	test/hs/Test/Ganeti/HTools/Graph.hs \
	test/hs/Test/Ganeti/HTools/Instance.hs \
	test/hs/Test/Ganeti/HTools/Loader.hs \
	test/hs/Test/Ganeti/HTools/Node.hs \
	test/hs/Test/Ganeti/HTools/PeerMap.hs \
	test/hs/Test/Ganeti/HTools/Types.hs \
	test/hs/Test/Ganeti/JSON.hs \
	test/hs/Test/Ganeti/Jobs.hs \
	test/hs/Test/Ganeti/JQueue.hs \
	test/hs/Test/Ganeti/Luxi.hs \
	test/hs/Test/Ganeti/Network.hs \
	test/hs/Test/Ganeti/Objects.hs \
	test/hs/Test/Ganeti/OpCodes.hs \
	test/hs/Test/Ganeti/Query/Filter.hs \
	test/hs/Test/Ganeti/Query/Language.hs \
	test/hs/Test/Ganeti/Query/Query.hs \
	test/hs/Test/Ganeti/Rpc.hs \
	test/hs/Test/Ganeti/Runtime.hs \
	test/hs/Test/Ganeti/Ssconf.hs \
	test/hs/Test/Ganeti/THH.hs \
	test/hs/Test/Ganeti/TestCommon.hs \
	test/hs/Test/Ganeti/TestHTools.hs \
	test/hs/Test/Ganeti/TestHelper.hs \
	test/hs/Test/Ganeti/Types.hs \
	test/hs/Test/Ganeti/Utils.hs

HS_LIBTEST_SRCS = $(HS_LIB_SRCS) $(HS_TEST_SRCS)

HS_BUILT_SRCS = \
	test/hs/Test/Ganeti/TestImports.hs \
	src/Ganeti/Constants.hs \
	src/Ganeti/Version.hs
HS_BUILT_SRCS_IN = $(patsubst %,%.in,$(HS_BUILT_SRCS))

$(RUN_IN_TEMPDIR): | stamp-directories

doc/html/index.html: ENABLE_MANPAGES =
doc/man-html/index.html: ENABLE_MANPAGES = 1
doc/man-html/index.html: doc/manpages-enabled.rst $(mandocrst)

# Note: we use here an order-only prerequisite, as the contents of
# _autoconf.py are not actually influencing the html build output: it
# has to exist in order for the sphinx module to be loaded
# successfully, but we certainly don't want the docs to be rebuilt if
# it changes
doc/html/index.html doc/man-html/index.html: $(docinput) doc/conf.py \
	configure.ac $(RUN_IN_TEMPDIR) lib/build/sphinx_ext.py \
	lib/build/shell_example_lexer.py lib/opcodes.py lib/ht.py \
	doc/css/style.css \
	| $(BUILT_PYTHON_SOURCES)
	@test -n "$(SPHINX)" || \
	    { echo 'sphinx-build' not found during configure; exit 1; }
if !MANPAGES_IN_DOC
	if test -n '$(ENABLE_MANPAGES)'; then \
	  echo 'Man pages in documentation were disabled at configure time' >&2; \
	  exit 1; \
	fi
endif
## Sphinx provides little control over what content should be included. Some
## mechanisms exist, but they all have drawbacks or actual issues. Since we
## build two different versions of the documentation--once without man pages and
## once, if enabled, with them--some control is necessary. xmpp-wrapper provides
## us with this, but requires running in a temporary directory. It moves the
## correct files into place depending on environment variables.
	dir=$(dir $@) && \
	@mkdir_p@ $$dir && \
	PYTHONPATH=. ENABLE_MANPAGES=$(ENABLE_MANPAGES) COPY_DOC=1 \
	$(RUN_IN_TEMPDIR) autotools/sphinx-wrapper $(SPHINX) -q -W -b html \
	    -d . \
	    -D version="$(VERSION_MAJOR).$(VERSION_MINOR)" \
	    -D release="$(PACKAGE_VERSION)" \
	    -D graphviz_dot="$(DOT)" \
	    -D enable_manpages="$(ENABLE_MANPAGES)" \
	    doc $(CURDIR)/$$dir && \
	rm -f $$dir/.buildinfo $$dir/objects.inv
	touch $@

doc/html: doc/html/index.html

doc/man-html: doc/man-html/index.html

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

doc/manpages-enabled.rst: Makefile | $(built_base_sources)
	{ echo '.. This file is automatically generated, do not edit!'; \
	  echo ''; \
	  echo 'Man pages'; \
	  echo '========='; \
	  echo; \
	  echo '.. toctree::'; \
	  echo '   :maxdepth: 1'; \
	  echo; \
	  for i in $(notdir $(mandocrst)); do \
	    echo "   $$i"; \
	  done | LC_ALL=C sort; \
	} > $@

doc/man-%.rst: man/%.gen Makefile $(REPLACE_VARS_SED) | $(built_base_sources)
if MANPAGES_IN_DOC
	{ echo '.. This file is automatically updated at build time from $<.'; \
	  echo '.. Do not edit.'; \
	  echo; \
	  echo "$*"; \
	  echo '=========================================='; \
	  tail -n +3 $< | sed -f $(REPLACE_VARS_SED); \
	} > $@
else
	echo 'Man pages in documentation were disabled at configure time' >&2; \
	exit 1;
endif

# Things to build but not to install (add it to EXTRA_DIST if it should be
# distributed)
noinst_DATA = \
	doc/html \
	$(BUILT_EXAMPLES) \
	doc/examples/bash_completion \
	doc/examples/bash_completion-debug \
	$(manhtml)

if MANPAGES_IN_DOC
noinst_DATA += doc/man-html
endif

gnt_scripts = \
	scripts/gnt-backup \
	scripts/gnt-cluster \
	scripts/gnt-debug \
	scripts/gnt-group \
	scripts/gnt-instance \
	scripts/gnt-job \
	scripts/gnt-network \
	scripts/gnt-node \
	scripts/gnt-os \
	scripts/gnt-storage

PYTHON_BOOTSTRAP_SBIN = \
	daemons/ganeti-masterd \
	daemons/ganeti-noded \
	daemons/ganeti-rapi \
	daemons/ganeti-watcher \
	$(gnt_scripts)

PYTHON_BOOTSTRAP = \
	$(PYTHON_BOOTSTRAP_SBIN) \
	tools/burnin \
	tools/ensure-dirs \
	tools/node-cleanup \
	tools/node-daemon-setup \
	tools/prepare-node-join

qa_scripts = \
	qa/__init__.py \
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
bin_SCRIPTS += $(HS_BIN_PROGS)
install-exec-hook:
	@mkdir_p@ $(DESTDIR)$(iallocatorsdir)
# FIXME: this is a hardcoded logic, instead of auto-resolving
	$(LN_S) -f ../../../bin/htools \
	  $(DESTDIR)$(iallocatorsdir)/hail
	for role in $(HS_BIN_ROLES); do \
	  $(LN_S) -f htools $(DESTDIR)$(bindir)/$$role ; \
	done
endif

$(HS_ALL_PROGS): %: %.hs $(HS_LIBTEST_SRCS) $(HS_BUILT_SRCS) Makefile
	@if [ "$(notdir $@)" = "test" ] && [ "$(HS_NODEV)" ]; then \
	  echo "Error: cannot run unittests without the development" \
	       " libraries (see devnotes.rst)" 1>&2; \
	  exit 1; \
	fi
	@rm -f $(notdir $@).tix
	$(GHC) --make \
	  $(HFLAGS) \
	  $(HS_NOCURL) $(HS_PARALLEL3) $(HS_REGEX_PCRE) \
	  -osuf $(notdir $@).o -hisuf $(notdir $@).hi \
	  $(HEXTRA) $(HEXTRA_INT) $@
	@touch "$@"

# for the test/hs/htest binary, we need to enable profiling/coverage
test/hs/htest: HEXTRA_INT=-fhpc -itest/hs

# we compile the hpc-htools binary with the program coverage
test/hs/hpc-htools: HEXTRA_INT=-fhpc

# we compile the hpc-mon-collector binary with the program coverage
test/hs/hpc-mon-collector: HEXTRA_INT=-fhpc

# test dependency
test/hs/offline-tests.sh: test/hs/hpc-htools test/hs/hpc-mon-collector

# rules for building profiling-enabled versions of the haskell
# programs: hs-prof does the full two-step build, whereas
# hs-prof-quick does only the final rebuild (hs-prof must have been
# run before)
.PHONY: hs-prof hs-prof-quick
hs-prof:
	@if [ -z "$(TARGET)" ]; then \
	  echo "You need to define TARGET when running this rule" 1>&2; \
	  exit 1; \
	fi
	$(MAKE) $(AM_MAKEFLAGS) clean
	$(MAKE) $(AM_MAKEFLAGS) $(TARGET) HEXTRA="-osuf o"
	rm -f $(HS_ALL_PROGS)
	$(MAKE) $(AM_MAKEFLAGS) hs-prof-quick

hs-prof-quick:
	@if [ -z "$(TARGET)" ]; then \
	  echo "You need to define TARGET when running this rule" 1>&2; \
	  exit 1; \
	fi
	$(MAKE) $(AM_MAKEFLAGS) $(TARGET) HEXTRA="-osuf prof_o -prof -auto-all"

dist_sbin_SCRIPTS = \
	tools/ganeti-listrunner

nodist_sbin_SCRIPTS = \
	$(PYTHON_BOOTSTRAP_SBIN) \
	daemons/ganeti-cleaner

if ENABLE_CONFD
src/ganeti-confd: src/hconfd
	cp -f $< $@

nodist_sbin_SCRIPTS += src/ganeti-confd
endif

python_scripts = \
	tools/cfgshell \
	tools/cfgupgrade \
	tools/cfgupgrade12 \
	tools/cluster-merge \
	tools/confd-client \
	tools/fmtjson \
	tools/lvmstrap \
	tools/move-instance \
	tools/ovfconverter \
	tools/sanitize-config

dist_tools_SCRIPTS = \
	$(python_scripts) \
	tools/kvm-console-wrapper \
	tools/master-ip-setup \
	tools/xen-console-wrapper

nodist_tools_python_scripts = \
	tools/node-cleanup

nodist_tools_SCRIPTS = \
	$(nodist_tools_python_scripts) \
	tools/vcluster-setup

pkglib_python_scripts = \
	daemons/import-export \
	tools/check-cert-expired

nodist_pkglib_python_scripts = \
	tools/burnin \
	tools/ensure-dirs \
	tools/node-daemon-setup \
	tools/prepare-node-join

myexeclib_SCRIPTS = \
	daemons/daemon-util \
	tools/kvm-ifup \
	$(pkglib_python_scripts) \
	$(HS_MYEXECLIB_PROGS)

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
	autotools/check-imports \
	autotools/check-man-dashes \
	autotools/check-man-references \
	autotools/check-man-warnings \
	autotools/check-news \
	autotools/check-python-code \
	autotools/check-tar \
	autotools/check-version \
	autotools/convert-constants \
	autotools/docpp \
	autotools/gen-py-coverage \
	autotools/sphinx-wrapper \
	autotools/testrunner \
	autotools/wrong-hardcoded-paths \
	$(RUN_IN_TEMPDIR) \
	daemons/daemon-util.in \
	daemons/ganeti-cleaner.in \
	$(pkglib_python_scripts) \
	devel/upload \
	devel/webserver \
	tools/kvm-ifup.in \
	tools/vcluster-setup.in \
	$(docinput) \
	doc/html \
	$(BUILT_EXAMPLES:%=%.in) \
	doc/examples/ganeti.default \
	doc/examples/ganeti.default-debug \
	doc/examples/hooks/ethers \
	doc/examples/gnt-debug/README \
	doc/examples/gnt-debug/delay0.json \
	doc/examples/gnt-debug/delay50.json \
	test/py/lockperf.py \
	test/py/testutils.py \
	test/py/mocks.py \
	$(dist_TESTS) \
	$(TEST_FILES) \
	man/footer.rst \
	$(manrst) \
	$(maninput) \
	qa/qa-sample.json \
	$(qa_scripts) \
	$(HS_LIBTEST_SRCS) $(HS_BUILT_SRCS_IN) \
	$(HS_PROG_SRCS) \
	src/lint-hints.hs \
	test/hs/cli-tests-defs.sh \
	test/hs/offline-test.sh \
	.ghci

man_MANS = \
	man/ganeti-cleaner.8 \
	man/ganeti-confd.8 \
	man/ganeti-listrunner.8 \
	man/ganeti-masterd.8 \
	man/ganeti-noded.8 \
	man/ganeti-os-interface.7 \
	man/ganeti-extstorage-interface.7 \
	man/ganeti-rapi.8 \
	man/ganeti-watcher.8 \
	man/ganeti.7 \
	man/gnt-backup.8 \
	man/gnt-cluster.8 \
	man/gnt-debug.8 \
	man/gnt-group.8 \
	man/gnt-network.8 \
	man/gnt-instance.8 \
	man/gnt-job.8 \
	man/gnt-node.8 \
	man/gnt-os.8 \
	man/gnt-storage.8 \
	man/hail.1 \
	man/hbal.1 \
	man/hcheck.1 \
	man/hinfo.1 \
	man/hscan.1 \
	man/hspace.1 \
	man/hroller.1 \
	man/htools.1 \
	man/mon-collector.7

# Remove extensions from all filenames in man_MANS
mannoext = $(patsubst %.1,%,$(patsubst %.7,%,$(patsubst %.8,%,$(man_MANS))))

manrst = $(patsubst %,%.rst,$(mannoext))
manhtml = $(patsubst %.rst,%.html,$(manrst))
mangen = $(patsubst %.rst,%.gen,$(manrst))
maninput = \
	$(patsubst %.1,%.1.in,$(patsubst %.7,%.7.in,$(patsubst %.8,%.8.in,$(man_MANS)))) \
	$(patsubst %.html,%.html.in,$(manhtml)) \
	$(mangen)

TEST_FILES = \
	test/data/htools/clean-nonzero-score.data \
	test/data/htools/common-suffix.data \
	test/data/htools/empty-cluster.data \
	test/data/htools/hail-alloc-drbd.json \
	test/data/htools/hail-change-group.json \
	test/data/htools/hail-invalid-reloc.json \
	test/data/htools/hail-node-evac.json \
	test/data/htools/hail-reloc-drbd.json \
	test/data/htools/hbal-excl-tags.data \
	test/data/htools/hbal-split-insts.data \
	test/data/htools/invalid-node.data \
	test/data/htools/missing-resources.data \
	test/data/htools/n1-failure.data \
	test/data/htools/rapi/groups.json \
	test/data/htools/rapi/info.json \
	test/data/htools/rapi/instances.json \
	test/data/htools/rapi/nodes.json \
	test/hs/shelltests/htools-balancing.test \
	test/hs/shelltests/htools-basic.test \
	test/hs/shelltests/htools-dynutil.test \
	test/hs/shelltests/htools-excl.test \
	test/hs/shelltests/htools-hail.test \
	test/hs/shelltests/htools-hspace.test \
	test/hs/shelltests/htools-invalid.test \
	test/hs/shelltests/htools-multi-group.test \
	test/hs/shelltests/htools-no-backend.test \
	test/hs/shelltests/htools-rapi.test \
	test/hs/shelltests/htools-single-group.test \
	test/hs/shelltests/htools-text-backend.test \
	test/hs/shelltests/htools-mon-collector.test \
	test/data/bdev-drbd-8.0.txt \
	test/data/bdev-drbd-8.3.txt \
	test/data/bdev-drbd-disk.txt \
	test/data/bdev-drbd-net-ip4.txt \
	test/data/bdev-drbd-net-ip6.txt \
	test/data/cert1.pem \
	test/data/cert2.pem \
	test/data/instance-minor-pairing.txt \
	test/data/ip-addr-show-dummy0.txt \
	test/data/ip-addr-show-lo-ipv4.txt \
	test/data/ip-addr-show-lo-ipv6.txt \
	test/data/ip-addr-show-lo-oneline-ipv4.txt \
	test/data/ip-addr-show-lo-oneline-ipv6.txt \
	test/data/ip-addr-show-lo-oneline.txt \
	test/data/ip-addr-show-lo.txt \
	test/data/kvm_0.12.5_help.txt \
	test/data/kvm_0.15.90_help.txt \
	test/data/kvm_0.9.1_help.txt \
	test/data/kvm_0.9.1_help_boot_test.txt \
	test/data/kvm_1.0_help.txt \
	test/data/kvm_1.1.2_help.txt \
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
	test/data/ovfdata/other/rawdisk.raw \
	test/data/ovfdata/ova.ova \
	test/data/ovfdata/rawdisk.raw \
	test/data/ovfdata/second_disk.vmdk \
	test/data/ovfdata/unsafe_path.ini \
	test/data/ovfdata/virtualbox.ovf \
	test/data/ovfdata/wrong_config.ini \
	test/data/ovfdata/wrong_extension.ovd \
	test/data/ovfdata/wrong_manifest.mf \
	test/data/ovfdata/wrong_manifest.ovf \
	test/data/ovfdata/wrong_ova.ova \
	test/data/ovfdata/wrong_xml.ovf \
	test/data/proc_drbd8.txt \
	test/data/proc_drbd80-emptyline.txt \
	test/data/proc_drbd83.txt \
	test/data/proc_drbd83_sync.txt \
	test/data/proc_drbd83_sync_want.txt \
	test/data/proc_drbd83_sync_krnl2.6.39.txt \
	test/data/qa-minimal-nodes-instances-only.json \
	test/data/sys_drbd_usermode_helper.txt \
	test/data/vgreduce-removemissing-2.02.02.txt \
	test/data/vgreduce-removemissing-2.02.66-fail.txt \
	test/data/vgreduce-removemissing-2.02.66-ok.txt \
	test/data/vgs-missing-pvs-2.02.02.txt \
	test/data/vgs-missing-pvs-2.02.66.txt \
	test/data/xen-xm-info-4.0.1.txt \
	test/data/xen-xm-list-4.0.1-dom0-only.txt \
	test/data/xen-xm-list-4.0.1-four-instances.txt \
	test/py/ganeti-cli.test \
	test/py/gnt-cli.test \
	test/py/import-export_unittest-helper

python_tests = \
	doc/examples/rapi_testutils.py \
	test/py/cfgupgrade_unittest.py \
	test/py/docs_unittest.py \
	test/py/ganeti.asyncnotifier_unittest.py \
	test/py/ganeti.backend_unittest-runasroot.py \
	test/py/ganeti.backend_unittest.py \
	test/py/ganeti.bdev_unittest.py \
	test/py/ganeti.cli_unittest.py \
	test/py/ganeti.client.gnt_cluster_unittest.py \
	test/py/ganeti.client.gnt_instance_unittest.py \
	test/py/ganeti.client.gnt_job_unittest.py \
	test/py/ganeti.cmdlib_unittest.py \
	test/py/ganeti.compat_unittest.py \
	test/py/ganeti.confd.client_unittest.py \
	test/py/ganeti.config_unittest.py \
	test/py/ganeti.constants_unittest.py \
	test/py/ganeti.daemon_unittest.py \
	test/py/ganeti.errors_unittest.py \
	test/py/ganeti.hooks_unittest.py \
	test/py/ganeti.ht_unittest.py \
	test/py/ganeti.http_unittest.py \
	test/py/ganeti.hypervisor.hv_chroot_unittest.py \
	test/py/ganeti.hypervisor.hv_fake_unittest.py \
	test/py/ganeti.hypervisor.hv_kvm_unittest.py \
	test/py/ganeti.hypervisor.hv_lxc_unittest.py \
	test/py/ganeti.hypervisor.hv_xen_unittest.py \
	test/py/ganeti.hypervisor_unittest.py \
	test/py/ganeti.impexpd_unittest.py \
	test/py/ganeti.jqueue_unittest.py \
	test/py/ganeti.jstore_unittest.py \
	test/py/ganeti.locking_unittest.py \
	test/py/ganeti.luxi_unittest.py \
	test/py/ganeti.masterd.iallocator_unittest.py \
	test/py/ganeti.masterd.instance_unittest.py \
	test/py/ganeti.mcpu_unittest.py \
	test/py/ganeti.netutils_unittest.py \
	test/py/ganeti.objects_unittest.py \
	test/py/ganeti.objectutils_unittest.py \
	test/py/ganeti.opcodes_unittest.py \
	test/py/ganeti.ovf_unittest.py \
	test/py/ganeti.qlang_unittest.py \
	test/py/ganeti.query_unittest.py \
	test/py/ganeti.rapi.baserlib_unittest.py \
	test/py/ganeti.rapi.client_unittest.py \
	test/py/ganeti.rapi.resources_unittest.py \
	test/py/ganeti.rapi.rlib2_unittest.py \
	test/py/ganeti.rapi.testutils_unittest.py \
	test/py/ganeti.rpc_unittest.py \
	test/py/ganeti.runtime_unittest.py \
	test/py/ganeti.serializer_unittest.py \
	test/py/ganeti.server.rapi_unittest.py \
	test/py/ganeti.ssconf_unittest.py \
	test/py/ganeti.ssh_unittest.py \
	test/py/ganeti.storage_unittest.py \
	test/py/ganeti.tools.burnin_unittest.py \
	test/py/ganeti.tools.ensure_dirs_unittest.py \
	test/py/ganeti.tools.node_daemon_setup_unittest.py \
	test/py/ganeti.tools.prepare_node_join_unittest.py \
	test/py/ganeti.uidpool_unittest.py \
	test/py/ganeti.utils.algo_unittest.py \
	test/py/ganeti.utils.filelock_unittest.py \
	test/py/ganeti.utils.hash_unittest.py \
	test/py/ganeti.utils.io_unittest-runasroot.py \
	test/py/ganeti.utils.io_unittest.py \
	test/py/ganeti.utils.log_unittest.py \
	test/py/ganeti.utils.lvm_unittest.py \
	test/py/ganeti.utils.mlock_unittest.py \
	test/py/ganeti.utils.nodesetup_unittest.py \
	test/py/ganeti.utils.process_unittest.py \
	test/py/ganeti.utils.retry_unittest.py \
	test/py/ganeti.utils.text_unittest.py \
	test/py/ganeti.utils.wrapper_unittest.py \
	test/py/ganeti.utils.x509_unittest.py \
	test/py/ganeti.utils_unittest.py \
	test/py/ganeti.vcluster_unittest.py \
	test/py/ganeti.workerpool_unittest.py \
	test/py/pycurl_reset_unittest.py \
	test/py/qa.qa_config_unittest.py \
	test/py/tempfile_fork_unittest.py

haskell_tests = test/hs/htest

dist_TESTS = \
	test/py/check-cert-expired_unittest.bash \
	test/py/daemon-util_unittest.bash \
	test/py/ganeti-cleaner_unittest.bash \
	test/py/import-export_unittest.bash \
	test/py/cli-test.bash \
	test/py/bash_completion.bash \
	$(python_tests)

nodist_TESTS =
check_SCRIPTS =

if WANT_HSTESTS
nodist_TESTS += $(haskell_tests)
dist_TESTS += test/hs/offline-test.sh
check_SCRIPTS += \
	test/hs/hpc-htools \
	test/hs/hpc-mon-collector \
	$(HS_BUILT_TEST_HELPERS)
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
	$(nodist_tools_python_scripts) \
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
	test/py/check-cert-expired_unittest.bash \
	test/py/daemon-util_unittest.bash \
	test/py/ganeti-cleaner_unittest.bash \
	test/py/import-export_unittest.bash \
	test/py/cli-test.bash \
	test/py/bash_completion.bash \
	test/hs/offline-test.sh \
	test/hs/cli-tests-defs.sh \
	$(all_python_code) \
	$(HS_LIBTEST_SRCS) $(HS_PROG_SRCS) \
	$(docinput)

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

test/py/daemon-util_unittest.bash: daemons/daemon-util

test/py/ganeti-cleaner_unittest.bash: daemons/ganeti-cleaner

test/py/bash_completion.bash: doc/examples/bash_completion-debug

tools/kvm-ifup: tools/kvm-ifup.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

tools/vcluster-setup: tools/vcluster-setup.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

daemons/%:: daemons/%.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

doc/examples/%:: doc/examples/%.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

doc/examples/bash_completion: BC_ARGS = --compact
doc/examples/bash_completion-debug: BC_ARGS =

doc/examples/bash_completion doc/examples/bash_completion-debug: \
	$(BUILD_BASH_COMPLETION) $(RUN_IN_TEMPDIR) \
	lib/cli.py $(gnt_scripts) $(client_PYTHON) tools/burnin \
	daemons/ganeti-cleaner \
	$(GENERATED_FILES) $(HS_GENERATED_FILES)
	PYTHONPATH=. $(RUN_IN_TEMPDIR) \
	  $(CURDIR)/$(BUILD_BASH_COMPLETION) $(BC_ARGS) > $@

man/%.gen: man/%.rst lib/query.py lib/build/sphinx_ext.py \
	lib/build/shell_example_lexer.py \
	| $(RUN_IN_TEMPDIR) $(BUILT_PYTHON_SOURCES)
	@echo "Checking $< for hardcoded paths..."
	@if grep -nEf autotools/wrong-hardcoded-paths $<; then \
	  echo "Man page $< has hardcoded paths (see above)!" 1>&2 ; \
	  exit 1; \
	fi
	set -e ; \
	trap 'echo auto-removing $@; rm $@' EXIT; \
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(DOCPP) < $< > $@ ;\
	$(CHECK_MAN_REFERENCES) $@; \
	trap - EXIT

man/%.7.in man/%.8.in man/%.1.in: man/%.gen man/footer.rst
	@test -n "$(PANDOC)" || \
	  { echo 'pandoc' not found during configure; exit 1; }
	set -o pipefail ; \
	trap 'echo auto-removing $@; rm $@' EXIT; \
	$(PANDOC) -s -f rst -t man $< man/footer.rst | \
	  sed -e 's/\\@/@/g' > $@; \
	if test -n "$(MAN_HAS_WARNINGS)"; then $(CHECK_MAN_WARNINGS) $@; fi; \
	$(CHECK_MAN_DASHES) $@; \
	trap - EXIT

man/%.html.in: man/%.gen man/footer.rst
	@test -n "$(PANDOC)" || \
	  { echo 'pandoc' not found during configure; exit 1; }
	set -o pipefail ; \
	$(PANDOC) --toc -s -f rst -t html $< man/footer.rst | \
	  sed -e 's/\\@/@/g' > $@

man/%: man/%.in  $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

epydoc.conf: epydoc.conf.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@

vcs-version:
	if test -d .git; then \
	  git describe > $@; \
	elif test ! -f $@ ; then \
	  echo "Cannot auto-generate $@ file"; exit 1; \
	fi

.PHONY: clean-vcs-version
clean-vcs-version:
	rm -f vcs-version

.PHONY: regen-vcs-version
regen-vcs-version:
	@set -e; \
	cd $(srcdir); \
	if test -d .git; then \
	  T=`mktemp` ; trap 'rm -f $$T' EXIT; \
	  git describe > $$T; \
	  if ! cmp --quiet $$T vcs-version; then \
	    mv $$T vcs-version; \
	  fi; \
	fi

src/Ganeti/Version.hs: src/Ganeti/Version.hs.in \
	vcs-version $(built_base_sources)
	set -e; \
	VCSVER=`cat $(abs_top_srcdir)/vcs-version`; \
	sed -e "s/%ver%/$$VCSVER/" < $< > $@

src/Ganeti/Constants.hs: src/Ganeti/Constants.hs.in \
	lib/constants.py lib/_autoconf.py lib/luxi.py lib/errors.py \
	lib/jstore.py $(RUN_IN_TEMPDIR) \
	$(CONVERT_CONSTANTS) $(built_base_sources) \
	| lib/_vcsversion.py
	set -e; \
	{ cat $< ; \
	  PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(CONVERT_CONSTANTS); \
	} > $@

test/hs/Test/Ganeti/TestImports.hs: test/hs/Test/Ganeti/TestImports.hs.in \
	$(built_base_sources)
	set -e; \
	{ cat $< ; \
	  echo ; \
	  for name in $(filter-out Ganeti.THH,$(subst /,.,$(patsubst %.hs,%,$(patsubst src/%,%,$(HS_LIB_SRCS))))) ; do \
	    echo "import $$name ()" ; \
	  done ; \
	} > $@

lib/_autoconf.py: Makefile | stamp-directories
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
	  echo "SSH_LOGIN_USER = '$(SSH_LOGIN_USER)'"; \
	  echo "SSH_CONSOLE_USER = '$(SSH_CONSOLE_USER)'"; \
	  echo "EXPORT_DIR = '$(EXPORT_DIR)'"; \
	  echo "OS_SEARCH_PATH = [$(OS_SEARCH_PATH)]"; \
	  echo "ES_SEARCH_PATH = [$(ES_SEARCH_PATH)]"; \
	  echo "XEN_BOOTLOADER = '$(XEN_BOOTLOADER)'"; \
	  echo "XEN_CONFIG_DIR = '$(XEN_CONFIG_DIR)'"; \
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
	  echo "HTOOLS_PROGS = [$(foreach i,$(HS_HTOOLS_PROGS),'$(i)',)]"; \
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
	  echo "HTOOLS = True"; \
	  echo "ENABLE_CONFD = $(ENABLE_CONFD)"; \
	  echo "XEN_CMD = '$(XEN_CMD)'"; \
	  echo "ENABLE_SPLIT_QUERY = $(ENABLE_SPLIT_QUERY)"; \
	  echo "ENABLE_RESTRICTED_COMMANDS = $(ENABLE_RESTRICTED_COMMANDS)"; \
	  echo "ENABLE_MONITORING = $(ENABLE_MONITORING)"; \
## Write dictionary with man page name as the key and the section number as the
## value
	  echo "MAN_PAGES = {"; \
	  for i in $(notdir $(man_MANS)); do \
	    echo "$$i" | sed -re 's/^(.*)\.([0-9]+)$$/  "\1": \2,/g'; \
	  done; \
	  echo "}"; \
	} > $@

lib/_vcsversion.py: Makefile vcs-version | stamp-directories
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

$(SHELL_ENV_INIT): Makefile stamp-directories
	set -e; \
	{ echo '# Allow overriding for tests'; \
	  echo 'readonly LOCALSTATEDIR=$${LOCALSTATEDIR:-$${GANETI_ROOTDIR:-}$(localstatedir)}'; \
	  echo 'readonly SYSCONFDIR=$${SYSCONFDIR:-$${GANETI_ROOTDIR:-}$(sysconfdir)}'; \
	  echo; \
	  echo 'readonly PKGLIBDIR=$(pkglibdir)'; \
	  echo 'readonly LOG_DIR="$$LOCALSTATEDIR/log/ganeti"'; \
	  echo 'readonly RUN_DIR="$$LOCALSTATEDIR/run/ganeti"'; \
	  echo 'readonly DATA_DIR="$$LOCALSTATEDIR/lib/ganeti"'; \
	  echo 'readonly CONF_DIR="$$SYSCONFDIR/ganeti"'; \
	} > $@

## Writes sed script to replace placeholders with build-time values. The
## additional quotes after the first @ sign are necessary to stop configure
## from replacing those values as well.
$(REPLACE_VARS_SED): $(SHELL_ENV_INIT) Makefile stamp-directories
	set -e; \
	{ echo 's#@''PREFIX@#$(prefix)#g'; \
	  echo 's#@''SYSCONFDIR@#$(sysconfdir)#g'; \
	  echo 's#@''LOCALSTATEDIR@#$(localstatedir)#g'; \
	  echo 's#@''BINDIR@#$(bindir)#g'; \
	  echo 's#@''SBINDIR@#$(sbindir)#g'; \
	  echo 's#@''LIBDIR@#$(libdir)#g'; \
	  echo 's#@''GANETI_VERSION@#$(PACKAGE_VERSION)#g'; \
	  echo 's#@''CUSTOM_XEN_BOOTLOADER@#$(XEN_BOOTLOADER)#g'; \
	  echo 's#@''CUSTOM_XEN_KERNEL@#$(XEN_KERNEL)#g'; \
	  echo 's#@''CUSTOM_XEN_INITRD@#$(XEN_INITRD)#g'; \
	  echo 's#@''CUSTOM_IALLOCATOR_SEARCH_PATH@#$(IALLOCATOR_SEARCH_PATH)#g'; \
	  echo 's#@''CUSTOM_EXPORT_DIR@#$(EXPORT_DIR)#g'; \
	  echo 's#@''RPL_FILE_STORAGE_DIR@#$(FILE_STORAGE_DIR)#g'; \
	  echo 's#@''RPL_SSH_INITD_SCRIPT@#$(SSH_INITD_SCRIPT)#g'; \
	  echo 's#@''PKGLIBDIR@#$(pkglibdir)#g'; \
	  echo 's#@''GNTMASTERUSER@#$(MASTERD_USER)#g'; \
	  echo 's#@''GNTRAPIUSER@#$(RAPI_USER)#g'; \
	  echo 's#@''GNTCONFDUSER@#$(CONFD_USER)#g'; \
	  echo 's#@''GNTNODEDUSER@#$(NODED_USER)#g'; \
	  echo 's#@''GNTRAPIGROUP@#$(RAPI_GROUP)#g'; \
	  echo 's#@''GNTADMINGROUP@#$(ADMIN_GROUP)#g'; \
	  echo 's#@''GNTCONFDGROUP@#$(CONFD_GROUP)#g'; \
	  echo 's#@''GNTMASTERDGROUP@#$(MASTERD_GROUP)#g'; \
	  echo 's#@''GNTDAEMONSGROUP@#$(DAEMONS_GROUP)#g'; \
	  echo 's#@''CUSTOM_ENABLE_CONFD@#$(ENABLE_CONFD)#g'; \
	  echo 's#@''MODULES@#$(strip $(lint_python_code))#g'; \
	  echo 's#@''XEN_CONFIG_DIR@#$(XEN_CONFIG_DIR)#g'; \
	  echo; \
	  echo '/^@SHELL_ENV_INIT@$$/ {'; \
	  echo '  r $(SHELL_ENV_INIT)'; \
	  echo '  d'; \
	  echo '}'; \
	} > $@

# Using deferred evaluation
daemons/ganeti-%: MODULE = ganeti.server.$(patsubst ganeti-%,%,$(notdir $@))
daemons/ganeti-watcher: MODULE = ganeti.watcher
scripts/%: MODULE = ganeti.client.$(subst -,_,$(notdir $@))
tools/burnin: MODULE = ganeti.tools.burnin
tools/ensure-dirs: MODULE = ganeti.tools.ensure_dirs
tools/node-daemon-setup: MODULE = ganeti.tools.node_daemon_setup
tools/prepare-node-join: MODULE = ganeti.tools.prepare_node_join
tools/node-cleanup: MODULE = ganeti.tools.node_cleanup
$(HS_BUILT_TEST_HELPERS): TESTROLE = $(patsubst test/hs/%,%,$@)

$(PYTHON_BOOTSTRAP): Makefile | stamp-directories
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
	  echo "HTOOLS=$(TESTROLE) exec ./test/hs/hpc-htools \"\$$@\""; \
	} > $@
	chmod u+x $@

stamp-directories: Makefile
	$(MAKE) $(AM_MAKEFLAGS) ganeti
	@mkdir_p@ $(DIRS) $(BUILDTIME_DIR_AUTOCREATE)
	touch $@

# We need to create symlinks because "make distcheck" will not install Python
# files when building.
stamp-srclinks: Makefile | stamp-directories
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
check-dirs: $(GENERATED_FILES)
	@set -e; \
	find . -type d \( -name . -o -name .git -prune -o -print \) | { \
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
	  test -z "$$error"; \
	}

.PHONY: check-local
check-local: check-dirs $(GENERATED_FILES)
	$(CHECK_PYTHON_CODE) $(check_python_code)
	PYTHONPATH=. $(CHECK_HEADER) $(check_python_code)
	$(CHECK_VERSION) $(VERSION) $(top_srcdir)/NEWS
	$(CHECK_NEWS) < $(top_srcdir)/NEWS
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(CHECK_IMPORTS) . $(standalone_python_modules)
	@expver=$(VERSION_MAJOR).$(VERSION_MINOR); \
	error= ; \
	if test "`head -n 1 $(top_srcdir)/README`" != "Ganeti $$expver"; then \
	  echo "Incorrect version in README, expected $$expver" >&2; \
	  error=1; \
	fi; \
	for file in doc/iallocator.rst doc/hooks.rst doc/virtual-cluster.rst \
	    doc/security.rst; do \
	  if test "`sed -ne '4 p' $(top_srcdir)/$$file`" != \
	    "Documents Ganeti version $$expver"; then \
	    echo "Incorrect version in $$file, expected $$expver" >&2; \
	    error=1; \
	  fi; \
	done; \
	if ! test -f $(top_srcdir)/doc/design-$$expver.rst; then \
	  echo "File $(top_srcdir)/doc/design-$$expver.rst not found" >&2; \
	  error=1; \
	fi; \
	if test "`sed -ne '5 p' $(top_srcdir)/doc/design-draft.rst`" != \
	  ".. Last updated for Ganeti $$expver"; then \
	  echo "doc/design-draft.rst was not updated for version $$expver" >&2; \
	  error=1; \
	fi; \
	for file in configure.ac $(HS_LIBTEST_SRCS) $(HS_PROG_SRCS); do \
	  if test $$(wc --max-line-length < $(top_srcdir)/$$file) -gt 80; then \
	    echo "Longest line in $$file is longer than 80 characters" >&2; \
	    error=1; \
	  fi; \
	done; \
	test -z "$$error"

.PHONY: hs-tests
hs-tests: test/hs/htest | $(BUILT_PYTHON_SOURCES)
	@rm -f htest.tix
	./test/hs/htest

.PHONY: hs-shell
hs-shell: test/hs/hpc-htools test/hs/hpc-mon-collector $(HS_BUILT_TEST_HELPERS)
	@rm -f hpc-htools.tix hpc-mon-collector.tix
	HBINARY="./test/hs/hpc-htools" ./test/hs/offline-test.sh

.PHONY: hs-check
hs-check: hs-tests hs-shell

# E111: indentation is not a multiple of four
# E121: continuation line indentation is not a multiple of four
#       (since our indent level is not 4)
# E125: continuation line does not distinguish itself from next logical line
#       (since our indent level is not 4)
# E127: continuation line over-indented for visual indent
#       (since our indent level is not 4)
# note: do NOT add E128 here; it's a valid style error in most cases!
# I've seen real errors, but also some cases were we indent wrongly
# due to line length; try to rework the cases where it is triggered,
# instead of silencing it
# E261: at least two spaces before inline comment
# E501: line too long (80 characters)
PEP8_IGNORE = E111,E121,E125,E127,E261,E501

# For excluding pep8 expects filenames only, not whole paths
PEP8_EXCLUDE = $(subst $(space),$(comma),$(strip $(notdir $(BUILT_PYTHON_SOURCES))))

LINT_TARGETS = pylint pylint-qa
if HAS_PEP8
LINT_TARGETS += pep8
endif
if HAS_HLINT
LINT_TARGETS += hlint
endif

.PHONY: lint
lint: $(LINT_TARGETS)

.PHONY: pylint
pylint: $(GENERATED_FILES)
	@test -n "$(PYLINT)" || { echo 'pylint' not found during configure; exit 1; }
	$(PYLINT) $(LINT_OPTS) $(lint_python_code)

.PHONY: pylint-qa
pylint-qa: $(GENERATED_FILES)
	@test -n "$(PYLINT)" || { echo 'pylint' not found during configure; exit 1; }
	cd $(top_srcdir)/qa && \
	  PYTHONPATH=$(abs_top_srcdir) $(PYLINT) $(LINT_OPTS) \
	  --rcfile  ../pylintrc $(patsubst qa/%.py,%,$(qa_scripts))

.PHONY: pep8
pep8: $(GENERATED_FILES)
	@test -n "$(PEP8)" || { echo 'pep8' not found during configure; exit 1; }
	$(PEP8) --ignore='$(PEP8_IGNORE)' --exclude='$(PEP8_EXCLUDE)' \
	  --repeat $(pep8_python_code)

# FIXME: remove ignore "Use void" when GHC 6.x is deprecated
HLINT_EXCLUDES = src/Ganeti/THH.hs test/hs/hpc-htools.hs
.PHONY: hlint
hlint: $(HS_BUILT_SRCS) src/lint-hints.hs
	@test -n "$(HLINT)" || { echo 'hlint' not found during configure; exit 1; }
	@rm -f doc/hs-lint.html
	if tty -s; then C="-c"; else C=""; fi; \
	$(HLINT) --utf8 --report=doc/hs-lint.html --cross $$C \
	  --ignore "Use first" \
	  --ignore "Use &&&" \
	  --ignore "Use void" \
	  --ignore "Reduce duplication" \
	  --hint src/lint-hints \
	  $(filter-out $(HLINT_EXCLUDES),$(HS_LIBTEST_SRCS) $(HS_PROG_SRCS))
	@if [ ! -f doc/hs-lint.html ]; then \
	  echo "All good" > doc/hs-lint.html; \
	fi

# a dist hook rule for updating the vcs-version file; this is
# hardcoded due to where it needs to build the file...
dist-hook:
	$(MAKE) $(AM_MAKEFLAGS) regen-vcs-version
	rm -f $(top_distdir)/vcs-version
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
	if test -e $(top_distdir)/doc/man-html; then \
	  echo "Found documentation including man pages in final archive" >&2; \
	  exit 1; \
	fi

# When building a release, stricter checks should be used
distcheck-release dist-release: export BUILD_RELEASE = 1
distcheck-release: distcheck

distrebuildcheck: dist
	set -e; \
	builddir=$$(mktemp -d $(abs_srcdir)/distrebuildcheck.XXXXXXX); \
	trap "echo Removing $$builddir; cd $(abs_srcdir); rm -rf $$builddir" EXIT; \
	cd $$builddir; \
	tar xzf $(abs_srcdir)/$(distdir).tar.gz; \
	cd $(distdir); \
	./configure; \
	$(MAKE) maintainer-clean; \
	cp $(abs_srcdir)/vcs-version .; \
	./configure; \
	$(MAKE) $(AM_MAKEFLAGS)

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

.PHONY: apidoc
if WANT_HSAPIDOC
apidoc: py-apidoc hs-apidoc
else
apidoc: py-apidoc
endif

.PHONY: py-apidoc
py-apidoc: epydoc.conf $(RUN_IN_TEMPDIR) $(GENERATED_FILES)
	env - PATH="$$PATH" PYTHONPATH="$$PYTHONPATH" \
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
	for i in $(ALL_APIDOC_HS_DIRS); do \
	  @mkdir_p@ $$i; \
	done
	$(HSCOLOUR) -print-css > $(APIDOC_HS_DIR)/Ganeti/hscolour.css
	$(LN_S) ../hscolour.css $(APIDOC_HS_DIR)/Ganeti/HTools/hscolour.css
	$(LN_S) ../hscolour.css $(APIDOC_HS_DIR)/Ganeti/Confd/hscolour.css
	set -e ; \
	cd src; \
	if [ "$(HS_NOCURL)" ]; \
	then OPTGHC="--optghc=$(HS_NOCURL)"; \
	else OPTGHC=""; \
	fi; \
	if [ "$(HS_PARALLEL3)" ]; \
	then OPTGHC="$$OPTGHC --optghc=$(HS_PARALLEL3)"; \
	fi; \
	if [ "$(HS_REGEX_PCRE)" ]; \
	then OPTGHC="$$OPTGHC --optghc=$(HS_REGEX_PCRE)"; \
	fi; \
	RELSRCS="$(HS_LIB_SRCS:src/%=%) $(patsubst src/%,%,$(filter src/%,$(HS_BUILT_SRCS)))"; \
	for file in $$RELSRCS; do \
	  hfile=`echo $$file|sed 's/\\.hs$$//'`.html; \
	  $(HSCOLOUR) -css -anchor $$file > ../$(APIDOC_HS_DIR)/$$hfile ; \
	done ; \
	$(HADDOCK) --odir ../$(APIDOC_HS_DIR) --html --ignore-all-exports -w \
	  -t ganeti -p haddock-prologue \
	  --source-module="%{MODULE/.//}.html" \
	  --source-entity="%{MODULE/.//}.html#%{NAME}" \
	  $$OPTGHC \
	  $(filter-out Ganeti/HTools/ExtLoader.hs,$(HS_LIB_SRCS:src/%=%))

.PHONY: TAGS
TAGS: $(GENERATED_FILES)
	rm -f TAGS
	$(GHC) -e ":etags" -v0 \
	  $(filter-out -O -Werror,$(HFLAGS)) \
	  $(HS_NOCURL) $(HS_PARALLEL3) $(HS_REGEX_PCRE) \
	  $(HS_LIBTEST_SRCS)
	find . -path './lib/*.py' -o -path './scripts/gnt-*' -o \
	  -path './daemons/ganeti-*' -o -path './tools/*' -o \
	  -path './qa/*.py' | \
	  etags -l python -a -

.PHONY: coverage
if WANT_HTOOLS
coverage: py-coverage hs-coverage
else
coverage: py-coverage
endif

.PHONY: py-coverage
py-coverage: $(GENERATED_FILES) $(python_tests)
	@test -n "$(PYCOVERAGE)" || \
	    { echo 'python-coverage' not found during configure; exit 1; }
	set -e; \
	COVERAGE=$(PYCOVERAGE) \
	COVERAGE_FILE=$(CURDIR)/$(COVERAGE_PY_DIR)/data \
	TEXT_COVERAGE=$(CURDIR)/$(COVERAGE_PY_DIR)/report.txt \
	HTML_COVERAGE=$(CURDIR)/$(COVERAGE_PY_DIR) \
	$(PLAIN_TESTS_ENVIRONMENT) \
	$(abs_top_srcdir)/autotools/gen-py-coverage \
	$(python_tests)

.PHONY: hs-coverage
hs-coverage: $(haskell_tests) test/hs/hpc-htools test/hs/hpc-mon-collector
	rm -f *.tix
	$(MAKE) $(AM_MAKEFLAGS) hs-check
	@mkdir_p@ $(COVERAGE_HS_DIR)
	hpc sum --union $(HPCEXCL) \
	  htest.tix hpc-htools.tix hpc-mon-collector.tix > coverage-hs.tix
	hpc markup --destdir=$(COVERAGE_HS_DIR) coverage-hs.tix
	hpc report coverage-hs.tix
	$(LN_S) -f hpc_index.html $(COVERAGE_HS_DIR)/index.html

# Special "kind-of-QA" target for htools, needs special setup (all
# tools compiled with -fhpc)
.PHONY: live-test
live-test: all
	set -e ; \
	cd src; \
	rm -f .hpc; $(LN_S) ../.hpc .hpc; \
	rm -f *.tix *.mix; \
	./live-test.sh; \
	hpc sum --union $(HPCEXCL) $(addsuffix .tix,$(HS_PROGS:src/%=%)) \
	  --output=live-test.tix ; \
	@mkdir_p@ ../$(COVERAGE_HS_DIR) ; \
	hpc markup --destdir=../$(COVERAGE_HS_DIR) live-test \
	  --srcdir=.. $(HPCEXCL) ; \
	hpc report --srcdir=.. live-test $(HPCEXCL)

commit-check: distcheck lint apidoc

.PHONY: gitignore-check
gitignore-check:
	@if [ -n "`git status --short`" ]; then \
	  echo "Git status is not clean!" 1>&2 ; \
	  git status --short; \
	  exit 1; \
	fi

# target to rebuild all man pages (both groff and html output)
.PHONY: man
man: $(man_MANS) $(manhtml)

# Target that builds all binaries (including those that are not
# rebuilt except when running the tests)
.PHONY: really-all
really-all: all $(check_SCRIPTS) $(haskell_tests) $(HS_ALL_PROGS)

# we don't need the ancient implicit rules:
%: %,v
%: RCS/%,v
%: RCS/%
%: s.%
%: SCCS/s.%

-include ./Makefile.local

# vim: set noet :
