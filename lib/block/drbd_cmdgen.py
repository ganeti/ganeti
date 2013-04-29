#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""DRBD command generating classes"""

import logging
import shlex

from ganeti import constants
from ganeti import errors


class DRBD83CmdGenerator(object):
  """Generates drbdsetup commands suited for the DRBD <= 8.3 syntax

  """
  # command line options for barriers
  _DISABLE_DISK_OPTION = "--no-disk-barrier"  # -a
  _DISABLE_DRAIN_OPTION = "--no-disk-drain"   # -D
  _DISABLE_FLUSH_OPTION = "--no-disk-flushes" # -i
  _DISABLE_META_FLUSH_OPTION = "--no-md-flushes"  # -m

  def __init__(self, drbd_info):
    self._drbd_info = drbd_info

  def GenShowCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "show"]

  def GenLocalInitCmds(self, minor, data_dev, meta_dev, size_mb, params):
    args = ["drbdsetup", self._DevPath(minor), "disk",
            data_dev, meta_dev, "0",
            "-e", "detach",
            "--create-device"]
    if size_mb:
      args.extend(["-d", "%sm" % size_mb])

    version = self._drbd_info.GetVersion()
    vmaj = version["k_major"]
    vmin = version["k_minor"]
    vrel = version["k_point"]

    barrier_args = \
      self._ComputeDiskBarrierArgs(vmaj, vmin, vrel,
                                   params[constants.LDP_BARRIERS],
                                   params[constants.LDP_NO_META_FLUSH])
    args.extend(barrier_args)

    if params[constants.LDP_DISK_CUSTOM]:
      args.extend(shlex.split(params[constants.LDP_DISK_CUSTOM]))

    return [args]

  def GenNetInitCmd(self, minor, family, lhost, lport, rhost, rport, protocol,
                    dual_pri, hmac, secret, params):
    args = ["drbdsetup", self._DevPath(minor), "net",
            "%s:%s:%s" % (family, lhost, lport),
            "%s:%s:%s" % (family, rhost, rport), protocol,
            "-A", "discard-zero-changes",
            "-B", "consensus",
            "--create-device",
            ]
    if dual_pri:
      args.append("-m")
    if hmac and secret:
      args.extend(["-a", hmac, "-x", secret])

    if params[constants.LDP_NET_CUSTOM]:
      args.extend(shlex.split(params[constants.LDP_NET_CUSTOM]))

    return args

  def GenSyncParamsCmd(self, minor, params):
    args = ["drbdsetup", self._DevPath(minor), "syncer"]
    if params[constants.LDP_DYNAMIC_RESYNC]:
      version = self._drbd_info.GetVersion()
      vmin = version["k_minor"]
      vrel = version["k_point"]

      # By definition we are using 8.x, so just check the rest of the version
      # number
      if vmin != 3 or vrel < 9:
        msg = ("The current DRBD version (8.%d.%d) does not support the "
               "dynamic resync speed controller" % (vmin, vrel))
        logging.error(msg)
        return [msg]

      if params[constants.LDP_PLAN_AHEAD] == 0:
        msg = ("A value of 0 for c-plan-ahead disables the dynamic sync speed"
               " controller at DRBD level. If you want to disable it, please"
               " set the dynamic-resync disk parameter to False.")
        logging.error(msg)
        return [msg]

      # add the c-* parameters to args
      args.extend(["--c-plan-ahead", params[constants.LDP_PLAN_AHEAD],
                   "--c-fill-target", params[constants.LDP_FILL_TARGET],
                   "--c-delay-target", params[constants.LDP_DELAY_TARGET],
                   "--c-max-rate", params[constants.LDP_MAX_RATE],
                   "--c-min-rate", params[constants.LDP_MIN_RATE],
                   ])

    else:
      args.extend(["-r", "%d" % params[constants.LDP_RESYNC_RATE]])

    args.append("--create-device")

    return args

  def GenPauseSyncCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "pause-sync"]

  def GenResumeSyncCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "resume-sync"]

  def GenPrimaryCmd(self, minor, force):
    cmd = ["drbdsetup", self._DevPath(minor), "primary"]

    if force:
      cmd.append("-o")

    return cmd

  def GenSecondaryCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "secondary"]

  def GenDetachCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "detach"]

  def GenDisconnectCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "disconnect"]

  def GenDownCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "down"]

  def GenResizeCmd(self, minor, size_mb):
    return ["drbdsetup", self._DevPath(minor), "resize", "-s", "%dm" % size_mb]

  @staticmethod
  def _DevPath(minor):
    """Return the path to a drbd device for a given minor.

    """
    return "/dev/drbd%d" % minor

  @classmethod
  def _ComputeDiskBarrierArgs(cls, vmaj, vmin, vrel, disabled_barriers,
                              disable_meta_flush):
    """Compute the DRBD command line parameters for disk barriers

    Returns a list of the disk barrier parameters as requested via the
    disabled_barriers and disable_meta_flush arguments, and according to the
    supported ones in the DRBD version vmaj.vmin.vrel

    If the desired option is unsupported, raises errors.BlockDeviceError.

    """
    disabled_barriers_set = frozenset(disabled_barriers)
    if not disabled_barriers_set in constants.DRBD_VALID_BARRIER_OPT:
      raise errors.BlockDeviceError("%s is not a valid option set for DRBD"
                                    " barriers" % disabled_barriers)

    args = []

    # The following code assumes DRBD 8.x, with x < 4 and x != 1 (DRBD 8.1.x
    # does not exist)
    if not vmaj == 8 and vmin in (0, 2, 3):
      raise errors.BlockDeviceError("Unsupported DRBD version: %d.%d.%d" %
                                    (vmaj, vmin, vrel))

    def _AppendOrRaise(option, min_version):
      """Helper for DRBD options"""
      if min_version is not None and vrel >= min_version:
        args.append(option)
      else:
        raise errors.BlockDeviceError("Could not use the option %s as the"
                                      " DRBD version %d.%d.%d does not support"
                                      " it." % (option, vmaj, vmin, vrel))

    # the minimum version for each feature is encoded via pairs of (minor
    # version -> x) where x is version in which support for the option was
    # introduced.
    meta_flush_supported = disk_flush_supported = {
      0: 12,
      2: 7,
      3: 0,
      }

    disk_drain_supported = {
      2: 7,
      3: 0,
      }

    disk_barriers_supported = {
      3: 0,
      }

    # meta flushes
    if disable_meta_flush:
      _AppendOrRaise(cls._DISABLE_META_FLUSH_OPTION,
                     meta_flush_supported.get(vmin, None))

    # disk flushes
    if constants.DRBD_B_DISK_FLUSH in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_FLUSH_OPTION,
                     disk_flush_supported.get(vmin, None))

    # disk drain
    if constants.DRBD_B_DISK_DRAIN in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_DRAIN_OPTION,
                     disk_drain_supported.get(vmin, None))

    # disk barriers
    if constants.DRBD_B_DISK_BARRIERS in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_DISK_OPTION,
                     disk_barriers_supported.get(vmin, None))

    return args
