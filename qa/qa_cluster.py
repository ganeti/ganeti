#
#

# Copyright (C) 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""Cluster related QA tests.

"""

import os
import re
import tempfile
import time

from ganeti import _constants
from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import pathutils

from qa import qa_config
from qa import qa_daemon
from qa import qa_error
from qa import qa_instance
from qa import qa_job_utils
from qa import qa_logging
from qa import qa_rapi
from qa import qa_utils

from qa_utils import AssertEqual, AssertCommand, AssertRedirectedCommand, \
  GetCommandOutput, CheckFileUnmodified


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


def _GetClusterField(field_path):
  """Get the value of a cluster field.

  @type field_path: list of strings
  @param field_path: Names of the groups/fields to navigate to get the desired
      value, e.g. C{["Default node parameters", "oob_program"]}
  @return: The effective value of the field (the actual type depends on the
      chosen field)

  """
  assert isinstance(field_path, list)
  assert field_path
  ret = qa_utils.GetObjectInfo(["gnt-cluster", "info"])
  for key in field_path:
    ret = ret[key]
  return ret


# Cluster-verify errors (date, "ERROR", then error code)
_CVERROR_RE = re.compile(r"^[\w\s:]+\s+- (ERROR|WARNING):([A-Z0-9_-]+):")


def _GetCVErrorCodes(cvout):
  errs = set()
  warns = set()
  for l in cvout.splitlines():
    m = _CVERROR_RE.match(l)
    if m:
      etype = m.group(1)
      ecode = m.group(2)
      if etype == "ERROR":
        errs.add(ecode)
      elif etype == "WARNING":
        warns.add(ecode)
  return (errs, warns)


def _CheckVerifyErrors(actual, expected, etype):
  exp_codes = compat.UniqueFrozenset(e for (_, e, _) in expected)
  if not actual.issuperset(exp_codes):
    missing = exp_codes.difference(actual)
    raise qa_error.Error("Cluster-verify didn't return these expected"
                         " %ss: %s" % (etype, utils.CommaJoin(missing)))


def _CheckVerifyNoWarnings(actual, expected):
  exp_codes = compat.UniqueFrozenset(e for (_, e, _) in expected)
  excess = actual.intersection(exp_codes)
  if excess:
    raise qa_error.Error("Cluster-verify returned these warnings:"
                         " %s" % (utils.CommaJoin(excess)))


def AssertClusterVerify(fail=False, errors=None,
                        warnings=None, no_warnings=None):
  """Run cluster-verify and check the result, ignoring warnings by default.

  @type fail: bool
  @param fail: if cluster-verify is expected to fail instead of succeeding.
  @type errors: list of tuples
  @param errors: List of CV_XXX errors that are expected; if specified, all the
      errors listed must appear in cluster-verify output. A non-empty value
      implies C{fail=True}.
  @type warnings: list of tuples
  @param warnings: List of CV_XXX warnings that are expected to be raised; if
      specified, all the errors listed must appear in cluster-verify output.
  @type no_warnings: list of tuples
  @param no_warnings: List of CV_XXX warnings that we expect NOT to be raised.
  """
  cvcmd = "gnt-cluster verify"
  mnode = qa_config.GetMasterNode()
  if errors or warnings or no_warnings:
    with CheckFileUnmodified(mnode.primary, pathutils.CLUSTER_CONF_FILE):
      cvout = GetCommandOutput(mnode.primary, cvcmd + " --error-codes",
                               fail=(fail or errors))
    print(cvout)
    (act_errs, act_warns) = _GetCVErrorCodes(cvout)
    if errors:
      _CheckVerifyErrors(act_errs, errors, "error")
    if warnings:
      _CheckVerifyErrors(act_warns, warnings, "warning")
    if no_warnings:
      _CheckVerifyNoWarnings(act_warns, no_warnings)

  else:
    with CheckFileUnmodified(mnode.primary, pathutils.CLUSTER_CONF_FILE):
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


def TestClusterInit():
  """gnt-cluster init"""
  # If we don't modify the SSH setup by Ganeti, we have to ensure connectivity
  # before
  master = qa_config.GetMasterNode()
  if not qa_config.GetModifySshSetup():
    (key_type, _, priv_key_file, pub_key_file, auth_key_path) = \
      qa_config.GetSshConfig()
    AssertCommand("echo -e 'y\n' | ssh-keygen -t %s -f %s -q -N ''"
                  % (key_type, priv_key_file))
    AssertCommand("cat %s >> %s" % (pub_key_file, auth_key_path))
    for node in qa_config.get("nodes"):
      if node != master:
        for key_file in [priv_key_file, pub_key_file]:
          AssertCommand("scp -oStrictHostKeyChecking=no %s %s:%s" %
                        (key_file, node.primary, key_file))
        AssertCommand("ssh %s \'cat %s >> %s\'"
                      % (node.primary, pub_key_file, auth_key_path))

  # Initialize cluster
  enabled_disk_templates = qa_config.GetEnabledDiskTemplates()
  cmd = [
    "gnt-cluster", "init",
    "--primary-ip-version=%d" % qa_config.get("primary_ip_version", 4),
    "--enabled-hypervisors=%s" % ",".join(qa_config.GetEnabledHypervisors()),
    "--enabled-disk-templates=%s" %
      ",".join(enabled_disk_templates),
    ]

  if not qa_config.GetModifySshSetup():
    cmd.append("--no-ssh-init")

  if constants.DT_FILE in enabled_disk_templates:
    cmd.append(
        "--file-storage-dir=%s" %
        qa_config.get("default-file-storage-dir",
                      pathutils.DEFAULT_FILE_STORAGE_DIR))
  if constants.DT_SHARED_FILE in enabled_disk_templates:
    cmd.append(
        "--shared-file-storage-dir=%s" %
        qa_config.get("default-shared-file-storage-dir",
                      pathutils.DEFAULT_SHARED_FILE_STORAGE_DIR))
  if constants.DT_GLUSTER in enabled_disk_templates:
    cmd.append(
        "--gluster-storage-dir=%s" %
        qa_config.get("default-gluster-storage-dir",
                      pathutils.DEFAULT_GLUSTER_STORAGE_DIR))

  for spec_type in ("mem-size", "disk-size", "disk-count", "cpu-count",
                    "nic-count"):
    spec_values = []
    for spec_val in ("min", "max", "std"):
      spec = qa_config.get("ispec_%s_%s" %
                           (spec_type.replace("-", "_"), spec_val), None)
      if spec is not None:
        spec_values.append("%s=%d" % (spec_val, spec))
    if spec_values:
      cmd.append("--specs-%s=%s" % (spec_type, ",".join(spec_values)))

  master = qa_config.GetMasterNode()
  if master.secondary:
    cmd.append("--secondary-ip=%s" % master.secondary)

  if utils.IsLvmEnabled(qa_config.GetEnabledDiskTemplates()):
    vgname = qa_config.get("vg-name", constants.DEFAULT_VG)
    if vgname:
      cmd.append("--vg-name=%s" % vgname)
    else:
      raise qa_error.Error("Please specify a volume group if you enable"
                           " lvm-based disk templates in the QA.")

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
    # This option was removed in 2.10, but in order to not break QA of older
    # branches we remove it from the extra_args if it is in there.
    opt_drbd_storage = "--no-drbd-storage"
    if opt_drbd_storage in extra_args:
      extra_args.remove(opt_drbd_storage)
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
    print(qa_logging.FormatError('"rename" entry is missing'))
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

  with qa_job_utils.PausedWatcher():
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


def TestClusterVerifyDisksBrokenDRBD(instance, inst_nodes):
  """gnt-cluster verify-disks with broken DRBD"""
  qa_daemon.TestPauseWatcher()

  try:
    info = qa_instance.GetInstanceInfo(instance.name)
    snode = inst_nodes[1]
    for idx, minor in enumerate(info["drbd-minors"][snode.primary]):
      if idx % 2 == 0:
        break_drbd_cmd = \
          "(drbdsetup %d down >/dev/null 2>&1;" \
          " drbdsetup down resource%d >/dev/null 2>&1) || /bin/true" % \
          (minor, minor)
      else:
        break_drbd_cmd = \
          "(drbdsetup %d detach >/dev/null 2>&1;" \
          " drbdsetup detach %d >/dev/null 2>&1) || /bin/true" % \
          (minor, minor)
      AssertCommand(break_drbd_cmd, node=snode)

    verify_output = GetCommandOutput(qa_config.GetMasterNode().primary,
                                     "gnt-cluster verify-disks")
    activation_msg = "Activating disks for instance '%s'" % instance.name
    if activation_msg not in verify_output:
      raise qa_error.Error("gnt-cluster verify-disks did not activate broken"
                           " DRBD disks:\n%s" % verify_output)

    verify_output = GetCommandOutput(qa_config.GetMasterNode().primary,
                                     "gnt-cluster verify-disks")
    if activation_msg in verify_output:
      raise qa_error.Error("gnt-cluster verify-disks wants to activate broken"
                           " DRBD disks on second attempt:\n%s" % verify_output)

    AssertCommand(_CLUSTER_VERIFY)
  finally:
    qa_daemon.TestResumeWatcher()


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
  # if no lvm-based templates are supported, skip the test
  if not qa_config.IsStorageTypeSupported(constants.ST_LVM_VG):
    return
  vgname = qa_config.get("vg-name", constants.DEFAULT_VG)
  lvname = _QA_LV_PREFIX + "test"
  lvfullname = "/".join([vgname, lvname])

  # Clean cluster
  AssertClusterVerify()

  AssertCommand(["gnt-cluster", "modify", "--reserved-lvs", ""])
  AssertCommand(["lvcreate", "-L1G", "-n", lvname, vgname])
  AssertClusterVerify(fail=False,
                      warnings=[constants.CV_ENODEORPHANLV])

  AssertCommand(["gnt-cluster", "modify", "--reserved-lvs",
                 "%s,.*/other-test" % lvfullname])
  AssertClusterVerify(no_warnings=[constants.CV_ENODEORPHANLV])

  AssertCommand(["gnt-cluster", "modify", "--reserved-lvs",
                ".*/%s.*" % _QA_LV_PREFIX])
  AssertClusterVerify(no_warnings=[constants.CV_ENODEORPHANLV])

  AssertCommand(["gnt-cluster", "modify", "--reserved-lvs", ""])
  AssertClusterVerify(fail=False,
                      warnings=[constants.CV_ENODEORPHANLV])

  AssertCommand(["lvremove", "-f", lvfullname])
  AssertClusterVerify()


def TestClusterModifyEmpty():
  """gnt-cluster modify"""
  AssertCommand(["gnt-cluster", "modify"], fail=True)


def TestClusterModifyDisk():
  """gnt-cluster modify -D"""
  for param in _FAIL_PARAMS:
    AssertCommand(["gnt-cluster", "modify", "-D", param], fail=True)


def _GetOtherEnabledDiskTemplate(undesired_disk_templates,
                                 enabled_disk_templates):
  """Returns one template that is not in the undesired set.

  @type undesired_disk_templates: list of string
  @param undesired_disk_templates: a list of disk templates that we want to
      exclude when drawing one disk template from the list of enabled
      disk templates
  @type enabled_disk_templates: list of string
  @param enabled_disk_templates: list of enabled disk templates (in QA)

  """
  desired_templates = list(set(enabled_disk_templates)
                                - set(undesired_disk_templates))
  if desired_templates:
    template = desired_templates[0]
  else:
    # If no desired disk template is available for QA, choose 'diskless' and
    # hope for the best.
    template = constants.ST_DISKLESS

  return template


def TestClusterModifyFileBasedStorageDir(
    file_disk_template, dir_config_key, default_dir, option_name):
  """Tests gnt-cluster modify wrt to file-based directory options.

  @type file_disk_template: string
  @param file_disk_template: file-based disk template
  @type dir_config_key: string
  @param dir_config_key: key for the QA config to retrieve the default
     directory value
  @type default_dir: string
  @param default_dir: default directory, if the QA config does not specify
     it
  @type option_name: string
  @param option_name: name of the option of 'gnt-cluster modify' to
     change the directory

  """
  enabled_disk_templates = qa_config.GetEnabledDiskTemplates()
  assert file_disk_template in constants.DTS_FILEBASED
  if not qa_config.IsTemplateSupported(file_disk_template):
    return

  # Get some non-file-based disk template to disable file storage
  other_disk_template = _GetOtherEnabledDiskTemplate(
    utils.storage.GetDiskTemplatesOfStorageTypes(constants.ST_FILE,
                                                 constants.ST_SHARED_FILE),
    enabled_disk_templates
  )

  file_storage_dir = qa_config.get(dir_config_key, default_dir)
  invalid_file_storage_dir = "/boot/"

  for fail, cmd in [
    (False, ["gnt-cluster", "modify",
             "--enabled-disk-templates=%s" % file_disk_template,
             "--ipolicy-disk-templates=%s" % file_disk_template]),
    (False, ["gnt-cluster", "modify",
             "--%s=%s" % (option_name, file_storage_dir)]),
    (False, ["gnt-cluster", "modify",
             "--%s=%s" % (option_name, invalid_file_storage_dir)]),
    # file storage dir is set to an inacceptable path, thus verify
    # should fail
    (True, ["gnt-cluster", "verify"]),
    # unsetting the storage dir while file storage is enabled
    # should fail
    (True, ["gnt-cluster", "modify",
            "--%s=" % option_name]),
    (False, ["gnt-cluster", "modify",
             "--%s=%s" % (option_name, file_storage_dir)]),
    (False, ["gnt-cluster", "modify",
             "--enabled-disk-templates=%s" % other_disk_template,
             "--ipolicy-disk-templates=%s" % other_disk_template]),
    (False, ["gnt-cluster", "modify",
             "--%s=%s" % (option_name, invalid_file_storage_dir)]),
    # file storage is set to an inacceptable path, but file storage
    # is disabled, thus verify should not fail
    (False, ["gnt-cluster", "verify"]),
    # unsetting the file storage dir while file storage is not enabled
    # should be fine
    (False, ["gnt-cluster", "modify",
             "--%s=" % option_name]),
    # resetting everything to sane values
    (False, ["gnt-cluster", "modify",
             "--%s=%s" % (option_name, file_storage_dir),
             "--enabled-disk-templates=%s" % ",".join(enabled_disk_templates),
             "--ipolicy-disk-templates=%s" % ",".join(enabled_disk_templates)])
    ]:
    AssertCommand(cmd, fail=fail)


def TestClusterModifyFileStorageDir():
  """gnt-cluster modify --file-storage-dir=..."""
  TestClusterModifyFileBasedStorageDir(
      constants.DT_FILE, "default-file-storage-dir",
      pathutils.DEFAULT_FILE_STORAGE_DIR,
      "file-storage-dir")


def TestClusterModifySharedFileStorageDir():
  """gnt-cluster modify --shared-file-storage-dir=..."""
  TestClusterModifyFileBasedStorageDir(
      constants.DT_SHARED_FILE, "default-shared-file-storage-dir",
      pathutils.DEFAULT_SHARED_FILE_STORAGE_DIR,
      "shared-file-storage-dir")


def TestClusterModifyDiskTemplates():
  """gnt-cluster modify --enabled-disk-templates=..."""
  enabled_disk_templates = qa_config.GetEnabledDiskTemplates()
  default_disk_template = qa_config.GetDefaultDiskTemplate()

  _TestClusterModifyDiskTemplatesArguments(default_disk_template)
  _TestClusterModifyDiskTemplatesDrbdHelper(enabled_disk_templates)
  _TestClusterModifyDiskTemplatesVgName(enabled_disk_templates)

  _RestoreEnabledDiskTemplates()
  nodes = qa_config.AcquireManyNodes(2)

  instance_template = enabled_disk_templates[0]
  instance = qa_instance.CreateInstanceByDiskTemplate(nodes, instance_template)

  _TestClusterModifyUsedDiskTemplate(instance_template,
                                     enabled_disk_templates)

  qa_instance.TestInstanceRemove(instance)
  _RestoreEnabledDiskTemplates()


def TestClusterModifyInstallImage():
  """gnt-cluster modify --install-image=...'"""
  master = qa_config.GetMasterNode()

  image = \
      GetCommandOutput(master.primary,
                       "mktemp --tmpdir ganeti-install-image.XXXXXX").strip()
  AssertCommand(["gnt-cluster", "modify", "--install-image=%s" % image])
  AssertCommand(["rm", image])


def _RestoreEnabledDiskTemplates():
  """Sets the list of enabled disk templates back to the list of enabled disk
     templates from the QA configuration. This can be used to make sure that
     the tests that modify the list of disk templates do not interfere with
     other tests.

  """
  enabled_disk_templates = qa_config.GetEnabledDiskTemplates()
  cmd = ["gnt-cluster", "modify",
         "--enabled-disk-templates=%s" % ",".join(enabled_disk_templates),
         "--ipolicy-disk-templates=%s" % ",".join(enabled_disk_templates),
         ]

  if utils.IsLvmEnabled(qa_config.GetEnabledDiskTemplates()):
    vgname = qa_config.get("vg-name", constants.DEFAULT_VG)
    cmd.append("--vg-name=%s" % vgname)

  AssertCommand(cmd, fail=False)


def _TestClusterModifyDiskTemplatesDrbdHelper(enabled_disk_templates):
  """Tests argument handling of 'gnt-cluster modify' with respect to
     the parameter '--drbd-usermode-helper'. This test is independent
     of instances.

  """
  _RestoreEnabledDiskTemplates()

  if constants.DT_DRBD8 not in enabled_disk_templates:
    return
  if constants.DT_PLAIN not in enabled_disk_templates:
    return

  drbd_usermode_helper = qa_config.get("drbd-usermode-helper", "/bin/true")
  bogus_usermode_helper = "/tmp/pinkbunny"
  for command, fail in [
    (["gnt-cluster", "modify",
      "--enabled-disk-templates=%s" % constants.DT_DRBD8,
      "--ipolicy-disk-templates=%s" % constants.DT_DRBD8], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper=%s" % drbd_usermode_helper], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper=%s" % bogus_usermode_helper], True),
    # unsetting helper when DRBD is enabled should not work
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper="], True),
    (["gnt-cluster", "modify",
      "--enabled-disk-templates=%s" % constants.DT_PLAIN,
      "--ipolicy-disk-templates=%s" % constants.DT_PLAIN], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper="], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper=%s" % drbd_usermode_helper], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper=%s" % drbd_usermode_helper,
      "--enabled-disk-templates=%s" % constants.DT_DRBD8,
      "--ipolicy-disk-templates=%s" % constants.DT_DRBD8], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper=",
      "--enabled-disk-templates=%s" % constants.DT_PLAIN,
      "--ipolicy-disk-templates=%s" % constants.DT_PLAIN], False),
    (["gnt-cluster", "modify",
      "--drbd-usermode-helper=%s" % drbd_usermode_helper,
      "--enabled-disk-templates=%s" % constants.DT_DRBD8,
      "--ipolicy-disk-templates=%s" % constants.DT_DRBD8], False),
    ]:
    AssertCommand(command, fail=fail)
  _RestoreEnabledDiskTemplates()


def _TestClusterModifyDiskTemplatesArguments(default_disk_template):
  """Tests argument handling of 'gnt-cluster modify' with respect to
     the parameter '--enabled-disk-templates'. This test is independent
     of instances.

  """
  _RestoreEnabledDiskTemplates()

  # bogus templates
  AssertCommand(["gnt-cluster", "modify",
                 "--enabled-disk-templates=pinkbunny"],
                fail=True)

  # duplicate entries do no harm
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s,%s" %
      (default_disk_template, default_disk_template),
     "--ipolicy-disk-templates=%s" % default_disk_template],
    fail=False)


def _TestClusterModifyDiskTemplatesVgName(enabled_disk_templates):
  """Tests argument handling of 'gnt-cluster modify' with respect to
     the parameter '--enabled-disk-templates' and '--vg-name'. This test is
     independent of instances.

  """
  if not utils.IsLvmEnabled(enabled_disk_templates):
    # These tests only make sense if lvm is enabled for QA
    return

  # determine an LVM and a non-LVM disk template for the tests
  non_lvm_template = _GetOtherEnabledDiskTemplate(constants.DTS_LVM,
                                                  enabled_disk_templates)
  lvm_template = list(set(enabled_disk_templates) & constants.DTS_LVM)[0]

  vgname = qa_config.get("vg-name", constants.DEFAULT_VG)

  # Clean start: unset volume group name, disable lvm storage
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % non_lvm_template,
     "--ipolicy-disk-templates=%s" % non_lvm_template,
     "--vg-name="],
    fail=False)

  # Try to enable lvm, when no volume group is given
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % lvm_template,
     "--ipolicy-disk-templates=%s" % lvm_template],
    fail=True)

  # Set volume group, with lvm still disabled: just a warning
  AssertCommand(["gnt-cluster", "modify", "--vg-name=%s" % vgname], fail=False)

  # Try unsetting vg name and enabling lvm at the same time
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % lvm_template,
     "--ipolicy-disk-templates=%s" % lvm_template,
     "--vg-name="],
    fail=True)

  # Enable lvm with vg name present
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % lvm_template,
     "--ipolicy-disk-templates=%s" % lvm_template],
    fail=False)

  # Try unsetting vg name with lvm still enabled
  AssertCommand(["gnt-cluster", "modify", "--vg-name="], fail=True)

  # Disable lvm with vg name still set
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % non_lvm_template,
     "--ipolicy-disk-templates=%s" % non_lvm_template,
     ],
    fail=False)

  # Try unsetting vg name with lvm disabled
  AssertCommand(["gnt-cluster", "modify", "--vg-name="], fail=False)

  # Set vg name and enable lvm at the same time
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % lvm_template,
     "--ipolicy-disk-templates=%s" % lvm_template,
     "--vg-name=%s" % vgname],
    fail=False)

  # Unset vg name and disable lvm at the same time
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % non_lvm_template,
     "--ipolicy-disk-templates=%s" % non_lvm_template,
     "--vg-name="],
    fail=False)

  _RestoreEnabledDiskTemplates()


def _TestClusterModifyUsedDiskTemplate(instance_template,
                                       enabled_disk_templates):
  """Tests that disk templates that are currently in use by instances cannot
     be disabled on the cluster.

  """
  # If the list of enabled disk templates contains only one template
  # we need to add some other templates, because the list of enabled disk
  # templates can only be set to a non-empty list.
  new_disk_templates = list(set(enabled_disk_templates)
                              - set([instance_template]))
  if not new_disk_templates:
    new_disk_templates = list(set([constants.DT_DISKLESS, constants.DT_BLOCK])
                                - set([instance_template]))
  AssertCommand(
    ["gnt-cluster", "modify",
     "--enabled-disk-templates=%s" % ",".join(new_disk_templates),
     "--ipolicy-disk-templates=%s" % ",".join(new_disk_templates)],
    fail=True)


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


def _GetClusterIPolicy():
  """Return the run-time values of the cluster-level instance policy.

  @rtype: tuple
  @return: (policy, specs), where:
      - policy is a dictionary of the policy values, instance specs excluded
      - specs is a dictionary containing only the specs, using the internal
        format (see L{constants.IPOLICY_DEFAULTS} for an example)

  """
  info = qa_utils.GetObjectInfo(["gnt-cluster", "info"])
  policy = info["Instance policy - limits for instances"]
  (ret_policy, ret_specs) = qa_utils.ParseIPolicy(policy)

  # Sanity checks
  assert "minmax" in ret_specs and "std" in ret_specs
  assert len(ret_specs["minmax"]) > 0
  assert len(ret_policy) > 0
  return (ret_policy, ret_specs)


def TestClusterModifyIPolicy():
  """gnt-cluster modify --ipolicy-*"""
  basecmd = ["gnt-cluster", "modify"]
  (old_policy, old_specs) = _GetClusterIPolicy()
  for par in ["vcpu-ratio", "spindle-ratio"]:
    curr_val = float(old_policy[par])
    test_values = [
      (True, 1.0),
      (True, 1.5),
      (True, 2),
      (False, "a"),
      # Restore the old value
      (True, curr_val),
      ]
    for (good, val) in test_values:
      cmd = basecmd + ["--ipolicy-%s=%s" % (par, val)]
      AssertCommand(cmd, fail=not good)
      if good:
        curr_val = val
      # Check the affected parameter
      (eff_policy, eff_specs) = _GetClusterIPolicy()
      AssertEqual(float(eff_policy[par]), curr_val)
      # Check everything else
      AssertEqual(eff_specs, old_specs)
      for p in eff_policy.keys():
        if p == par:
          continue
        AssertEqual(eff_policy[p], old_policy[p])

  # Allowing disk templates via ipolicy requires them to be
  # enabled on the cluster.
  if not (qa_config.IsTemplateSupported(constants.DT_PLAIN)
          and qa_config.IsTemplateSupported(constants.DT_DRBD8)):
    return
  # Disk templates are treated slightly differently
  par = "disk-templates"
  disp_str = "allowed disk templates"
  curr_val = old_policy[disp_str]
  test_values = [
    (True, constants.DT_PLAIN),
    (True, "%s,%s" % (constants.DT_PLAIN, constants.DT_DRBD8)),
    (False, "thisisnotadisktemplate"),
    (False, ""),
    # Restore the old value
    (True, curr_val.replace(" ", "")),
    ]
  for (good, val) in test_values:
    cmd = basecmd + ["--ipolicy-%s=%s" % (par, val)]
    AssertCommand(cmd, fail=not good)
    if good:
      curr_val = val
    # Check the affected parameter
    (eff_policy, eff_specs) = _GetClusterIPolicy()
    AssertEqual(eff_policy[disp_str].replace(" ", ""), curr_val)
    # Check everything else
    AssertEqual(eff_specs, old_specs)
    for p in eff_policy.keys():
      if p == disp_str:
        continue
      AssertEqual(eff_policy[p], old_policy[p])


def TestClusterSetISpecs(new_specs=None, diff_specs=None, fail=False,
                         old_values=None):
  """Change instance specs.

  At most one of new_specs or diff_specs can be specified.

  @type new_specs: dict
  @param new_specs: new complete specs, in the same format returned by
      L{_GetClusterIPolicy}
  @type diff_specs: dict
  @param diff_specs: partial specs, it can be an incomplete specifications, but
      if min/max specs are specified, their number must match the number of the
      existing specs
  @type fail: bool
  @param fail: if the change is expected to fail
  @type old_values: tuple
  @param old_values: (old_policy, old_specs), as returned by
      L{_GetClusterIPolicy}
  @return: same as L{_GetClusterIPolicy}

  """
  build_cmd = lambda opts: ["gnt-cluster", "modify"] + opts
  return qa_utils.TestSetISpecs(
    new_specs=new_specs, diff_specs=diff_specs,
    get_policy_fn=_GetClusterIPolicy, build_cmd_fn=build_cmd,
    fail=fail, old_values=old_values)


def TestClusterModifyISpecs():
  """gnt-cluster modify --specs-*"""
  params = ["memory-size", "disk-size", "disk-count", "cpu-count", "nic-count"]
  (cur_policy, cur_specs) = _GetClusterIPolicy()
  # This test assumes that there is only one min/max bound
  assert len(cur_specs[constants.ISPECS_MINMAX]) == 1
  for par in params:
    test_values = [
      (True, 0, 4, 12),
      (True, 4, 4, 12),
      (True, 4, 12, 12),
      (True, 4, 4, 4),
      (False, 4, 0, 12),
      (False, 4, 16, 12),
      (False, 4, 4, 0),
      (False, 12, 4, 4),
      (False, 12, 4, 0),
      (False, "a", 4, 12),
      (False, 0, "a", 12),
      (False, 0, 4, "a"),
      # This is to restore the old values
      (True,
       cur_specs[constants.ISPECS_MINMAX][0][constants.ISPECS_MIN][par],
       cur_specs[constants.ISPECS_STD][par],
       cur_specs[constants.ISPECS_MINMAX][0][constants.ISPECS_MAX][par])
      ]
    for (good, mn, st, mx) in test_values:
      new_vals = {
        constants.ISPECS_MINMAX: [{
          constants.ISPECS_MIN: {par: mn},
          constants.ISPECS_MAX: {par: mx}
          }],
        constants.ISPECS_STD: {par: st}
        }
      cur_state = (cur_policy, cur_specs)
      # We update cur_specs, as we've copied the values to restore already
      (cur_policy, cur_specs) = TestClusterSetISpecs(
        diff_specs=new_vals, fail=not good, old_values=cur_state)

    # Get the ipolicy command
    mnode = qa_config.GetMasterNode()
    initcmd = GetCommandOutput(mnode.primary, "gnt-cluster show-ispecs-cmd")
    modcmd = ["gnt-cluster", "modify"]
    opts = initcmd.split()
    assert opts[0:2] == ["gnt-cluster", "init"]
    for k in range(2, len(opts) - 1):
      if opts[k].startswith("--ipolicy-"):
        assert k + 2 <= len(opts)
        modcmd.extend(opts[k:k + 2])
    # Re-apply the ipolicy (this should be a no-op)
    AssertCommand(modcmd)
    new_initcmd = GetCommandOutput(mnode.primary, "gnt-cluster show-ispecs-cmd")
    AssertEqual(initcmd, new_initcmd)


def _TestClusterModifyUserShutdownXen(nodes):
  """Tests user shutdown cluster wide for the KVM hypervisor.

  Note that for the Xen hypervisor, the KVM daemon should never run.

  """
  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=true"])

  # Give time for kvmd to start and stop on all nodes
  time.sleep(5)

  for node in nodes:
    AssertCommand("pgrep ganeti-kvmd", node=node, fail=True)

  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=false"])

  for node in nodes:
    AssertCommand("pgrep ganeti-kvmd", node=node, fail=True)


def _TestClusterModifyUserShutdownKvm(nodes):
  """Tests user shutdown cluster wide for the KVM hypervisor.

  Note that for the KVM hypervisor, the KVM daemon should run
  according to '--user-shutdown' and whether the node is VM capable.

  """
  # How much time to wait for kvmd to start/stop
  kvmd_cycle_time = 4

  # Start kvmd on all nodes
  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=true"])
  time.sleep(kvmd_cycle_time)
  for node in nodes:
    AssertCommand("pgrep ganeti-kvmd", node=node)

  # Test VM capable node attribute
  test_node = None

  for node in nodes:
    node_info = qa_utils.GetObjectInfo(["gnt-node", "info", node.primary])[0]
    if "vm_capable" in node_info and node_info["vm_capable"]:
      test_node = node
      break

  if test_node is None:
    raise qa_error.Error("Failed to find viable node for this test")

  # Stop kvmd by disabling vm capable
  AssertCommand(["gnt-node", "modify", "--vm-capable=no", test_node.primary])
  time.sleep(kvmd_cycle_time)
  AssertCommand("pgrep ganeti-kvmd", node=test_node, fail=True)

  # Start kvmd by enabling vm capable
  AssertCommand(["gnt-node", "modify", "--vm-capable=yes", test_node.primary])
  time.sleep(kvmd_cycle_time)
  AssertCommand("pgrep ganeti-kvmd", node=test_node)

  # Stop kvmd on all nodes by removing KVM from the enabled hypervisors
  enabled_hypervisors = qa_config.GetEnabledHypervisors()

  AssertCommand(["gnt-cluster", "modify", "--enabled-hypervisors=xen-pvm"])
  time.sleep(kvmd_cycle_time)
  for node in nodes:
    AssertCommand("pgrep ganeti-kvmd", node=node, fail=True)

  # Start kvmd on all nodes by restoring KVM to the enabled hypervisors
  AssertCommand(["gnt-cluster", "modify",
                 "--enabled-hypervisors=%s" % ",".join(enabled_hypervisors)])
  time.sleep(kvmd_cycle_time)
  for node in nodes:
    AssertCommand("pgrep ganeti-kvmd", node=node)

  # Stop kvmd on all nodes
  AssertCommand(["gnt-cluster", "modify", "--user-shutdown=false"])
  time.sleep(kvmd_cycle_time)
  for node in nodes:
    AssertCommand("pgrep ganeti-kvmd", node=node, fail=True)


def TestClusterModifyUserShutdown():
  """Tests user shutdown cluster wide.

  """
  enabled_hypervisors = qa_config.GetEnabledHypervisors()
  nodes = qa_config.get("nodes")

  for (hv, fn) in [(constants.HT_XEN_PVM, _TestClusterModifyUserShutdownXen),
                   (constants.HT_XEN_HVM, _TestClusterModifyUserShutdownXen),
                   (constants.HT_KVM, _TestClusterModifyUserShutdownKvm)]:
    if hv in enabled_hypervisors:
      qa_daemon.TestPauseWatcher()
      fn(nodes)
      qa_daemon.TestResumeWatcher()
    else:
      print("%s hypervisor is not enabled, skipping test for this hypervisor" \
          % hv)


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


def _AssertSsconfCertFiles():
  """This asserts that all ssconf_master_candidate_certs have the same content.

  """
  (vcluster_master, _) = qa_config.GetVclusterSettings()
  if vcluster_master:
    print("Skipping asserting SsconfCertFiles for Vcluster")
    return
  nodes = qa_config.get("nodes")
  ssconf_file = "/var/lib/ganeti/ssconf_master_candidates_certs"
  ssconf_content = {}
  for node in nodes:
    cmd = ["cat", ssconf_file]
    print("Ssconf Master Certificates of node '%s'." % node.primary)
    result_output = GetCommandOutput(node.primary, utils.ShellQuoteArgs(cmd))
    ssconf_content[node] = result_output

    # Clean up result to make it comparable:
    # remove trailing whitespace from each line, remove empty lines, sort lines
    lines_node = result_output.split('\n')
    lines_node = [line.strip() for line in lines_node if len(line.strip()) > 0]
    lines_node.sort()

    ssconf_content[node] = lines_node

  first_node = nodes[0]
  for node in nodes[1:]:
    if not ssconf_content[node] == ssconf_content[first_node]:
      raise Exception("Cert list of node '%s' differs from the list of node"
                      " '%s'." % (node, first_node))


def _TestSSHKeyChanges(master_node):
  """Tests a lot of SSH key type- and size- related functionality.

  @type master_node: L{qa_config._QaNode}
  @param master_node: The cluster master.

  """
  # Helper fn to avoid specifying base params too many times
  def _RenewWithParams(new_params, verify=True, fail=False):
    AssertCommand(["gnt-cluster", "renew-crypto", "--new-ssh-keys", "-f",
                   "--no-ssh-key-check"] + new_params, fail=fail)
    if not fail and verify:
      AssertCommand(["gnt-cluster", "verify"])

  # First test the simplest change
  _RenewWithParams([])

  # And stop here if vcluster
  (vcluster_master, _) = qa_config.GetVclusterSettings()
  if vcluster_master:
    print("Skipping further SSH key replacement checks for vcluster")
    return

  # And the actual tests
  with qa_config.AcquireManyNodesCtx(1, exclude=[master_node]) as nodes:
    node_name = nodes[0].primary

    # Another helper function for checking whether a specific key can log in
    def _CheckLoginWithKey(key_path, fail=False):
      AssertCommand(["ssh", "-oIdentityFile=%s" % key_path, "-oBatchMode=yes",
                     "-oStrictHostKeyChecking=no", "-oIdentitiesOnly=yes",
                     "-F/dev/null", node_name, "true"],
                    fail=fail, forward_agent=False)

    _RenewWithParams(["--ssh-key-type=dsa"])
    _CheckLoginWithKey("/root/.ssh/id_dsa")
    # Stash the key for now
    old_key_backup = qa_utils.BackupFile(master_node.primary,
                                         "/root/.ssh/id_dsa")

    try:
      _RenewWithParams(["--ssh-key-type=rsa"])
      _CheckLoginWithKey("/root/.ssh/id_rsa")
      # And check that we cannot log in with the old key
      _CheckLoginWithKey(old_key_backup, fail=True)
    finally:
      AssertCommand(["rm", "-f", old_key_backup])

    _RenewWithParams(["--ssh-key-bits=4096"])
    _RenewWithParams(["--ssh-key-bits=521"], fail=True)

    # Restore the cluster to its pristine state, skipping the verify as we did
    # way too many already
    _RenewWithParams(["--ssh-key-type=rsa", "--ssh-key-bits=2048"],
                     verify=False)


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
    fh = tempfile.NamedTemporaryFile(mode="w")

    # Ensure certificate doesn't cause "gnt-cluster verify" to complain
    validity = constants.SSL_CERT_EXPIRATION_WARN * 3

    utils.GenerateSelfSignedSslCert(fh.name, 1, validity=validity)

    tmpcert = qa_utils.UploadFile(master.primary, fh.name)
    try:
      AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                     "--rapi-certificate=%s" % tmpcert])
    finally:
      AssertCommand(["rm", "-f", tmpcert])

    # Custom cluster domain secret
    cds_fh = tempfile.NamedTemporaryFile(mode="w")
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
                   "--new-rapi-certificate", "--new-cluster-domain-secret",
                   "--new-node-certificates", "--new-ssh-keys",
                   "--no-ssh-key-check"])
    _AssertSsconfCertFiles()
    AssertCommand(["gnt-cluster", "verify"])

    # Only renew node certificates
    AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                   "--new-node-certificates"])
    _AssertSsconfCertFiles()
    AssertCommand(["gnt-cluster", "verify"])

    # Only renew cluster certificate
    AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                   "--new-cluster-certificate"])
    _AssertSsconfCertFiles()
    AssertCommand(["gnt-cluster", "verify"])

    # Comprehensively test various types of SSH key changes
    _TestSSHKeyChanges(master)

    # Restore RAPI certificate
    AssertCommand(["gnt-cluster", "renew-crypto", "--force",
                   "--rapi-certificate=%s" % rapi_cert_backup])
    _AssertSsconfCertFiles()
    AssertCommand(["gnt-cluster", "verify"])
  finally:
    AssertCommand(["rm", "-f", rapi_cert_backup])

  # Since renew-crypto replaced the RAPI cert, reload it.
  if qa_rapi.Enabled():
    qa_rapi.ReloadCertificates()


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
      print("Not enough instances, continuing anyway.")

    if len(instances) < 1:
      raise qa_error.Error("Burnin needs at least one instance")

    burnin_file = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               "../tools/burnin")
    script = qa_utils.UploadFile(master.primary, burnin_file)
    try:
      disks = qa_config.GetDiskOptions()
      # Run burnin
      cmd = ["env",
             "PYTHONPATH=%s" % _constants.VERSIONEDSHAREDIR,
             script,
             "--os=%s" % qa_config.get("os"),
             "--minmem-size=%s" % qa_config.get(constants.BE_MINMEM),
             "--maxmem-size=%s" % qa_config.get(constants.BE_MAXMEM),
             "--disk-size=%s" % ",".join([d.get("size") for d in disks]),
             "--disk-growth=%s" % ",".join([d.get("growth") for d in disks]),
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

  # Flush the configuration to prevent race conditions when loading it
  # on another node
  print(qa_logging.FormatInfo("Flushing the configuration on the master node"))
  AssertCommand(["gnt-debug", "wconfd", "flushconfig"])

  cmd = ["gnt-cluster", "master-failover"]
  node_list_cmd = ["gnt-node", "list"]
  try:
    AssertCommand(cmd, node=failovermaster)
    AssertCommand(node_list_cmd, node=failovermaster)
    # Back to original master node
    AssertCommand(cmd, node=master)
    AssertCommand(node_list_cmd, node=master)
  finally:
    failovermaster.Release()


def TestUpgrade():
  """Test gnt-cluster upgrade.

  This tests the 'gnt-cluster upgrade' command by flipping
  between the current and a different version of Ganeti.
  To also recover subtle points in the configuration up/down
  grades, instances are left over both upgrades.

  """
  this_version = qa_config.get("dir-version")
  other_version = qa_config.get("other-dir-version")
  if this_version is None or other_version is None:
    print(qa_utils.FormatInfo("Test not run, as versions not specified"))
    return

  inst_creates = []
  upgrade_instances = qa_config.get("upgrade-instances", [])
  live_instances = []
  for (test_name, templ, cf, n) in qa_instance.available_instance_tests:
    if (qa_config.TestEnabled(test_name) and
        qa_config.IsTemplateSupported(templ) and
        templ in upgrade_instances):
      inst_creates.append((cf, n))

  for (cf, n) in inst_creates:
    nodes = qa_config.AcquireManyNodes(n)
    live_instances.append(cf(nodes))

  # 2.16 only - prior to performing a downgrade, we have to make sure that the
  # SSH keys used are such that the lower version can still use them,
  # regardless of cluster defaults.
  if constants.VERSION_MINOR != 16:
    raise qa_error.Error("Please remove the key type downgrade code in 2.17")
  AssertCommand(["gnt-cluster", "renew-crypto", "--no-ssh-key-check", "-f",
                 "--new-ssh-keys", "--ssh-key-type=dsa"])

  AssertRedirectedCommand(["gnt-cluster", "upgrade", "--to", other_version])
  AssertRedirectedCommand(["gnt-cluster", "verify"])

  for instance in live_instances:
    qa_instance.TestInstanceRemove(instance)
    instance.Release()
  live_instances = []
  for (cf, n) in inst_creates:
    nodes = qa_config.AcquireManyNodes(n)
    live_instances.append(cf(nodes))

  AssertRedirectedCommand(["gnt-cluster", "upgrade", "--to", this_version])
  AssertRedirectedCommand(["gnt-cluster", "verify"])

  for instance in live_instances:
    qa_instance.TestInstanceRemove(instance)
    instance.Release()


def _NodeQueueDrainFile(node):
  """Returns path to queue drain file for a node.

  """
  return qa_utils.MakeNodePath(node, pathutils.JOB_QUEUE_DRAIN_FILE)


def _AssertDrainFile(node, **kwargs):
  """Checks for the queue drain file.

  """
  AssertCommand(["test", "-f", _NodeQueueDrainFile(node)], node=node, **kwargs)


def TestClusterMasterFailoverWithDrainedQueue():
  """gnt-cluster master-failover with drained queue"""
  master = qa_config.GetMasterNode()
  failovermaster = qa_config.AcquireNode(exclude=master)

  # Ensure queue is not drained
  for node in [master, failovermaster]:
    _AssertDrainFile(node, fail=True)

  # Drain queue on failover master
  AssertCommand(["touch", _NodeQueueDrainFile(failovermaster)],
                node=failovermaster)

  cmd = ["gnt-cluster", "master-failover"]
  try:
    _AssertDrainFile(failovermaster)
    AssertCommand(cmd, node=failovermaster)
    _AssertDrainFile(master, fail=True)
    _AssertDrainFile(failovermaster, fail=True)

    # Back to original master node
    AssertCommand(cmd, node=master)
  finally:
    failovermaster.Release()

  # Ensure queue is not drained
  for node in [master, failovermaster]:
    _AssertDrainFile(node, fail=True)


def TestClusterCopyfile():
  """gnt-cluster copyfile"""
  master = qa_config.GetMasterNode()

  uniqueid = utils.NewUUID()

  # Create temporary file
  f = tempfile.NamedTemporaryFile(mode="w")
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
  es_path = ["Default node parameters", "exclusive_storage"]
  oldvalue = _GetClusterField(es_path)
  AssertCommand(["gnt-cluster", "modify", "--node-parameters",
                 "exclusive_storage=%s" % newvalue])
  effvalue = _GetClusterField(es_path)
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
  AssertClusterVerify(fail=False,
                      warnings=[constants.CV_ENODEORPHANLV])
  AssertCommand(["lvcreate", "-L1G", "-n", lvname2, vgname], node=node_name)
  AssertClusterVerify(fail=True,
                      errors=[constants.CV_ENODELVM],
                      warnings=[constants.CV_ENODEORPHANLV])
  AssertCommand(["lvremove", "-f", "/".join([vgname, lvname1])], node=node_name)
  AssertCommand(["lvremove", "-f", "/".join([vgname, lvname2])], node=node_name)
  AssertClusterVerify()


def TestInstanceCommunication():
  """Tests instance communication via 'gnt-cluster modify'"""
  master = qa_config.GetMasterNode()

  # Check that the 'default' node group exists
  cmd = ["gnt-group", "list", "--no-headers", "-o", "name"]
  result_output = GetCommandOutput(master.primary, utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "default", msg="Checking 'default' group")

  # Check that no networks exist
  cmd = ["gnt-network", "list", "--no-headers", "-o", "name"]
  result_output = GetCommandOutput(master.primary, utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "", msg="Checking networks")

  # Modify cluster parameter 'instance-communication-network' and
  # check whether the cluster creates the instance communication
  # network and connects it to the 'default' node group
  network_name = "mynetwork"

  cmd = "gnt-cluster modify --instance-communication-network=%s" % network_name
  result_output = qa_utils.GetCommandOutput(master.primary, cmd)
  print(result_output)

  cmd = ["gnt-network", "list", "--no-headers", "-o", "name", network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "mynetwork", msg="Checking 'mynetwork'")

  cmd = ["gnt-network", "list", "--no-headers", "-o", "group_list",
         network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  # <nodegroup> (<mode>, <link>, <vlan>), for this test, VLAN is nothing
  AssertEqual(result_output.strip(), "default (routed, communication_rt, )",
              msg="Checking network connected groups")

  # Check that the network has the parameters necessary for instance
  # communication
  cmd = ["gnt-network", "list", "--no-headers", "-o", "gateway",
         network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "-", msg="Checking gateway")

  cmd = ["gnt-network", "list", "--no-headers", "-o", "gateway6",
         network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "-", msg="Checking gateway6")

  cmd = ["gnt-network", "list", "--no-headers", "-o", "network",
         network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTANCE_COMMUNICATION_NETWORK4,
              msg="Checking network")

  cmd = ["gnt-network", "list", "--no-headers", "-o", "network6",
         network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTANCE_COMMUNICATION_NETWORK6,
              msg="Checking network6")

  # Add a new group and check whether the instance communication
  # network connects to this new group
  #
  # We don't assume any particular group order and allow the output of
  # 'gnt-network list' to print the 'default' and 'mygroup' groups in
  # any order.
  group = "mygroup"

  cmd = ["gnt-group", "add", group]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  print(result_output)

  cmd = ["gnt-network", "list", "--no-headers", "-o", "group_list",
         network_name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))

  try:
    r1 = "mygroup (routed, communication_rt, )," \
         " default (routed, communication_rt, )"
    AssertEqual(result_output.strip(), r1,
                msg="Checking network connected groups")
  except qa_error.Error:
    r2 = "default (routed, communication_rt, )," \
         " mygroup (routed, communication_rt, )"
    AssertEqual(result_output.strip(), r2,
                msg="Checking network connected groups")

  # Modify cluster parameter 'instance-communication-network' to the
  # same value and check that nothing happens.
  cmd = "gnt-cluster modify --instance-communication-network=%s" % network_name
  result_output = qa_utils.GetCommandOutput(master.primary, cmd)
  print(result_output)

  # Disable instance communication network, disconnect the instance
  # communication network and remove it, and remove the group
  cmd = "gnt-cluster modify --instance-communication-network="
  result_output = qa_utils.GetCommandOutput(master.primary, cmd)
  print(result_output)

  cmd = ["gnt-network", "disconnect", network_name]
  AssertCommand(utils.ShellQuoteArgs(cmd))

  cmd = ["gnt-network", "remove", network_name]
  AssertCommand(utils.ShellQuoteArgs(cmd))

  cmd = ["gnt-group", "remove", group]
  AssertCommand(utils.ShellQuoteArgs(cmd))

  # Check that the 'default' node group exists
  cmd = ["gnt-group", "list", "--no-headers", "-o", "name"]
  result_output = GetCommandOutput(master.primary, utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "default", msg="Checking 'default' group")

  # Check that no networks exist
  cmd = ["gnt-network", "list", "--no-headers", "-o", "name"]
  result_output = GetCommandOutput(master.primary, utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), "", msg="Checking networks")
