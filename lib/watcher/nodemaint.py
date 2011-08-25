#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""Module doing node maintenance for Ganeti watcher.

"""

import logging

from ganeti import bdev
from ganeti import constants
from ganeti import errors
from ganeti import hypervisor
from ganeti import netutils
from ganeti import ssconf
from ganeti import utils
from ganeti import confd

import ganeti.confd.client # pylint: disable-msg=W0611


class NodeMaintenance(object):
  """Talks to confd daemons and possible shutdown instances/drbd devices.

  """
  def __init__(self):
    self.store_cb = confd.client.StoreResultCallback()
    self.filter_cb = confd.client.ConfdFilterCallback(self.store_cb)
    self.confd_client = confd.client.GetConfdClient(self.filter_cb)

  @staticmethod
  def ShouldRun():
    """Checks whether node maintenance should run.

    """
    try:
      return ssconf.SimpleStore().GetMaintainNodeHealth()
    except errors.ConfigurationError, err:
      logging.error("Configuration error, not activating node maintenance: %s",
                    err)
      return False

  @staticmethod
  def GetRunningInstances():
    """Compute list of hypervisor/running instances.

    """
    hyp_list = ssconf.SimpleStore().GetHypervisorList()
    results = []
    for hv_name in hyp_list:
      try:
        hv = hypervisor.GetHypervisor(hv_name)
        ilist = hv.ListInstances()
        results.extend([(iname, hv_name) for iname in ilist])
      except: # pylint: disable-msg=W0702
        logging.error("Error while listing instances for hypervisor %s",
                      hv_name, exc_info=True)
    return results

  @staticmethod
  def GetUsedDRBDs():
    """Get list of used DRBD minors.

    """
    return bdev.DRBD8.GetUsedDevs().keys()

  @classmethod
  def DoMaintenance(cls, role):
    """Maintain the instance list.

    """
    if role == constants.CONFD_NODE_ROLE_OFFLINE:
      inst_running = cls.GetRunningInstances()
      cls.ShutdownInstances(inst_running)
      drbd_running = cls.GetUsedDRBDs()
      cls.ShutdownDRBD(drbd_running)
    else:
      logging.debug("Not doing anything for role %s", role)

  @staticmethod
  def ShutdownInstances(inst_running):
    """Shutdown running instances.

    """
    names_running = set([i[0] for i in inst_running])
    if names_running:
      logging.info("Following instances should not be running,"
                   " shutting them down: %s", utils.CommaJoin(names_running))
      # this dictionary will collapse duplicate instance names (only
      # xen pvm/vhm) into a single key, which is fine
      i2h = dict(inst_running)
      for name in names_running:
        hv_name = i2h[name]
        hv = hypervisor.GetHypervisor(hv_name)
        hv.StopInstance(None, force=True, name=name)

  @staticmethod
  def ShutdownDRBD(drbd_running):
    """Shutdown active DRBD devices.

    """
    if drbd_running:
      logging.info("Following DRBD minors should not be active,"
                   " shutting them down: %s", utils.CommaJoin(drbd_running))
      for minor in drbd_running:
        # pylint: disable-msg=W0212
        # using the private method as is, pending enhancements to the DRBD
        # interface
        bdev.DRBD8._ShutdownAll(minor)

  def Exec(self):
    """Check node status versus cluster desired state.

    """
    my_name = netutils.Hostname.GetSysName()
    req = \
      confd.client.ConfdClientRequest(type=constants.CONFD_REQ_NODE_ROLE_BYNAME,
                                      query=my_name)
    self.confd_client.SendRequest(req, async=False, coverage=-1)
    timed_out, _, _ = self.confd_client.WaitForReply(req.rsalt)
    if not timed_out:
      # should have a valid response
      status, result = self.store_cb.GetResponse(req.rsalt)
      assert status, "Missing result but received replies"
      if not self.filter_cb.consistent[req.rsalt]:
        logging.warning("Inconsistent replies, not doing anything")
        return
      self.DoMaintenance(result.server_reply.answer)
    else:
      logging.warning("Confd query timed out, cannot do maintenance actions")
