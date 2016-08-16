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

"""Gluster storage class.

This class is very similar to FileStorage, given that Gluster when mounted
behaves essentially like a regular file system. Unlike RBD, there are no
special provisions for block device abstractions (yet).

"""
import logging
import os
import socket

from ganeti import utils
from ganeti import errors
from ganeti import netutils
from ganeti import constants
from ganeti import ssconf

from ganeti.utils import io
from ganeti.storage import base
from ganeti.storage.filestorage import FileDeviceHelper


class GlusterVolume(object):
  """This class represents a Gluster volume.

  Volumes are uniquely identified by:

    - their IP address
    - their port
    - the volume name itself

  Two GlusterVolume objects x, y with same IP address, port and volume name
  are considered equal.

  """

  def __init__(self, server_addr, port, volume, _run_cmd=utils.RunCmd,
               _mount_point=None):
    """Creates a Gluster volume object.

    @type server_addr: str
    @param server_addr: The address to connect to

    @type port: int
    @param port: The port to connect to (Gluster standard is 24007)

    @type volume: str
    @param volume: The gluster volume to use for storage.

    """
    self.server_addr = server_addr
    server_ip = netutils.Hostname.GetIP(self.server_addr)
    self._server_ip = server_ip
    port = netutils.ValidatePortNumber(port)
    self._port = port
    self._volume = volume
    if _mount_point: # tests
      self.mount_point = _mount_point
    else:
      self.mount_point = ssconf.SimpleStore().GetGlusterStorageDir()

    self._run_cmd = _run_cmd

  @property
  def server_ip(self):
    return self._server_ip

  @property
  def port(self):
    return self._port

  @property
  def volume(self):
    return self._volume

  def __eq__(self, other):
    return (self.server_ip, self.port, self.volume) == \
           (other.server_ip, other.port, other.volume)

  def __repr__(self):
    return """GlusterVolume("{ip}", {port}, "{volume}")""" \
             .format(ip=self.server_ip, port=self.port, volume=self.volume)

  def __hash__(self):
    return (self.server_ip, self.port, self.volume).__hash__()

  def _IsMounted(self):
    """Checks if we are mounted or not.

    @rtype: bool
    @return: True if this volume is mounted.

    """
    if not os.path.exists(self.mount_point):
      return False

    return os.path.ismount(self.mount_point)

  def _GuessMountFailReasons(self):
    """Try and give reasons why the mount might've failed.

    @rtype: str
    @return: A semicolon-separated list of problems found with the current setup
             suitable for display to the user.

    """

    reasons = []

    # Does the mount point exist?
    if not os.path.exists(self.mount_point):
      reasons.append("%r: does not exist" % self.mount_point)

    # Okay, it exists, but is it a directory?
    elif not os.path.isdir(self.mount_point):
      reasons.append("%r: not a directory" % self.mount_point)

    # If, for some unfortunate reason, this folder exists before mounting:
    #
    #   /var/run/ganeti/gluster/gv0/10.0.0.1:30000:gv0/
    #   '--------- cwd ------------'
    #
    # and you _are_ trying to mount the gluster volume gv0 on 10.0.0.1:30000,
    # then the mount.glusterfs command parser gets confused and this command:
    #
    #   mount -t glusterfs 10.0.0.1:30000:gv0 /var/run/ganeti/gluster/gv0
    #                      '-- remote end --' '------ mountpoint -------'
    #
    # gets parsed instead like this:
    #
    #   mount -t glusterfs 10.0.0.1:30000:gv0 /var/run/ganeti/gluster/gv0
    #                      '-- mountpoint --' '----- syntax error ------'
    #
    # and if there _is_ a gluster server running locally at the default remote
    # end, localhost:24007, then this is not a network error and therefore... no
    # usage message gets printed out. All you get is a Byson parser error in the
    # gluster log files about an unexpected token in line 1, "". (That's stdin.)
    #
    # Not that we rely on that output in any way whatsoever...

    parser_confusing = io.PathJoin(self.mount_point,
                                   self._GetFUSEMountString())
    if os.path.exists(parser_confusing):
      reasons.append("%r: please delete, rename or move." % parser_confusing)

    # Let's try something else: can we connect to the server?
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      sock.connect((self.server_ip, self.port))
      sock.close()
    except socket.error as err:
      reasons.append("%s:%d: %s" % (self.server_ip, self.port, err.strerror))

    reasons.append("try running 'gluster volume info %s' on %s to ensure"
                   " it exists, it is started and it is using the tcp"
                   " transport" % (self.volume, self.server_ip))

    return "; ".join(reasons)

  def _GetFUSEMountString(self):
    """Return the string FUSE needs to mount this volume.

    @rtype: str
    """

    return "-o server-port={port} {ip}:/{volume}" \
              .format(port=self.port, ip=self.server_ip, volume=self.volume)

  def GetKVMMountString(self, path):
    """Return the string KVM needs to use this volume.

    @rtype: str
    """

    ip = self.server_ip
    if netutils.IPAddress.GetAddressFamily(ip) == socket.AF_INET6:
      ip = "[%s]" % ip
    return "gluster://{ip}:{port}/{volume}/{path}" \
              .format(ip=ip, port=self.port, volume=self.volume, path=path)

  def Mount(self):
    """Try and mount the volume. No-op if the volume is already mounted.

    @raises BlockDeviceError: if the mount was unsuccessful

    @rtype: context manager
    @return: A simple context manager that lets you use this volume for
             short lived operations like so::

              with volume.mount():
                # Do operations on volume
              # Volume is now unmounted

    """

    class _GlusterVolumeContextManager(object):

      def __init__(self, volume):
        self.volume = volume

      def __enter__(self):
        # We're already mounted.
        return self

      def __exit__(self, *exception_information):
        self.volume.Unmount()
        return False # do not swallow exceptions.

    if self._IsMounted():
      return _GlusterVolumeContextManager(self)

    command = ["mount",
               "-t", "glusterfs",
               self._GetFUSEMountString(),
               self.mount_point]

    io.Makedirs(self.mount_point)
    self._run_cmd(" ".join(command),
                  # Why set cwd? Because it's an area we control. If,
                  # for some unfortunate reason, this folder exists:
                  #   "/%s/" % _GetFUSEMountString()
                  # ...then the gluster parser gets confused and treats
                  # _GetFUSEMountString() as your mount point and
                  # self.mount_point becomes a syntax error.
                  cwd=self.mount_point)

    # mount.glusterfs exits with code 0 even after failure.
    # https://bugzilla.redhat.com/show_bug.cgi?id=1031973
    if not self._IsMounted():
      reasons = self._GuessMountFailReasons()
      if not reasons:
        reasons = "%r failed." % (" ".join(command))
      base.ThrowError("%r: mount failure: %s",
                      self.mount_point,
                      reasons)

    return _GlusterVolumeContextManager(self)

  def Unmount(self):
    """Try and unmount the volume.

    Failures are logged but otherwise ignored.

    @raises BlockDeviceError: if the volume was not mounted to begin with.
    """

    if not self._IsMounted():
      base.ThrowError("%r: should be mounted but isn't.", self.mount_point)

    result = self._run_cmd(["umount",
                            self.mount_point])

    if result.failed:
      logging.warning("Failed to unmount %r from %r: %s",
                      self, self.mount_point, result.fail_reason)


class GlusterStorage(base.BlockDev):
  """File device using the Gluster backend.

  This class represents a file storage backend device stored on Gluster. Ganeti
  mounts and unmounts the Gluster devices automatically.

  The unique_id for the file device is a (file_driver, file_path) tuple.

  """
  def __init__(self, unique_id, children, size, params, dyn_params, **kwargs):
    """Initalizes a file device backend.

    """
    if children:
      base.ThrowError("Invalid setup for file device")

    try:
      self.driver, self.path = unique_id
    except ValueError: # wrong number of arguments
      raise ValueError("Invalid configuration data %s" % repr(unique_id))

    server_addr = params[constants.GLUSTER_HOST]
    port = params[constants.GLUSTER_PORT]
    volume = params[constants.GLUSTER_VOLUME]

    self.volume = GlusterVolume(server_addr, port, volume)
    self.full_path = io.PathJoin(self.volume.mount_point, self.path)
    self.file = None

    super(GlusterStorage, self).__init__(unique_id, children, size,
                                         params, dyn_params, **kwargs)

    self.Attach()

  def Assemble(self):
    """Assemble the device.

    Checks whether the file device exists, raises BlockDeviceError otherwise.

    """
    assert self.attached, "Gluster file assembled without being attached"
    self.file.Exists(assert_exists=True)

  def Shutdown(self):
    """Shutdown the device.

    """

    self.file = None
    self.dev_path = None
    self.attached = False

  def Open(self, force=False, exclusive=True):
    """Make the device ready for I/O.

    This is a no-op for the file type.

    """
    assert self.attached, "Gluster file opened without being attached"

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    This is a no-op for the file type.
    """
    pass

  def Remove(self):
    """Remove the file backing the block device.

    @rtype: boolean
    @return: True if the removal was successful

    """
    with self.volume.Mount():
      self.file = FileDeviceHelper(self.full_path)
      if self.file.Remove():
        self.file = None
        return True
      else:
        return False

  def Rename(self, new_id):
    """Renames the file.

    """
    # TODO: implement rename for file-based storage
    base.ThrowError("Rename is not supported for Gluster storage")

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the file

    @param amount: the amount (in mebibytes) to grow with

    """
    self.file.Grow(amount, dryrun, backingstore, excl_stor)

  def Attach(self, **kwargs):
    """Attach to an existing file.

    Check if this file already exists.

    @rtype: boolean
    @return: True if file exists

    """
    try:
      self.volume.Mount()
      self.file = FileDeviceHelper(self.full_path)
      self.dev_path = self.full_path
    except Exception as err:
      self.volume.Unmount()
      raise err

    self.attached = self.file.Exists()
    return self.attached

  def GetActualSize(self):
    """Return the actual disk size.

    @note: the device needs to be active when this is called

    """
    return self.file.Size()

  def GetUserspaceAccessUri(self, hypervisor):
    """Generate KVM userspace URIs to be used as `-drive file` settings.

    @see: L{BlockDev.GetUserspaceAccessUri}
    @see: https://github.com/qemu/qemu/commit/8d6d89cb63c57569864ecdeb84d3a1c2eb
    """

    if hypervisor == constants.HT_KVM:
      return self.volume.GetKVMMountString(self.path)
    else:
      base.ThrowError("Hypervisor %s doesn't support Gluster userspace access" %
                      hypervisor)

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, **kwargs):
    """Create a new file.

    @param size: the size of file in MiB

    @rtype: L{bdev.FileStorage}
    @return: an instance of FileStorage

    """
    if excl_stor:
      raise errors.ProgrammerError("FileStorage device requested with"
                                   " exclusive_storage")
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    full_path = unique_id[1]

    server_addr = params[constants.GLUSTER_HOST]
    port = params[constants.GLUSTER_PORT]
    volume = params[constants.GLUSTER_VOLUME]

    volume_obj = GlusterVolume(server_addr, port, volume)
    full_path = io.PathJoin(volume_obj.mount_point, full_path)

    # Possible optimization: defer actual creation to first Attach, rather
    # than mounting and unmounting here, then remounting immediately after.
    with volume_obj.Mount():
      FileDeviceHelper.CreateFile(full_path, size, create_folders=True)

    return GlusterStorage(unique_id, children, size, params, dyn_params,
                          **kwargs)
