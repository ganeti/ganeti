# Configure script for Ganeti
m4_define([gnt_version_major], [2])
m4_define([gnt_version_minor], [1])
m4_define([gnt_version_revision], [0])
m4_define([gnt_version_suffix], [~rc5])
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
  [file_storage_dir="$withval"],
  [file_storage_dir="/srv/ganeti/file-storage"])
AC_SUBST(FILE_STORAGE_DIR, $file_storage_dir)

# --with-kvm-path=...
AC_ARG_WITH([kvm-path],
  [AS_HELP_STRING([--with-kvm-path=PATH],
    [absolute path to the kvm binary]
    [ (default is /usr/bin/kvm)]
  )],
  [kvm_path="$withval"],
  [kvm_path="/usr/bin/kvm"])
AC_SUBST(KVM_PATH, $kvm_path)

# ---with-lvm-stripecount=...
AC_ARG_WITH([lvm-stripecount],
  [AS_HELP_STRING([--with-lvm-stripecount=NUM],
    [the number of stripes to use for LVM volumes]
    [ (default is 1)]
  )],
  [lvm_stripecount="$withval"],
  [lvm_stripecount="1"])
AC_SUBST(LVM_STRIPECOUNT, $lvm_stripecount)

# Check common programs
AC_PROG_INSTALL
AC_PROG_LN_S

# Check for docbook programs
AC_ARG_VAR(DOCBOOK2MAN, [docbook2man path])
AC_PATH_PROG(DOCBOOK2MAN, [docbook2man], [])
if test -z "$DOCBOOK2MAN"
then
  AC_MSG_WARN([docbook2man not found, man pages rebuild will not be possible])
fi

AC_ARG_VAR(DOCBOOK2HTML, [docbook2html path])
AC_PATH_PROG(DOCBOOK2HTML, [docbook2html], [])
if test -z "$DOCBOOK2HTML"
then
  AC_MSG_WARN([docbook2html not found, man pages rebuild will not be possible])
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

# Check for Python
AM_PATH_PYTHON(2.4)

AC_PYTHON_MODULE(OpenSSL, t)
AC_PYTHON_MODULE(simplejson, t)
AC_PYTHON_MODULE(pyparsing, t)
AC_PYTHON_MODULE(pyinotify, t)

AC_CONFIG_FILES([ Makefile ])

AC_OUTPUT
