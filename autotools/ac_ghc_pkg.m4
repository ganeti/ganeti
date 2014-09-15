#####

# Copyright (C) 2012 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
