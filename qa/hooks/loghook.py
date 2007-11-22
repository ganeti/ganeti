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


"""QA hook to log all function calls.

"""

from ganeti import utils

import qa_utils
import qa_config

from qa_utils import AssertEqual, StartSSH


class LogHook:
  def __init__(self):
    file_name = qa_config.get('options', {}).get('hook-logfile', None)
    if file_name:
      self.log = open(file_name, "a+")
    else:
      self.log = None

  def __del__(self):
    if self.log:
      self.log.close()

  def run(self, ctx):
    if not self.log:
      return

    msg = "%s-%s" % (ctx.phase, ctx.name)
    if ctx.phase == 'post':
      msg += " success=%s" % ctx.success
    if ctx.args:
      msg += " %s" % repr(ctx.args)
    if ctx.kwargs:
      msg += " %s" % repr(ctx.kwargs)
    if ctx.phase == 'pre':
      self.log.write("---\n")
    self.log.write(msg)
    self.log.write("\n")
    self.log.flush()


hook = LogHook
