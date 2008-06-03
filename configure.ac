# Configure script for Ganeti
AC_PREREQ(2.59)
AC_INIT(ganeti, 1.2.4~rc1, ganeti@googlegroups.com)
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

# --enable-rapi
AC_ARG_ENABLE([rapi],
  [AS_HELP_STRING([--enable-rapi],
    [Whether to enable remote API daemon]
  )])
if test "$enable_rapi" = "yes"
then
  enable_rapi_py=True
else
  enable_rapi=no
  enable_rapi_py=False
fi
AC_SUBST(PY_ENABLE_RAPI, $enable_rapi_py)


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
  devel/Makefile
  doc/Makefile
  doc/examples/Makefile
  lib/Makefile
  lib/rapi/Makefile
  man/Makefile
  qa/Makefile
  qa/hooks/Makefile
  scripts/Makefile
  test/Makefile
  tools/Makefile
])

AC_OUTPUT
