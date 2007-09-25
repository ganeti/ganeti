# Configure script for Ganeti

AC_PREREQ(2.59)
AC_INIT(ganeti, 1.2b2, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AM_INIT_AUTOMAKE([foreign tar-ustar])

# --with-ssh-initscript=...
AC_ARG_WITH([ssh-initscript],
  [AS_HELP_STRING([--with-ssh-initscript],
    [SSH init script to use (default is /etc/init.d/ssh)]
  )],
  [ssh_initd_script="$withval"],
  [ssh_initd_script="/etc/init.d/ssh"])
AC_SUBST(SSH_INITD_SCRIPT, $ssh_initd_script)

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
