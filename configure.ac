# Configure script for Ganeti
m4_define([gnt_version_major], [2])
m4_define([gnt_version_minor], [13])
m4_define([gnt_version_revision], [0])
m4_define([gnt_version_suffix], [~alpha1])
m4_define([gnt_version_full],
          m4_format([%d.%d.%d%s],
                    gnt_version_major, gnt_version_minor,
                    gnt_version_revision, gnt_version_suffix))

AC_PREREQ(2.59)
AC_INIT(ganeti, gnt_version_full, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AC_CONFIG_SRCDIR(configure)
AM_INIT_AUTOMAKE([1.9 foreign tar-ustar -Wall -Wno-portability]
                 m4_esyscmd([case `automake --version | head -n 1` in
                             *1.11*);;
                             *) echo serial-tests;;
                             esac]))

AC_SUBST([VERSION_MAJOR], gnt_version_major)
AC_SUBST([VERSION_MINOR], gnt_version_minor)
AC_SUBST([VERSION_REVISION], gnt_version_revision)
AC_SUBST([VERSION_SUFFIX], gnt_version_suffix)
AC_SUBST([VERSION_FULL], gnt_version_full)

AC_SUBST([BINDIR], $bindir)
AC_SUBST([SBINDIR], $sbindir)
AC_SUBST([MANDIR], $mandir)

# --enable-versionfull
AC_ARG_ENABLE([versionfull],
  [AS_HELP_STRING([--enable-versionfull],
                  m4_normalize([use the full version string rather
                  than major.minor for version directories]))],
  [[if test "$enableval" != no; then
      USE_VERSION_FULL=yes
    else
      USER_VERSION_FULL=no
    fi
  ]],
  [USE_VERSION_FULL=no
  ])
AC_SUBST(USE_VERSION_FULL, $USE_VERSION_FULL)
AM_CONDITIONAL([USE_VERSION_FULL], [test "$USE_VERSION_FULL" = yes])

# --enable-symlinks
AC_ARG_ENABLE([symlinks],
  [AS_HELP_STRING([--enable-symlinks],
                  m4_normalize([also install version-dependent symlinks under
                  $sysconfdir (default: disabled)]))],
  [[if test "$enableval" != yes; then
      INSTALL_SYMLINKS=no
    else
      INSTALL_SYMLINKS=yes
    fi
  ]],
  [INSTALL_SYMLINKS=no
  ])
AC_SUBST(INSTALL_SYMLINKS, $INSTALL_SYMLINKS)
AM_CONDITIONAL([INSTALL_SYMLINKS], [test "$INSTALL_SYMLINKS" = yes])

# --enable-haskell-profiling
AC_ARG_ENABLE([haskell-profiling],
  [AS_HELP_STRING([--enable-haskell-profiling],
                  m4_normalize([enable profiling for Haskell binaries
                  (default: disabled)]))],
  [[if test "$enableval" != yes; then
      HPROFILE=no
    else
      HPROFILE=yes
    fi
  ]],
  [HPROFILE=no
  ])
AC_SUBST(HPROFILE, $HPROFILE)
AM_CONDITIONAL([HPROFILE], [test "$HPROFILE" = yes])

# --enable-haskell-coverage
AC_ARG_ENABLE([haskell-coverage],
  [AS_HELP_STRING([--enable-haskell-coverage],
                  m4_normalize([enable coverage for Haskell binaries
                  (default: disabled)]))],
  [[if test "$enableval" != yes; then
      HCOVERAGE=no
    else
      HCOVERAGE=yes
    fi
  ]],
  [HCOVERAGE=no
  ])
AC_SUBST(HCOVERAGE, $HCOVERAGE)
AM_CONDITIONAL([HCOVERAGE], [test "$HCOVERAGE" = yes])

# --enable-haskell-tests
AC_ARG_ENABLE([haskell-tests],
  [AS_HELP_STRING([--enable-haskell-tests],
                  m4_normalize([enable additinal Haskell development test code
                  (default: disabled)]))],
  [[if test "$enableval" != yes; then
      HTEST=no
    else
      HTEST=yes
    fi
  ]],
  [HTEST=no
  ])
AC_SUBST(HTEST, $HTEST)
AM_CONDITIONAL([HTEST], [test "$HTEST" = yes])

# --with-haskell-flags=
AC_ARG_WITH([haskell-flags],
  [AS_HELP_STRING([--with-haskell-flags=FLAGS],
    [Extra flags to pass to GHC]
  )],
  [hextra_configure="$withval"],
  [hextra_configure=""])
AC_SUBST(HEXTRA_CONFIGURE, $hextra_configure)

# --with-ssh-initscript=...
AC_ARG_WITH([ssh-initscript],
  [AS_HELP_STRING([--with-ssh-initscript=SCRIPT],
    [SSH init script to use (default is /etc/init.d/ssh)]
  )],
  [ssh_initd_script="$withval"],
  [ssh_initd_script="/etc/init.d/ssh"])
AC_SUBST(SSH_INITD_SCRIPT, $ssh_initd_script)

# --with-export-dir=...
AC_ARG_WITH([export-dir],
  [AS_HELP_STRING([--with-export-dir=DIR],
    [directory to use by default for instance image]
    [ exports (default is /srv/ganeti/export)]
  )],
  [export_dir="$withval"],
  [export_dir="/srv/ganeti/export"])
AC_SUBST(EXPORT_DIR, $export_dir)

# --with-ssh-config-dir=...
AC_ARG_WITH([ssh-config-dir],
  [AS_HELP_STRING([--with-ssh-config-dir=DIR],
    [ directory with ssh host keys ]
    [ (default is /etc/ssh)]
  )],
  [ssh_config_dir="$withval"],
  [ssh_config_dir="/etc/ssh"])
AC_SUBST(SSH_CONFIG_DIR, $ssh_config_dir)

# --with-xen-config-dir=...
AC_ARG_WITH([xen-config-dir],
  [AS_HELP_STRING([--with-xen-config-dir=DIR],
                  m4_normalize([Xen configuration directory
                                (default: /etc/xen)]))],
  [xen_config_dir="$withval"],
  [xen_config_dir=/etc/xen])
AC_SUBST(XEN_CONFIG_DIR, $xen_config_dir)

# --with-os-search-path=...
AC_ARG_WITH([os-search-path],
  [AS_HELP_STRING([--with-os-search-path=LIST],
    [comma separated list of directories to]
    [ search for OS images (default is /srv/ganeti/os)]
  )],
  [os_search_path="$withval"],
  [os_search_path="/srv/ganeti/os"])
AC_SUBST(OS_SEARCH_PATH, $os_search_path)

# --with-extstorage-search-path=...
AC_ARG_WITH([extstorage-search-path],
  [AS_HELP_STRING([--with-extstorage-search-path=LIST],
    [comma separated list of directories to]
    [ search for External Storage Providers]
    [ (default is /srv/ganeti/extstorage)]
  )],
  [es_search_path="$withval"],
  [es_search_path="/srv/ganeti/extstorage"])
AC_SUBST(ES_SEARCH_PATH, $es_search_path)

# --with-iallocator-search-path=...
AC_ARG_WITH([iallocator-search-path],
  [AS_HELP_STRING([--with-iallocator-search-path=LIST],
    [comma separated list of directories to]
    [ search for instance allocators (default is $libdir/ganeti/iallocators)]
  )],
  [iallocator_search_path="$withval"],
  [iallocator_search_path="$libdir/$PACKAGE_NAME/iallocators"])
AC_SUBST(IALLOCATOR_SEARCH_PATH, $iallocator_search_path)

# --with-xen-bootloader=...
AC_ARG_WITH([xen-bootloader],
  [AS_HELP_STRING([--with-xen-bootloader=PATH],
    [bootloader for Xen hypervisor (default is empty)]
  )],
  [xen_bootloader="$withval"],
  [xen_bootloader=])
AC_SUBST(XEN_BOOTLOADER, $xen_bootloader)

# --with-xen-kernel=...
AC_ARG_WITH([xen-kernel],
  [AS_HELP_STRING([--with-xen-kernel=PATH],
    [DomU kernel image for Xen hypervisor (default is /boot/vmlinuz-3-xenU)]
  )],
  [xen_kernel="$withval"],
  [xen_kernel="/boot/vmlinuz-3-xenU"])
AC_SUBST(XEN_KERNEL, $xen_kernel)

# --with-xen-initrd=...
AC_ARG_WITH([xen-initrd],
  [AS_HELP_STRING([--with-xen-initrd=PATH],
    [DomU initrd image for Xen hypervisor (default is /boot/initrd-3-xenU)]
  )],
  [xen_initrd="$withval"],
  [xen_initrd="/boot/initrd-3-xenU"])
AC_SUBST(XEN_INITRD, $xen_initrd)

# --with-kvm-kernel=...
AC_ARG_WITH([kvm-kernel],
  [AS_HELP_STRING([--with-kvm-kernel=PATH],
    [Guest kernel image for KVM hypervisor (default is /boot/vmlinuz-3-kvmU)]
  )],
  [kvm_kernel="$withval"],
  [kvm_kernel="/boot/vmlinuz-3-kvmU"])
AC_SUBST(KVM_KERNEL, $kvm_kernel)

# --with-kvm-path=...
AC_ARG_WITH([kvm-path],
  [AS_HELP_STRING([--with-kvm-path=PATH],
    [absolute path to the kvm binary]
    [ (default is /usr/bin/kvm)]
  )],
  [kvm_path="$withval"],
  [kvm_path="/usr/bin/kvm"])
AC_SUBST(KVM_PATH, $kvm_path)

# --with-lvm-stripecount=...
AC_ARG_WITH([lvm-stripecount],
  [AS_HELP_STRING([--with-lvm-stripecount=NUM],
    [the default number of stripes to use for LVM volumes]
    [ (default is 1)]
  )],
  [lvm_stripecount="$withval"],
  [lvm_stripecount=1])
AC_SUBST(LVM_STRIPECOUNT, $lvm_stripecount)

# --with-ssh-login-user=...
AC_ARG_WITH([ssh-login-user],
  [AS_HELP_STRING([--with-ssh-login-user=USERNAME],
    [user to use for SSH logins within the cluster (default is root)]
  )],
  [ssh_login_user="$withval"],
  [ssh_login_user=root])
AC_SUBST(SSH_LOGIN_USER, $ssh_login_user)

# --with-ssh-console-user=...
AC_ARG_WITH([ssh-console-user],
  [AS_HELP_STRING([--with-ssh-console-user=USERNAME],
    [user to use for SSH logins to access instance consoles (default is root)]
  )],
  [ssh_console_user="$withval"],
  [ssh_console_user=root])
AC_SUBST(SSH_CONSOLE_USER, $ssh_console_user)

# --with-default-user=...
AC_ARG_WITH([default-user],
  [AS_HELP_STRING([--with-default-user=USERNAME],
    [default user for daemons]
    [ (default is to run all daemons as root)]
  )],
  [user_default="$withval"],
  [user_default=root])

# --with-default-group=...
AC_ARG_WITH([default-group],
  [AS_HELP_STRING([--with-default-group=GROUPNAME],
    [default group for daemons]
    [ (default is to run all daemons under group root)]
  )],
  [group_default="$withval"],
  [group_default=root])

# --with-user-prefix=...
AC_ARG_WITH([user-prefix],
  [AS_HELP_STRING([--with-user-prefix=PREFIX],
    [prefix for daemon users]
    [ (default is to run all daemons as root; use --with-default-user]
    [ to change the default)]
  )],
  [user_masterd="${withval}masterd";
   user_metad="${withval}metad";
   user_rapi="${withval}rapi";
   user_confd="${withval}confd";
   user_wconfd="${withval}wconfd";
   user_kvmd="$user_default";
   user_luxid="${withval}masterd";
   user_noded="$user_default";
   user_mond="$user_default"],
  [user_masterd="$user_default";
   user_metad="$user_default";
   user_rapi="$user_default";
   user_confd="$user_default";
   user_wconfd="$user_default";
   user_kvmd="$user_default";
   user_luxid="$user_default";
   user_noded="$user_default";
   user_mond="$user_default"])
AC_SUBST(MASTERD_USER, $user_masterd)
AC_SUBST(METAD_USER, $user_metad)
AC_SUBST(RAPI_USER, $user_rapi)
AC_SUBST(CONFD_USER, $user_confd)
AC_SUBST(WCONFD_USER, $user_wconfd)
AC_SUBST(KVMD_USER, $user_kvmd)
AC_SUBST(LUXID_USER, $user_luxid)
AC_SUBST(NODED_USER, $user_noded)
AC_SUBST(MOND_USER, $user_mond)

# --with-group-prefix=...
AC_ARG_WITH([group-prefix],
  [AS_HELP_STRING([--with-group-prefix=PREFIX],
    [prefix for daemon POSIX groups]
    [ (default is to run all daemons under group root; use]
    [ --with-default-group to change the default)]
  )],
  [group_rapi="${withval}rapi";
   group_admin="${withval}admin";
   group_confd="${withval}confd";
   group_wconfd="${withval}wconfd";
   group_kvmd="$group_default";
   group_luxid="${withval}luxid";
   group_masterd="${withval}masterd";
   group_metad="${withval}metad";
   group_noded="$group_default";
   group_daemons="${withval}daemons";
   group_mond="$group_default"],
  [group_rapi="$group_default";
   group_admin="$group_default";
   group_confd="$group_default";
   group_wconfd="$group_default";
   group_kvmd="$group_default";
   group_luxid="$group_default";
   group_masterd="$group_default";
   group_metad="$group_default";
   group_noded="$group_default";
   group_daemons="$group_default";
   group_mond="$group_default"])
AC_SUBST(RAPI_GROUP, $group_rapi)
AC_SUBST(ADMIN_GROUP, $group_admin)
AC_SUBST(CONFD_GROUP, $group_confd)
AC_SUBST(WCONFD_GROUP, $group_wconfd)
AC_SUBST(KVMD_GROUP, $group_kvmd)
AC_SUBST(LUXID_GROUP, $group_luxid)
AC_SUBST(MASTERD_GROUP, $group_masterd)
AC_SUBST(METAD_GROUP, $group_metad)
AC_SUBST(NODED_GROUP, $group_noded)
AC_SUBST(DAEMONS_GROUP, $group_daemons)
AC_SUBST(MOND_GROUP, $group_mond)

# Print the config to the user
AC_MSG_NOTICE([Running ganeti-masterd as $group_masterd:$group_masterd])
AC_MSG_NOTICE([Running ganeti-metad as $group_metad:$group_metad])
AC_MSG_NOTICE([Running ganeti-rapi as $user_rapi:$group_rapi])
AC_MSG_NOTICE([Running ganeti-confd as $user_confd:$group_confd])
AC_MSG_NOTICE([Running ganeti-wconfd as $user_wconfd:$group_wconfd])
AC_MSG_NOTICE([Running ganeti-luxid as $user_luxid:$group_luxid])
AC_MSG_NOTICE([Group for daemons is $group_daemons])
AC_MSG_NOTICE([Group for clients is $group_admin])

# --enable-drbd-barriers
AC_ARG_ENABLE([drbd-barriers],
  [AS_HELP_STRING([--enable-drbd-barriers],
                  m4_normalize([enable the DRBD barriers functionality by
                                default (>= 8.0.12) (default: enabled)]))],
  [[if test "$enableval" != no; then
      DRBD_BARRIERS=n
      DRBD_NO_META_FLUSH=False
    else
      DRBD_BARRIERS=bf
      DRBD_NO_META_FLUSH=True
    fi
  ]],
  [DRBD_BARRIERS=n
   DRBD_NO_META_FLUSH=False
  ])
AC_SUBST(DRBD_BARRIERS, $DRBD_BARRIERS)
AC_SUBST(DRBD_NO_META_FLUSH, $DRBD_NO_META_FLUSH)

# --enable-syslog[=no/yes/only]
AC_ARG_ENABLE([syslog],
  [AS_HELP_STRING([--enable-syslog],
    [enable use of syslog (default: disabled), one of no/yes/only])],
  [[case "$enableval" in
      no)
        SYSLOG=no
        ;;
      yes)
        SYSLOG=yes
        ;;
      only)
        SYSLOG=only
        ;;
      *)
        SYSLOG=
        ;;
    esac
  ]],
  [SYSLOG=no])

if test -z "$SYSLOG"
then
  AC_MSG_ERROR([invalid value for syslog, choose one of no/yes/only])
fi
AC_SUBST(SYSLOG_USAGE, $SYSLOG)

# --enable-restricted-commands[=no/yes]
AC_ARG_ENABLE([restricted-commands],
  [AS_HELP_STRING([--enable-restricted-commands],
                  m4_normalize([enable restricted commands in the node daemon
                                (default: disabled)]))],
  [[if test "$enableval" = no; then
      enable_restricted_commands=False
    else
      enable_restricted_commands=True
    fi
  ]],
  [enable_restricted_commands=False])
AC_SUBST(ENABLE_RESTRICTED_COMMANDS, $enable_restricted_commands)

# --with-disk-separator=...
AC_ARG_WITH([disk-separator],
  [AS_HELP_STRING([--with-disk-separator=STRING],
    [Disk index separator, useful if the default of ':' is handled]
    [ specially by the hypervisor]
  )],
  [disk_separator="$withval"],
  [disk_separator=":"])
AC_SUBST(DISK_SEPARATOR, $disk_separator)

# Check common programs
AC_PROG_INSTALL
AC_PROG_LN_S

# check if ln is the GNU version of ln (and hence supports -T)
if ln --version 2> /dev/null | head -1 | grep -q GNU
then
  AC_SUBST(HAS_GNU_LN, True)
else
  AC_SUBST(HAS_GNU_LN, False)
fi

# Check for the ip command
AC_ARG_VAR(IP_PATH, [ip path])
AC_PATH_PROG(IP_PATH, [ip], [])
if test -z "$IP_PATH"
then
  AC_MSG_ERROR([ip command not found])
fi

# Check for pandoc
AC_ARG_VAR(PANDOC, [pandoc path])
AC_PATH_PROG(PANDOC, [pandoc], [])
if test -z "$PANDOC"
then
  AC_MSG_WARN([pandoc not found, man pages rebuild will not be possible])
fi

# Check for python-sphinx
AC_ARG_VAR(SPHINX, [sphinx-build path])
AC_PATH_PROG(SPHINX, [sphinx-build], [])
if test -z "$SPHINX"
then
  AC_MSG_WARN(m4_normalize([sphinx-build not found, documentation rebuild will
                            not be possible]))
else
  # Sphinx exits with code 1 when it prints its usage
  sphinxver=`{ $SPHINX --version 2>&1 || :; } | head -n 3`

  if ! echo "$sphinxver" | grep -q -w -e '^Sphinx' -e '^Usage:'; then
    AC_MSG_ERROR([Unable to determine Sphinx version])

  # Note: Character classes ([...]) need to be double quoted due to autoconf
  # using m4
  elif ! echo "$sphinxver" | grep -q -E \
       '^Sphinx[[[:space:]]]+(\(sphinx-build\)[[[:space:]]]+|v)[[1-9]]\>'; then
    AC_MSG_ERROR([Sphinx 1.0 or higher is required])
  fi
fi
AM_CONDITIONAL([HAS_SPHINX], [test -n "$SPHINX"])

AC_ARG_ENABLE([manpages-in-doc],
  [AS_HELP_STRING([--enable-manpages-in-doc],
                  m4_normalize([include man pages in HTML documentation
                                (requires sphinx; default disabled)]))],
  [case "$enableval" in
      yes) manpages_in_doc=yes ;;
      no) manpages_in_doc= ;;
      *)
        AC_MSG_ERROR([Bad value $enableval for --enable-manpages-in-doc])
        ;;
    esac
  ],
  [manpages_in_doc=])
AM_CONDITIONAL([MANPAGES_IN_DOC], [test -n "$manpages_in_doc"])
AC_SUBST(MANPAGES_IN_DOC, $manpages_in_doc)

if test -z "$SPHINX" -a -n "$manpages_in_doc"; then
  AC_MSG_ERROR([Including man pages in HTML documentation requires sphinx])
fi

# Check for graphviz (dot)
AC_ARG_VAR(DOT, [dot path])
AC_PATH_PROG(DOT, [dot], [])
if test -z "$DOT"
then
  AC_MSG_WARN(m4_normalize([dot (from the graphviz suite) not found,
                            documentation rebuild not possible]))
fi

# Check for pylint
AC_ARG_VAR(PYLINT, [pylint path])
AC_PATH_PROG(PYLINT, [pylint], [])
if test -z "$PYLINT"
then
  AC_MSG_WARN([pylint not found, checking code will not be possible])
fi

# Check for pep8
AC_ARG_VAR(PEP8, [pep8 path])
AC_PATH_PROG(PEP8, [pep8], [])
if test -z "$PEP8"
then
  AC_MSG_WARN([pep8 not found, checking code will not be complete])
fi
AM_CONDITIONAL([HAS_PEP8], [test -n "$PEP8"])

# Check for python-coverage
AC_ARG_VAR(PYCOVERAGE, [python-coverage path])
AC_PATH_PROGS(PYCOVERAGE, [python-coverage coverage], [])
if test -z "$PYCOVERAGE"
then
  AC_MSG_WARN(m4_normalize([python-coverage or coverage not found, evaluating
                            Python test coverage will not be possible]))
fi

# Check for socat
AC_ARG_VAR(SOCAT, [socat path])
AC_PATH_PROG(SOCAT, [socat], [])
if test -z "$SOCAT"
then
  AC_MSG_ERROR([socat not found])
fi

# Check for qemu-img
AC_ARG_VAR(QEMUIMG_PATH, [qemu-img path])
AC_PATH_PROG(QEMUIMG_PATH, [qemu-img], [])
if test -z "$QEMUIMG_PATH"
then
  AC_MSG_WARN([qemu-img not found, using ovfconverter will not be possible])
fi

# --enable-confd
ENABLE_CONFD=
AC_ARG_ENABLE([confd],
  [AS_HELP_STRING([--enable-confd],
  [enable the ganeti-confd daemon (default: check)])],
  [],
  [enable_confd=check])

ENABLE_MOND=
AC_ARG_ENABLE([monitoring],
  [AS_HELP_STRING([--enable-monitoring],
  [enable the ganeti monitoring daemon (default: check)])],
  [],
  [enable_monitoring=check])

# Check for ghc
AC_ARG_VAR(GHC, [ghc path])
AC_PATH_PROG(GHC, [ghc], [])
if test -z "$GHC"; then
  AC_MSG_FAILURE([ghc not found, compilation will not possible])
fi

AC_MSG_CHECKING([checking for extra GHC flags])
GHC_BYVERSION_FLAGS=
# check for GHC supported flags that vary accross versions
for flag in -fwarn-incomplete-uni-patterns; do
  if $GHC -e '0' $flag >/dev/null 2>/dev/null; then
   GHC_BYVERSION_FLAGS="$GHC_BYVERSION_FLAGS $flag"
  fi
done
AC_MSG_RESULT($GHC_BYVERSION_FLAGS)
AC_SUBST(GHC_BYVERSION_FLAGS)

# Check for ghc-pkg
AC_ARG_VAR(GHC_PKG, [ghc-pkg path])
AC_PATH_PROG(GHC_PKG, [ghc-pkg], [])
if test -z "$GHC_PKG"; then
  AC_MSG_FAILURE([ghc-pkg not found, compilation will not be possible])
fi

# check for modules, first custom/special checks
AC_MSG_NOTICE([checking for required haskell modules])
HS_PARALLEL3=
AC_GHC_PKG_CHECK([parallel-3.*], [HS_PARALLEL3=-DPARALLEL3],
                 [AC_GHC_PKG_REQUIRE(parallel)], t)
AC_SUBST(HS_PARALLEL3)

# and now standard modules
AC_GHC_PKG_REQUIRE(curl)
AC_GHC_PKG_REQUIRE(json)
AC_GHC_PKG_REQUIRE(network)
AC_GHC_PKG_REQUIRE(mtl)
AC_GHC_PKG_REQUIRE(bytestring)
AC_GHC_PKG_REQUIRE(base64-bytestring-1.*, t)
AC_GHC_PKG_REQUIRE(utf8-string)
AC_GHC_PKG_REQUIRE(zlib)
AC_GHC_PKG_REQUIRE(hslogger)
AC_GHC_PKG_REQUIRE(process)
AC_GHC_PKG_REQUIRE(attoparsec)
AC_GHC_PKG_REQUIRE(vector)
AC_GHC_PKG_REQUIRE(text)
AC_GHC_PKG_REQUIRE(hinotify)
AC_GHC_PKG_REQUIRE(Crypto)
AC_GHC_PKG_REQUIRE(lifted-base)
AC_GHC_PKG_REQUIRE(lens)

# extra modules for confd functionality; also needed for tests
HS_NODEV=
CONFD_PKG=
# if a new confd dependency is needed, add it here like:
# AC_GHC_PKG_CHECK([somepkg], [], [HS_NODEV=1; CONFD_PKG="$CONFD_PKG somepkg"])
HS_REGEX_PCRE=-DNO_REGEX_PCRE
AC_GHC_PKG_CHECK([regex-pcre], [HS_REGEX_PCRE=],
                 [HS_NODEV=1; CONFD_PKG="$CONFD_PKG regex-pcre"])

has_confd=False
if test "$enable_confd" != no; then
  if test -z "$CONFD_PKG"; then
    has_confd=True
  elif test "$enable_confd" = check; then
    AC_MSG_WARN(m4_normalize([The required extra libraries for confd were
                              not found ($CONFD_PKG), confd disabled]))
  else
    AC_MSG_FAILURE(m4_normalize([The confd functionality was requested, but
                                 required libraries were not found:
                                 $CONFD_PKG]))
  fi
fi
AC_SUBST(HS_REGEX_PCRE)
if test "$has_confd" = True; then
  AC_MSG_NOTICE([Enabling confd usage])
fi
AC_SUBST(ENABLE_CONFD, $has_confd)
AM_CONDITIONAL([ENABLE_CONFD], [test x$has_confd = xTrue])

#extra modules for monitoring daemon functionality; also needed for tests
MONITORING_PKG=
AC_GHC_PKG_CHECK([snap-server], [],
                 [NS_NODEV=1; MONITORING_PKG="$MONITORING_PKG snap-server"])

has_monitoring=False
if test "$enable_monitoring" != no; then
  MONITORING_DEP=
  if test "$has_confd" = False; then
    MONITORING_DEP="$MONITORING_DEP confd"
  fi
  has_monitoring_pkg=False
  if test -z "$MONITORING_PKG"; then
    has_monitoring_pkg=True
  elif test "$enable_monitoring" = check; then
    AC_MSG_WARN(m4_normalize([The required extra libraries for the monitoring
                              daemon were not found ($MONITORING_PKG),
                              monitoring disabled]))
  else
    AC_MSG_FAILURE(m4_normalize([The monitoring functionality was requested, but
                                 required libraries were not found:
                                 $MONITORING_PKG]))
  fi
  has_monitoring_dep=False
  if test -z "$MONITORING_DEP"; then
    has_monitoring_dep=True
  elif test "$enable_monitoring" = check; then
    AC_MSG_WARN(m4_normalize([The optional Ganeti components required for the
                              monitoring agent were not enabled
                              ($MONITORING_DEP), monitoring disabled]))
  else
    AC_MSG_FAILURE(m4_normalize([The monitoring functionality was requested, but
                                 required optional Ganeti components were not
                                 found: $MONITORING_DEP]))
  fi

fi
if test "$has_monitoring_pkg" = True -a "$has_monitoring_dep" = True; then
  has_monitoring=True
  AC_MSG_NOTICE([Enabling the monitoring agent usage])
fi
AC_SUBST(ENABLE_MOND, $has_monitoring)
AM_CONDITIONAL([ENABLE_MOND], [test "$has_monitoring" = True])

# development modules
AC_GHC_PKG_CHECK([QuickCheck-2.*], [], [HS_NODEV=1], t)
AC_GHC_PKG_CHECK([test-framework-0.6*], [], [
  AC_GHC_PKG_CHECK([test-framework-0.7*], [], [
    AC_GHC_PKG_CHECK([test-framework-0.8*], [], [HS_NODEV=1], t)
  ], t)
], t)
AC_GHC_PKG_CHECK([test-framework-hunit], [], [HS_NODEV=1])
AC_GHC_PKG_CHECK([test-framework-quickcheck2], [], [HS_NODEV=1])
AC_GHC_PKG_CHECK([temporary], [], [HS_NODEV=1])
if test -n "$HS_NODEV"; then
   AC_MSG_WARN(m4_normalize([Required development modules were not found,
                             you won't be able to run Haskell unittests]))
else
   AC_MSG_NOTICE([Haskell development modules found, unittests enabled])
fi
AC_SUBST(HS_NODEV)
AM_CONDITIONAL([HS_UNIT], [test -n $HS_NODEV])

# Check for HsColour
HS_APIDOC=no
AC_ARG_VAR(HSCOLOUR, [HsColour path])
AC_PATH_PROG(HSCOLOUR, [HsColour], [])
if test -z "$HSCOLOUR"; then
  AC_MSG_WARN(m4_normalize([HsColour not found, htools API documentation will
                            not be generated]))
fi

# Check for haddock
AC_ARG_VAR(HADDOCK, [haddock path])
AC_PATH_PROG(HADDOCK, [haddock], [])
if test -z "$HADDOCK"; then
  AC_MSG_WARN(m4_normalize([haddock not found, htools API documentation will
                            not be generated]))
fi
if test -n "$HADDOCK" && test -n "$HSCOLOUR"; then
  HS_APIDOC=yes
fi
AC_SUBST(HS_APIDOC)

# Check for hlint
AC_ARG_VAR(HLINT, [hlint path])
AC_PATH_PROG(HLINT, [hlint], [])
if test -z "$HLINT"; then
  AC_MSG_WARN([hlint not found, checking code will not be possible])
fi

AM_CONDITIONAL([WANT_HSTESTS], [test "x$HS_NODEV" = x])
AM_CONDITIONAL([WANT_HSAPIDOC], [test "$HS_APIDOC" = yes])
AM_CONDITIONAL([HAS_HLINT], [test "$HLINT"])

# Check for fakeroot
AC_ARG_VAR(FAKEROOT_PATH, [fakeroot path])
AC_PATH_PROG(FAKEROOT_PATH, [fakeroot], [])
if test -z "$FAKEROOT_PATH"; then
  AC_MSG_WARN(m4_normalize([fakeroot not found, tests that must run as root
                            will not be executed]))
fi
AM_CONDITIONAL([HAS_FAKEROOT], [test "x$FAKEROOT_PATH" != x])

SOCAT_USE_ESCAPE=
AC_ARG_ENABLE([socat-escape],
  [AS_HELP_STRING([--enable-socat-escape],
    [use escape functionality available in socat >= 1.7 (default: detect
     automatically)])],
  [[if test "$enableval" = yes; then
      SOCAT_USE_ESCAPE=True
    else
      SOCAT_USE_ESCAPE=False
    fi
  ]])

if test -z "$SOCAT_USE_ESCAPE"
then
  if $SOCAT -hh | grep -w -q escape; then
    SOCAT_USE_ESCAPE=True
  else
    SOCAT_USE_ESCAPE=False
  fi
fi

AC_SUBST(SOCAT_USE_ESCAPE)

SOCAT_USE_COMPRESS=
AC_ARG_ENABLE([socat-compress],
  [AS_HELP_STRING([--enable-socat-compress],
    [use OpenSSL compression option available in patched socat builds
     (see INSTALL for details; default: detect automatically)])],
  [[if test "$enableval" = yes; then
      SOCAT_USE_COMPRESS=True
    else
      SOCAT_USE_COMPRESS=False
    fi
  ]])

if test -z "$SOCAT_USE_COMPRESS"
then
  if $SOCAT -hhh | grep -w -q openssl-compress; then
    SOCAT_USE_COMPRESS=True
  else
    SOCAT_USE_COMPRESS=False
  fi
fi

AC_SUBST(SOCAT_USE_COMPRESS)

if man --help | grep -q -e --warnings
then
  MAN_HAS_WARNINGS=1
else
  MAN_HAS_WARNINGS=
  AC_MSG_WARN(m4_normalize([man does not support --warnings, man page checks
                            will not be possible]))
fi

AC_SUBST(MAN_HAS_WARNINGS)

# Check for Python
AM_PATH_PYTHON(2.6)

AC_PYTHON_MODULE(OpenSSL, t)
AC_PYTHON_MODULE(simplejson, t)
AC_PYTHON_MODULE(pyparsing, t)
AC_PYTHON_MODULE(pyinotify, t)
AC_PYTHON_MODULE(pycurl, t)
AC_PYTHON_MODULE(bitarray, t)
AC_PYTHON_MODULE(ipaddr, t)
AC_PYTHON_MODULE(mock)
AC_PYTHON_MODULE(affinity)
AC_PYTHON_MODULE(paramiko)

# Development-only Python modules
PY_NODEV=
AC_PYTHON_MODULE(yaml)
if test $HAVE_PYMOD_YAML == "no"; then
  PY_NODEV="$PY_NODEV yaml"
fi

if test -n "$PY_NODEV"; then
  AC_MSG_WARN(m4_normalize([Required development modules ($PY_NODEV) were not
                            found, you won't be able to run Python unittests]))
else
  AC_MSG_NOTICE([Python development modules found, unittests enabled])
fi
AC_SUBST(PY_NODEV)
AM_CONDITIONAL([PY_UNIT], [test -n $PY_NODEV])

include_makefile_ghc='
ifneq ($(MAKECMDGOALS),ganeti)
ifneq ($(MAKECMDGOALS),clean)
ifneq ($(MAKECMDGOALS),distclean)
include Makefile.ghc
endif
endif
endif
'
AC_SUBST([include_makefile_ghc])
AM_SUBST_NOTMAKE([include_makefile_ghc])

AC_CONFIG_FILES([ Makefile ])

AC_OUTPUT
