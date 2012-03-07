#!/bin/bash

# Copyright (C) 2012 Google Inc.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

# This is an offline testing script for most/all of the htools
# programs, checking basic command line functionality.

set -e

. $(dirname $0)/cli-tests-defs.sh

echo -n "Checking command line basic options "
for prog in $ALL_ROLES; do
  echo -n "."
  $prog --version >/dev/null
  $prog --help >/dev/null
  ! $prog --no-such-option 2>/dev/null
done
echo

echo All OK
