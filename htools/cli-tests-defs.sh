#

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

# This is an shell testing configuration fragment.

HBINARY=${HBINARY:-./htools/hpc-htools}

export TESTDATA_DIR=${TOP_SRCDIR:-.}/test/data/htools

hbal() {
  HTOOLS=hbal $HBINARY "$@"
}

hscan() {
  HTOOLS=hscan $HBINARY "$@"
}

hail() {
  HTOOLS=hail $HBINARY "$@"
}

hspace() {
  HTOOLS=hspace $HBINARY "$@"
}

hinfo() {
  HTOOLS=hinfo $HBINARY "$@"
}

hcheck() {
  HTOOLS=hinfo $HBINARY "$@"
}

ALL_ROLES="hbal hscan hail hspace hinfo hcheck"
