# Configure script for Ganeti
m4_define([gnt_version_major], [2])
m4_define([gnt_version_minor], [4])
m4_define([gnt_version_revision], [1])
m4_define([gnt_version_suffix], [])
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
    [DomU kernel image for Xen hypervisor (default is /boot/vmlinuz-2.6-xenU)]
  )],
  [xen_kernel="$withval"],
  [xen_kernel="/boot/vmlinuz-2.6-xenU"])
AC_SUBST(XEN_KERNEL, $xen_kernel)

# --with-xen-initrd=...
AC_ARG_WITH([xen-initrd],
  [AS_HELP_STRING([--with-xen-initrd=PATH],
    [DomU initrd image for Xen hypervisor (default is /boot/initrd-2.6-xenU)]
  )],
  [xen_initrd="$withval"],
  [xen_initrd="/boot/initrd-2.6-xenU"])
AC_SUBST(XEN_INITRD, $xen_initrd)

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
  [[file_storage_dir="/srv/ganeti/file-storage"; enable_file_storage="True"]])
AC_SUBST(FILE_STORAGE_DIR, $file_storage_dir)
AC_SUBST(ENABLE_FILE_STORAGE, $enable_file_storage)

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
    [the number of stripes to use for LVM volumes]
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
   group_daemons="${withval}daemons";],
  [group_rapi="root";
   group_admin="root";
   group_confd="root";
   group_masterd="root";
   group_daemons="root"])
AC_SUBST(RAPI_GROUP, $group_rapi)
AC_SUBST(ADMIN_GROUP, $group_admin)
AC_SUBST(CONFD_GROUP, $group_confd)
AC_SUBST(MASTERD_GROUP, $group_masterd)
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
    [enable the DRBD barrier functionality (>= 8.0.12) (default: enabled)])],
  [[if test "$enableval" != no; then
      DRBD_BARRIERS=True
    else
      DRBD_BARRIERS=False
    fi
  ]],
  [DRBD_BARRIERS=True])
AC_SUBST(DRBD_BARRIERS, $DRBD_BARRIERS)

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

# --with-disk-separator=...
AC_ARG_WITH([disk-separator],
  [AS_HELP_STRING([--with-disk-separator=STRING],
    [Disk index separator, useful if the default of ':' is handled specially by the hypervisor]
  )],
  [disk_separator="$withval"],
  [disk_separator=":"])
AC_SUBST(DISK_SEPARATOR, $disk_separator)

# Check common programs
AC_PROG_INSTALL
AC_PROG_LN_S

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
  AC_MSG_WARN([sphinx-build not found, documentation rebuild will not be possible])
fi

# Check for graphviz (dot)
AC_ARG_VAR(DOT, [dot path])
AC_PATH_PROG(DOT, [dot], [])
if test -z "$DOT"
then
  AC_MSG_WARN([dot (from the graphviz suite) not found, documentation rebuild not possible])
fi

# Check for pylint
AC_ARG_VAR(PYLINT, [pylint path])
AC_PATH_PROG(PYLINT, [pylint], [])
if test -z "$PYLINT"
then
  AC_MSG_WARN([pylint not found, checking code will not be possible])
fi

# Check for socat
AC_ARG_VAR(SOCAT, [socat path])
AC_PATH_PROG(SOCAT, [socat], [])
if test -z "$SOCAT"
then
  AC_MSG_ERROR([socat not found])
fi

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
  AC_MSG_WARN([man doesn't support --warnings, man pages checks
               will not be possible])
fi

AC_SUBST(MAN_HAS_WARNINGS)

# Check for Python
AM_PATH_PYTHON(2.4)

AC_PYTHON_MODULE(OpenSSL, t)
AC_PYTHON_MODULE(simplejson, t)
AC_PYTHON_MODULE(pyparsing, t)
AC_PYTHON_MODULE(pyinotify, t)
AC_PYTHON_MODULE(pycurl, t)

# This is optional but then we've limited functionality
AC_PYTHON_MODULE(paramiko)
if test "$HAVE_PYMOD_PARAMIKO" = "no"; then
  AC_MSG_WARN([You do not have paramiko installed. While this is optional you
               have to setup SSH and noded on the joining nodes yourself.])
fi

AC_CONFIG_FILES([ Makefile ])

AC_OUTPUT
