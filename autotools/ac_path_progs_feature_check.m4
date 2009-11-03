# Backport of AC_PATH_PROGS_FEATURE_CHECK from autoconf 2.64
# (available since version 2.62)
#
# The following code comes from lib/autoconf/programs.m4,
# in the autoconf 2.64 source code. Its copyright is:

#
# Copyright (C) 1992, 1993, 1994, 1995, 1996, 1998, 1999, 2000, 2001,
# 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009 Free Software
# Foundation, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

# As a special exception, the Free Software Foundation gives unlimited
# permission to copy, distribute and modify the configure scripts that
# are the output of Autoconf.  You need not follow the terms of the GNU
# General Public License when using or distributing such scripts, even
# though portions of the text of Autoconf appear in them.  The GNU
# General Public License (GPL) does govern all other use of the material
# that constitutes the Autoconf program.
#
# Certain portions of the Autoconf source text are designed to be copied
# (in certain cases, depending on the input) into the output of
# Autoconf.  We call these the "data" portions.  The rest of the Autoconf
# source text consists of comments plus executable code that decides which
# of the data portions to output in any given case.  We call these
# comments and executable code the "non-data" portions.  Autoconf never
# copies any of the non-data portions into its output.
#
# This special exception to the GPL applies to versions of Autoconf
# released by the Free Software Foundation.  When you make and
# distribute a modified version of Autoconf, you may extend this special
# exception to the GPL to apply to your modified version as well, *unless*
# your modified version has the potential to copy into its output some
# of the text that was the non-data portion of the version that you started
# with.  (In other words, unless your change moves or copies text from
# the non-data portions to the data portions.)  If your modification has
# such potential, you must delete any notice of this special exception
# to the GPL from your modified version.
#
# Written by David MacKenzie, with help from
# Franc,ois Pinard, Karl Berry, Richard Pixley, Ian Lance Taylor,
# Roland McGrath, Noah Friedman, david d zuhn, and many others.
#
# The code was modified by ultrotter@google.com, adding surrounding ifdefs.

m4_ifdef([AC_PATH_PROGS_FEATURE_CHECK],,
  m4_define([AC_PATH_PROGS_FEATURE_CHECK],
  [_$0([$1], [$2], [$3], m4_default([$4], [:]), [$5])dnl
  ]))

m4_ifdef([_AC_PATH_PROGS_FEATURE_CHECK],,
  m4_define([_AC_PATH_PROGS_FEATURE_CHECK],
  [if test -z "$$1"; then
    ac_path_$1_found=false
    # Loop through the user's path and test for each of PROGNAME-LIST
    _AS_PATH_WALK([$5],
    [for ac_prog in $2; do
      for ac_exec_ext in '' $ac_executable_extensions; do
        ac_path_$1="$as_dir/$ac_prog$ac_exec_ext"
        AS_EXECUTABLE_P(["$ac_path_$1"]) || continue
  $3
        $ac_path_$1_found && break 3
      done
    done])dnl
    if test -z "$ac_cv_path_$1"; then
      m4_default([$4],
        [AC_MSG_ERROR([no acceptable m4_bpatsubst([$2], [ .*]) could be dnl
  found in m4_default([$5], [\$PATH])])])
    fi
  else
    ac_cv_path_$1=$$1
  fi
  ]))

