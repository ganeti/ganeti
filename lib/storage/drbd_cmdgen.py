#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""DRBD command generating classes"""

import logging
import shlex

from ganeti import constants
from ganeti import errors


class BaseDRBDCmdGenerator(object):
  """Base class for DRBD command generators.

  This class defines the interface for the command generators and holds shared
  code.

  """
  def __init__(self, version):
    self._version = version

  def GenShowCmd(self, minor):
    raise NotImplementedError

  def GenInitMetaCmd(self, minor, meta_dev):
    raise NotImplementedError

  def GenLocalInitCmds(self, minor, data_dev, meta_dev, size_mb, params):
    raise NotImplementedError

  def GenNetInitCmd(self, minor, family, lhost, lport, rhost, rport, protocol,
                    dual_pri, hmac, secret, params):
    raise NotImplementedError

  def GenSyncParamsCmd(self, minor, params):
    raise NotImplementedError

  def GenPauseSyncCmd(self, minor):
    raise NotImplementedError

  def GenResumeSyncCmd(self, minor):
    raise NotImplementedError

  def GenPrimaryCmd(self, minor, force):
    raise NotImplementedError

  def GenSecondaryCmd(self, minor):
    raise NotImplementedError

  def GenDetachCmd(self, minor):
    raise NotImplementedError

  def GenDisconnectCmd(self, minor, family, lhost, lport, rhost, rport):
    raise NotImplementedError

  def GenDownCmd(self, minor):
    raise NotImplementedError

  def GenResizeCmd(self, minor, size_mb):
    raise NotImplementedError

  @staticmethod
  def _DevPath(minor):
    """Return the path to a drbd device for a given minor.

    """
    return "/dev/drbd%d" % minor


class DRBD83CmdGenerator(BaseDRBDCmdGenerator):
  """Generates drbdsetup commands suited for the DRBD <= 8.3 syntax.

  """
  # command line options for barriers
  _DISABLE_DISK_OPTION = "--no-disk-barrier"  # -a
  _DISABLE_DRAIN_OPTION = "--no-disk-drain"   # -D
  _DISABLE_FLUSH_OPTION = "--no-disk-flushes" # -i
  _DISABLE_META_FLUSH_OPTION = "--no-md-flushes"  # -m

  def __init__(self, version):
    super(DRBD83CmdGenerator, self).__init__(version)

  def GenShowCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "show"]

  def GenInitMetaCmd(self, minor, meta_dev):
    return ["drbdmeta", "--force", self._DevPath(minor),
            "v08", meta_dev, "0", "create-md"]

  def GenLocalInitCmds(self, minor, data_dev, meta_dev, size_mb, params):
    args = ["drbdsetup", self._DevPath(minor), "disk",
            data_dev, meta_dev, "0",
            "-e", "detach",
            "--create-device"]
    if size_mb:
      args.extend(["-d", "%sm" % size_mb])

    vmaj = self._version["k_major"]
    vmin = self._version["k_minor"]
    vrel = self._version["k_point"]

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
      vmin = self._version["k_minor"]
      vrel = self._version["k_point"]

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

  def GenDisconnectCmd(self, minor, family, lhost, lport, rhost, rport):
    return ["drbdsetup", self._DevPath(minor), "disconnect"]

  def GenDownCmd(self, minor):
    return ["drbdsetup", self._DevPath(minor), "down"]

  def GenResizeCmd(self, minor, size_mb):
    return ["drbdsetup", self._DevPath(minor), "resize", "-s", "%dm" % size_mb]

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


class DRBD84CmdGenerator(BaseDRBDCmdGenerator):
  """Generates drbdsetup commands suited for the DRBD >= 8.4 syntax.

  """
  # command line options for barriers
  _DISABLE_DISK_OPTION = "--disk-barrier=no"
  _DISABLE_DRAIN_OPTION = "--disk-drain=no"
  _DISABLE_FLUSH_OPTION = "--disk-flushes=no"
  _DISABLE_META_FLUSH_OPTION = "--md-flushes=no"

  def __init__(self, version):
    super(DRBD84CmdGenerator, self).__init__(version)

  def GenShowCmd(self, minor):
    return ["drbdsetup", "show", minor]

  def GenInitMetaCmd(self, minor, meta_dev):
    return ["drbdmeta", "--force", self._DevPath(minor),
            "v08", meta_dev, "flex-external", "create-md"]

  def GenLocalInitCmds(self, minor, data_dev, meta_dev, size_mb, params):
    cmds = []

    cmds.append(["drbdsetup", "new-resource", self._GetResource(minor)])
    cmds.append(["drbdsetup", "new-minor", self._GetResource(minor),
                 str(minor), "0"])
    # We need to apply the activity log before attaching the disk else drbdsetup
    # will fail.
    cmds.append(["drbdmeta", self._DevPath(minor),
                 "v08", meta_dev, "flex-external", "apply-al"])

    attach_cmd = ["drbdsetup", "attach", minor, data_dev, meta_dev, "flexible",
                  "--on-io-error=detach"]
    if size_mb:
      attach_cmd.extend(["--size", "%sm" % size_mb])

    barrier_args = \
      self._ComputeDiskBarrierArgs(params[constants.LDP_BARRIERS],
                                   params[constants.LDP_NO_META_FLUSH])
    attach_cmd.extend(barrier_args)

    if params[constants.LDP_DISK_CUSTOM]:
      attach_cmd.extend(shlex.split(params[constants.LDP_DISK_CUSTOM]))

    cmds.append(attach_cmd)

    return cmds

  def GenNetInitCmd(self, minor, family, lhost, lport, rhost, rport, protocol,
                    dual_pri, hmac, secret, params):
    args = ["drbdsetup", "connect", self._GetResource(minor),
            "%s:%s:%s" % (family, lhost, lport),
            "%s:%s:%s" % (family, rhost, rport),
            "--protocol", protocol,
            "--after-sb-0pri", "discard-zero-changes",
            "--after-sb-1pri", "consensus"
            ]
    if dual_pri:
      args.append("--allow-two-primaries")
    if hmac and secret:
      args.extend(["--cram-hmac-alg", hmac, "--shared-secret", secret])

    if params[constants.LDP_NET_CUSTOM]:
      args.extend(shlex.split(params[constants.LDP_NET_CUSTOM]))

    return args

  def GenSyncParamsCmd(self, minor, params):
    args = ["drbdsetup", "disk-options", minor]
    if params[constants.LDP_DYNAMIC_RESYNC]:
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
      args.extend(["--resync-rate", "%d" % params[constants.LDP_RESYNC_RATE]])

    return args

  def GenPauseSyncCmd(self, minor):
    return ["drbdsetup", "pause-sync", minor]

  def GenResumeSyncCmd(self, minor):
    return ["drbdsetup", "resume-sync", minor]

  def GenPrimaryCmd(self, minor, force):
    cmd = ["drbdsetup", "primary", minor]

    if force:
      cmd.append("--force")

    return cmd

  def GenSecondaryCmd(self, minor):
    return ["drbdsetup", "secondary", minor]

  def GenDetachCmd(self, minor):
    return ["drbdsetup", "detach", minor]

  def GenDisconnectCmd(self, minor, family, lhost, lport, rhost, rport):
    return ["drbdsetup", "disconnect",
            "%s:%s:%s" % (family, lhost, lport),
            "%s:%s:%s" % (family, rhost, rport)]

  def GenDownCmd(self, minor):
    return ["drbdsetup", "down", self._GetResource(minor)]

  def GenResizeCmd(self, minor, size_mb):
    return ["drbdsetup", "resize", minor, "--size", "%dm" % size_mb]

  @staticmethod
  def _GetResource(minor):
    """Return the resource name for a given minor.

    Currently we don't support DRBD volumes which share a resource, so we
    generate the resource name based on the minor the resulting volumes is
    assigned to.

    """
    return "resource%d" % minor

  @classmethod
  def _ComputeDiskBarrierArgs(cls, disabled_barriers, disable_meta_flush):
    """Compute the DRBD command line parameters for disk barriers

    """
    disabled_barriers_set = frozenset(disabled_barriers)
    if not disabled_barriers_set in constants.DRBD_VALID_BARRIER_OPT:
      raise errors.BlockDeviceError("%s is not a valid option set for DRBD"
                                    " barriers" % disabled_barriers)

    args = []

    # meta flushes
    if disable_meta_flush:
      args.append(cls._DISABLE_META_FLUSH_OPTION)

    # disk flushes
    if constants.DRBD_B_DISK_FLUSH in disabled_barriers_set:
      args.append(cls._DISABLE_FLUSH_OPTION)

    # disk drain
    if constants.DRBD_B_DISK_DRAIN in disabled_barriers_set:
      args.append(cls._DISABLE_DRAIN_OPTION)

    # disk barriers
    if constants.DRBD_B_DISK_BARRIERS in disabled_barriers_set:
      args.append(cls._DISABLE_DISK_OPTION)

    return args
