#
#

# Copyright (C) 2007, 2010, 2011, 2012, 2013 Google Inc.
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

import re
import tempfile
import os.path

from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import pathutils

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertEqual, AssertCommand, GetCommandOutput


# Prefix for LVM volumes created by QA code during tests
_QA_LV_PREFIX = "qa-"

#: cluster verify command
_CLUSTER_VERIFY = ["gnt-cluster", "verify"]


def _RemoveFileFromAllNodes(filename):
  """Removes a file from all nodes.

  """
  for node in qa_config.get("nodes"):
    AssertCommand(["rm", "-f", filename], node=node)


def _CheckFileOnAllNodes(filename, content):
  """Verifies the content of the given file on all nodes.

  """
  cmd = utils.ShellQuoteArgs(["cat", filename])
  for node in qa_config.get("nodes"):
    AssertEqual(qa_utils.GetCommandOutput(node.primary, cmd), content)


# "gnt-cluster info" fields
_CIFIELD_RE = re.compile(r"^[-\s]*(?P<field>[^\s:]+):\s*(?P<value>\S.*)$")


def _GetBoolClusterField(field):
  """Get the Boolean value of a cluster field.

  This function currently assumes that the field name is unique in the cluster
  configuration. An assertion checks this assumption.

  @type field: string
  @param field: Name of the field
  @rtype: bool
  @return: The effective value of the field

  """
  master = qa_config.GetMasterNode()
  infocmd = "gnt-cluster info"
  info_out = qa_utils.GetCommandOutput(master.primary, infocmd)
  ret = None
  for l in info_out.splitlines():
    m = _CIFIELD_RE.match(l)
    # FIXME: There should be a way to specify a field through a hierarchy
    if m and m.group("field") == field:
      # Make sure that ignoring the hierarchy doesn't cause a double match
      assert ret is None
      ret = (m.group("value").lower() == "true")
  if ret is not None:
    return ret
  raise qa_error.Error("Field not found in cluster configuration: %s" % field)


# Cluster-verify errors (date, "ERROR", then error code)
_CVERROR_RE = re.compile(r"^[\w\s:]+\s+- ERROR:([A-Z0-9_-]+):")


def _GetCVErrorCodes(cvout):
  ret = set()
  for l in cvout.splitlines():
    m = _CVERROR_RE.match(l)
    if m:
      ecode = m.group(1)
      ret.add(ecode)
  return ret


def AssertClusterVerify(fail=False, errors=None):
  """Run cluster-verify and check the result

  @type fail: bool
  @param fail: if cluster-verify is expected to fail instead of succeeding
  @type errors: list of tuples
  @param errors: List of CV_XXX errors that are expected; if specified, all the
      errors listed must appear in cluster-verify output. A non-empty value
      implies C{fail=True}.

  """
  cvcmd = "gnt-cluster verify"
  mnode = qa_config.GetMasterNode()
  if errors:
    cvout = GetCommandOutput(mnode.primary, cvcmd + " --error-codes",
                             fail=True)
    actual = _GetCVErrorCodes(cvout)
    expected = compat.UniqueFrozenset(e for (_, e, _) in errors)
    if not actual.issuperset(expected):
      missing = expected.difference(actual)
      raise qa_error.Error("Cluster-verify didn't return these expected"
                           " errors: %s" % utils.CommaJoin(missing))
  else:
    AssertCommand(cvcmd, fail=fail, node=mnode)


# data for testing failures due to bad keys/values for disk parameters
_FAIL_PARAMS = ["nonexistent:resync-rate=1",
                "drbd:nonexistent=1",
                "drbd:resync-rate=invalid",
                ]


def TestClusterInitDisk():
  """gnt-cluster init -D"""
  name = qa_config.get("name")
  for param in _FAIL_PARAMS:
    AssertCommand(["gnt-cluster", "init", "-D", param, name], fail=True)


def TestClusterInit(rapi_user, rapi_secret):
  """gnt-cluster init"""
  master = qa_config.GetMasterNode()

  rapi_users_path = qa_utils.MakeNodePath(master, pathutils.RAPI_USERS_FILE)
  rapi_dir = os.path.dirname(rapi_users_path)

  # First create the RAPI credentials
  fh = tempfile.NamedTemporaryFile()
  try:
    fh.write("%s %s write\n" % (rapi_user, rapi_secret))
    fh.flush()

    tmpru = qa_utils.UploadFile(master.primary, fh.name)
    try:
      AssertCommand(["mkdir", "-p", rapi_dir])
      AssertCommand(["mv", tmpru, rapi_users_path])
    finally:
      AssertCommand(["rm", "-f", tmpru])
  finally:
    fh.close()

  # Initialize cluster
  cmd = [
    "gnt-cluster", "init",
    "--primary-ip-version=%d" % qa_config.get("primary_ip_version", 4),
    "--enabled-hypervisors=%s" % ",".join(qa_config.GetEnabledHypervisors()),
    ]

  for spec_type in ("mem-size", "disk-size", "disk-count", "cpu-count",
                    "nic-count"):
    for spec_val in ("min", "max", "std"):
      spec = qa_config.get("ispec_%s_%s" %
                           (spec_type.replace("-", "_"), spec_val), None)
      if spec:
        cmd.append("--specs-%s=%s=%d" % (spec_type, spec_val, spec))

  if master.secondary:
    cmd.append("--secondary-ip=%s" % master.secondary)

  vgname = qa_config.get("vg-name", None)
  if vgname:
    cmd.append("--vg-name=%s" % vgname)

  master_netdev = qa_config.get("master-netdev", None)
  if master_netdev:
    cmd.append("--master-netdev=%s" % master_netdev)

  nicparams = qa_config.get("default-nicparams", None)
  if nicparams:
    cmd.append("--nic-parameters=%s" %
               ",".join(utils.FormatKeyValue(nicparams)))

  # Cluster value of the exclusive-storage node parameter
  e_s = qa_config.get("exclusive-storage")
  if e_s is not None:
    cmd.extend(["--node-parameters", "exclusive_storage=%s" % e_s])
  else:
    e_s = False
  qa_config.SetExclusiveStorage(e_s)

  extra_args = qa_config.get("cluster-init-args")
  if extra_args:
    cmd.extend(extra_args)

  cmd.append(qa_config.get("name"))

  AssertCommand(cmd)

  cmd = ["gnt-cluster", "modify"]

  # hypervisor parameter modifications
  hvp = qa_config.get("hypervisor-parameters", {})
  for k, v in hvp.items():
    cmd.extend(["-H", "%s:%s" % (k, v)])
  # backend parameter modifications
  bep = qa_config.get("backend-parameters", "")
  if bep:
    cmd.extend(["-B", bep])

  if len(cmd) > 2:
    AssertCommand(cmd)

  # OS parameters
  osp = qa_config.get("os-parameters", {})
  for k, v in osp.items():
    AssertCommand(["gnt-os", "modify", "-O", v, k])

  # OS hypervisor parameters
  os_hvp = qa_config.get("os-hvp", {})
  for os_name in os_hvp:
    for hv, hvp in os_hvp[os_name].items():
      AssertCommand(["gnt-os", "modify", "-H", "%s:%s" % (hv, hvp), os_name])


def TestClusterRename():
  """gnt-cluster rename"""
  cmd = ["gnt-cluster", "rename", "-f"]

  original_name = qa_config.get("name")
  rename_target = qa_config.get("rename", None)
  if rename_target is None:
    print qa_utils.FormatError('"rename" entry is missing')
    return

  for data in [
    cmd + [rename_target],
    _CLUSTER_VERIFY,
    cmd + [original_name],
    _CLUSTER_VERIFY,
    ]:
    AssertCommand(data)


def TestClusterOob():
  """out-of-band framework"""
  oob_path_exists = "/tmp/ganeti-qa-oob-does-exist-%s" % utils.NewUUID()

  AssertCommand(_CLUSTER_VERIFY)
  AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                 "oob_program=/tmp/ganeti-qa-oob-does-not-exist-%s" %
                 utils.NewUUID()])

  AssertCommand(_CLUSTER_VERIFY, fail=True)

  AssertCommand(["touch", oob_path_exists])
  AssertCommand(["chmod", "0400", oob_path_exists])
  AssertCommand(["gnt-cluster", "copyfile", oob_path_exists])

  try:
    AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                   "oob_program=%s" % oob_path_exists])

    AssertCommand(_CLUSTER_VERIFY, fail=True)

    AssertCommand(["chmod", "0500", oob_path_exists])
    AssertCommand(["gnt-cluster", "copyfile", oob_path_exists])

    AssertCommand(_CLUSTER_VERIFY)
  finally:
    AssertCommand(["gnt-cluster", "command", "rm", oob_path_exists])

  AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                 "oob_program="])


def TestClusterEpo():
  """gnt-cluster epo"""
  master = qa_config.GetMasterNode()

  # Assert that OOB is unavailable for all nodes
  result_output = GetCommandOutput(master.primary,
                                   "gnt-node list --verbose --no-headers -o"
                                   " powered")
  AssertEqual(compat.all(powered == "(unavail)"
                         for powered in result_output.splitlines()), True)

  # Conflicting
  AssertCommand(["gnt-cluster", "epo", "--groups", "--all"], fail=True)
  # --all doesn't expect arguments
  AssertCommand(["gnt-cluster", "epo", "--all", "some_arg"], fail=True)

  # Unless --all is given master is not allowed to be in the list
  AssertCommand(["gnt-cluster", "epo", "-f", master.primary], fail=True)

  # This shouldn't fail
  AssertCommand(["gnt-cluster", "epo", "-f", "--all"])

  # All instances should have been stopped now
  result_output = GetCommandOutput(master.primary,
                                   "gnt-instance list --no-headers -o status")
  # ERROR_down because the instance is stopped but not recorded as such
  AssertEqual(compat.all(status == "ERROR_down"
                         for status in result_output.splitlines()), True)

  # Now start everything again
  AssertCommand(["gnt-cluster", "epo", "--on", "-f", "--all"])

  # All instances should have been started now
  result_output = GetCommandOutput(master.primary,
                                   "gnt-instance list --no-headers -o status")
  AssertEqual(compat.all(status == "running"
                         for status in result_output.splitlines()), True)


def TestClusterVerify():
  """gnt-cluster verify"""
  AssertCommand(_CLUSTER_VERIFY)
  AssertCommand(["gnt-cluster", "verify-disks"])


def TestJobqueue():
  """gnt-debug test-jobqueue"""
  AssertCommand(["gnt-debug", "test-jobqueue"])


def TestDelay(node):
  """gnt-debug delay"""
  AssertCommand(["gnt-debug", "delay", "1"])
  AssertCommand(["gnt-debug", "delay", "--no-master", "1"])
  AssertCommand(["gnt-debug", "delay", "--no-master",
                 "-n", node.primary, "1"])


def TestClusterReservedLvs():
  """gnt-cluster reserved lvs"""
  vgname = qa_config.get("vg-name", constants.DEFAULT_VG)
  lvname = _QA_LV_PREFIX + "test"
  lvfullname = "/".join([vgname, lvname])
  for fail, cmd in [
    (False, _CLUSTER_VERIFY),
    (False, ["gnt-cluster", "modify", "--reserved-lvs", ""]),
    (False, ["lvcreate", "-L1G", "-n", lvname, vgname]),
    (True, _CLUSTER_VERIFY),
    (False, ["gnt-cluster", "modify", "--reserved-lvs",
             "%s,.*/other-test" % lvfullname]),
    (False, _CLUSTER_VERIFY),
    (False, ["gnt-cluster", "modify", "--reserved-lvs",
             ".*/%s.*" % _QA_LV_PREFIX]),
    (False, _CLUSTER_VERIFY),
    (False, ["gnt-cluster", "modify", "--reserved-lvs", ""]),
    (True, _CLUSTER_VERIFY),
    (False, ["lvremove", "-f", lvfullname]),
    (False, _CLUSTER_VERIFY),
    ]:
    AssertCommand(cmd, fail=fail)


def TestClusterModifyEmpty():
  """gnt-cluster modify"""
  AssertCommand(["gnt-cluster", "modify"], fail=True)


def TestClusterModifyDisk():
  """gnt-cluster modify -D"""
  for param in _FAIL_PARAMS:
    AssertCommand(["gnt-cluster", "modify", "-D", param], fail=True)


def TestClusterModifyBe():
  """gnt-cluster modify -B"""
  for fail, cmd in [
    # max/min mem
    (False, ["gnt-cluster", "modify", "-B", "maxmem=256"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *maxmem: 256$'"]),
    (False, ["gnt-cluster", "modify", "-B", "minmem=256"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *minmem: 256$'"]),
    (True, ["gnt-cluster", "modify", "-B", "maxmem=a"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *maxmem: 256$'"]),
    (True, ["gnt-cluster", "modify", "-B", "minmem=a"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *minmem: 256$'"]),
    (False, ["gnt-cluster", "modify", "-B", "maxmem=128,minmem=128"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *maxmem: 128$'"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *minmem: 128$'"]),
    # vcpus
    (False, ["gnt-cluster", "modify", "-B", "vcpus=4"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *vcpus: 4$'"]),
    (True, ["gnt-cluster", "modify", "-B", "vcpus=a"]),
    (False, ["gnt-cluster", "modify", "-B", "vcpus=1"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *vcpus: 1$'"]),
    # auto_balance
    (False, ["gnt-cluster", "modify", "-B", "auto_balance=False"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *auto_balance: False$'"]),
    (True, ["gnt-cluster", "modify", "-B", "auto_balance=1"]),
    (False, ["gnt-cluster", "modify", "-B", "auto_balance=True"]),
    (False, ["sh", "-c", "gnt-cluster info|grep '^ *auto_balance: True$'"]),
    ]:
    AssertCommand(cmd, fail=fail)

  # redo the original-requested BE parameters, if any
  bep = qa_config.get("backend-parameters", "")
  if bep:
    AssertCommand(["gnt-cluster", "modify", "-B", bep])


def TestClusterInfo():
  """gnt-cluster info"""
  AssertCommand(["gnt-cluster", "info"])


def TestClusterRedistConf():
  """gnt-cluster redist-conf"""
  AssertCommand(["gnt-cluster", "redist-conf"])


def TestClusterGetmaster():
  """gnt-cluster getmaster"""
  AssertCommand(["gnt-cluster", "getmaster"])


def TestClusterVersion():
  """gnt-cluster version"""
  AssertCommand(["gnt-cluster", "version"])


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
    AssertCommand(cmd + i, fail=True)

  # Invalid RAPI certificate
  cmd = ["gnt-cluster", "renew-crypto", "--force",
         "--rapi-certificate=/dev/null"]
  AssertCommand(cmd, fail=True)

  rapi_cert_backup = qa_utils.BackupFile(master.primary,
                                         pathutils.RAPI_CERT_FILE)
  try:
    # Custom RAPI certificate
    fh = tempfile.NamedTemporaryFile()

    # Ensure certificate doesn't cause "gnt-cluster verify" to complain
    validity = constants.SSL_CERT_EXPIRATION_WARN * 3

    utils.GenerateSelfSignedSslCert(fh.name, validity=validity)

    tmpcert = qa_utils.UploadFile(master.primary, fh.name)
    try:
      AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                     "--rapi-certificate=%s" % tmpcert])
    finally:
      AssertCommand(["rm", "-f", tmpcert])

    # Custom cluster domain secret
    cds_fh = tempfile.NamedTemporaryFile()
    cds_fh.write(utils.GenerateSecret())
    cds_fh.write("\n")
    cds_fh.flush()

    tmpcds = qa_utils.UploadFile(master.primary, cds_fh.name)
    try:
      AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                     "--cluster-domain-secret=%s" % tmpcds])
    finally:
      AssertCommand(["rm", "-f", tmpcds])

    # Normal case
    AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                   "--new-cluster-certificate", "--new-confd-hmac-key",
                   "--new-rapi-certificate", "--new-cluster-domain-secret"])

    # Restore RAPI certificate
    AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                   "--rapi-certificate=%s" % rapi_cert_backup])
  finally:
    AssertCommand(["rm", "-f", rapi_cert_backup])


def TestClusterBurnin():
  """Burnin"""
  master = qa_config.GetMasterNode()

  options = qa_config.get("options", {})
  disk_template = options.get("burnin-disk-template", constants.DT_DRBD8)
  parallel = options.get("burnin-in-parallel", False)
  check_inst = options.get("burnin-check-instances", False)
  do_rename = options.get("burnin-rename", "")
  do_reboot = options.get("burnin-reboot", True)
  reboot_types = options.get("reboot-types", constants.REBOOT_TYPES)

  # Get as many instances as we need
  instances = []
  try:
    try:
      num = qa_config.get("options", {}).get("burnin-instances", 1)
      for _ in range(0, num):
        instances.append(qa_config.AcquireInstance())
    except qa_error.OutOfInstancesError:
      print "Not enough instances, continuing anyway."

    if len(instances) < 1:
      raise qa_error.Error("Burnin needs at least one instance")

    script = qa_utils.UploadFile(master.primary, "../tools/burnin")
    try:
      # Run burnin
      cmd = [script,
             "--os=%s" % qa_config.get("os"),
             "--minmem-size=%s" % qa_config.get(constants.BE_MINMEM),
             "--maxmem-size=%s" % qa_config.get(constants.BE_MAXMEM),
             "--disk-size=%s" % ",".join(qa_config.get("disk")),
             "--disk-growth=%s" % ",".join(qa_config.get("disk-growth")),
             "--disk-template=%s" % disk_template]
      if parallel:
        cmd.append("--parallel")
        cmd.append("--early-release")
      if check_inst:
        cmd.append("--http-check")
      if do_rename:
        cmd.append("--rename=%s" % do_rename)
      if not do_reboot:
        cmd.append("--no-reboot")
      else:
        cmd.append("--reboot-types=%s" % ",".join(reboot_types))
      cmd += [inst.name for inst in instances]
      AssertCommand(cmd)
    finally:
      AssertCommand(["rm", "-f", script])

  finally:
    for inst in instances:
      inst.Release()


def TestClusterMasterFailover():
  """gnt-cluster master-failover"""
  master = qa_config.GetMasterNode()
  failovermaster = qa_config.AcquireNode(exclude=master)

  cmd = ["gnt-cluster", "master-failover"]
  try:
    AssertCommand(cmd, node=failovermaster)
    # Back to original master node
    AssertCommand(cmd, node=master)
  finally:
    failovermaster.Release()


def TestClusterMasterFailoverWithDrainedQueue():
  """gnt-cluster master-failover with drained queue"""
  drain_check = ["test", "-f", pathutils.JOB_QUEUE_DRAIN_FILE]

  master = qa_config.GetMasterNode()
  failovermaster = qa_config.AcquireNode(exclude=master)

  # Ensure queue is not drained
  for node in [master, failovermaster]:
    AssertCommand(drain_check, node=node, fail=True)

  # Drain queue on failover master
  AssertCommand(["touch", pathutils.JOB_QUEUE_DRAIN_FILE], node=failovermaster)

  cmd = ["gnt-cluster", "master-failover"]
  try:
    AssertCommand(drain_check, node=failovermaster)
    AssertCommand(cmd, node=failovermaster)
    AssertCommand(drain_check, fail=True)
    AssertCommand(drain_check, node=failovermaster, fail=True)

    # Back to original master node
    AssertCommand(cmd, node=master)
  finally:
    failovermaster.Release()

  AssertCommand(drain_check, fail=True)
  AssertCommand(drain_check, node=failovermaster, fail=True)


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
  testname = qa_utils.UploadFile(master.primary, f.name)
  try:
    # Copy file to all nodes
    AssertCommand(["gnt-cluster", "copyfile", testname])
    _CheckFileOnAllNodes(testname, uniqueid)
  finally:
    _RemoveFileFromAllNodes(testname)


def TestClusterCommand():
  """gnt-cluster command"""
  uniqueid = utils.NewUUID()
  rfile = "/tmp/gnt%s" % utils.NewUUID()
  rcmd = utils.ShellQuoteArgs(["echo", "-n", uniqueid])
  cmd = utils.ShellQuoteArgs(["gnt-cluster", "command",
                              "%s >%s" % (rcmd, rfile)])

  try:
    AssertCommand(cmd)
    _CheckFileOnAllNodes(rfile, uniqueid)
  finally:
    _RemoveFileFromAllNodes(rfile)


def TestClusterDestroy():
  """gnt-cluster destroy"""
  AssertCommand(["gnt-cluster", "destroy", "--yes-do-it"])


def TestClusterRepairDiskSizes():
  """gnt-cluster repair-disk-sizes"""
  AssertCommand(["gnt-cluster", "repair-disk-sizes"])


def TestSetExclStorCluster(newvalue):
  """Set the exclusive_storage node parameter at the cluster level.

  @type newvalue: bool
  @param newvalue: New value of exclusive_storage
  @rtype: bool
  @return: The old value of exclusive_storage

  """
  oldvalue = _GetBoolClusterField("exclusive_storage")
  AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                 "exclusive_storage=%s" % newvalue])
  effvalue = _GetBoolClusterField("exclusive_storage")
  if effvalue != newvalue:
    raise qa_error.Error("exclusive_storage has the wrong value: %s instead"
                         " of %s" % (effvalue, newvalue))
  qa_config.SetExclusiveStorage(newvalue)
  return oldvalue


def TestExclStorSharedPv(node):
  """cluster-verify reports LVs that share the same PV with exclusive_storage.

  """
  vgname = qa_config.get("vg-name", constants.DEFAULT_VG)
  lvname1 = _QA_LV_PREFIX + "vol1"
  lvname2 = _QA_LV_PREFIX + "vol2"
  node_name = node.primary
  AssertCommand(["lvcreate", "-L1G", "-n", lvname1, vgname], node=node_name)
  AssertClusterVerify(fail=True, errors=[constants.CV_ENODEORPHANLV])
  AssertCommand(["lvcreate", "-L1G", "-n", lvname2, vgname], node=node_name)
  AssertClusterVerify(fail=True, errors=[constants.CV_ENODELVM,
                                         constants.CV_ENODEORPHANLV])
  AssertCommand(["lvremove", "-f", "/".join([vgname, lvname1])], node=node_name)
  AssertCommand(["lvremove", "-f", "/".join([vgname, lvname2])], node=node_name)
  AssertClusterVerify()
