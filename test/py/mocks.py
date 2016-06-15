#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Module implementing a fake ConfigWriter"""


import os

from ganeti import locking
from ganeti import netutils


FAKE_CLUSTER_KEY = ("AAAAB3NzaC1yc2EAAAABIwAAAQEAsuGLw70et3eApJ/ZEJkAVZogIrm"
                    "EYPQJvb1ll52Ti0nr80Wztxibaa8bYGzY22rQIAloIlePeTGcJceAYK"
                    "PZgm0I/Mp2EUGg2NVsQZIzasz6cW0vYuiUbF9GkVlROmvOAykT58RfM"
                    "L8RhPrjrQxZc+NXgZtgDugYSZcXHDLUyWM1xKUoYy0MqYG6ZXCC/Zno"
                    "RThhmjOJgEmvwrMcTWQjmzH3NeJAxaBsEHR8tiVZ/Y23C/ULWLyNT6R"
                    "fB+DE7IovsMQaS+83AK1Teg7RWNyQczachatf/JT8VjUqFYjJepPjMb"
                    "vYdB2nQds7/+Bf40C/OpbvnAxna1kVtgFHAo18cQ==")


class FakeConfig(object):
  """Fake configuration object"""
  def __init__(self):
    self.write_count = 0

  def OutDate(self):
    pass

  def IsCluster(self):
    return True

  def GetNodeList(self):
    return ["a", "b", "c"]

  def GetRsaHostKey(self):
    return FAKE_CLUSTER_KEY

  def GetDsaHostKey(self):
    return FAKE_CLUSTER_KEY

  def GetClusterName(self):
    return "test.cluster"

  def GetMasterNode(self):
    return "a"

  def GetMasterNodeName(self):
    return netutils.Hostname.GetSysName()

  def GetDefaultIAllocator(self):
    return "testallocator"

  def GetNodeName(self, node_uuid):
    if node_uuid in self.GetNodeList():
      return "node_%s.example.com" % (node_uuid,)
    else:
      return None

  def GetNodeNames(self, node_uuids):
    return map(self.GetNodeName, node_uuids)


class FakeProc(object):
  """Fake processor object"""

  def Log(self, msg, *args, **kwargs):
    pass

  def LogWarning(self, msg, *args, **kwargs):
    pass

  def LogInfo(self, msg, *args, **kwargs):
    pass

  def LogStep(self, current, total, message):
    pass


class FakeGLM(object):
  """Fake global lock manager object"""

  def list_owned(self, _):
    return set()


class FakeContext(object):
  """Fake context object"""
  # pylint: disable=W0613

  def __init__(self):
    self.cfg = FakeConfig()
    self.glm = FakeGLM()

  def GetConfig(self, ec_id):
    return self.cfg

  def GetRpc(self, cfg):
    return None

  def GetWConfdContext(self, ec_id):
    return (None, None, None)


class FakeGetentResolver(object):
  """Fake runtime.GetentResolver"""

  def __init__(self):
    # As we nomally don't run under root we use our own uid/gid for all
    # fields. This way we don't run into permission denied problems.
    uid = os.getuid()
    gid = os.getgid()

    self.masterd_uid = uid
    self.masterd_gid = gid
    self.confd_uid = uid
    self.confd_gid = gid
    self.rapi_uid = uid
    self.rapi_gid = gid
    self.noded_uid = uid
    self.noded_gid = gid

    self.daemons_gid = gid
    self.admin_gid = gid

  def LookupUid(self, uid):
    return "user%s" % uid

  def LookupGid(self, gid):
    return "group%s" % gid


class FakeLU(object):
  HPATH = "fake-lu"
  HTYPE = None

  def __init__(self, processor, op, cfg, rpc_runner, prereq_err):
    self.proc = processor
    self.cfg = cfg
    self.op = op
    self.rpc = rpc_runner
    self.prereq_err = prereq_err

    self.needed_locks = {}
    self.opportunistic_locks = dict.fromkeys(locking.LEVELS, False)
    self.dont_collate_locks = dict.fromkeys(locking.LEVELS, False)
    self.add_locks = {}

    self.LogWarning = processor.LogWarning # pylint: disable=C0103

  def CheckArguments(self):
    pass

  def ExpandNames(self):
    pass

  def DeclareLocks(self, level):
    pass

  def CheckPrereq(self):
    if self.prereq_err:
      raise self.prereq_err

  def Exec(self, feedback_fn):
    pass

  def BuildHooksNodes(self):
    return ([], [])

  def BuildHooksEnv(self):
    return {}

  def PreparePostHookNodes(self, post_hook_node_uuids):
    # pylint: disable=W0613
    return []

  def HooksCallBack(self, phase, hook_results, feedback_fn, lu_result):
    # pylint: disable=W0613
    return lu_result
