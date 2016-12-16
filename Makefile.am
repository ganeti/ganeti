# Ganeti makefile
# - Indent with tabs only.
# - Keep files sorted; one line per file.
# - Directories in lib/ must have their own *dir variable (see hypervisor).
# - All directories must be listed DIRS.
# - Use autogen.sh to generate Makefile.in and configure script.

# For distcheck we need the haskell tests to be enabled. Note:
# The "correct" way would be to define AM_DISTCHECK_CONFIGURE_FLAGS.
# However, we still have to support older versions of autotools,
# so we cannot use that yet, hence we fall back to..
DISTCHECK_CONFIGURE_FLAGS = --enable-haskell-tests

# Automake doesn't export these variables before version 1.10.
abs_top_builddir = @abs_top_builddir@
abs_top_srcdir = @abs_top_srcdir@

# Helper values for calling builtin functions
empty :=
space := $(empty) $(empty)
comma := ,

# Helper function to strip src/ and test/hs/ from a list
strip_hsroot = $(patsubst src/%,%,$(patsubst test/hs/%,%,$(1)))

# Use bash in order to be able to use pipefail
SHELL=/bin/bash

EXTRA_DIST=

# Enable colors in shelltest
SHELLTESTARGS = "-c"

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
PRINT_PY_CONSTANTS = $(top_srcdir)/autotools/print-py-constants
BUILD_RPC = $(top_srcdir)/autotools/build-rpc
SHELL_ENV_INIT = autotools/shell-env-init

# starting as of Ganeti 2.10, all files are stored in two directories,
# with only symbolic links added at other places.
#
# $(versiondir) contains most of Ganeti and all architecture-dependent files
# $(versionedsharedir) contains only architecture-independent files; all python
# executables need to go directly to $(versionedsharedir), as all ganeti python
# mdules are installed outside the usual python path, i.e., as private modules.
#
# $(defaultversiondir) and $(defaultversionedsharedir) are the corresponding
# directories for "the currently running" version of Ganeti. We never install
# there, but all symbolic links go there, rather than directory to $(versiondir)
# or $(versionedsharedir). Note that all links to $(default*dir) need to be stable;
# so, if some currently architecture-independent executable is replaced by an
# architecture-dependent one (and hence has to go under $(versiondir)), add a link
# under $(versionedsharedir) but do not change the external links.
if USE_VERSION_FULL
DIRVERSION=$(VERSION_FULL)
else
DIRVERSION=$(VERSION_MAJOR).$(VERSION_MINOR)
endif
versiondir = $(libdir)/ganeti/$(DIRVERSION)
defaultversiondir = $(libdir)/ganeti/default
versionedsharedir = $(prefix)/share/ganeti/$(DIRVERSION)
defaultversionedsharedir = $(prefix)/share/ganeti/default

# Note: these are automake-specific variables, and must be named after
# the directory + 'dir' suffix
pkglibdir = $(versiondir)$(libdir)/ganeti
myexeclibdir = $(pkglibdir)
bindir = $(versiondir)/$(BINDIR)
sbindir = $(versiondir)$(SBINDIR)
mandir = $(versionedsharedir)/root$(MANDIR)
pkgpythondir = $(versionedsharedir)/ganeti
pkgpython_rpc_stubdir = $(versionedsharedir)/ganeti/rpc/stub
gntpythondir = $(versionedsharedir)
pkgpython_bindir = $(versionedsharedir)
gnt_python_sbindir = $(versionedsharedir)
tools_pythondir = $(versionedsharedir)

clientdir = $(pkgpythondir)/client
cmdlibdir = $(pkgpythondir)/cmdlib
cmdlib_clusterdir = $(pkgpythondir)/cmdlib/cluster
configdir = $(pkgpythondir)/config
hypervisordir = $(pkgpythondir)/hypervisor
hypervisor_hv_kvmdir = $(pkgpythondir)/hypervisor/hv_kvm
jqueuedir = $(pkgpythondir)/jqueue
storagedir = $(pkgpythondir)/storage
httpdir = $(pkgpythondir)/http
masterddir = $(pkgpythondir)/masterd
confddir = $(pkgpythondir)/confd
rapidir = $(pkgpythondir)/rapi
rpcdir = $(pkgpythondir)/rpc
rpc_stubdir = $(pkgpythondir)/rpc/stub
serverdir = $(pkgpythondir)/server
watcherdir = $(pkgpythondir)/watcher
impexpddir = $(pkgpythondir)/impexpd
utilsdir = $(pkgpythondir)/utils
toolsdir = $(pkglibdir)/tools
iallocatorsdir = $(pkglibdir)/iallocators
pytoolsdir = $(pkgpythondir)/tools
docdir = $(versiondir)$(datadir)/doc/$(PACKAGE)
ifupdir = $(sysconfdir)/ganeti

if USE_BACKUP_DIR
backup_dir = $(BACKUP_DIR)
else
backup_dir = $(localstatedir)/lib
endif

SYMLINK_TARGET_DIRS = \
	$(sysconfdir)/ganeti \
	$(libdir)/ganeti/iallocators \
	$(libdir)/ganeti/tools \
	$(prefix)/share/ganeti \
	$(BINDIR) \
	$(SBINDIR) \
	$(MANDIR)/man1 \
	$(MANDIR)/man7 \
	$(MANDIR)/man8

# Delete output file if an error occurred while building it
.DELETE_ON_ERROR:

HS_DIRS = \
	src \
	src/Ganeti \
	src/Ganeti/Confd \
	src/Ganeti/Curl \
	src/Ganeti/Cpu \
	src/Ganeti/DataCollectors \
	src/Ganeti/Daemon \
	src/Ganeti/Hs2Py \
	src/Ganeti/HTools \
	src/Ganeti/HTools/Backend \
	src/Ganeti/HTools/Cluster \
	src/Ganeti/HTools/Program \
	src/Ganeti/HTools/Tags \
	src/Ganeti/Hypervisor \
	src/Ganeti/Hypervisor/Xen \
	src/Ganeti/JQScheduler \
	src/Ganeti/JQueue \
	src/Ganeti/Locking \
	src/Ganeti/Logging \
	src/Ganeti/Monitoring \
	src/Ganeti/Metad \
	src/Ganeti/Objects \
	src/Ganeti/OpCodes \
	src/Ganeti/Query \
	src/Ganeti/Storage \
	src/Ganeti/Storage/Diskstats \
	src/Ganeti/Storage/Drbd \
	src/Ganeti/Storage/Lvm \
	src/Ganeti/THH \
	src/Ganeti/Utils \
	src/Ganeti/WConfd \
	test/hs \
	test/hs/Test \
	test/hs/Test/Ganeti \
	test/hs/Test/Ganeti/Storage \
	test/hs/Test/Ganeti/Storage/Diskstats \
	test/hs/Test/Ganeti/Storage/Drbd \
	test/hs/Test/Ganeti/Storage/Lvm \
	test/hs/Test/Ganeti/Confd \
	test/hs/Test/Ganeti/HTools \
	test/hs/Test/Ganeti/HTools/Backend \
	test/hs/Test/Ganeti/Hypervisor \
	test/hs/Test/Ganeti/Hypervisor/Xen \
	test/hs/Test/Ganeti/JQueue \
	test/hs/Test/Ganeti/Locking \
	test/hs/Test/Ganeti/Objects \
	test/hs/Test/Ganeti/Query \
	test/hs/Test/Ganeti/THH \
	test/hs/Test/Ganeti/Utils \
	test/hs/Test/Ganeti/WConfd

# Haskell directories without the roots (src, test/hs)
HS_DIRS_NOROOT = $(filter-out src,$(filter-out test/hs,$(HS_DIRS)))

DIRS = \
	$(HS_DIRS) \
	autotools \
	cabal \
	daemons \
	devel \
	devel/data \
	doc \
	doc/css \
	doc/examples \
	doc/examples/gnt-debug \
	doc/examples/hooks \
	doc/examples/systemd \
	doc/users \
	test/data/htools \
	test/data/htools/rapi \
	test/hs/shelltests \
	test/autotools \
	lib \
	lib/build \
	lib/client \
	lib/cmdlib \
	lib/cmdlib/cluster \
	lib/confd \
	lib/config \
	lib/jqueue \
	lib/http \
	lib/hypervisor \
	lib/hypervisor/hv_kvm \
	lib/impexpd \
	lib/masterd \
	lib/rapi \
	lib/rpc \
	lib/rpc/stub \
	lib/server \
	lib/storage \
	lib/tools \
	lib/utils \
	lib/watcher \
	man \
	qa \
	qa/patch \
	test \
	test/data \
	test/data/bdev-rbd \
	test/data/ovfdata \
	test/data/ovfdata/other \
	test/data/cgroup_root \
	test/data/cgroup_root/memory \
	test/data/cgroup_root/memory/lxc \
	test/data/cgroup_root/memory/lxc/instance1 \
	test/data/cgroup_root/cpuset \
	test/data/cgroup_root/cpuset/some_group \
	test/data/cgroup_root/cpuset/some_group/lxc \
	test/data/cgroup_root/cpuset/some_group/lxc/instance1 \
	test/data/cgroup_root/devices \
	test/data/cgroup_root/devices/some_group \
	test/data/cgroup_root/devices/some_group/lxc \
	test/data/cgroup_root/devices/some_group/lxc/instance1 \
	test/py \
	test/py/testutils \
	test/py/cmdlib \
	test/py/cmdlib/testsupport \
	tools

ALL_APIDOC_HS_DIRS = \
	$(APIDOC_HS_DIR) \
	$(patsubst %,$(APIDOC_HS_DIR)/%,$(call strip_hsroot,$(HS_DIRS_NOROOT)))

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
	apps \
	dist \
	doc/html \
	doc/man-html

DIRCHECK_EXCLUDE = \
	$(BUILDTIME_DIRS) \
	ganeti-[0-9]*.[0-9]*.[0-9]* \
	doc/html/_* \
	doc/man-html/_* \
	tools/shebang \
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
	$(addsuffix /*.$(HTEST_SUFFIX)_hi,$(HS_DIRS)) \
	$(addsuffix /*.$(HTEST_SUFFIX)_o,$(HS_DIRS)) \
	$(HASKELL_PACKAGE_VERSIONS_FILE) \
	$(CABAL_EXECUTABLES_APPS_STAMPS) \
	empty-cabal-config \
	ganeti.cabal \
	$(HASKELL_PACKAGE_IDS_FILE) \
	$(HASKELL_PACKAGE_VERSIONS_FILE) \
	Makefile.ghc \
	Makefile.ghc.bak \
	$(PYTHON_BOOTSTRAP) \
	$(gnt_python_sbin_SCRIPTS) \
	epydoc.conf \
	$(REPLACE_VARS_SED) \
	$(SHELL_ENV_INIT) \
	daemons/daemon-util \
	daemons/ganeti-cleaner \
	devel/squeeze-amd64.tar.gz \
	devel/squeeze-amd64.conf \
	$(mandocrst) \
	doc/manpages-enabled.rst \
	$(BUILT_EXAMPLES) \
	doc/examples/bash_completion \
	doc/examples/bash_completion-debug \
	$(userspecs) \
	lib/_generated_rpc.py \
	$(man_MANS) \
	$(manhtml) \
	tools/kvm-ifup \
	tools/kvm-ifup-os \
	tools/xen-ifup-os \
	tools/vif-ganeti \
	tools/vif-ganeti-metad \
	tools/net-common \
	tools/users-setup \
	tools/ssl-update \
	tools/vcluster-setup \
	tools/prepare-node-join \
	tools/ssh-update \
	$(python_scripts_shebang) \
	stamp-directories \
	stamp-srclinks \
	$(nodist_pkgpython_PYTHON) \
	$(nodist_pkgpython_rpc_stub_PYTHON) \
	$(gnt_scripts) \
	$(HS_ALL_PROGS) $(HS_BUILT_SRCS) \
	$(HS_BUILT_TEST_HELPERS) \
	src/ganeti-confd \
	src/ganeti-wconfd \
	src/ganeti-luxid \
	src/ganeti-metad \
	src/ganeti-mond \
	.hpc/*.mix src/*.tix test/hs/*.tix *.tix \
	doc/hs-lint.html

GENERATED_FILES = \
	$(built_base_sources) \
	$(built_python_sources) \
	$(PYTHON_BOOTSTRAP) \
	$(gnt_python_sbin_SCRIPTS)

clean-local:
	rm -rf tools/shebang
	rm -rf apps
	rm -rf dist

HS_GENERATED_FILES = $(HS_PROGS) src/hluxid src/ganeti-luxid \
	src/hconfd src/ganeti-confd
if ENABLE_MOND
HS_GENERATED_FILES += src/ganeti-mond
endif
if ENABLE_METADATA
HS_GENERATED_FILES += src/ganeti-metad
endif

built_base_sources = \
	stamp-directories \
	stamp-srclinks

built_python_base_sources = \
	lib/_constants.py \
	lib/_vcsversion.py \
	lib/opcodes.py \
	lib/rpc/stub/wconfd.py

if ENABLE_METADATA
built_python_base_sources += lib/rpc/stub/metad.py
endif

built_python_sources = \
	$(nodist_pkgpython_PYTHON) \
	$(nodist_pkgpython_rpc_stub_PYTHON)

# these are all built from the underlying %.in sources
BUILT_EXAMPLES = \
	doc/examples/ganeti-kvm-poweroff.initd \
	doc/examples/ganeti.cron \
	doc/examples/ganeti.initd \
	doc/examples/ganeti.logrotate \
	doc/examples/ganeti-master-role.ocf \
	doc/examples/ganeti-node-role.ocf \
	doc/examples/gnt-config-backup \
	doc/examples/hooks/ipsec \
	doc/examples/systemd/ganeti-common.service \
	doc/examples/systemd/ganeti-confd.service \
	doc/examples/systemd/ganeti-kvmd.service \
	doc/examples/systemd/ganeti-luxid.service \
	doc/examples/systemd/ganeti-metad.service \
	doc/examples/systemd/ganeti-mond.service \
	doc/examples/systemd/ganeti-noded.service \
	doc/examples/systemd/ganeti-rapi.service \
	doc/examples/systemd/ganeti-wconfd.service

nodist_ifup_SCRIPTS = \
	tools/kvm-ifup-os \
	tools/xen-ifup-os

nodist_pkgpython_PYTHON = \
	$(built_python_base_sources) \
	lib/_generated_rpc.py

nodist_pkgpython_rpc_stub_PYTHON = \
	lib/rpc/stub/wconfd.py

if ENABLE_METADATA
nodist_pkgpython_rpc_stub_PYTHON += lib/rpc/stub/metad.py
endif

nodist_pkgpython_bin_SCRIPTS = \
	$(nodist_pkglib_python_scripts)

pkgpython_bin_SCRIPTS = \
	$(pkglib_python_scripts)

noinst_PYTHON = \
	lib/build/__init__.py \
	lib/build/shell_example_lexer.py \
	lib/build/sphinx_ext.py

pkgpython_PYTHON = \
	lib/__init__.py \
	lib/asyncnotifier.py \
	lib/backend.py \
	lib/bootstrap.py \
	lib/cli.py \
	lib/cli_opts.py \
	lib/compat.py \
	lib/constants.py \
	lib/daemon.py \
	lib/errors.py \
	lib/hooksmaster.py \
	lib/ht.py \
	lib/jstore.py \
	lib/locking.py \
	lib/luxi.py \
	lib/mcpu.py \
	lib/metad.py \
	lib/netutils.py \
	lib/objects.py \
	lib/opcodes_base.py \
	lib/outils.py \
	lib/ovf.py \
	lib/pathutils.py \
	lib/qlang.py \
	lib/query.py \
	lib/rpc_defs.py \
	lib/runtime.py \
	lib/serializer.py \
	lib/ssconf.py \
	lib/ssh.py \
	lib/uidpool.py \
	lib/vcluster.py \
	lib/network.py \
	lib/wconfd.py \
	lib/workerpool.py

client_PYTHON = \
	lib/client/__init__.py \
	lib/client/base.py \
	lib/client/gnt_backup.py \
	lib/client/gnt_cluster.py \
	lib/client/gnt_debug.py \
	lib/client/gnt_group.py \
	lib/client/gnt_instance.py \
	lib/client/gnt_job.py \
	lib/client/gnt_node.py \
	lib/client/gnt_network.py \
	lib/client/gnt_os.py \
	lib/client/gnt_storage.py \
	lib/client/gnt_filter.py

cmdlib_PYTHON = \
	lib/cmdlib/__init__.py \
	lib/cmdlib/backup.py \
	lib/cmdlib/base.py \
	lib/cmdlib/common.py \
	lib/cmdlib/group.py \
	lib/cmdlib/instance.py \
	lib/cmdlib/instance_create.py \
	lib/cmdlib/instance_helpervm.py \
	lib/cmdlib/instance_migration.py \
	lib/cmdlib/instance_operation.py \
	lib/cmdlib/instance_query.py \
	lib/cmdlib/instance_set_params.py \
	lib/cmdlib/instance_storage.py \
	lib/cmdlib/instance_utils.py \
	lib/cmdlib/misc.py \
	lib/cmdlib/network.py \
	lib/cmdlib/node.py \
	lib/cmdlib/operating_system.py \
	lib/cmdlib/query.py \
	lib/cmdlib/tags.py \
	lib/cmdlib/test.py

cmdlib_cluster_PYTHON = \
	lib/cmdlib/cluster/__init__.py \
	lib/cmdlib/cluster/verify.py

config_PYTHON = \
	lib/config/__init__.py \
	lib/config/verify.py \
	lib/config/temporary_reservations.py \
	lib/config/utils.py

hypervisor_PYTHON = \
	lib/hypervisor/__init__.py \
	lib/hypervisor/hv_base.py \
	lib/hypervisor/hv_chroot.py \
	lib/hypervisor/hv_fake.py \
	lib/hypervisor/hv_lxc.py \
	lib/hypervisor/hv_xen.py

hypervisor_hv_kvm_PYTHON = \
	lib/hypervisor/hv_kvm/__init__.py \
	lib/hypervisor/hv_kvm/monitor.py \
	lib/hypervisor/hv_kvm/netdev.py

jqueue_PYTHON = \
	lib/jqueue/__init__.py \
	lib/jqueue/exec.py

storage_PYTHON = \
	lib/storage/__init__.py \
	lib/storage/bdev.py \
	lib/storage/base.py \
	lib/storage/container.py \
	lib/storage/drbd.py \
	lib/storage/drbd_info.py \
	lib/storage/drbd_cmdgen.py \
	lib/storage/extstorage.py \
	lib/storage/filestorage.py \
	lib/storage/gluster.py

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

rpc_PYTHON = \
	lib/rpc/__init__.py \
	lib/rpc/client.py \
	lib/rpc/errors.py \
	lib/rpc/node.py \
	lib/rpc/transport.py

rpc_stub_PYTHON = \
	lib/rpc/stub/__init__.py

pytools_PYTHON = \
	lib/tools/__init__.py \
	lib/tools/burnin.py \
	lib/tools/common.py \
	lib/tools/ensure_dirs.py \
	lib/tools/node_cleanup.py \
	lib/tools/node_daemon_setup.py \
	lib/tools/prepare_node_join.py \
	lib/tools/ssh_update.py \
	lib/tools/ssl_update.py \
	lib/tools/cfgupgrade.py

utils_PYTHON = \
	lib/utils/__init__.py \
	lib/utils/algo.py \
	lib/utils/filelock.py \
	lib/utils/hash.py \
	lib/utils/io.py \
	lib/utils/livelock.py \
	lib/utils/log.py \
	lib/utils/lvm.py \
	lib/utils/mlock.py \
	lib/utils/nodesetup.py \
	lib/utils/process.py \
	lib/utils/retry.py \
	lib/utils/security.py \
	lib/utils/storage.py \
	lib/utils/text.py \
	lib/utils/tags.py \
	lib/utils/version.py \
	lib/utils/wrapper.py \
	lib/utils/x509.py \
	lib/utils/bitarrays.py

docinput = \
	doc/admin.rst \
	doc/cluster-keys-replacement.rst \
	doc/cluster-merge.rst \
	doc/conf.py \
	doc/css/style.css \
	doc/design-2.0.rst \
	doc/design-2.1.rst \
	doc/design-2.2.rst \
	doc/design-2.3.rst \
	doc/design-2.4.rst \
	doc/design-2.5.rst \
	doc/design-2.6.rst \
	doc/design-2.7.rst \
	doc/design-2.8.rst \
	doc/design-2.9.rst \
	doc/design-2.10.rst \
	doc/design-2.11.rst \
	doc/design-2.12.rst \
	doc/design-2.13.rst \
	doc/design-2.14.rst \
	doc/design-2.15.rst \
	doc/design-2.16.rst \
	doc/design-allocation-efficiency.rst \
	doc/design-autorepair.rst \
	doc/design-bulk-create.rst \
	doc/design-ceph-ganeti-support.rst \
	doc/design-configlock.rst \
	doc/design-chained-jobs.rst \
	doc/design-cmdlib-unittests.rst \
	doc/design-cpu-pinning.rst \
	doc/design-cpu-speed.rst \
	doc/design-daemons.rst \
	doc/design-dedicated-allocation.rst \
	doc/design-device-uuid-name.rst \
	doc/design-disk-conversion.rst \
	doc/design-disks.rst \
	doc/design-draft.rst \
	doc/design-file-based-disks-ownership.rst \
	doc/design-file-based-storage.rst \
	doc/design-glusterfs-ganeti-support.rst \
	doc/design-hotplug.rst \
	doc/design-hroller.rst \
	doc/design-hsqueeze.rst \
	doc/design-htools-2.3.rst \
	doc/design-http-server.rst \
	doc/design-hugepages-support.rst \
	doc/design-ifdown.rst \
	doc/design-impexp2.rst \
	doc/design-internal-shutdown.rst \
	doc/design-kvmd.rst \
	doc/design-location.rst \
	doc/design-linuxha.rst \
	doc/design-lu-generated-jobs.rst \
	doc/design-monitoring-agent.rst \
	doc/design-move-instance-improvements.rst \
	doc/design-multi-reloc.rst \
	doc/design-multi-storage-htools.rst \
	doc/design-multi-version-tests.rst \
	doc/design-network.rst \
	doc/design-network2.rst \
	doc/design-node-add.rst \
	doc/design-node-security.rst \
	doc/design-oob.rst \
	doc/design-openvswitch.rst \
	doc/design-opportunistic-locking.rst \
	doc/design-optables.rst \
	doc/design-os.rst \
	doc/design-ovf-support.rst \
	doc/design-partitioned.rst \
	doc/design-plain-redundancy.rst \
	doc/design-performance-tests.rst \
	doc/design-query-splitting.rst \
	doc/design-query2.rst \
	doc/design-query-splitting.rst \
	doc/design-reason-trail.rst \
	doc/design-repaird.rst \
	doc/design-reservations.rst \
	doc/design-resource-model.rst \
	doc/design-restricted-commands.rst \
	doc/design-scsi-kvm.rst \
	doc/design-shared-storage.rst \
	doc/design-shared-storage-redundancy.rst \
	doc/design-ssh-ports.rst \
	doc/design-storagetypes.rst \
	doc/design-sync-rate-throttling.rst \
	doc/design-systemd.rst \
	doc/design-upgrade.rst \
	doc/design-virtual-clusters.rst \
	doc/design-x509-ca.rst \
	doc/dev-codestyle.rst \
	doc/devnotes.rst \
	doc/glossary.rst \
	doc/hooks.rst \
	doc/iallocator.rst \
	doc/index.rst \
	doc/install-quick.rst \
	doc/install.rst \
	doc/locking.rst \
	doc/manpages-disabled.rst \
	doc/monitoring-query-format.rst \
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
if ENABLE_MOND
HS_MYEXECLIB_PROGS=src/mon-collector
else
HS_MYEXECLIB_PROGS=
endif

# Haskell programs to be compiled by "make really-all"
HS_COMPILE_PROGS = \
	src/ganeti-kvmd \
	src/ganeti-wconfd \
	src/hconfd \
	src/hluxid \
	src/hs2py \
	src/rpc-test
if ENABLE_MOND
HS_COMPILE_PROGS += src/ganeti-mond
endif
if ENABLE_METADATA
HS_COMPILE_PROGS += src/ganeti-metad
endif

# All Haskell non-test programs to be compiled but not automatically installed
HS_PROGS = $(HS_BIN_PROGS) $(HS_MYEXECLIB_PROGS)

HS_BIN_ROLES = harep hbal hscan hspace hinfo hcheck hroller hsqueeze
HS_HTOOLS_PROGS = $(HS_BIN_ROLES) hail

# Haskell programs that cannot be disabled at configure (e.g., unlike
# 'mon-collector')
HS_DEFAULT_PROGS = \
	$(HS_BIN_PROGS) \
	test/hs/hpc-htools \
	test/hs/hpc-mon-collector \
	$(HS_COMPILE_PROGS)

if HTEST
HS_DEFAULT_PROGS += test/hs/htest
else
EXTRA_DIST += test/hs/htest.hs
endif

HS_ALL_PROGS = $(HS_DEFAULT_PROGS) $(HS_MYEXECLIB_PROGS)

HS_TEST_PROGS = $(filter test/%,$(HS_ALL_PROGS))
HS_SRC_PROGS = $(filter-out test/%,$(HS_ALL_PROGS))

HS_PROG_SRCS = $(patsubst %,%.hs,$(HS_DEFAULT_PROGS)) src/mon-collector.hs
HS_BUILT_TEST_HELPERS = $(HS_BIN_ROLES:%=test/hs/%) test/hs/hail

HFLAGS = \
	-O -Wall -isrc \
	-fwarn-monomorphism-restriction \
	-fwarn-tabs \
	-optP-include -optP$(HASKELL_PACKAGE_VERSIONS_FILE) \
	-hide-all-packages \
	`cat $(HASKELL_PACKAGE_IDS_FILE)` \
	$(GHC_BYVERSION_FLAGS)
if DEVELOPER_MODE
HFLAGS += -Werror
endif

HTEST_SUFFIX = hpc
HPROF_SUFFIX = prof

DEP_SUFFIXES =
if GHC_LE_76
DEP_SUFFIXES += -dep-suffix $(HPROF_SUFFIX) -dep-suffix $(HTEST_SUFFIX)
else
# GHC >= 7.8 stopped putting underscores into -dep-suffix by itself
# (https://ghc.haskell.org/trac/ghc/ticket/9749) so we have to put them.
# It also needs -dep-suffix "" for the .o file.
DEP_SUFFIXES += -dep-suffix $(HPROF_SUFFIX)_ -dep-suffix $(HTEST_SUFFIX)_ \
	-dep-suffix ""
endif

# GHC > 7.6 needs -dynamic-too when using Template Haskell since its
# ghci is switched to loading dynamic libraries by default.
# It must only be used in non-profiling GHC invocations.
# We also don't use it in compilations that use HTEST_SUFFIX (which are
# compiled with -fhpc) because HPC coverage doesn't interact well with
# GHCI shared lib loading (https://ghc.haskell.org/trac/ghc/ticket/9762).
HFLAGS_DYNAMIC =
if !GHC_LE_76
HFLAGS_DYNAMIC += -dynamic-too
endif

if HPROFILE
HPROFFLAGS = -prof -fprof-auto-top -osuf $(HPROF_SUFFIX)_o \
	-hisuf $(HPROF_SUFFIX)_hi -rtsopts
endif
if HCOVERAGE
HFLAGS += -fhpc
endif
if HTEST
HFLAGS += -DTEST
endif

HTEST_FLAGS = $(HFLAGS) -fhpc -itest/hs \
	-osuf $(HTEST_SUFFIX)_o \
	-hisuf $(HTEST_SUFFIX)_hi

# extra flags that can be overriden on the command line (e.g. -Wwarn, etc.)
HEXTRA =
# combination of HEXTRA and HEXTRA_CONFIGURE
HEXTRA_COMBINED = $(HEXTRA) $(HEXTRA_CONFIGURE)

# extra flags used for test/hs/htest
# Only use the threaded runtime and run tests in parallel for GHC > 7.6. A bug
# in base that wasn't fixed until 4.7.0.0 in GHC 7.8 causes random file lock
# errors in the JQueue tests with the threaded runtime.
# See https://ghc.haskell.org/trac/ghc/ticket/7646
if GHC_LE_76
HEXTRA_TEST =
else
HEXTRA_TEST = -threaded -with-rtsopts=-N
endif

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
	src/Ganeti/BasicTypes.hs \
	src/Ganeti/Codec.hs \
	src/Ganeti/Common.hs \
	src/Ganeti/Compat.hs \
	src/Ganeti/Confd/Client.hs \
	src/Ganeti/Confd/ClientFunctions.hs \
	src/Ganeti/Confd/Server.hs \
	src/Ganeti/Confd/Types.hs \
	src/Ganeti/Confd/Utils.hs \
	src/Ganeti/Config.hs \
	src/Ganeti/ConfigReader.hs \
	src/Ganeti/Constants.hs \
	src/Ganeti/ConstantUtils.hs \
	src/Ganeti/Cpu/LoadParser.hs \
	src/Ganeti/Cpu/Types.hs \
	src/Ganeti/Curl/Multi.hs \
	src/Ganeti/Daemon.hs \
	src/Ganeti/Daemon/Utils.hs \
	src/Ganeti/DataCollectors.hs \
	src/Ganeti/DataCollectors/CLI.hs \
	src/Ganeti/DataCollectors/CPUload.hs \
	src/Ganeti/DataCollectors/Diskstats.hs \
	src/Ganeti/DataCollectors/Drbd.hs \
	src/Ganeti/DataCollectors/InstStatus.hs \
	src/Ganeti/DataCollectors/InstStatusTypes.hs \
	src/Ganeti/DataCollectors/Lv.hs \
	src/Ganeti/DataCollectors/Program.hs \
	src/Ganeti/DataCollectors/Types.hs \
	src/Ganeti/DataCollectors/XenCpuLoad.hs \
	src/Ganeti/Errors.hs \
	src/Ganeti/HTools/AlgorithmParams.hs \
	src/Ganeti/HTools/Backend/IAlloc.hs \
	src/Ganeti/HTools/Backend/Luxi.hs \
	src/Ganeti/HTools/Backend/MonD.hs \
	src/Ganeti/HTools/Backend/Rapi.hs \
	src/Ganeti/HTools/Backend/Simu.hs \
	src/Ganeti/HTools/Backend/Text.hs \
	src/Ganeti/HTools/CLI.hs \
	src/Ganeti/HTools/Cluster.hs \
	src/Ganeti/HTools/Cluster/AllocatePrimitives.hs \
	src/Ganeti/HTools/Cluster/AllocateSecondary.hs \
	src/Ganeti/HTools/Cluster/AllocationSolution.hs \
	src/Ganeti/HTools/Cluster/Evacuate.hs \
	src/Ganeti/HTools/Cluster/Metrics.hs \
	src/Ganeti/HTools/Cluster/Moves.hs \
	src/Ganeti/HTools/Cluster/Utils.hs \
	src/Ganeti/HTools/Container.hs \
	src/Ganeti/HTools/Dedicated.hs \
	src/Ganeti/HTools/ExtLoader.hs \
	src/Ganeti/HTools/GlobalN1.hs \
	src/Ganeti/HTools/Graph.hs \
	src/Ganeti/HTools/Group.hs \
	src/Ganeti/HTools/Instance.hs \
	src/Ganeti/HTools/Loader.hs \
	src/Ganeti/HTools/Nic.hs \
	src/Ganeti/HTools/Node.hs \
	src/Ganeti/HTools/PeerMap.hs \
	src/Ganeti/HTools/Program/Hail.hs \
	src/Ganeti/HTools/Program/Harep.hs \
	src/Ganeti/HTools/Program/Hbal.hs \
	src/Ganeti/HTools/Program/Hcheck.hs \
	src/Ganeti/HTools/Program/Hinfo.hs \
	src/Ganeti/HTools/Program/Hscan.hs \
	src/Ganeti/HTools/Program/Hspace.hs \
	src/Ganeti/HTools/Program/Hsqueeze.hs \
	src/Ganeti/HTools/Program/Hroller.hs \
	src/Ganeti/HTools/Program/Main.hs \
	src/Ganeti/HTools/Tags.hs \
	src/Ganeti/HTools/Tags/Constants.hs \
	src/Ganeti/HTools/Types.hs \
	src/Ganeti/Hypervisor/Xen.hs \
	src/Ganeti/Hypervisor/Xen/XmParser.hs \
	src/Ganeti/Hypervisor/Xen/Types.hs \
	src/Ganeti/Hash.hs \
	src/Ganeti/Hs2Py/GenConstants.hs \
	src/Ganeti/Hs2Py/GenOpCodes.hs \
	src/Ganeti/Hs2Py/OpDoc.hs \
	src/Ganeti/JQScheduler.hs \
	src/Ganeti/JQScheduler/Filtering.hs \
	src/Ganeti/JQScheduler/ReasonRateLimiting.hs \
	src/Ganeti/JQScheduler/Types.hs \
	src/Ganeti/JQueue.hs \
	src/Ganeti/JQueue/Lens.hs \
	src/Ganeti/JQueue/Objects.hs \
	src/Ganeti/JSON.hs \
	src/Ganeti/Jobs.hs \
	src/Ganeti/Kvmd.hs \
	src/Ganeti/Lens.hs \
	src/Ganeti/Locking/Allocation.hs \
	src/Ganeti/Locking/Types.hs \
	src/Ganeti/Locking/Locks.hs \
	src/Ganeti/Locking/Waiting.hs \
	src/Ganeti/Logging.hs \
	src/Ganeti/Logging/Lifted.hs \
	src/Ganeti/Logging/WriterLog.hs \
	src/Ganeti/Luxi.hs \
	src/Ganeti/Network.hs \
	src/Ganeti/Objects.hs \
	src/Ganeti/Objects/BitArray.hs \
	src/Ganeti/Objects/Disk.hs \
	src/Ganeti/Objects/Instance.hs \
	src/Ganeti/Objects/Lens.hs \
	src/Ganeti/Objects/Nic.hs \
	src/Ganeti/OpCodes.hs \
	src/Ganeti/OpCodes/Lens.hs \
	src/Ganeti/OpParams.hs \
	src/Ganeti/Path.hs \
	src/Ganeti/Parsers.hs \
	src/Ganeti/PyValue.hs \
	src/Ganeti/Query/Cluster.hs \
	src/Ganeti/Query/Common.hs \
	src/Ganeti/Query/Exec.hs \
	src/Ganeti/Query/Export.hs \
	src/Ganeti/Query/Filter.hs \
	src/Ganeti/Query/FilterRules.hs \
	src/Ganeti/Query/Group.hs \
	src/Ganeti/Query/Instance.hs \
	src/Ganeti/Query/Job.hs \
	src/Ganeti/Query/Language.hs \
	src/Ganeti/Query/Locks.hs \
	src/Ganeti/Query/Network.hs \
	src/Ganeti/Query/Node.hs \
	src/Ganeti/Query/Query.hs \
	src/Ganeti/Query/Server.hs \
	src/Ganeti/Query/Types.hs \
	src/Ganeti/PartialParams.hs \
	src/Ganeti/Rpc.hs \
	src/Ganeti/Runtime.hs \
	src/Ganeti/SlotMap.hs \
	src/Ganeti/Ssconf.hs \
	src/Ganeti/Storage/Diskstats/Parser.hs \
	src/Ganeti/Storage/Diskstats/Types.hs \
	src/Ganeti/Storage/Drbd/Parser.hs \
	src/Ganeti/Storage/Drbd/Types.hs \
	src/Ganeti/Storage/Lvm/LVParser.hs \
	src/Ganeti/Storage/Lvm/Types.hs \
	src/Ganeti/Storage/Utils.hs \
	src/Ganeti/THH.hs \
	src/Ganeti/THH/Field.hs \
	src/Ganeti/THH/HsRPC.hs \
	src/Ganeti/THH/PyRPC.hs \
	src/Ganeti/THH/PyType.hs \
	src/Ganeti/THH/Types.hs \
	src/Ganeti/THH/RPC.hs \
	src/Ganeti/Types.hs \
	src/Ganeti/UDSServer.hs \
	src/Ganeti/Utils.hs \
	src/Ganeti/Utils/Atomic.hs \
	src/Ganeti/Utils/AsyncWorker.hs \
	src/Ganeti/Utils/IORef.hs \
	src/Ganeti/Utils/Livelock.hs \
	src/Ganeti/Utils/Monad.hs \
	src/Ganeti/Utils/MultiMap.hs \
	src/Ganeti/Utils/MVarLock.hs \
	src/Ganeti/Utils/Random.hs \
	src/Ganeti/Utils/Statistics.hs \
	src/Ganeti/Utils/UniStd.hs \
	src/Ganeti/Utils/Validate.hs \
	src/Ganeti/VCluster.hs \
	src/Ganeti/WConfd/ConfigState.hs \
	src/Ganeti/WConfd/ConfigModifications.hs \
	src/Ganeti/WConfd/ConfigVerify.hs \
	src/Ganeti/WConfd/ConfigWriter.hs \
	src/Ganeti/WConfd/Client.hs \
	src/Ganeti/WConfd/Core.hs \
	src/Ganeti/WConfd/DeathDetection.hs \
	src/Ganeti/WConfd/Language.hs \
	src/Ganeti/WConfd/Monad.hs \
	src/Ganeti/WConfd/Persistent.hs \
	src/Ganeti/WConfd/Server.hs \
	src/Ganeti/WConfd/Ssconf.hs \
	src/Ganeti/WConfd/TempRes.hs

if ENABLE_MOND
HS_LIB_SRCS += src/Ganeti/Monitoring/Server.hs
else
EXTRA_DIST += src/Ganeti/Monitoring/Server.hs
endif

if ENABLE_METADATA
HS_LIB_SRCS += \
	src/Ganeti/Metad/Config.hs \
	src/Ganeti/Metad/ConfigCore.hs \
	src/Ganeti/Metad/ConfigServer.hs \
	src/Ganeti/Metad/Server.hs \
	src/Ganeti/Metad/Types.hs \
	src/Ganeti/Metad/WebServer.hs
else
EXTRA_DIST += \
	src/Ganeti/Metad/Config.hs \
	src/Ganeti/Metad/ConfigCore.hs \
	src/Ganeti/Metad/ConfigServer.hs \
	src/Ganeti/Metad/Server.hs \
	src/Ganeti/Metad/Types.hs \
	src/Ganeti/Metad/WebServer.hs
endif

HS_TEST_SRCS = \
	test/hs/Test/AutoConf.hs \
	test/hs/Test/Ganeti/Attoparsec.hs \
	test/hs/Test/Ganeti/BasicTypes.hs \
	test/hs/Test/Ganeti/Common.hs \
	test/hs/Test/Ganeti/Confd/Types.hs \
	test/hs/Test/Ganeti/Confd/Utils.hs \
	test/hs/Test/Ganeti/Constants.hs \
	test/hs/Test/Ganeti/Daemon.hs \
	test/hs/Test/Ganeti/Errors.hs \
	test/hs/Test/Ganeti/HTools/Backend/MonD.hs \
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
	test/hs/Test/Ganeti/Hypervisor/Xen/XmParser.hs \
	test/hs/Test/Ganeti/JSON.hs \
	test/hs/Test/Ganeti/Jobs.hs \
	test/hs/Test/Ganeti/JQScheduler.hs \
	test/hs/Test/Ganeti/JQueue.hs \
	test/hs/Test/Ganeti/JQueue/Objects.hs \
	test/hs/Test/Ganeti/Kvmd.hs \
	test/hs/Test/Ganeti/Luxi.hs \
	test/hs/Test/Ganeti/Locking/Allocation.hs \
	test/hs/Test/Ganeti/Locking/Locks.hs \
	test/hs/Test/Ganeti/Locking/Waiting.hs \
	test/hs/Test/Ganeti/Network.hs \
	test/hs/Test/Ganeti/PartialParams.hs \
	test/hs/Test/Ganeti/Objects.hs \
	test/hs/Test/Ganeti/Objects/BitArray.hs \
	test/hs/Test/Ganeti/OpCodes.hs \
	test/hs/Test/Ganeti/Query/Aliases.hs \
	test/hs/Test/Ganeti/Query/Filter.hs \
	test/hs/Test/Ganeti/Query/Instance.hs \
	test/hs/Test/Ganeti/Query/Language.hs \
	test/hs/Test/Ganeti/Query/Network.hs \
	test/hs/Test/Ganeti/Query/Query.hs \
	test/hs/Test/Ganeti/Rpc.hs \
	test/hs/Test/Ganeti/Runtime.hs \
	test/hs/Test/Ganeti/SlotMap.hs \
	test/hs/Test/Ganeti/Ssconf.hs \
	test/hs/Test/Ganeti/Storage/Diskstats/Parser.hs \
	test/hs/Test/Ganeti/Storage/Drbd/Parser.hs \
	test/hs/Test/Ganeti/Storage/Drbd/Types.hs \
	test/hs/Test/Ganeti/Storage/Lvm/LVParser.hs \
	test/hs/Test/Ganeti/THH.hs \
	test/hs/Test/Ganeti/THH/Types.hs \
	test/hs/Test/Ganeti/TestCommon.hs \
	test/hs/Test/Ganeti/TestHTools.hs \
	test/hs/Test/Ganeti/TestHelper.hs \
	test/hs/Test/Ganeti/Types.hs \
	test/hs/Test/Ganeti/Utils.hs \
	test/hs/Test/Ganeti/Utils/MultiMap.hs \
	test/hs/Test/Ganeti/Utils/Statistics.hs \
	test/hs/Test/Ganeti/WConfd/Ssconf.hs \
	test/hs/Test/Ganeti/WConfd/TempRes.hs


HS_LIBTEST_SRCS = $(HS_LIB_SRCS) $(HS_TEST_SRCS)

HS_BUILT_SRCS = \
	test/hs/Test/Ganeti/TestImports.hs \
	src/AutoConf.hs \
	src/Ganeti/Hs2Py/ListConstants.hs \
	src/Ganeti/Curl/Internal.hs \
	src/Ganeti/Version.hs
HS_BUILT_SRCS_IN = \
	$(patsubst %,%.in,$(filter-out src/Ganeti/Curl/Internal.hs,$(HS_BUILT_SRCS))) \
	src/Ganeti/Curl/Internal.hsc \
	lib/_constants.py.in \
	lib/opcodes.py.in_after \
	lib/opcodes.py.in_before

HS_LIBTESTBUILT_SRCS = $(HS_LIBTEST_SRCS) $(HS_BUILT_SRCS)

$(RUN_IN_TEMPDIR): | stamp-directories

doc/html/index.html: ENABLE_MANPAGES =
doc/man-html/index.html: ENABLE_MANPAGES = 1
doc/man-html/index.html: doc/manpages-enabled.rst $(mandocrst)

if HAS_SPHINX_PRE13
        SPHINX_HTML_THEME=default
else
        SPHINX_HTML_THEME=classic
endif
# Note: we use here an order-only prerequisite, as the contents of
# _constants.py are not actually influencing the html build output: it
# has to exist in order for the sphinx module to be loaded
# successfully, but we certainly don't want the docs to be rebuilt if
# it changes
doc/html/index.html doc/man-html/index.html: $(docinput) doc/conf.py \
	configure.ac $(RUN_IN_TEMPDIR) lib/build/sphinx_ext.py \
	lib/build/shell_example_lexer.py lib/ht.py \
	doc/css/style.css lib/rapi/connector.py lib/rapi/rlib2.py \
	autotools/sphinx-wrapper | $(built_python_sources)
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
        HTML_THEME=$(SPHINX_HTML_THEME) \
	$(RUN_IN_TEMPDIR) autotools/sphinx-wrapper $(SPHINX) -q -W -b html \
		-d . \
		-D version="$(VERSION_MAJOR).$(VERSION_MINOR)" \
		-D release="$(PACKAGE_VERSION)" \
		-D graphviz_dot="$(DOT)" \
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

doc/users/%: doc/users/%.in Makefile $(REPLACE_VARS_SED)
	cat $< | sed -f $(REPLACE_VARS_SED) | LC_ALL=C sort | uniq | (grep -v '^root' || true) > $@

userspecs = \
	doc/users/users \
	doc/users/groups \
	doc/users/groupmemberships

# Things to build but not to install (add it to EXTRA_DIST if it should be
# distributed)
noinst_DATA = \
	$(BUILT_EXAMPLES) \
	doc/examples/bash_completion \
	doc/examples/bash_completion-debug \
	$(userspecs) \
	$(manhtml)

if HAS_SPHINX
if MANPAGES_IN_DOC
noinst_DATA += doc/man-html
else
noinst_DATA += doc/html
endif
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
	scripts/gnt-storage \
	scripts/gnt-filter

gnt_scripts_basenames = \
	$(patsubst scripts/%,%,$(patsubst daemons/%,%,$(gnt_scripts) $(gnt_python_sbin_SCRIPTS)))

gnt_python_sbin_SCRIPTS = \
	$(PYTHON_BOOTSTRAP_SBIN)

gntpython_SCRIPTS = $(gnt_scripts)

PYTHON_BOOTSTRAP_SBIN = \
	daemons/ganeti-noded \
	daemons/ganeti-rapi \
	daemons/ganeti-watcher

PYTHON_BOOTSTRAP = \
	tools/burnin \
	tools/ensure-dirs \
	tools/node-cleanup \
	tools/node-daemon-setup \
	tools/prepare-node-join \
	tools/ssh-update \
	tools/ssl-update

qa_scripts = \
	qa/__init__.py \
	qa/ganeti-qa.py \
	qa/qa_cluster.py \
	qa/qa_config.py \
	qa/qa_daemon.py \
	qa/qa_env.py \
	qa/qa_error.py \
	qa/qa_filters.py \
	qa/qa_group.py \
	qa/qa_instance.py \
	qa/qa_instance_utils.py \
	qa/qa_iptables.py \
	qa/qa_job.py \
	qa/qa_job_utils.py \
	qa/qa_logging.py \
	qa/qa_monitoring.py \
	qa/qa_network.py \
	qa/qa_node.py \
	qa/qa_os.py \
	qa/qa_performance.py \
	qa/qa_rapi.py \
	qa/qa_tags.py \
	qa/qa_utils.py

bin_SCRIPTS = $(HS_BIN_PROGS)
install-exec-hook:
	@mkdir_p@ $(DESTDIR)$(iallocatorsdir)
# FIXME: this is a hardcoded logic, instead of auto-resolving
	$(LN_S) -f ../../../bin/htools \
	  $(DESTDIR)$(iallocatorsdir)/hail
	for role in $(HS_BIN_ROLES); do \
	  $(LN_S) -f htools $(DESTDIR)$(bindir)/$$role ; \
	done

HS_SRCS = $(HS_LIBTESTBUILT_SRCS)

HS_MAKEFILE_GHC_SRCS = $(HS_SRC_PROGS:%=%.hs)
if WANT_HSTESTS
HS_MAKEFILE_GHC_SRCS += $(HS_TEST_PROGS:%=%.hs)
endif
Makefile.ghc: $(HS_MAKEFILE_GHC_SRCS) Makefile $(HASKELL_PACKAGE_VERSIONS_FILE) \
              | $(built_base_sources) $(HS_BUILT_SRCS)
	$(GHC) -M -dep-makefile $@ $(DEP_SUFFIXES) $(HFLAGS) $(HFLAGS_DYNAMIC) \
		-itest/hs \
		$(HEXTRA_COMBINED) $(HS_MAKEFILE_GHC_SRCS)
# Since ghc -M does not generate dependency line for object files, dependencies
# from a target executable seed object (e.g. src/hluxid.o) to objects which
# finally will be linked to the target object (e.g. src/Ganeti/Daemon.o) are
# missing in Makefile.ghc.
# see: https://www.haskell.org/ghc/docs/7.6.2/html/users_guide/separate-compilation.html#makefile-dependencies
# Following substitutions will add dependencies between object files which
# corresponds to the interface file already there as a dependency for each
# object listed in Makefile.ghc.
# e.g. src/hluxid.o : src/Ganeti/Daemon.hi
#        => src/hluxid.o : src/Ganeti/Daemon.hi src/Ganeti/Daemon.o
	sed -i -r -e 's/([^ ]+)\.hi$$/\1.hi \1.o/' -e 's/([^ ]+)_hi$$/\1_hi \1_o/' $@

@include_makefile_ghc@

# Contains the package-id flags for the current build: "-package-id" followed
# by the name and hash of the package, one for each dependency.
# Obtained from the setup-config using the Cabal API
# (CabalDependenciesMacros.hs) after `cabal configure`.
# This file is created along with HASKELL_PACKAGE_VERSIONS_FILE; if you want
# to depend on it in a rule, depend on HASKELL_PACKAGE_VERSIONS_FILE instead.
HASKELL_PACKAGE_IDS_FILE = ganeti.depsflags

# Defines the MIN_VERSION_* macros for all Haskell packages used in this
# compilation.
# The versions are determined using `cabal configure`, which takes them from
# the ghc-pkg database.
# At the moment, we don't support cabal sandboxes, so we use cabal configure
# with the --user flag.
# Note: `cabal configure` and CabalDependenciesMacros.hs perform no
# downloading (only `cabal install` can do that).
HASKELL_PACKAGE_VERSIONS_FILE = cabal_macros.h

$(HASKELL_PACKAGE_VERSIONS_FILE): Makefile ganeti.cabal \
                                  cabal/CabalDependenciesMacros.hs
	touch empty-cabal-config
	$(CABAL) --config-file=empty-cabal-config configure --user \
	  -f`test $(HTEST) == yes && echo "htest" || echo "-htest"` \
	  -f`test $(ENABLE_MOND) == True && echo "mond" || echo "-mond"` \
	  -f`test $(ENABLE_METADATA) == True && echo "metad" || echo "-metad"`
	runhaskell $(abs_top_srcdir)/cabal/CabalDependenciesMacros.hs \
	  ganeti.cabal \
	  $(HASKELL_PACKAGE_IDS_FILE) \
	  $(HASKELL_PACKAGE_VERSIONS_FILE)

# Like the %.o rule, but allows access to the test/hs directory.
# This uses HFLAGS instead of HTEST_FLAGS because it's only for generating
# object files (.o for GHC <= 7.6, .o/.so for newer GHCs) that are loaded
# in GHCI when evaluating TH. The actual test-with-coverage .hpc_o files
# are created in the `%.$(HTEST_SUFFIX)_o` rule.
test/hs/%.o: $(HASKELL_PACKAGE_VERSIONS_FILE)
	@echo '[GHC|test]: $@ <- test/hs/$^'
	@set -o pipefail ; \
	$(GHC) -c $(HFLAGS) -itest/hs $(HFLAGS_DYNAMIC) \
		$(HEXTRA_COMBINED) $(HEXTRA_TEST) $(@:%.o=%.hs) | \
		sed '/^Loading package /d'

%.o: $(HASKELL_PACKAGE_VERSIONS_FILE)
	@echo '[GHC]: $@ <- $^'
	@set -o pipefail ; \
	$(GHC) -c $(HFLAGS) $(HFLAGS_DYNAMIC) \
		$(HEXTRA_COMBINED) $(@:%.o=%.hs) | \
		sed '/^Loading package /d'

# For TH+profiling we need to compile twice: Once without profiling,
# and then once with profiling. See
# http://www.haskell.org/ghc/docs/7.0.4/html/users_guide/template-haskell.html#id636646
if HPROFILE
%.$(HPROF_SUFFIX)_o: %.o
	@echo '[GHC|prof]: $@ <- $^'
	@set -o pipefail ; \
	$(GHC) -c $(HFLAGS) \
	  $(HPROFFLAGS) \
		$(HEXTRA_COMBINED) \
		$(@:%.$(HPROF_SUFFIX)_o=%.hs) | \
		sed '/^Loading package /d'
endif

# We depend on the non-test .o file here because we need the corresponding .so
# file for GHC > 7.6 ghci dynamic loading for TH, and creating the .o file
# will create the .so file since we use -dynamic-too (using the `test/hs/%.o`
# rule).
%.$(HTEST_SUFFIX)_o: %.o
	@echo '[GHC|test]: $@ <- $^'
	@set -o pipefail ; \
	$(GHC) -c $(HTEST_FLAGS) \
		$(HEXTRA_COMBINED) $(HEXTRA_TEST) $(@:%.$(HTEST_SUFFIX)_o=%.hs) | \
		sed '/^Loading package /d'

%.hi: %.o ;
%.$(HTEST_SUFFIX)_hi: %.$(HTEST_SUFFIX)_o ;
%.$(HPROF_SUFFIX)_hi: %.$(HPROF_SUFFIX)_o ;

if HPROFILE
$(HS_SRC_PROGS): %: %.$(HPROF_SUFFIX)_o | stamp-directories
	@echo '[GHC-link]: $@'
	$(GHC) $(HFLAGS) $(HPROFFLAGS) \
		$(HEXTRA_COMBINED) --make $(@:%=%.hs)
else
$(HS_SRC_PROGS): %: %.o | stamp-directories
	@echo '[GHC-link]: $@'
	$(GHC) $(HFLAGS) $(HFLAGS_DYNAMIC) \
		$(HEXTRA_COMBINED) --make $(@:%=%.hs)
endif
	@rm -f $(notdir $@).tix
	@touch "$@"

$(HS_TEST_PROGS): %: %.$(HTEST_SUFFIX)_o \
	                   | stamp-directories $(built_python_sources)
	@if [ "$(HS_NODEV)" ]; then \
	  echo "Error: cannot run unittests without the development" \
	       " libraries (see devnotes.rst)" 1>&2; \
	  exit 1; \
	fi
	@echo '[GHC-link|test]: $@'
	$(GHC) $(HTEST_FLAGS) \
		$(HEXTRA_COMBINED) $(HEXTRA_TEST) --make $(@:%=%.hs)
	@rm -f $(notdir $@).tix
	@touch "$@"

dist_sbin_SCRIPTS = \
	tools/ganeti-listrunner

nodist_sbin_SCRIPTS = \
	daemons/ganeti-cleaner \
	src/ganeti-kvmd \
	src/ganeti-luxid \
	src/ganeti-confd \
	src/ganeti-wconfd

src/ganeti-luxid: src/hluxid
	cp -f $< $@

# strip path prefixes off the sbin scripts
all_sbin_scripts = \
	$(patsubst tools/%,%,$(patsubst daemons/%,%,$(patsubst scripts/%,%,\
	$(patsubst src/%,%,$(dist_sbin_SCRIPTS) $(nodist_sbin_SCRIPTS)))))

src/ganeti-confd: src/hconfd
	cp -f $< $@

if ENABLE_MOND
nodist_sbin_SCRIPTS += src/ganeti-mond
endif

if ENABLE_METADATA
nodist_sbin_SCRIPTS += src/ganeti-metad
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
	tools/post-upgrade \
	tools/sanitize-config \
	tools/query-config

python_scripts_shebang = \
	$(patsubst tools/%,tools/shebang/%, $(python_scripts))

tools/shebang/%: tools/%
	mkdir -p tools/shebang
	head -1 $< | sed 's|#!/usr/bin/python|#!$(PYTHON)|' > $@
	echo '# Generated file; do not edit.' >> $@
	tail -n +2 $< >> $@

dist_tools_SCRIPTS = \
	tools/kvm-console-wrapper \
	tools/master-ip-setup \
	tools/xen-console-wrapper

dist_tools_python_SCRIPTS = \
	tools/burnin

nodist_tools_python_SCRIPTS = \
	tools/node-cleanup \
	$(python_scripts_shebang)

tools_python_basenames = \
	$(patsubst shebang/%,%,\
	$(patsubst tools/%,%,\
	$(dist_tools_python_SCRIPTS) $(nodist_tools_python_SCRIPTS)))

nodist_tools_SCRIPTS = \
	tools/users-setup \
	tools/vcluster-setup

tools_basenames = $(patsubst tools/%,%,$(nodist_tools_SCRIPTS) $(dist_tools_SCRIPTS))

pkglib_python_scripts = \
	daemons/import-export \
	tools/check-cert-expired

nodist_pkglib_python_scripts = \
	tools/ensure-dirs \
	tools/node-daemon-setup \
	tools/prepare-node-join \
	tools/ssh-update \
	tools/ssl-update

pkglib_python_basenames = \
	$(patsubst daemons/%,%,$(patsubst tools/%,%,\
	$(pkglib_python_scripts) $(nodist_pkglib_python_scripts)))

myexeclib_SCRIPTS = \
	daemons/daemon-util \
	tools/kvm-ifup \
	tools/kvm-ifup-os \
	tools/xen-ifup-os \
	tools/vif-ganeti \
	tools/vif-ganeti-metad \
	tools/net-common \
	$(HS_MYEXECLIB_PROGS)

# compute the basenames of the myexeclib_scripts
myexeclib_scripts_basenames = \
	$(patsubst tools/%,%,$(patsubst daemons/%,%,$(patsubst src/%,%,$(myexeclib_SCRIPTS))))

EXTRA_DIST += \
	NEWS \
	UPGRADE \
	epydoc.conf.in \
	pylintrc \
	pylintrc-test \
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
	autotools/docpp \
	autotools/gen-py-coverage \
	autotools/print-py-constants \
	autotools/sphinx-wrapper \
	autotools/testrunner \
	autotools/wrong-hardcoded-paths \
	cabal/cabal-from-modules.py \
	$(RUN_IN_TEMPDIR) \
	daemons/daemon-util.in \
	daemons/ganeti-cleaner.in \
	$(pkglib_python_scripts) \
	devel/build_chroot \
	devel/upload \
	devel/webserver \
	tools/kvm-ifup.in \
	tools/ifup-os.in \
	tools/vif-ganeti.in \
	tools/vif-ganeti-metad.in \
	tools/net-common.in \
	tools/vcluster-setup.in \
	$(python_scripts) \
	$(docinput) \
	doc/html \
	$(BUILT_EXAMPLES:%=%.in) \
	doc/examples/ganeti.default \
	doc/examples/ganeti.default-debug \
	doc/examples/hooks/ethers \
	doc/examples/gnt-debug/README \
	doc/examples/gnt-debug/delay0.json \
	doc/examples/gnt-debug/delay50.json \
	doc/examples/systemd/ganeti-master.target \
	doc/examples/systemd/ganeti-node.target \
	doc/examples/systemd/ganeti.service \
	doc/examples/systemd/ganeti.target \
	doc/users/groupmemberships.in \
	doc/users/groups.in \
	doc/users/users.in \
	ganeti.cabal \
	cabal/ganeti.template.cabal \
	cabal/CabalDependenciesMacros.hs \
	$(dist_TESTS) \
	$(TEST_FILES) \
	$(python_test_support) \
	$(python_test_utils) \
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
	man/ganeti-luxid.8 \
	man/ganeti-listrunner.8 \
	man/ganeti-kvmd.8 \
	man/ganeti-mond.8 \
	man/ganeti-noded.8 \
	man/ganeti-os-interface.7 \
	man/ganeti-extstorage-interface.7 \
	man/ganeti-rapi.8 \
	man/ganeti-watcher.8 \
	man/ganeti-wconfd.8 \
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
	man/gnt-filter.8 \
	man/hail.1 \
	man/harep.1 \
	man/hbal.1 \
	man/hcheck.1 \
	man/hinfo.1 \
	man/hscan.1 \
	man/hspace.1 \
	man/hsqueeze.1 \
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

manfullpath = $(patsubst man/%.1,man1/%.1,\
	$(patsubst man/%.7,man7/%.7,\
	$(patsubst man/%.8,man8/%.8,$(man_MANS))))

TEST_FILES = \
	test/autotools/autotools-check-news.test \
	test/data/htools/clean-nonzero-score.data \
	test/data/htools/common-suffix.data \
	test/data/htools/empty-cluster.data \
	test/data/htools/hail-alloc-dedicated-1.json \
	test/data/htools/hail-alloc-desired-location.json \
	test/data/htools/hail-alloc-drbd.json \
	test/data/htools/hail-alloc-drbd-restricted.json \
	test/data/htools/hail-alloc-ext.json \
	test/data/htools/hail-alloc-invalid-network.json \
	test/data/htools/hail-alloc-invalid-twodisks.json \
	test/data/htools/hail-alloc-restricted-network.json \
	test/data/htools/hail-alloc-nlocation.json \
	test/data/htools/hail-alloc-plain-tags.json \
	test/data/htools/hail-alloc-secondary.json \
	test/data/htools/hail-alloc-spindles.json \
	test/data/htools/hail-alloc-twodisks.json \
	test/data/htools/hail-change-group.json \
	test/data/htools/hail-invalid-reloc.json \
	test/data/htools/hail-node-evac.json \
	test/data/htools/hail-reloc-drbd.json \
	test/data/htools/hail-reloc-drbd-crowded.json \
	test/data/htools/hbal-cpu-speed.data \
	test/data/htools/hbal-desiredlocation-1.data \
	test/data/htools/hbal-desiredlocation-2.data \
	test/data/htools/hbal-desiredlocation-3.data \
	test/data/htools/hbal-desiredlocation-4.data \
	test/data/htools/hbal-dyn.data \
	test/data/htools/hbal-evac.data \
	test/data/htools/hbal-excl-tags.data \
	test/data/htools/hbal-forth.data \
	test/data/htools/hbal-location-1.data \
	test/data/htools/hbal-location-exclusion.data \
	test/data/htools/hbal-location-2.data \
	test/data/htools/hbal-migration-1.data \
	test/data/htools/hbal-migration-2.data \
	test/data/htools/hbal-migration-3.data \
	test/data/htools/hail-multialloc-dedicated.json \
	test/data/htools/hbal-soft-errors.data \
	test/data/htools/hbal-soft-errors2.data \
	test/data/htools/hbal-split-insts.data \
	test/data/htools/hspace-bad-group.data \
	test/data/htools/hspace-existing.data \
	test/data/htools/hspace-groups-one.data \
	test/data/htools/hspace-groups-two.data \
	test/data/htools/hspace-tiered-dualspec-exclusive.data \
	test/data/htools/hspace-tiered-dualspec.data \
	test/data/htools/hspace-tiered-exclusive.data \
	test/data/htools/hspace-tiered-ipolicy.data \
	test/data/htools/hspace-tiered-mixed.data \
	test/data/htools/hspace-tiered-resourcetypes.data \
	test/data/htools/hspace-tiered-vcpu.data \
	test/data/htools/hspace-tiered.data \
	test/data/htools/invalid-node.data \
	test/data/htools/missing-resources.data \
	test/data/htools/multiple-master.data \
	test/data/htools/multiple-tags.data \
	test/data/htools/n1-failure.data \
	test/data/htools/partly-used.data \
	test/data/htools/rapi/groups.json \
	test/data/htools/rapi/info.json \
	test/data/htools/rapi/instances.json \
	test/data/htools/rapi/nodes.json \
	test/data/htools/hroller-full.data \
	test/data/htools/hroller-nodegroups.data \
	test/data/htools/hroller-nonredundant.data \
	test/data/htools/hroller-online.data \
	test/data/htools/hsqueeze-mixed-instances.data \
	test/data/htools/hsqueeze-overutilized.data \
	test/data/htools/hsqueeze-underutilized.data \
	test/data/htools/plain-n1-restriction.data \
	test/data/htools/shared-n1-failure.data \
	test/data/htools/shared-n1-restriction.data \
	test/data/htools/unique-reboot-order.data \
	test/data/mond-data.txt \
	test/hs/shelltests/htools-balancing.test \
	test/hs/shelltests/htools-basic.test \
	test/hs/shelltests/htools-dynutil.test \
	test/hs/shelltests/htools-excl.test \
	test/hs/shelltests/htools-hail.test \
	test/hs/shelltests/htools-hbal-evac.test \
	test/hs/shelltests/htools-hbal.test \
	test/hs/shelltests/htools-hcheck.test \
	test/hs/shelltests/htools-hroller.test \
	test/hs/shelltests/htools-hspace.test \
	test/hs/shelltests/htools-hsqueeze.test \
	test/hs/shelltests/htools-invalid.test \
	test/hs/shelltests/htools-multi-group.test \
	test/hs/shelltests/htools-no-backend.test \
	test/hs/shelltests/htools-rapi.test \
	test/hs/shelltests/htools-single-group.test \
	test/hs/shelltests/htools-text-backend.test \
	test/hs/shelltests/htools-mon-collector.test \
	test/data/bdev-drbd-8.0.txt \
	test/data/bdev-drbd-8.3.txt \
	test/data/bdev-drbd-8.4.txt \
	test/data/bdev-drbd-8.4-no-disk-params.txt \
	test/data/bdev-drbd-disk.txt \
	test/data/bdev-drbd-net-ip4.txt \
	test/data/bdev-drbd-net-ip6.txt \
	test/data/bdev-rbd/json_output_empty.txt \
	test/data/bdev-rbd/json_output_extra_matches.txt \
	test/data/bdev-rbd/json_output_no_matches.txt \
	test/data/bdev-rbd/json_output_ok.txt \
	test/data/bdev-rbd/plain_output_new_extra_matches.txt \
	test/data/bdev-rbd/plain_output_new_no_matches.txt \
	test/data/bdev-rbd/plain_output_new_ok.txt \
	test/data/bdev-rbd/plain_output_old_empty.txt \
	test/data/bdev-rbd/plain_output_old_extra_matches.txt \
	test/data/bdev-rbd/plain_output_old_no_matches.txt \
	test/data/bdev-rbd/plain_output_old_ok.txt \
	test/data/bdev-rbd/output_invalid.txt \
	test/data/cert1.pem \
	test/data/cert2.pem \
	test/data/cgroup_root/memory/lxc/instance1/memory.limit_in_bytes \
	test/data/cgroup_root/cpuset/some_group/lxc/instance1/cpuset.cpus \
	test/data/cgroup_root/devices/some_group/lxc/instance1/devices.list \
	test/data/cluster_config_2.7.json \
	test/data/cluster_config_2.8.json \
	test/data/cluster_config_2.9.json \
	test/data/cluster_config_2.10.json \
	test/data/cluster_config_2.11.json \
	test/data/cluster_config_2.12.json \
	test/data/cluster_config_2.13.json \
	test/data/cluster_config_2.14.json \
	test/data/cluster_config_2.15.json \
	test/data/instance-minor-pairing.txt \
	test/data/instance-disks.txt \
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
	test/data/kvm_runtime.json \
	test/data/lvs_lv.txt \
	test/data/NEWS_OK.txt \
	test/data/NEWS_previous_unreleased.txt \
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
	test/data/proc_cgroup.txt \
	test/data/proc_diskstats.txt \
	test/data/proc_drbd8.txt \
	test/data/proc_drbd80-emptyline.txt \
	test/data/proc_drbd80-emptyversion.txt \
	test/data/proc_drbd83.txt \
	test/data/proc_drbd83_sync.txt \
	test/data/proc_drbd83_sync_want.txt \
	test/data/proc_drbd83_sync_krnl2.6.39.txt \
	test/data/proc_drbd84.txt \
	test/data/proc_drbd84_emptyfirst.txt \
	test/data/proc_drbd84_sync.txt \
	test/data/proc_meminfo.txt \
	test/data/proc_cpuinfo.txt \
	test/data/qa-minimal-nodes-instances-only.json \
	test/data/sys_drbd_usermode_helper.txt \
	test/data/vgreduce-removemissing-2.02.02.txt \
	test/data/vgreduce-removemissing-2.02.66-fail.txt \
	test/data/vgreduce-removemissing-2.02.66-ok.txt \
	test/data/vgs-missing-pvs-2.02.02.txt \
	test/data/vgs-missing-pvs-2.02.66.txt \
	test/data/xen-xl-list-4.4-crashed-instances.txt \
	test/data/xen-xm-info-4.0.1.txt \
	test/data/xen-xm-list-4.0.1-dom0-only.txt \
	test/data/xen-xm-list-4.0.1-four-instances.txt \
	test/data/xen-xm-list-long-4.0.1.txt \
	test/data/xen-xm-uptime-4.0.1.txt \
	test/py/ganeti-cli.test \
	test/py/gnt-cli.test \
	test/py/import-export_unittest-helper


python_tests = \
	doc/examples/rapi_testutils.py \
	test/py/cmdlib/backup_unittest.py \
	test/py/cmdlib/cluster_unittest.py \
	test/py/cmdlib/cmdlib_unittest.py \
	test/py/cmdlib/group_unittest.py \
	test/py/cmdlib/instance_unittest.py \
	test/py/cmdlib/instance_migration_unittest.py \
	test/py/cmdlib/instance_query_unittest.py \
	test/py/cmdlib/instance_storage_unittest.py \
	test/py/cmdlib/node_unittest.py \
	test/py/cmdlib/test_unittest.py \
	test/py/cfgupgrade_unittest.py \
	test/py/docs_unittest.py \
	test/py/ganeti.asyncnotifier_unittest.py \
	test/py/ganeti.backend_unittest-runasroot.py \
	test/py/ganeti.backend_unittest.py \
	test/py/ganeti.bootstrap_unittest.py \
	test/py/ganeti.cli_unittest.py \
	test/py/ganeti.cli_opts_unittest.py \
	test/py/ganeti.client.gnt_cluster_unittest.py \
	test/py/ganeti.client.gnt_instance_unittest.py \
	test/py/ganeti.client.gnt_job_unittest.py \
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
	test/py/ganeti.opcodes_unittest.py \
	test/py/ganeti.outils_unittest.py \
	test/py/ganeti.ovf_unittest.py \
	test/py/ganeti.qlang_unittest.py \
	test/py/ganeti.query_unittest.py \
	test/py/ganeti.rapi.baserlib_unittest.py \
	test/py/ganeti.rapi.client_unittest.py \
	test/py/ganeti.rapi.resources_unittest.py \
	test/py/ganeti.rapi.rlib2_unittest.py \
	test/py/ganeti.rapi.testutils_unittest.py \
	test/py/ganeti.rpc_unittest.py \
	test/py/ganeti.rpc.client_unittest.py \
	test/py/ganeti.runtime_unittest.py \
	test/py/ganeti.serializer_unittest.py \
	test/py/ganeti.server.rapi_unittest.py \
	test/py/ganeti.ssconf_unittest.py \
	test/py/ganeti.ssh_unittest.py \
	test/py/ganeti.storage.bdev_unittest.py \
	test/py/ganeti.storage.container_unittest.py \
	test/py/ganeti.storage.drbd_unittest.py \
	test/py/ganeti.storage.filestorage_unittest.py \
	test/py/ganeti.storage.gluster_unittest.py \
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
	test/py/ganeti.utils.security_unittest.py \
	test/py/ganeti.utils.storage_unittest.py \
	test/py/ganeti.utils.text_unittest.py \
	test/py/ganeti.utils.version_unittest.py \
	test/py/ganeti.utils.wrapper_unittest.py \
	test/py/ganeti.utils.x509_unittest.py \
	test/py/ganeti.utils.bitarrays_unittest.py \
	test/py/ganeti.utils_unittest.py \
	test/py/ganeti.vcluster_unittest.py \
	test/py/ganeti.workerpool_unittest.py \
	test/py/pycurl_reset_unittest.py \
	test/py/qa.qa_config_unittest.py \
	test/py/tempfile_fork_unittest.py

python_test_support = \
	test/py/__init__.py \
	test/py/lockperf.py \
	test/py/testutils_ssh.py \
	test/py/mocks.py \
	test/py/testutils/__init__.py \
	test/py/testutils/config_mock.py \
	test/py/cmdlib/__init__.py \
	test/py/cmdlib/testsupport/__init__.py \
	test/py/cmdlib/testsupport/cmdlib_testcase.py \
	test/py/cmdlib/testsupport/iallocator_mock.py \
	test/py/cmdlib/testsupport/livelock_mock.py \
	test/py/cmdlib/testsupport/netutils_mock.py \
	test/py/cmdlib/testsupport/pathutils_mock.py \
	test/py/cmdlib/testsupport/processor_mock.py \
	test/py/cmdlib/testsupport/rpc_runner_mock.py \
	test/py/cmdlib/testsupport/ssh_mock.py \
	test/py/cmdlib/testsupport/utils_mock.py \
	test/py/cmdlib/testsupport/util.py \
	test/py/cmdlib/testsupport/wconfd_mock.py

haskell_tests = test/hs/htest

dist_TESTS = \
	test/py/check-cert-expired_unittest.bash \
	test/py/daemon-util_unittest.bash \
	test/py/systemd_unittest.bash \
	test/py/ganeti-cleaner_unittest.bash \
	test/py/import-export_unittest.bash \
	test/py/cli-test.bash \
	test/py/bash_completion.bash

if PY_UNIT
dist_TESTS += $(python_tests)
endif

nodist_TESTS =
check_SCRIPTS =

if WANT_HSTESTS
nodist_TESTS += $(haskell_tests)
# test dependency
test/hs/offline-test.sh: test/hs/hpc-htools test/hs/hpc-mon-collector
dist_TESTS += test/hs/offline-test.sh
check_SCRIPTS += \
	test/hs/hpc-htools \
	test/hs/hpc-mon-collector \
	$(HS_BUILT_TEST_HELPERS)
endif

TESTS = $(dist_TESTS) $(nodist_TESTS)

# Environment for all tests
PLAIN_TESTS_ENVIRONMENT = \
	PYTHONPATH=.:./test/py \
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
	$(pkgpython_PYTHON) \
	$(client_PYTHON) \
	$(cmdlib_PYTHON) \
	$(cmdlib_cluster_PYTHON) \
	$(config_PYTHON) \
	$(hypervisor_PYTHON) \
	$(hypervisor_hv_kvm_PYTHON) \
	$(jqueue_PYTHON) \
	$(storage_PYTHON) \
	$(rapi_PYTHON) \
	$(server_PYTHON) \
	$(rpc_PYTHON) \
	$(rpc_stub_PYTHON) \
	$(pytools_PYTHON) \
	$(http_PYTHON) \
	$(confd_PYTHON) \
	$(masterd_PYTHON) \
	$(impexpd_PYTHON) \
	$(utils_PYTHON) \
	$(watcher_PYTHON) \
	$(noinst_PYTHON) \
	$(qa_scripts)

if PY_UNIT
all_python_code += $(python_tests)
all_python_code += $(python_test_support)
all_python_code += $(python_test_utils)
endif

srclink_files = \
	man/footer.rst \
	test/py/check-cert-expired_unittest.bash \
	test/py/daemon-util_unittest.bash \
	test/py/systemd_unittest.bash \
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
	$(gnt_python_sbin_SCRIPTS) \
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
	$(gnt_python_sbin_SCRIPTS) \
	qa \
	$(python_test_support)
	$(python_test_utils)

test/py/daemon-util_unittest.bash: daemons/daemon-util

test/py/systemd_unittest.bash: daemons/daemon-util $(BUILT_EXAMPLES)

test/py/ganeti-cleaner_unittest.bash: daemons/ganeti-cleaner

test/py/bash_completion.bash: doc/examples/bash_completion-debug

tools/kvm-ifup: tools/kvm-ifup.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

tools/kvm-ifup-os: tools/ifup-os.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) -e "s/ifup-os:/kvm-ifup-os:/" < $< > $@
	chmod +x $@

tools/xen-ifup-os: tools/ifup-os.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) -e "s/ifup-os:/xen-ifup-os:/" < $< > $@
	chmod +x $@

tools/vif-ganeti: tools/vif-ganeti.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

tools/vif-ganeti-metad: tools/vif-ganeti-metad.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

tools/net-common: tools/net-common.in $(REPLACE_VARS_SED)
	sed -f $(REPLACE_VARS_SED) < $< > $@
	chmod +x $@

tools/users-setup: Makefile $(userspecs)
	set -e; \
	{ echo '#!/bin/sh'; \
	  echo 'if [ "x$$1" != "x--yes-do-it" ];'; \
	  echo 'then echo "This will do the following changes"'; \
	  $(AWK) -- '{print "echo + Will add group ",$$1; count++}\
	             END {if (count == 0) {print "echo + No groups to add"}}' doc/users/groups; \
	  $(AWK) -- '{if (NF > 1) {print "echo + Will add user",$$1,"with primary group",$$2} \
	                          else {print "echo + Will add user",$$1}; count++}\
	             END {if (count == 0) {print "echo + No users to add"}}' doc/users/users; \
	  $(AWK) -- '{print "echo + Will add user",$$1,"to group",$$2}' doc/users/groupmemberships; \
	  echo 'echo'; \
	  echo 'echo "OK? (y/n)"'; \
	  echo 'read confirm'; \
	  echo 'if [ "x$$confirm" != "xy" ]; then exit 0; fi'; \
	  echo 'fi'; \
	  $(AWK) -- '{print "groupadd --system",$$1}' doc/users/groups; \
	  $(AWK) -- '{if (NF > 1) {print "useradd --system --gid",$$2,$$1} else {print "useradd --system",$$1}}' doc/users/users; \
	  $(AWK) -- '{print "usermod --append --groups",$$2,$$1}' doc/users/groupmemberships; \
	} > $@
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
	| $(RUN_IN_TEMPDIR) $(built_python_sources)
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
	set -o pipefail -e; \
	trap 'echo auto-removing $@; rm $@' EXIT; \
	$(PANDOC) -s -f rst -t man $< man/footer.rst | \
	  sed -e 's/\\@/@/g' > $@; \
	if test -n "$(MAN_HAS_WARNINGS)"; then LC_ALL=en_US.UTF-8 $(CHECK_MAN_WARNINGS) $@; fi; \
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
	  git describe | tr '"' - > $@; \
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
	sed -e 's"%ver%"'"$$VCSVER"'"' < $< > $@

src/Ganeti/Hs2Py/ListConstants.hs: src/Ganeti/Hs2Py/ListConstants.hs.in \
				   src/Ganeti/Constants.hs \
			         | stamp-directories
	@echo Generating $@
	@set -e; \
## Extract constant names from 'Constants.hs' by extracting the left
## side of all lines containing an equal sign (i.e., '=') and
## prepending the apostrophe sign (i.e., "'").
##
## For example, the constant
##   adminstDown = ...
## becomes
##   'adminstDown
	NAMES=$$(sed -e "/^--/ d" $(abs_top_srcdir)/src/Ganeti/Constants.hs |\
		 sed -n -e "/=/ s/\(.*\) =.*/    '\1:/g p"); \
	m4 -DPY_CONSTANT_NAMES="$$NAMES" \
		$(abs_top_srcdir)/src/Ganeti/Hs2Py/ListConstants.hs.in > $@

src/Ganeti/Curl/Internal.hs: src/Ganeti/Curl/Internal.hsc | stamp-directories
	hsc2hs -o $@ $<

test/hs/Test/Ganeti/TestImports.hs: test/hs/Test/Ganeti/TestImports.hs.in \
	$(built_base_sources)
	set -e; \
	{ cat $< ; \
	  echo ; \
	  for name in $(filter-out Ganeti.THH,$(subst /,.,$(patsubst %.hs,%,$(patsubst src/%,%,$(HS_LIB_SRCS))))) ; do \
	    echo "import $$name ()" ; \
	  done ; \
	} > $@

lib/_constants.py: Makefile src/hs2py lib/_constants.py.in | stamp-directories
	cat $(abs_top_srcdir)/lib/_constants.py.in > $@
	src/hs2py --constants >> $@

lib/constants.py: lib/_constants.py

src/AutoConf.hs: Makefile src/AutoConf.hs.in $(PRINT_PY_CONSTANTS) \
	       | $(built_base_sources)
	@echo "m4 ... >" $@
	@m4 -DPACKAGE_VERSION="$(PACKAGE_VERSION)" \
	    -DVERSION_MAJOR="$(VERSION_MAJOR)" \
	    -DVERSION_MINOR="$(VERSION_MINOR)" \
	    -DVERSION_REVISION="$(VERSION_REVISION)" \
	    -DVERSION_SUFFIX="$(VERSION_SUFFIX)" \
	    -DVERSION_FULL="$(VERSION_FULL)" \
	    -DDIRVERSION="$(DIRVERSION)" \
	    -DLOCALSTATEDIR="$(localstatedir)" \
	    -DSYSCONFDIR="$(sysconfdir)" \
	    -DSSH_CONFIG_DIR="$(SSH_CONFIG_DIR)" \
	    -DSSH_LOGIN_USER="$(SSH_LOGIN_USER)" \
	    -DSSH_CONSOLE_USER="$(SSH_CONSOLE_USER)" \
	    -DEXPORT_DIR="$(EXPORT_DIR)" \
	    -DBACKUP_DIR="$(backup_dir)" \
	    -DOS_SEARCH_PATH="\"$(OS_SEARCH_PATH)\"" \
	    -DES_SEARCH_PATH="\"$(ES_SEARCH_PATH)\"" \
	    -DXEN_BOOTLOADER="$(XEN_BOOTLOADER)" \
	    -DXEN_CONFIG_DIR="$(XEN_CONFIG_DIR)" \
	    -DXEN_KERNEL="$(XEN_KERNEL)" \
	    -DXEN_INITRD="$(XEN_INITRD)" \
	    -DKVM_KERNEL="$(KVM_KERNEL)" \
	    -DSHARED_FILE_STORAGE_DIR="$(SHARED_FILE_STORAGE_DIR)" \
	    -DIALLOCATOR_SEARCH_PATH="\"$(IALLOCATOR_SEARCH_PATH)\"" \
	    -DDEFAULT_BRIDGE="$(DEFAULT_BRIDGE)" \
	    -DDEFAULT_VG="$(DEFAULT_VG)" \
	    -DKVM_PATH="$(KVM_PATH)" \
	    -DIP_PATH="$(IP_PATH)" \
	    -DSOCAT_PATH="$(SOCAT)" \
	    -DPYTHON_PATH="$(PYTHON)" \
	    -DSOCAT_USE_ESCAPE="$(SOCAT_USE_ESCAPE)" \
	    -DSOCAT_USE_COMPRESS="$(SOCAT_USE_COMPRESS)" \
	    -DLVM_STRIPECOUNT="$(LVM_STRIPECOUNT)" \
	    -DTOOLSDIR="$(libdir)/ganeti/tools" \
	    -DGNT_SCRIPTS="$(foreach i,$(notdir $(gnt_scripts)),\"$(i)\":)" \
	    -DHS_HTOOLS_PROGS="$(foreach i,$(HS_HTOOLS_PROGS),\"$(i)\":)" \
	    -DPKGLIBDIR="$(libdir)/ganeti" \
	    -DSHAREDIR="$(prefix)/share/ganeti" \
	    -DVERSIONEDSHAREDIR="$(versionedsharedir)" \
	    -DDRBD_BARRIERS="$(DRBD_BARRIERS)" \
	    -DDRBD_NO_META_FLUSH="$(DRBD_NO_META_FLUSH)" \
	    -DSYSLOG_USAGE="$(SYSLOG_USAGE)" \
	    -DDAEMONS_GROUP="$(DAEMONS_GROUP)" \
	    -DADMIN_GROUP="$(ADMIN_GROUP)" \
	    -DMASTERD_USER="$(MASTERD_USER)" \
	    -DMASTERD_GROUP="$(MASTERD_GROUP)" \
	    -DMETAD_USER="$(METAD_USER)" \
	    -DMETAD_GROUP="$(METAD_GROUP)" \
	    -DRAPI_USER="$(RAPI_USER)" \
	    -DRAPI_GROUP="$(RAPI_GROUP)" \
	    -DCONFD_USER="$(CONFD_USER)" \
	    -DCONFD_GROUP="$(CONFD_GROUP)" \
	    -DWCONFD_USER="$(WCONFD_USER)" \
	    -DWCONFD_GROUP="$(WCONFD_GROUP)" \
	    -DKVMD_USER="$(KVMD_USER)" \
	    -DKVMD_GROUP="$(KVMD_GROUP)" \
	    -DLUXID_USER="$(LUXID_USER)" \
	    -DLUXID_GROUP="$(LUXID_GROUP)" \
	    -DNODED_USER="$(NODED_USER)" \
	    -DNODED_GROUP="$(NODED_GROUP)" \
	    -DMOND_USER="$(MOND_USER)" \
	    -DMOND_GROUP="$(MOND_GROUP)" \
	    -DMETAD_USER="$(METAD_USER)" \
	    -DMETAD_GROUP="$(METAD_GROUP)" \
	    -DDISK_SEPARATOR="$(DISK_SEPARATOR)" \
	    -DQEMUIMG_PATH="$(QEMUIMG_PATH)" \
	    -DXEN_CMD="$(XEN_CMD)" \
	    -DENABLE_RESTRICTED_COMMANDS="$(ENABLE_RESTRICTED_COMMANDS)" \
	    -DENABLE_METADATA="$(ENABLE_METADATA)" \
	    -DENABLE_MOND="$(ENABLE_MOND)" \
	    -DHAS_GNU_LN="$(HAS_GNU_LN)" \
	    -DMAN_PAGES="$$(for i in $(notdir $(man_MANS)); do \
	                    echo -n "$$i" | sed -re 's/^(.*)\.([0-9]+)$$/("\1",\2):/g'; \
	                    done)" \
	    -DAF_INET4="$$(PYTHONPATH=. $(PYTHON) $(PRINT_PY_CONSTANTS) AF_INET4)" \
	    -DAF_INET6="$$(PYTHONPATH=. $(PYTHON) $(PRINT_PY_CONSTANTS) AF_INET6)" \
	$(abs_top_srcdir)/src/AutoConf.hs.in > $@

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

lib/opcodes.py: Makefile src/hs2py lib/opcodes.py.in_before \
		lib/opcodes.py.in_after | stamp-directories
	cat $(abs_top_srcdir)/lib/opcodes.py.in_before > $@
	src/hs2py --opcodes >> $@
	cat $(abs_top_srcdir)/lib/opcodes.py.in_after >> $@

# Generating the RPC wrappers depends on many things, so make sure
# it's built at the end of the built sources
lib/_generated_rpc.py: lib/rpc_defs.py $(BUILD_RPC) | $(built_base_sources) $(built_python_base_sources)
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(BUILD_RPC) lib/rpc_defs.py > $@

if ENABLE_METADATA
lib/rpc/stub/metad.py: Makefile src/hs2py | stamp-directories
	src/hs2py --metad-rpc > $@
endif

lib/rpc/stub/wconfd.py: Makefile src/hs2py | stamp-directories
	src/hs2py --wconfd-rpc > $@

$(SHELL_ENV_INIT): Makefile stamp-directories
	set -e; \
	{ echo '# Allow overriding for tests'; \
	  echo 'readonly LOCALSTATEDIR=$${LOCALSTATEDIR:-$${GANETI_ROOTDIR:-}$(localstatedir)}'; \
	  echo 'readonly SYSCONFDIR=$${SYSCONFDIR:-$${GANETI_ROOTDIR:-}$(sysconfdir)}'; \
	  echo; \
	  echo 'readonly PKGLIBDIR=$(libdir)/ganeti'; \
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
	  echo 's#@''BINDIR@#$(BINDIR)#g'; \
	  echo 's#@''SBINDIR@#$(SBINDIR)#g'; \
	  echo 's#@''LIBDIR@#$(libdir)#g'; \
	  echo 's#@''GANETI_VERSION@#$(PACKAGE_VERSION)#g'; \
	  echo 's#@''CUSTOM_XEN_BOOTLOADER@#$(XEN_BOOTLOADER)#g'; \
	  echo 's#@''CUSTOM_XEN_KERNEL@#$(XEN_KERNEL)#g'; \
	  echo 's#@''CUSTOM_XEN_INITRD@#$(XEN_INITRD)#g'; \
	  echo 's#@''CUSTOM_IALLOCATOR_SEARCH_PATH@#$(IALLOCATOR_SEARCH_PATH)#g'; \
	  echo 's#@''CUSTOM_EXPORT_DIR@#$(EXPORT_DIR)#g'; \
	  echo 's#@''RPL_SSH_INITD_SCRIPT@#$(SSH_INITD_SCRIPT)#g'; \
	  echo 's#@''PKGLIBDIR@#$(libdir)/ganeti#g'; \
	  echo 's#@''GNTMASTERUSER@#$(MASTERD_USER)#g'; \
	  echo 's#@''GNTRAPIUSER@#$(RAPI_USER)#g'; \
	  echo 's#@''GNTCONFDUSER@#$(CONFD_USER)#g'; \
	  echo 's#@''GNTWCONFDUSER@#$(WCONFD_USER)#g'; \
	  echo 's#@''GNTLUXIDUSER@#$(LUXID_USER)#g'; \
	  echo 's#@''GNTNODEDUSER@#$(NODED_USER)#g'; \
	  echo 's#@''GNTMONDUSER@#$(MOND_USER)#g'; \
	  echo 's#@''GNTMETADUSER@#$(METAD_USER)#g'; \
	  echo 's#@''GNTRAPIGROUP@#$(RAPI_GROUP)#g'; \
	  echo 's#@''GNTADMINGROUP@#$(ADMIN_GROUP)#g'; \
	  echo 's#@''GNTCONFDGROUP@#$(CONFD_GROUP)#g'; \
	  echo 's#@''GNTNODEDGROUP@#$(NODED_GROUP)#g'; \
	  echo 's#@''GNTWCONFDGROUP@#$(CONFD_GROUP)#g'; \
	  echo 's#@''GNTLUXIDGROUP@#$(LUXID_GROUP)#g'; \
	  echo 's#@''GNTMASTERDGROUP@#$(MASTERD_GROUP)#g'; \
	  echo 's#@''GNTMONDGROUP@#$(MOND_GROUP)#g'; \
	  echo 's#@''GNTMETADGROUP@#$(METAD_GROUP)#g'; \
	  echo 's#@''GNTDAEMONSGROUP@#$(DAEMONS_GROUP)#g'; \
	  echo 's#@''CUSTOM_ENABLE_MOND@#$(ENABLE_MOND)#g'; \
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
tools/ssh-update: MODULE = ganeti.tools.ssh_update
tools/node-cleanup: MODULE = ganeti.tools.node_cleanup
tools/ssl-update: MODULE = ganeti.tools.ssl_update
$(HS_BUILT_TEST_HELPERS): TESTROLE = $(patsubst test/hs/%,%,$@)

$(PYTHON_BOOTSTRAP) $(gnt_scripts) $(gnt_python_sbin_SCRIPTS): Makefile | stamp-directories
	test -n "$(MODULE)" || { echo Missing module; exit 1; }
	set -e; \
	{ echo '#!${PYTHON}'; \
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

.PHONY: check-news
check-news:
	RELEASE=$(PACKAGE_VERSION) $(CHECK_NEWS) < $(top_srcdir)/NEWS

.PHONY: check-local
check-local: check-dirs check-news $(GENERATED_FILES)
	$(CHECK_PYTHON_CODE) $(check_python_code)
	PYTHONPATH=. $(CHECK_HEADER) \
	    $(filter-out $(GENERATED_FILES),$(check_python_code))
	$(CHECK_VERSION) $(VERSION) $(top_srcdir)/NEWS
	PYTHONPATH=. $(RUN_IN_TEMPDIR) $(CURDIR)/$(CHECK_IMPORTS) . $(standalone_python_modules)
	error= ; \
	if [ "x`echo $(VERSION_SUFFIX)|grep 'alpha'`" == "x" ]; then \
	  expver=$(VERSION_MAJOR).$(VERSION_MINOR); \
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
	fi; \
	for file in configure.ac $(HS_LIBTEST_SRCS) $(HS_PROG_SRCS); do \
	  if test $$(wc --max-line-length < $(top_srcdir)/$$file) -gt 80; then \
	    echo "Longest line in $$file is longer than 80 characters" >&2; \
	    error=1; \
	  fi; \
	done; \
	test -z "$$error"

.PHONY: hs-test-%
hs-test-%: test/hs/htest
	@rm -f htest.tix
	test/hs/htest -t $*

.PHONY: hs-tests
hs-tests: test/hs/htest
	@rm -f htest.tix
	./test/hs/htest

.PHONY: py-tests
py-tests: $(python_tests) ganeti $(built_python_sources)
	error=; \
	for file in $(python_tests); \
	  do if ! $(TESTS_ENVIRONMENT) $$file; then error=1; fi; \
	done; \
	test -z "$$error"

.PHONY: hs-shell-%
hs-shell-%: test/hs/hpc-htools test/hs/hpc-mon-collector \
            $(HS_BUILT_TEST_HELPERS)
	@rm -f hpc-htools.tix hpc-mon-collector.tix
	HBINARY="./test/hs/hpc-htools" \
	SHELLTESTARGS=$(SHELLTESTARGS) \
	./test/hs/offline-test.sh $*

.PHONY: hs-shell
hs-shell: test/hs/hpc-htools test/hs/hpc-mon-collector $(HS_BUILT_TEST_HELPERS)
	@rm -f hpc-htools.tix hpc-mon-collector.tix
	HBINARY="./test/hs/hpc-htools" \
	SHELLTESTARGS=$(SHELLTESTARGS) \
	./test/hs/offline-test.sh

.PHONY: hs-check
hs-check: hs-tests hs-shell

# E111: indentation is not a multiple of four
# E121: continuation line indentation is not a multiple of four
#       (since our indent level is not 4)
# E125: continuation line does not distinguish itself from next logical line
#       (since our indent level is not 4)
# E123: closing bracket does not match indentation of opening bracket's line
# E127: continuation line over-indented for visual indent
#       (since our indent level is not 4)
# note: do NOT add E128 here; it's a valid style error in most cases!
# I've seen real errors, but also some cases were we indent wrongly
# due to line length; try to rework the cases where it is triggered,
# instead of silencing it
# E261: at least two spaces before inline comment
# E501: line too long (80 characters)
PEP8_IGNORE = E111,E121,E123,E125,E127,E261,E501

# For excluding pep8 expects filenames only, not whole paths
PEP8_EXCLUDE = $(subst $(space),$(comma),$(strip $(notdir $(built_python_sources))))

# A space-separated list of pylint warnings to completely ignore:
# I0013 = disable warnings for ignoring whole files
# R0912 = disable too many branches warning. It's useful, but ganeti requires
#         a lot of refactoring to fix this.
# R0204 = disable redefined-variable-type warning. There are a large number of
#         cases where Ganeti assigns multiple types (eg set/list, float/int) to
#         the same variable, and these are benign.
# C0325 = disable superfluous-parens. There are a lot of cases where this is
#         overzealous, eg where we use parens to make it clear that we're
#         deliberately doing a comparison that should yield bool, or are using
#         parens clarify precedence or to allow multi-line expressions.
# C0330 = disable wrong indentation warnings. pylint is much more strict than
#         pep8, and it would be too invasive to fix all these.
LINT_DISABLE = I0013 R0912 R0204 C0325 C0330
# Additional pylint options
LINT_OPTS =
# The combined set of pylint options
LINT_OPTS_ALL = $(LINT_OPTS) \
  $(addprefix --disable=,$(LINT_DISABLE))

# Whitelist loading pycurl C extension for attribute checking
LINT_OPTS_ALL += --extension-pkg-whitelist=pycurl

LINT_TARGETS = pylint pylint-qa pylint-test
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
	$(PYLINT) $(LINT_OPTS_ALL) $(lint_python_code)

.PHONY: pylint-qa
pylint-qa: $(GENERATED_FILES)
	@test -n "$(PYLINT)" || { echo 'pylint' not found during configure; exit 1; }
	cd $(top_srcdir)/qa && \
	  PYTHONPATH=$(abs_top_srcdir) $(PYLINT) $(LINT_OPTS_ALL) \
		--rcfile  ../pylintrc $(patsubst qa/%.py,%,$(qa_scripts))
# FIXME: lint all test code, not just the newly added test support
pylint-test: $(GENERATED_FILES)
	@test -n "$(PYLINT)" || { echo 'pylint' not found during configure; exit 1; }
	cd $(top_srcdir) && \
		PYTHONPATH=.:./test/py $(PYLINT) $(LINT_OPTS_ALL) \
		--rcfile=pylintrc-test  $(python_test_support) $(python_test_utils)

.PHONY: pep8
pep8: $(GENERATED_FILES)
	@test -n "$(PEP8)" || { echo 'pep8' not found during configure; exit 1; }
	$(PEP8) --ignore='$(PEP8_IGNORE)' --exclude='$(PEP8_EXCLUDE)' \
	  --repeat $(pep8_python_code)

HLINT_EXCLUDES = src/Ganeti/THH.hs test/hs/hpc-htools.hs
.PHONY: hlint
hlint: $(HS_BUILT_SRCS) src/lint-hints.hs
	@test -n "$(HLINT)" || { echo 'hlint' not found during configure; exit 1; }
	@rm -f doc/hs-lint.html
	if tty -s; then C="-c"; else C=""; fi; \
	$(HLINT) --utf8 --report=doc/hs-lint.html --cross $$C \
	  --hint src/lint-hints \
	  --cpp-file=$(HASKELL_PACKAGE_VERSIONS_FILE) \
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
	if test -e $(top_distdir)/doc/man-html; then \
	  echo "Found documentation including man pages in final archive" >&2; \
	  exit 1; \
	fi

# Backwards compatible distcheck-release target
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
	for dir in $(SYMLINK_TARGET_DIRS); do \
	  @mkdir_p@  $(DESTDIR)$$dir; \
	done
	$(LN_S) -f $(sysconfdir)/ganeti/lib $(DESTDIR)$(defaultversiondir)
	$(LN_S) -f $(sysconfdir)/ganeti/share $(DESTDIR)$(defaultversionedsharedir)
	for prog in $(HS_BIN_ROLES); do \
	  $(LN_S) -f $(defaultversiondir)$(BINDIR)/$$prog $(DESTDIR)$(BINDIR)/$$prog; \
	done
	$(LN_S) -f $(defaultversiondir)$(libdir)/ganeti/iallocators/hail $(DESTDIR)$(libdir)/ganeti/iallocators/hail
	for prog in $(all_sbin_scripts); do \
	  $(LN_S) -f $(defaultversiondir)$(SBINDIR)/$$prog $(DESTDIR)$(SBINDIR)/$$prog; \
	done
	for prog in $(gnt_scripts_basenames); do \
	  $(LN_S) -f $(defaultversionedsharedir)/$$prog $(DESTDIR)$(SBINDIR)/$$prog; \
	done
	for prog in $(pkglib_python_basenames); do \
	  $(LN_S) -f $(defaultversionedsharedir)/$$prog $(DESTDIR)$(libdir)/ganeti/$$prog; \
	done
	for prog in $(tools_python_basenames); do \
	  $(LN_S) -f $(defaultversionedsharedir)/$$prog $(DESTDIR)$(libdir)/ganeti/tools/$$prog; \
	done
	for prog in $(tools_basenames); do \
	  $(LN_S) -f $(defaultversiondir)/$(libdir)/ganeti/tools/$$prog $(DESTDIR)$(libdir)/ganeti/tools/$$prog; \
	done
	if ! test -n '$(ENABLE_MANPAGES)'; then \
	  for man in $(manfullpath); do \
	    $(LN_S) -f $(defaultversionedsharedir)/root$(MANDIR)/$$man $(DESTDIR)$(MANDIR)/$$man; \
	  done; \
	fi
	for prog in $(myexeclib_scripts_basenames); do \
	  $(LN_S) -f $(defaultversiondir)$(libdir)/ganeti/$$prog $(DESTDIR)$(libdir)/ganeti/$$prog; \
	done
if INSTALL_SYMLINKS
	$(LN_S) -f $(versionedsharedir) $(DESTDIR)$(sysconfdir)/ganeti/share
	$(LN_S) -f $(versiondir) $(DESTDIR)$(sysconfdir)/ganeti/lib
endif

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
hs-apidoc: $(APIDOC_HS_DIR)/index.html

$(APIDOC_HS_DIR)/index.html: $(HS_LIBTESTBUILT_SRCS) Makefile
	@test -n "$(HSCOLOUR)" || \
	    { echo 'HsColour' not found during configure; exit 1; }
	@test -n "$(HADDOCK)" || \
	    { echo 'haddock' not found during configure; exit 1; }
	rm -rf $(APIDOC_HS_DIR)/*
	for i in $(ALL_APIDOC_HS_DIRS); do \
	  @mkdir_p@ $$i; \
	  $(HSCOLOUR) -print-css > $$i/hscolour.css; \
	done
	set -e ; \
	export LC_ALL=en_US.UTF-8; \
	OPTGHC="--optghc=-isrc --optghc=-itest/hs"; \
	OPTGHC="$$OPTGHC --optghc=-optP-include --optghc=-optP$(HASKELL_PACKAGE_VERSIONS_FILE)"; \
	for file in $(HS_LIBTESTBUILT_SRCS); do \
	  f_nosrc=$${file##src/}; \
	  f_notst=$${f_nosrc##test/hs/}; \
	  f_html=$${f_notst%%.hs}.html; \
	  $(HSCOLOUR) -css -anchor $$file > $(APIDOC_HS_DIR)/$$f_html ; \
	done ; \
	$(HADDOCK) --odir $(APIDOC_HS_DIR) --html --hoogle --ignore-all-exports -w \
	  -t ganeti -p src/haddock-prologue \
	  --source-module="%{MODULE/.//}.html" \
	  --source-entity="%{MODULE/.//}.html#%{NAME}" \
	  $$OPTGHC \
	  $(HS_LIBTESTBUILT_SRCS)

.PHONY: TAGS
TAGS: $(GENERATED_FILES)
	rm -f TAGS
	$(GHC) -e ":etags TAGS_hs" -v0 \
	  $(filter-out -O -Werror,$(HFLAGS)) \
		-osuf tags.o \
		-hisuf tags.hi \
	-lcurl \
	  $(HS_LIBTEST_SRCS)
	find . -path './lib/*.py' -o -path './scripts/gnt-*' -o \
	  -path './daemons/ganeti-*' -o -path './tools/*' -o \
	  -path './qa/*.py' | \
	  etags --etags-include=TAGS_hs -L -

.PHONY: coverage

COVERAGE_TESTS=
if HS_UNIT
COVERAGE_TESTS += hs-coverage
endif
if PY_UNIT
COVERAGE_TESTS += py-coverage
endif

coverage: $(COVERAGE_TESTS)

test/py/docs_unittest.py: $(gnt_scripts)

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
	hpc report coverage-hs.tix | tee $(COVERAGE_HS_DIR)/report.txt
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

commit-check: autotools-check distcheck lint apidoc

autotools-check:
	TESTDATA_DIR=./test/data shelltest $(SHELLTESTARGS) \
  $(abs_top_srcdir)/test/autotools/*-*.test \
  -- --hide-successes

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

CABAL_EXECUTABLES = $(HS_DEFAULT_PROGS)
CABAL_EXECUTABLES_HS = $(patsubst %,%.hs,$(CABAL_EXECUTABLES))
CABAL_EXECUTABLES_APPS_STAMPS = $(patsubst src/%,apps/%.hs.stamp,$(patsubst test/hs/%,apps/%.hs.stamp,$(CABAL_EXECUTABLES)))

# Executable symlinks
apps/%.hs.stamp: Makefile
	mkdir -p apps
	rm -f $(basename $@)
	ln -s ../$(filter %/$(basename $(notdir $@)),$(CABAL_EXECUTABLES_HS)) $(basename $@)
	touch $@

# Builds the cabal file
ganeti.cabal: cabal/ganeti.template.cabal Makefile cabal/cabal-from-modules.py $(CABAL_EXECUTABLES_APPS_STAMPS)
	@echo $(subst /,.,$(patsubst %.hs,%,$(patsubst test/hs/%,%,$(patsubst src/%,%,$(HS_SRCS))))) \
	  | python $(abs_top_srcdir)/cabal/cabal-from-modules.py $(abs_top_srcdir)/cabal/ganeti.template.cabal > $@

	for p in $(CABAL_EXECUTABLES); do \
	  echo                                   >> $@; \
	  echo "executable `basename $$p`"       >> $@; \
	  echo "  hs-source-dirs: apps"          >> $@; \
	  echo "  main-is: `basename $$p`.hs"    >> $@; \
	  echo "  default-language: Haskell2010" >> $@; \
	  echo "  build-depends:"                >> $@; \
	  echo "      base"                      >> $@; \
	  echo "    , ganeti"                    >> $@; \
	  if [ $$p == test/hs/htest ]; then \
	    echo "    , hslogger"                  >> $@; \
	    echo "    , test-framework"            >> $@; \
	  elif [ $$p == src/rpc-test ]; then \
	    echo "    , json"                      >> $@; \
	  fi \
	done

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

# support inspecting the value of a make variable

print-%:
	@echo $($*)

# vim: set noet :
