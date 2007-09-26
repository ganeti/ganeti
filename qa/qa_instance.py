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


"""Instance related QA tests.

"""

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils

from qa_utils import AssertEqual, StartSSH


def _GetGenericAddParameters():
  return ['--os-size=%s' % qa_config.get('os-size'),
          '--swap-size=%s' % qa_config.get('swap-size'),
          '--memory=%s' % qa_config.get('mem')]


def _DiskTest(node, args):
  master = qa_config.GetMasterNode()

  instance = qa_config.AcquireInstance()
  try:
    cmd = (['gnt-instance', 'add',
            '--os-type=%s' % qa_config.get('os'),
            '--node=%s' % node['primary']] +
           _GetGenericAddParameters())
    if args:
      cmd += args
    cmd.append(instance['name'])

    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
    return instance
  except:
    qa_config.ReleaseInstance(instance)
    raise


def TestInstanceAddWithPlainDisk(node):
  """gnt-instance add -t plain"""
  return _DiskTest(node, ['--disk-template=plain'])


def TestInstanceAddWithLocalMirrorDisk(node):
  """gnt-instance add -t local_raid1"""
  return _DiskTest(node, ['--disk-template=local_raid1'])


def TestInstanceAddWithRemoteRaidDisk(node, node2):
  """gnt-instance add -t remote_raid1"""
  return _DiskTest(node,
                   ['--disk-template=remote_raid1',
                    '--secondary-node=%s' % node2['primary']])


def TestInstanceRemove(instance):
  """gnt-instance remove"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'remove', '-f', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  qa_config.ReleaseInstance(instance)


def TestInstanceStartup(instance):
  """gnt-instance startup"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'startup', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceShutdown(instance):
  """gnt-instance shutdown"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'shutdown', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceFailover(instance):
  """gnt-instance failover"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'failover', '--force', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceInfo(instance):
  """gnt-instance info"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-instance', 'info', instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestInstanceExport(instance, node):
  """gnt-backup export"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-backup', 'export', '-n', node['primary'], instance['name']]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

  return qa_utils.ResolveInstanceName(instance)


def TestInstanceImport(node, newinst, expnode, name):
  """gnt-backup import"""
  master = qa_config.GetMasterNode()

  cmd = (['gnt-backup', 'import',
          '--disk-template=plain',
          '--no-ip-check',
          '--src-node=%s' % expnode['primary'],
          '--src-dir=%s/%s' % (constants.EXPORT_DIR, name),
          '--node=%s' % node['primary']] +
         _GetGenericAddParameters())
  cmd.append(newinst['name'])
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)
