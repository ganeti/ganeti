#####

# Copyright (C) 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

#####
#
# SYNOPSIS
#
#   AC_GHC_PKG_CHECK(modname, action_found, action_not_found, extended)
#
# DESCRIPTION
#
#   Checks for a Haskell (GHC) module. If found, execute the second
#   argument, if not found, the third one.
#
#   If the fourth argument is non-empty, then the check will be some
#   via 'ghc-pkg list' (which supports patterns), otherwise it will
#   use just 'ghc-pkg latest'.
#
#
#####

AC_DEFUN([AC_GHC_PKG_CHECK],[
    if test -z $GHC_PKG; then
        AC_MSG_ERROR([GHC_PKG not defined])
    fi
    AC_MSG_CHECKING([haskell library $1])
    if test -n "$4"; then
      GHC_PKG_RESULT=$($GHC_PKG --simple-output list '$1'|tail -n1)
    else
      GHC_PKG_RESULT=$($GHC_PKG latest '$1' 2>/dev/null)
    fi
    if test -n "$GHC_PKG_RESULT"; then
      AC_MSG_RESULT($GHC_PKG_RESULT)
      $2
    else
      AC_MSG_RESULT([no])
      $3
    fi
])

#####
#
# SYNOPSIS
#
#   AC_GHC_PKG_REQUIRE(modname, extended)
#
# DESCRIPTION
#
#   Checks for a Haskell (GHC) module, and abort if not found. If the
#   second argument is non-empty, then the check will be some via
#   'ghc-pkg list' (which supports patterns), otherwise it will use
#   just 'ghc-pkg latest'.
#
#
#####

AC_DEFUN([AC_GHC_PKG_REQUIRE],[
    AC_GHC_PKG_CHECK($1, [],
                     [AC_MSG_FAILURE([Required Haskell module $1 not found])],
                     $2)
])
