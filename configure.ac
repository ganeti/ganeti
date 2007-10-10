# Configure script for Ganeti
AC_PREREQ(2.59)
AC_INIT(ganeti, 1.2b2, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AC_CONFIG_SRCDIR(configure)
AM_INIT_AUTOMAKE([foreign tar-ustar])

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

# Check common programs
AC_PROG_INSTALL
AC_PROG_LN_S

# Check for Python
AM_PATH_PYTHON(2.4)

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
  scripts/Makefile
  test/Makefile
  tools/Makefile
])

AC_OUTPUT
