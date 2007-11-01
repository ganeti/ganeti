# Copyright (C) 2007 Google Inc.
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


from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils

from qa_utils import AssertEqual, StartSSH


def UploadKnownHostsFile(localpath):
  """Uploading known_hosts file.

  """
  master = qa_config.GetMasterNode()

  tmpfile = qa_utils.UploadFile(master['primary'], localpath)
  try:
    cmd = ['mv', tmpfile, constants.SSH_KNOWN_HOSTS_FILE]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
  except:
    cmd = ['rm', '-f', tmpfile]
    AssertEqual(StartSSH(master['primary'],
                utils.ShellQuoteArgs(cmd)).wait(), 0)
    raise
