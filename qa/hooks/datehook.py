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


"""Example QA hook.

"""

from ganeti import utils

import qa_utils
import qa_config

from qa_utils import AssertEqual, StartSSH


class DateHook:
  def run(self, ctx):
    if ctx.name == 'cluster-init' and ctx.phase == 'pre':
      self._CallDate(ctx)

  def _CallDate(self, ctx):
    for node in qa_config.get('nodes'):
      cmd = ['date']
      AssertEqual(StartSSH(node['primary'],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)

hook = DateHook
