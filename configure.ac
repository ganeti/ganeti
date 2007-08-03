# Configure script for Ganeti

AC_PREREQ(2.59)
AC_INIT(ganeti, 1.2a, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AM_INIT_AUTOMAKE(foreign)

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

AC_CONFIG_FILES([Makefile man/Makefile docs/Makefile 
  testing/Makefile tools/Makefile
  lib/Makefile scripts/Makefile daemons/Makefile])
AC_OUTPUT
