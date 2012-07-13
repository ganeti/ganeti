# Configure script for Ganeti
m4_define([gnt_version_major], [2])
m4_define([gnt_version_minor], [6])
m4_define([gnt_version_revision], [0])
m4_define([gnt_version_suffix], [~rc3])
m4_define([gnt_version_full],
          m4_format([%d.%d.%d%s],
                    gnt_version_major, gnt_version_minor,
                    gnt_version_revision, gnt_version_suffix))

AC_PREREQ(2.59)
AC_INIT(ganeti, gnt_version_full, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AC_CONFIG_SRCDIR(configure)
AM_INIT_AUTOMAKE([1.9 foreign tar-ustar -Wall -Wno-portability])

AC_SUBST([VERSION_MAJOR], gnt_version_major)
AC_SUBST([VERSION_MINOR], gnt_version_minor)
AC_SUBST([VERSION_REVISION], gnt_version_revision)
AC_SUBST([VERSION_SUFFIX], gnt_version_suffix)
AC_SUBST([VERSION_FULL], gnt_version_full)

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

# --with-os-search-path=...
# do a bit of black sed magic to for quoting of the strings in the list
AC_ARG_WITH([os-search-path],
  [AS_HELP_STRING([--with-os-search-path=LIST],
    [comma separated list of directories to]
    [ search for OS images (default is /srv/ganeti/os)]
  )],
  [os_search_path=`echo -n "$withval" | sed -e "s/\([[^,]]*\)/'\1'/g"`],
  [os_search_path="'/srv/ganeti/os'"])
AC_SUBST(OS_SEARCH_PATH, $os_search_path)

# --with-iallocator-search-path=...
# do a bit of black sed magic to for quoting of the strings in the list
AC_ARG_WITH([iallocator-search-path],
  [AS_HELP_STRING([--with-iallocator-search-path=LIST],
    [comma separated list of directories to]
    [ search for instance allocators (default is $libdir/ganeti/iallocators)]
  )],
  [iallocator_search_path=`echo -n "$withval" | sed -e "s/\([[^,]]*\)/'\1'/g"`],
  [iallocator_search_path="'$libdir/$PACKAGE_NAME/iallocators'"])
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

# --with-xen-cmd=...
AC_ARG_WITH([xen-cmd],
  [AS_HELP_STRING([--with-xen-cmd=CMD],
    [Sets the xen cli interface command (default is xm)]
  )],
  [xen_cmd="$withval"],
  [xen_cmd="xm"])
AC_SUBST(XEN_CMD, $xen_cmd)

if ! test "$XEN_CMD" = xl -o "$XEN_CMD" = xm; then
  AC_MSG_ERROR([Unsupported xen command specified])
fi

# --with-kvm-kernel=...
AC_ARG_WITH([kvm-kernel],
  [AS_HELP_STRING([--with-kvm-kernel=PATH],
    [Guest kernel image for KVM hypervisor (default is /boot/vmlinuz-3-kvmU)]
  )],
  [kvm_kernel="$withval"],
  [kvm_kernel="/boot/vmlinuz-3-kvmU"])
AC_SUBST(KVM_KERNEL, $kvm_kernel)

# --with-file-storage-dir=...
AC_ARG_WITH([file-storage-dir],
  [AS_HELP_STRING([--with-file-storage-dir=PATH],
    [directory to store files for file-based backend]
    [ (default is /srv/ganeti/file-storage)]
  )],
  [[file_storage_dir="$withval";
    if test "$withval" != no; then
      enable_file_storage=True
    else
      enable_file_storage=False
    fi
  ]],
  [[file_storage_dir="/srv/ganeti/file-storage";
    enable_file_storage="True"]])
AC_SUBST(FILE_STORAGE_DIR, $file_storage_dir)
AC_SUBST(ENABLE_FILE_STORAGE, $enable_file_storage)

# --with-shared-file-storage-dir=...
AC_ARG_WITH([shared-file-storage-dir],
  [AS_HELP_STRING([--with-shared-file-storage-dir=PATH],
    [directory to store files for shared file-based backend]
    [ (default is /srv/ganeti/shared-file-storage)]
  )],
  [[shared_file_storage_dir="$withval";
    if test "$withval" != no; then
      enable_shared_file_storage=True
    else
      enable_shared_file_storage=False
    fi
  ]],
  [[shared_file_storage_dir="/srv/ganeti/shared-file-storage";
    enable_shared_file_storage="True"]])
AC_SUBST(SHARED_FILE_STORAGE_DIR, $shared_file_storage_dir)
AC_SUBST(ENABLE_SHARED_FILE_STORAGE, $enable_shared_file_storage)

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
  [lvm_stripecount="1"])
AC_SUBST(LVM_STRIPECOUNT, $lvm_stripecount)

# --with-user-prefix=...
AC_ARG_WITH([user-prefix],
  [AS_HELP_STRING([--with-user-prefix=PREFIX],
    [prefix for daemon users]
    [ (default is to run all daemons as root)]
  )],
  [user_masterd="${withval}masterd";
   user_rapi="${withval}rapi";
   user_confd="${withval}confd";
   user_noded="root"],
  [user_masterd="root";
   user_rapi="root";
   user_confd="root";
   user_noded="root"])
AC_SUBST(MASTERD_USER, $user_masterd)
AC_SUBST(RAPI_USER, $user_rapi)
AC_SUBST(CONFD_USER, $user_confd)
AC_SUBST(NODED_USER, $user_noded)

# --with-group-prefix=...
AC_ARG_WITH([group-prefix],
  [AS_HELP_STRING([--with-group-prefix=PREFIX],
    [prefix for daemon POSIX groups]
    [ (default is to run all daemons under group root)]
  )],
  [group_rapi="${withval}rapi";
   group_admin="${withval}admin";
   group_confd="${withval}confd";
   group_masterd="${withval}masterd";
   group_noded="root";
   group_daemons="${withval}daemons";],
  [group_rapi="root";
   group_admin="root";
   group_confd="root";
   group_masterd="root";
   group_noded="root";
   group_daemons="root"])
AC_SUBST(RAPI_GROUP, $group_rapi)
AC_SUBST(ADMIN_GROUP, $group_admin)
AC_SUBST(CONFD_GROUP, $group_confd)
AC_SUBST(MASTERD_GROUP, $group_masterd)
AC_SUBST(NODED_GROUP, $group_noded)
AC_SUBST(DAEMONS_GROUP, $group_daemons)

# Print the config to the user
AC_MSG_NOTICE([Running ganeti-masterd as $group_masterd:$group_masterd])
AC_MSG_NOTICE([Running ganeti-rapi as $user_rapi:$group_rapi])
AC_MSG_NOTICE([Running ganeti-confd as $user_confd:$group_confd])
AC_MSG_NOTICE([Group for daemons is $group_daemons])
AC_MSG_NOTICE([Group for clients is $group_admin])

# --enable-drbd-barriers
AC_ARG_ENABLE([drbd-barriers],
  [AS_HELP_STRING([--enable-drbd-barriers],
    [enable by default the DRBD barriers functionality (>= 8.0.12) (default: enabled)])],
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

# --enable-htools
HTOOLS=
AC_ARG_ENABLE([htools],
        [AS_HELP_STRING([--enable-htools],
        [enable use of htools (needs GHC and libraries, default: check)])],
        [],
        [enable_htools=check])

# --enable-htools-rapi
HTOOLS_RAPI=
AC_ARG_ENABLE([htools-rapi],
        [AS_HELP_STRING([--enable-htools-rapi],
        [enable use of RAPI in htools (needs curl, default: no)])],
        [],
        [enable_htools_rapi=no])

# --enable-htools
ENABLE_CONFD=
AC_ARG_ENABLE([confd],
  [AS_HELP_STRING([--enable-confd],
  [enable the ganeti-confd daemon (default: python, options haskell/python/no)])],
  [[case "$enableval" in
      no)
        enable_confd=False
        py_confd=False
        hs_confd=False
        ;;
      yes|python)
        enable_confd=True
        py_confd=True
        hs_confd=False
        ;;
      haskell)
        enable_confd=True
        py_confd=False
        hs_confd=True
        ;;
      *)
        echo "Invalid value for enable-confd '$enableval'"
        exit 1
        ;;
    esac
  ]],
  [enable_confd=True;py_confd=True;hs_confd=False])
AC_SUBST(ENABLE_CONFD, $enable_confd)
AC_SUBST(PY_CONFD, $py_confd)
AC_SUBST(HS_CONFD, $hs_confd)

AM_CONDITIONAL([WANT_CONFD], [test x$enable_confd = xTrue])
AM_CONDITIONAL([PY_CONFD], [test x$py_confd = xTrue])
AM_CONDITIONAL([HS_CONFD], [test x$hs_confd = xTrue])

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
AM_CONDITIONAL([HAS_PEP8], [test "$PEP8"])

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

if test "$enable_htools" != "no"; then

# Check for ghc
AC_ARG_VAR(GHC, [ghc path])
AC_PATH_PROG(GHC, [ghc], [])
if test -z "$GHC"; then
  if test "$enable_htools" != "check"; then
    AC_MSG_FAILURE([ghc not found, htools compilation will not possible])
  fi
fi

# Check for ghc-pkg
HTOOLS_MODULES=
AC_ARG_VAR(GHC_PKG, [ghc-pkg path])
AC_PATH_PROG(GHC_PKG, [ghc-pkg], [])
if test -z "$GHC_PKG"; then
  if test "$enable_htools" != "check"; then
    AC_MSG_FAILURE([ghc-pkg not found, htools compilation will not be possible])
  fi
else
  # check for modules
  AC_MSG_NOTICE([checking for required haskell modules])
  HTOOLS_NOCURL=-DNO_CURL
  if test "$enable_htools_rapi" != "no"; then
    AC_MSG_CHECKING([curl])
    GHC_PKG_CURL=$($GHC_PKG latest curl)
    if test -z "$GHC_PKG_CURL"; then
      if test "$enable_htools_rapi" = "check"; then
        AC_MSG_WARN(m4_normalize([The curl library not found, htools will be
                                  compiled without RAPI support]))
      else
        AC_MSG_FAILURE(m4_normalize([The curl library was not found, but it has
                                     been requested]))
      fi
    else
      HTOOLS_NOCURL=
    fi
    AC_MSG_RESULT($GHC_PKG_CURL)
  fi
  AC_SUBST(GHC_PKG_CURL)
  AC_SUBST(HTOOLS_NOCURL)
  AC_MSG_CHECKING([parallel])
  GHC_PKG_PARALLEL=$($GHC_PKG --simple-output list 'parallel-3.*')
  if test -n "$GHC_PKG_PARALLEL"
  then
    HTOOLS_PARALLEL3=-DPARALLEL3
  else
    GHC_PKG_PARALLEL=$($GHC_PKG --simple-output list 'parallel-2.*')
  fi
  if test -z "$GHC_PKG_PARALLEL"
  then
    GHC_PKG_PARALLEL=$($GHC_PKG --simple-output list 'parallel-1.*')
  fi
  AC_SUBST(GHC_PKG_PARALLEL)
  AC_SUBST(HTOOLS_PARALLEL3)
  AC_MSG_RESULT($GHC_PKG_PARALLEL)
  AC_MSG_CHECKING([json])
  GHC_PKG_JSON=$($GHC_PKG latest json)
  AC_MSG_RESULT($GHC_PKG_JSON)
  AC_MSG_CHECKING([network])
  GHC_PKG_NETWORK=$($GHC_PKG latest network)
  AC_MSG_RESULT($GHC_PKG_NETWORK)
  AC_MSG_CHECKING([QuickCheck 2.x])
  GHC_PKG_QUICKCHECK=$($GHC_PKG --simple-output list 'QuickCheck-2.*')
  AC_MSG_RESULT($GHC_PKG_QUICKCHECK)
  if test -z "$GHC_PKG_PARALLEL" || test -z "$GHC_PKG_JSON" || \
     test -z "$GHC_PKG_NETWORK"; then
    if test "$enable_htools" != "check"; then
      AC_MSG_FAILURE(m4_normalize([Required Haskell modules not found, htools
                                   compilation disabled]))
    fi
  else
    # we leave the other modules to be auto-selected
    HTOOLS_MODULES="-package $GHC_PKG_PARALLEL"
  fi
  if test -z "$GHC_PKG_QUICKCHECK"; then
     AC_MSG_WARN(m4_normalize([The QuickCheck 2.x module was not found,
                               you won't be able to run Haskell unittests]))
  fi
fi
AC_SUBST(HTOOLS_MODULES)
AC_SUBST(GHC_PKG_QUICKCHECK)

if test "$enable_htools" != "no"; then
  if test -z "$GHC" || test -z "$HTOOLS_MODULES"; then
    AC_MSG_WARN(m4_normalize([Haskell compiler/required libraries not found,
                              htools compilation disabled]))
  else
    HTOOLS=yes
  fi
fi
AC_SUBST(HTOOLS)

# Check for HsColour
HTOOLS_APIDOC=no
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
if test "$HADDOCK" && test "$HSCOLOUR"; then
  HTOOLS_APIDOC=yes
fi
AC_SUBST(HTOOLS_APIDOC)

# Check for hlint
HLINT=no
AC_ARG_VAR(HLINT, [hlint path])
AC_PATH_PROG(HLINT, [hlint], [])
if test -z "$HLINT"; then
  AC_MSG_WARN([hlint not found, checking code will not be possible])
fi

fi # end if enable_htools, define automake conditions

if test "$HTOOLS" != "yes" && test "$HS_CONFD" = "True"; then
   AC_MSG_ERROR(m4_normalize([cannot enable Haskell version of ganeti-confd if
                              htools support is not enabled]))
fi

AM_CONDITIONAL([WANT_HTOOLS], [test x$HTOOLS = xyes])
AM_CONDITIONAL([WANT_HTOOLSTESTS], [test "x$GHC_PKG_QUICKCHECK" != x])
AM_CONDITIONAL([WANT_HTOOLSAPIDOC], [test x$HTOOLS_APIDOC = xyes])
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
AM_PATH_PYTHON(2.4)

AC_PYTHON_MODULE(OpenSSL, t)
AC_PYTHON_MODULE(simplejson, t)
AC_PYTHON_MODULE(pyparsing, t)
AC_PYTHON_MODULE(pyinotify, t)
AC_PYTHON_MODULE(pycurl, t)
AC_PYTHON_MODULE(affinity)

# This is optional but then we've limited functionality
AC_PYTHON_MODULE(paramiko)
if test "$HAVE_PYMOD_PARAMIKO" = "no"; then
  AC_MSG_WARN(m4_normalize([You do not have Paramiko installed. While this is
                            optional you have to configure SSH and the node
                            daemon on the joining nodes yourself.]))
fi

AC_CONFIG_FILES([ Makefile ])

AC_OUTPUT
