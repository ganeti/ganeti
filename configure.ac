# Configure script for Ganeti
m4_define([gnt_version_major], [1])
m4_define([gnt_version_minor], [2])
m4_define([gnt_version_revision], [3])
m4_define([gnt_version_suffix], [])
m4_define([gnt_version_full],
          m4_format([%d.%d.%d%s],
                    gnt_version_major, gnt_version_minor,
                    gnt_version_revision, gnt_version_suffix))

AC_PREREQ(2.59)
AC_INIT(ganeti, gnt_version_full, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AC_CONFIG_SRCDIR(configure)
AM_INIT_AUTOMAKE([foreign tar-ustar])

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

# Check common programs
AC_PROG_INSTALL
AC_PROG_LN_S

# Check for Python
AM_PATH_PYTHON(2.4)

AC_PYTHON_MODULE(twisted.internet, t)
AC_PYTHON_MODULE(twisted.cred, t)
AC_PYTHON_MODULE(twisted.spread, t)
AC_PYTHON_MODULE(OpenSSL, t)
AC_PYTHON_MODULE(simplejson, t)
AC_PYTHON_MODULE(pyparsing, t)

# Check for docbook2man
found_docbook2man=
AC_CHECK_PROG(found_docbook2man, [docbook2man], [yes])
if test "$found_docbook2man" != "yes"
then
  AC_MSG_WARN([docbook2man not found.])
fi

AC_CONFIG_FILES([
  Makefile
  daemons/Makefile
  doc/Makefile
  doc/examples/Makefile
  lib/Makefile
  man/Makefile
  qa/Makefile
  qa/hooks/Makefile
  scripts/Makefile
  test/Makefile
  tools/Makefile
])

AC_OUTPUT
