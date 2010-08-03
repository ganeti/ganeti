#
#

# Copyright (C) 2007, 2010 Google Inc.
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


"""Cluster related QA tests.

"""

import tempfile

from ganeti import constants
from ganeti import utils

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertEqual, AssertNotEqual, StartSSH


def _RemoveFileFromAllNodes(filename):
  """Removes a file from all nodes.

  """
  for node in qa_config.get('nodes'):
    cmd = ['rm', '-f', filename]
    AssertEqual(StartSSH(node['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)


def _CheckFileOnAllNodes(filename, content):
  """Verifies the content of the given file on all nodes.

  """
  cmd = utils.ShellQuoteArgs(["cat", filename])
  for node in qa_config.get('nodes'):
    AssertEqual(qa_utils.GetCommandOutput(node['primary'], cmd),
                content)


def TestClusterInit(rapi_user, rapi_secret):
  """gnt-cluster init"""
  master = qa_config.GetMasterNode()

  # First create the RAPI credentials
  fh = tempfile.NamedTemporaryFile()
  try:
    fh.write("%s %s write\n" % (rapi_user, rapi_secret))
    fh.flush()

    tmpru = qa_utils.UploadFile(master["primary"], fh.name)
    try:
      cmd = ["mv", tmpru, constants.RAPI_USERS_FILE]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)
    finally:
      cmd = ["rm", "-f", tmpru]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)
  finally:
    fh.close()

  # Initialize cluster
  cmd = ['gnt-cluster', 'init']

  cmd.append("--primary-ip-version=%d" %
             qa_config.get("primary_ip_version", 4))

  if master.get('secondary', None):
    cmd.append('--secondary-ip=%s' % master['secondary'])

  bridge = qa_config.get('bridge', None)
  if bridge:
    cmd.append('--bridge=%s' % bridge)
    cmd.append('--master-netdev=%s' % bridge)

  htype = qa_config.get('enabled-hypervisors', None)
  if htype:
    cmd.append('--enabled-hypervisors=%s' % htype)

  cmd.append(qa_config.get('name'))

  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestClusterRename():
  """gnt-cluster rename"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-cluster', 'rename', '-f']

  original_name = qa_config.get('name')
  rename_target = qa_config.get('rename', None)
  if rename_target is None:
    print qa_utils.FormatError('"rename" entry is missing')
    return

  cmd_1 = cmd + [rename_target]
  cmd_2 = cmd + [original_name]

  cmd_verify = ['gnt-cluster', 'verify']

  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd_1)).wait(), 0)

  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd_verify)).wait(), 0)

  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd_2)).wait(), 0)

  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd_verify)).wait(), 0)


def TestClusterVerify():
  """gnt-cluster verify"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-cluster', 'verify']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

def TestClusterReservedLvs():
  """gnt-cluster reserved lvs"""
  master = qa_config.GetMasterNode()
  CVERIFY = ['gnt-cluster', 'verify']
  for rcode, cmd in [
    (0, CVERIFY),
    (0, ['gnt-cluster', 'modify', '--reserved-lvs', '']),
    (0, ['lvcreate', '-L1G', '-nqa-test', 'xenvg']),
    (1, CVERIFY),
    (0, ['gnt-cluster', 'modify', '--reserved-lvs', 'qa-test,other-test']),
    (0, CVERIFY),
    (0, ['gnt-cluster', 'modify', '--reserved-lvs', 'qa-.*']),
    (0, CVERIFY),
    (0, ['gnt-cluster', 'modify', '--reserved-lvs', '']),
    (1, CVERIFY),
    (0, ['lvremove', '-f', 'xenvg/qa-test']),
    (0, CVERIFY),
    ]:
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), rcode)


def TestClusterInfo():
  """gnt-cluster info"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-cluster', 'info']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestClusterGetmaster():
  """gnt-cluster getmaster"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-cluster', 'getmaster']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestClusterVersion():
  """gnt-cluster version"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-cluster', 'version']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestClusterRenewCrypto():
  """gnt-cluster renew-crypto"""
  master = qa_config.GetMasterNode()

  # Conflicting options
  cmd = ["gnt-cluster", "renew-crypto", "--force",
         "--new-cluster-certificate", "--new-confd-hmac-key"]
  conflicting = [
    ["--new-rapi-certificate", "--rapi-certificate=/dev/null"],
    ["--new-cluster-domain-secret", "--cluster-domain-secret=/dev/null"],
    ]
  for i in conflicting:
    AssertNotEqual(StartSSH(master["primary"],
                            utils.ShellQuoteArgs(cmd + i)).wait(), 0)

  # Invalid RAPI certificate
  cmd = ["gnt-cluster", "renew-crypto", "--force",
         "--rapi-certificate=/dev/null"]
  AssertNotEqual(StartSSH(master["primary"],
                          utils.ShellQuoteArgs(cmd)).wait(), 0)

  rapi_cert_backup = qa_utils.BackupFile(master["primary"],
                                         constants.RAPI_CERT_FILE)
  try:
    # Custom RAPI certificate
    fh = tempfile.NamedTemporaryFile()

    # Ensure certificate doesn't cause "gnt-cluster verify" to complain
    validity = constants.SSL_CERT_EXPIRATION_WARN * 3

    utils.GenerateSelfSignedSslCert(fh.name, validity=validity)

    tmpcert = qa_utils.UploadFile(master["primary"], fh.name)
    try:
      cmd = ["gnt-cluster", "renew-crypto", "--force",
             "--rapi-certificate=%s" % tmpcert]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)
    finally:
      cmd = ["rm", "-f", tmpcert]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)

    # Custom cluster domain secret
    cds_fh = tempfile.NamedTemporaryFile()
    cds_fh.write(utils.GenerateSecret())
    cds_fh.write("\n")
    cds_fh.flush()

    tmpcds = qa_utils.UploadFile(master["primary"], cds_fh.name)
    try:
      cmd = ["gnt-cluster", "renew-crypto", "--force",
             "--cluster-domain-secret=%s" % tmpcds]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)
    finally:
      cmd = ["rm", "-f", tmpcds]
      AssertEqual(StartSSH(master["primary"],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)

    # Normal case
    cmd = ["gnt-cluster", "renew-crypto", "--force",
           "--new-cluster-certificate", "--new-confd-hmac-key",
           "--new-rapi-certificate", "--new-cluster-domain-secret"]
    AssertEqual(StartSSH(master["primary"],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

    # Restore RAPI certificate
    cmd = ["gnt-cluster", "renew-crypto", "--force",
           "--rapi-certificate=%s" % rapi_cert_backup]
    AssertEqual(StartSSH(master["primary"],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
  finally:
    cmd = ["rm", "-f", rapi_cert_backup]
    AssertEqual(StartSSH(master["primary"],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)


def TestClusterBurnin():
  """Burnin"""
  master = qa_config.GetMasterNode()

  options = qa_config.get('options', {})
  disk_template = options.get('burnin-disk-template', 'drbd')
  parallel = options.get('burnin-in-parallel', False)
  check_inst = options.get('burnin-check-instances', False)
  do_rename = options.get('burnin-rename', '')
  do_reboot = options.get('burnin-reboot', True)
  reboot_types = options.get("reboot-types", constants.REBOOT_TYPES)

  # Get as many instances as we need
  instances = []
  try:
    try:
      num = qa_config.get('options', {}).get('burnin-instances', 1)
      for _ in range(0, num):
        instances.append(qa_config.AcquireInstance())
    except qa_error.OutOfInstancesError:
      print "Not enough instances, continuing anyway."

    if len(instances) < 1:
      raise qa_error.Error("Burnin needs at least one instance")

    script = qa_utils.UploadFile(master['primary'], '../tools/burnin')
    try:
      # Run burnin
      cmd = [script,
             '--os=%s' % qa_config.get('os'),
             '--disk-size=%s' % ",".join(qa_config.get('disk')),
             '--disk-growth=%s' % ",".join(qa_config.get('disk-growth')),
             '--disk-template=%s' % disk_template]
      if parallel:
        cmd.append('--parallel')
        cmd.append('--early-release')
      if check_inst:
        cmd.append('--http-check')
      if do_rename:
        cmd.append('--rename=%s' % do_rename)
      if not do_reboot:
        cmd.append('--no-reboot')
      else:
        cmd.append('--reboot-types=%s' % ",".join(reboot_types))
      cmd += [inst['name'] for inst in instances]
      AssertEqual(StartSSH(master['primary'],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)
    finally:
      cmd = ['rm', '-f', script]
      AssertEqual(StartSSH(master['primary'],
                           utils.ShellQuoteArgs(cmd)).wait(), 0)
  finally:
    for inst in instances:
      qa_config.ReleaseInstance(inst)


def TestClusterMasterFailover():
  """gnt-cluster master-failover"""
  master = qa_config.GetMasterNode()

  failovermaster = qa_config.AcquireNode(exclude=master)
  try:
    cmd = ['gnt-cluster', 'master-failover']
    AssertEqual(StartSSH(failovermaster['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)

    cmd = ['gnt-cluster', 'master-failover']
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
  finally:
    qa_config.ReleaseNode(failovermaster)


def TestClusterCopyfile():
  """gnt-cluster copyfile"""
  master = qa_config.GetMasterNode()

  uniqueid = utils.NewUUID()

  # Create temporary file
  f = tempfile.NamedTemporaryFile()
  f.write(uniqueid)
  f.flush()
  f.seek(0)

  # Upload file to master node
  testname = qa_utils.UploadFile(master['primary'], f.name)
  try:
    # Copy file to all nodes
    cmd = ['gnt-cluster', 'copyfile', testname]
    AssertEqual(StartSSH(master['primary'],
                         utils.ShellQuoteArgs(cmd)).wait(), 0)
    _CheckFileOnAllNodes(testname, uniqueid)
  finally:
    _RemoveFileFromAllNodes(testname)


def TestClusterCommand():
  """gnt-cluster command"""
  master = qa_config.GetMasterNode()

  uniqueid = utils.NewUUID()
  rfile = "/tmp/gnt%s" % utils.NewUUID()
  rcmd = utils.ShellQuoteArgs(['echo', '-n', uniqueid])
  cmd = utils.ShellQuoteArgs(['gnt-cluster', 'command',
                              "%s >%s" % (rcmd, rfile)])

  try:
    AssertEqual(StartSSH(master['primary'], cmd).wait(), 0)
    _CheckFileOnAllNodes(rfile, uniqueid)
  finally:
    _RemoveFileFromAllNodes(rfile)


def TestClusterDestroy():
  """gnt-cluster destroy"""
  master = qa_config.GetMasterNode()

  cmd = ['gnt-cluster', 'destroy', '--yes-do-it']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)
