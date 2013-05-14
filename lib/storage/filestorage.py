#
#

# Copyright (C) 2013 Google Inc.
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


"""File storage functions.

"""

from ganeti import errors
from ganeti import utils

DF_M_UNIT = 'M'
DF_MIN_NUM_COLS = 4
DF_NUM_LINES = 2


def _ParseDfResult(dfresult):
  """Parses the output of the call of the 'df' tool.

     @type dfresult: string
     @param dfresult: output of the 'df' call
     @return: tuple (size, free) of the total and free disk space in MebiBytes
  """
  df_lines = dfresult.splitlines()
  if len(df_lines) != DF_NUM_LINES:
    raise errors.CommandError("'df' output has wrong number of lines: %s" %
                              len(df_lines))
  df_values = df_lines[1].strip().split()
  if len(df_values) < DF_MIN_NUM_COLS:
    raise errors.CommandError("'df' output does not have enough columns: %s" %
                              len(df_values))
  size_str = df_values[1]
  if size_str[-1] != DF_M_UNIT:
    raise errors.CommandError("'df': 'size' not given in Mebibytes.")
  free_str = df_values[3]
  if free_str[-1] != DF_M_UNIT:
    raise errors.CommandError("'df': 'free' not given in Mebibytes.")
  size = int(size_str[:-1])
  free = int(free_str[:-1])
  return (size, free)


def GetSpaceInfo(path, _parsefn=_ParseDfResult):
  """Retrieves the free and total space of the device where the file is
     located.

     @type path: string
     @param path: Path of the file whose embracing device's capacity is
       reported.
     @type _parsefn: function
     @param _parsefn: Function that parses the output of the 'df' command;
       given as parameter to make this code more testable.
     @return: a dictionary containing 'vg_size' and 'vg_free'
  """
  cmd = ['df', '-BM', path]
  result = utils.RunCmd(cmd)
  if result.failed:
    raise errors.CommandError("Failed to run 'df' command: %s - %s" %
                              (result.fail_reason, result.output))
  (size, free) = _parsefn(result.stdout)
  return {"vg_size": size, "vg_free": free}
