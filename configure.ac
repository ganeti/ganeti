# Configure script for Ganeti

AC_PREREQ(2.59)
AC_INIT(ganeti, 1.2b2, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AM_INIT_AUTOMAKE([foreign tar-ustar dist-bzip2])

# Check common programs
AC_PROG_INSTALL

# Check for Python
AM_PATH_PYTHON(2.4)

# Check for docbook2man
found_docbook2man=
AC_CHECK_PROG(found_docbook2man, [docbook2man], [yes])
if test "$found_docbook2man" != "yes"
then
  AC_MSG_WARN([docbook2man not found.])
fi

AC_SUBST(PACKAGE_VERSION)

AC_CONFIG_FILES([Makefile man/Makefile doc/Makefile
  testing/Makefile tools/Makefile
  lib/Makefile scripts/Makefile daemons/Makefile
  doc/examples/Makefile lib/version.py])

AC_OUTPUT
