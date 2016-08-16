#
#

# Copyright (C) 2013 Google Inc.
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


"""QA utility functions for managing instances

"""

from ganeti import utils
from ganeti import constants
from ganeti import pathutils

import qa_config
import qa_error
import qa_utils

from qa_utils import AssertIn, AssertCommand


def RemoveInstance(instance):
  AssertCommand(["gnt-instance", "remove", "-f", instance.name])


def GetGenericAddParameters(inst, disk_template, force_mac=None):
  params = ["-B"]
  params.append("%s=%s,%s=%s" % (constants.BE_MINMEM,
                                 qa_config.get(constants.BE_MINMEM),
                                 constants.BE_MAXMEM,
                                 qa_config.get(constants.BE_MAXMEM)))

  if disk_template != constants.DT_DISKLESS:
    for idx, disk in enumerate(qa_config.GetDiskOptions()):
      size = disk.get("size")
      name = disk.get("name")
      diskparams = "%s:size=%s" % (idx, size)
      if name:
        diskparams += ",name=%s" % name
      if qa_config.AreSpindlesSupported():
        spindles = disk.get("spindles")
        if spindles is None:
          raise qa_error.Error("'spindles' is a required parameter for disks"
                               " when you enable exclusive storage tests")
        diskparams += ",spindles=%s" % spindles
      params.extend(["--disk", diskparams])

  # Set static MAC address if configured
  if force_mac:
    nic0_mac = force_mac
  else:
    nic0_mac = inst.GetNicMacAddr(0, None)

  if nic0_mac:
    params.extend(["--net", "0:mac=%s" % nic0_mac])

  return params


def _CreateInstanceByDiskTemplateRaw(nodes_spec, disk_template, fail=False):
  """Creates an instance with the given disk template on the given nodes(s).
     Note that this function does not check if enough nodes are given for
     the respective disk template.

  @type nodes_spec: string
  @param nodes_spec: string specification of one node (by node name) or several
                     nodes according to the requirements of the disk template
  @type disk_template: string
  @param disk_template: the disk template to be used by the instance
  @return: the created instance

  """
  instance = qa_config.AcquireInstance()
  try:
    cmd = (["gnt-instance", "add",
            "--os-type=%s" % qa_config.get("os"),
            "--disk-template=%s" % disk_template,
            "--node=%s" % nodes_spec] +
           GetGenericAddParameters(instance, disk_template))
    cmd.append(instance.name)

    AssertCommand(cmd, fail=fail)

    if not fail:
      CheckSsconfInstanceList(instance.name)
      instance.SetDiskTemplate(disk_template)

      return instance
  except:
    instance.Release()
    raise

  # Handle the case where creation is expected to fail
  assert fail
  instance.Release()
  return None


def CreateInstanceDrbd8(nodes, fail=False):
  """Creates an instance using disk template 'drbd' on the given nodes.

  @type nodes: list of nodes
  @param nodes: nodes to be used by the instance
  @return: the created instance

  """
  assert len(nodes) > 1
  return _CreateInstanceByDiskTemplateRaw(
    ":".join(n.primary for n in nodes), constants.DT_DRBD8, fail=fail)


def CreateInstanceByDiskTemplateOneNode(nodes, disk_template, fail=False):
  """Creates an instance using the given disk template for disk templates
     for which one given node is sufficient. These templates are for example:
     plain, diskless, file, sharedfile, blockdev, rados.

  @type nodes: list of nodes
  @param nodes: a list of nodes, whose first element is used to create the
                instance
  @type disk_template: string
  @param disk_template: the disk template to be used by the instance
  @return: the created instance

  """
  assert len(nodes) > 0
  return _CreateInstanceByDiskTemplateRaw(nodes[0].primary, disk_template,
                                          fail=fail)


def CreateInstanceByDiskTemplate(nodes, disk_template, fail=False):
  """Given a disk template, this function creates an instance using
     the template. It uses the required number of nodes depending on
     the disk template. This function is intended to be used by tests
     that don't care about the specifics of the instance other than
     that it uses the given disk template.

     Note: If you use this function, make sure to call
     'TestInstanceRemove' at the end of your tests to avoid orphaned
     instances hanging around and interfering with the following tests.

  @type nodes: list of nodes
  @param nodes: the list of the nodes on which the instance will be placed;
                it needs to have sufficiently many elements for the given
                disk template
  @type disk_template: string
  @param disk_template: the disk template to be used by the instance
  @return: the created instance

  """
  if disk_template == constants.DT_DRBD8:
    return CreateInstanceDrbd8(nodes, fail=fail)
  elif disk_template in [constants.DT_DISKLESS, constants.DT_PLAIN,
                         constants.DT_FILE]:
    return CreateInstanceByDiskTemplateOneNode(nodes, disk_template, fail=fail)
  else:
    # FIXME: This assumes that for all other disk templates, we only need one
    # node and no disk template specific parameters. This else-branch is
    # currently only used in cases where we expect failure. Extend it when
    # QA needs for these templates change.
    return CreateInstanceByDiskTemplateOneNode(nodes, disk_template, fail=fail)


def _ReadSsconfInstanceList():
  """Reads ssconf_instance_list from the master node.

  """
  master = qa_config.GetMasterNode()

  ssconf_path = utils.PathJoin(pathutils.DATA_DIR,
                               "ssconf_%s" % constants.SS_INSTANCE_LIST)

  cmd = ["cat", qa_utils.MakeNodePath(master, ssconf_path)]

  return qa_utils.GetCommandOutput(master.primary,
                                   utils.ShellQuoteArgs(cmd)).splitlines()


def CheckSsconfInstanceList(instance):
  """Checks if a certain instance is in the ssconf instance list.

  @type instance: string
  @param instance: Instance name

  """
  AssertIn(qa_utils.ResolveInstanceName(instance),
           _ReadSsconfInstanceList())
