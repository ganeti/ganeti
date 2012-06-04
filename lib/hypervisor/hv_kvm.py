#
#

# Copyright (C) 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""KVM hypervisor

"""

import errno
import os
import os.path
import re
import tempfile
import time
import logging
import pwd
import struct
import fcntl
import shutil
import socket
import stat
import StringIO
try:
  import affinity   # pylint: disable=F0401
except ImportError:
  affinity = None

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import serializer
from ganeti import objects
from ganeti import uidpool
from ganeti import ssconf
from ganeti import netutils
from ganeti import pathutils
from ganeti.hypervisor import hv_base
from ganeti.utils import wrapper as utils_wrapper


_KVM_NETWORK_SCRIPT = pathutils.CONF_DIR + "/kvm-vif-bridge"
_KVM_START_PAUSED_FLAG = "-S"

# TUN/TAP driver constants, taken from <linux/if_tun.h>
# They are architecture-independent and already hardcoded in qemu-kvm source,
# so we can safely include them here.
TUNSETIFF = 0x400454ca
TUNGETIFF = 0x800454d2
TUNGETFEATURES = 0x800454cf
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000
IFF_VNET_HDR = 0x4000


def _ProbeTapVnetHdr(fd):
  """Check whether to enable the IFF_VNET_HDR flag.

  To do this, _all_ of the following conditions must be met:
   1. TUNGETFEATURES ioctl() *must* be implemented
   2. TUNGETFEATURES ioctl() result *must* contain the IFF_VNET_HDR flag
   3. TUNGETIFF ioctl() *must* be implemented; reading the kernel code in
      drivers/net/tun.c there is no way to test this until after the tap device
      has been created using TUNSETIFF, and there is no way to change the
      IFF_VNET_HDR flag after creating the interface, catch-22! However both
      TUNGETIFF and TUNGETFEATURES were introduced in kernel version 2.6.27,
      thus we can expect TUNGETIFF to be present if TUNGETFEATURES is.

   @type fd: int
   @param fd: the file descriptor of /dev/net/tun

  """
  req = struct.pack("I", 0)
  try:
    res = fcntl.ioctl(fd, TUNGETFEATURES, req)
  except EnvironmentError:
    logging.warning("TUNGETFEATURES ioctl() not implemented")
    return False

  tunflags = struct.unpack("I", res)[0]
  if tunflags & IFF_VNET_HDR:
    return True
  else:
    logging.warning("Host does not support IFF_VNET_HDR, not enabling")
    return False


def _OpenTap(vnet_hdr=True):
  """Open a new tap device and return its file descriptor.

  This is intended to be used by a qemu-type hypervisor together with the -net
  tap,fd=<fd> command line parameter.

  @type vnet_hdr: boolean
  @param vnet_hdr: Enable the VNET Header
  @return: (ifname, tapfd)
  @rtype: tuple

  """
  try:
    tapfd = os.open("/dev/net/tun", os.O_RDWR)
  except EnvironmentError:
    raise errors.HypervisorError("Failed to open /dev/net/tun")

  flags = IFF_TAP | IFF_NO_PI

  if vnet_hdr and _ProbeTapVnetHdr(tapfd):
    flags |= IFF_VNET_HDR

  # The struct ifreq ioctl request (see netdevice(7))
  ifr = struct.pack("16sh", "", flags)

  try:
    res = fcntl.ioctl(tapfd, TUNSETIFF, ifr)
  except EnvironmentError:
    raise errors.HypervisorError("Failed to allocate a new TAP device")

  # Get the interface name from the ioctl
  ifname = struct.unpack("16sh", res)[0].strip("\x00")
  return (ifname, tapfd)


class QmpMessage:
  """QEMU Messaging Protocol (QMP) message.

  """
  def __init__(self, data):
    """Creates a new QMP message based on the passed data.

    """
    if not isinstance(data, dict):
      raise TypeError("QmpMessage must be initialized with a dict")

    self.data = data

  def __getitem__(self, field_name):
    """Get the value of the required field if present, or None.

    Overrides the [] operator to provide access to the message data,
    returning None if the required item is not in the message
    @return: the value of the field_name field, or None if field_name
             is not contained in the message

    """
    return self.data.get(field_name, None)

  def __setitem__(self, field_name, field_value):
    """Set the value of the required field_name to field_value.

    """
    self.data[field_name] = field_value

  @staticmethod
  def BuildFromJsonString(json_string):
    """Build a QmpMessage from a JSON encoded string.

    @type json_string: str
    @param json_string: JSON string representing the message
    @rtype: L{QmpMessage}
    @return: a L{QmpMessage} built from json_string

    """
    # Parse the string
    data = serializer.LoadJson(json_string)
    return QmpMessage(data)

  def __str__(self):
    # The protocol expects the JSON object to be sent as a single line.
    return serializer.DumpJson(self.data)

  def __eq__(self, other):
    # When comparing two QmpMessages, we are interested in comparing
    # their internal representation of the message data
    return self.data == other.data


class QmpConnection:
  """Connection to the QEMU Monitor using the QEMU Monitor Protocol (QMP).

  """
  _FIRST_MESSAGE_KEY = "QMP"
  _EVENT_KEY = "event"
  _ERROR_KEY = "error"
  _RETURN_KEY = RETURN_KEY = "return"
  _ACTUAL_KEY = ACTUAL_KEY = "actual"
  _ERROR_CLASS_KEY = "class"
  _ERROR_DATA_KEY = "data"
  _ERROR_DESC_KEY = "desc"
  _EXECUTE_KEY = "execute"
  _ARGUMENTS_KEY = "arguments"
  _CAPABILITIES_COMMAND = "qmp_capabilities"
  _MESSAGE_END_TOKEN = "\r\n"
  _SOCKET_TIMEOUT = 5

  def __init__(self, monitor_filename):
    """Instantiates the QmpConnection object.

    @type monitor_filename: string
    @param monitor_filename: the filename of the UNIX raw socket on which the
                             QMP monitor is listening

    """
    self.monitor_filename = monitor_filename
    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # We want to fail if the server doesn't send a complete message
    # in a reasonable amount of time
    self.sock.settimeout(self._SOCKET_TIMEOUT)
    self._connected = False
    self._buf = ""

  def _check_socket(self):
    sock_stat = None
    try:
      sock_stat = os.stat(self.monitor_filename)
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        raise errors.HypervisorError("No qmp socket found")
      else:
        raise errors.HypervisorError("Error checking qmp socket: %s",
                                     utils.ErrnoOrStr(err))
    if not stat.S_ISSOCK(sock_stat.st_mode):
      raise errors.HypervisorError("Qmp socket is not a socket")

  def _check_connection(self):
    """Make sure that the connection is established.

    """
    if not self._connected:
      raise errors.ProgrammerError("To use a QmpConnection you need to first"
                                   " invoke connect() on it")

  def connect(self):
    """Connects to the QMP monitor.

    Connects to the UNIX socket and makes sure that we can actually send and
    receive data to the kvm instance via QMP.

    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    if self._connected:
      raise errors.ProgrammerError("Cannot connect twice")

    self._check_socket()

    # Check file existance/stuff
    try:
      self.sock.connect(self.monitor_filename)
    except EnvironmentError:
      raise errors.HypervisorError("Can't connect to qmp socket")
    self._connected = True

    # Check if we receive a correct greeting message from the server
    # (As per the QEMU Protocol Specification 0.1 - section 2.2)
    greeting = self._Recv()
    if not greeting[self._FIRST_MESSAGE_KEY]:
      self._connected = False
      raise errors.HypervisorError("kvm: qmp communication error (wrong"
                                   " server greeting")

    # Let's put the monitor in command mode using the qmp_capabilities
    # command, or else no command will be executable.
    # (As per the QEMU Protocol Specification 0.1 - section 4)
    self.Execute(self._CAPABILITIES_COMMAND)

  def _ParseMessage(self, buf):
    """Extract and parse a QMP message from the given buffer.

    Seeks for a QMP message in the given buf. If found, it parses it and
    returns it together with the rest of the characters in the buf.
    If no message is found, returns None and the whole buffer.

    @raise errors.ProgrammerError: when there are data serialization errors

    """
    message = None
    # Check if we got the message end token (CRLF, as per the QEMU Protocol
    # Specification 0.1 - Section 2.1.1)
    pos = buf.find(self._MESSAGE_END_TOKEN)
    if pos >= 0:
      try:
        message = QmpMessage.BuildFromJsonString(buf[:pos + 1])
      except Exception, err:
        raise errors.ProgrammerError("QMP data serialization error: %s" % err)
      buf = buf[pos + 1:]

    return (message, buf)

  def _Recv(self):
    """Receives a message from QMP and decodes the received JSON object.

    @rtype: QmpMessage
    @return: the received message
    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    self._check_connection()

    # Check if there is already a message in the buffer
    (message, self._buf) = self._ParseMessage(self._buf)
    if message:
      return message

    recv_buffer = StringIO.StringIO(self._buf)
    recv_buffer.seek(len(self._buf))
    try:
      while True:
        data = self.sock.recv(4096)
        if not data:
          break
        recv_buffer.write(data)

        (message, self._buf) = self._ParseMessage(recv_buffer.getvalue())
        if message:
          return message

    except socket.timeout, err:
      raise errors.HypervisorError("Timeout while receiving a QMP message: "
                                   "%s" % (err))
    except socket.error, err:
      raise errors.HypervisorError("Unable to receive data from KVM using the"
                                   " QMP protocol: %s" % err)

  def _Send(self, message):
    """Encodes and sends a message to KVM using QMP.

    @type message: QmpMessage
    @param message: message to send to KVM
    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    self._check_connection()
    try:
      message_str = str(message)
    except Exception, err:
      raise errors.ProgrammerError("QMP data deserialization error: %s" % err)

    try:
      self.sock.sendall(message_str)
    except socket.timeout, err:
      raise errors.HypervisorError("Timeout while sending a QMP message: "
                                   "%s (%s)" % (err.string, err.errno))
    except socket.error, err:
      raise errors.HypervisorError("Unable to send data from KVM using the"
                                   " QMP protocol: %s" % err)

  def Execute(self, command, arguments=None):
    """Executes a QMP command and returns the response of the server.

    @type command: str
    @param command: the command to execute
    @type arguments: dict
    @param arguments: dictionary of arguments to be passed to the command
    @rtype: dict
    @return: dictionary representing the received JSON object
    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    self._check_connection()
    message = QmpMessage({self._EXECUTE_KEY: command})
    if arguments:
      message[self._ARGUMENTS_KEY] = arguments
    self._Send(message)

    # Events can occur between the sending of the command and the reception
    # of the response, so we need to filter out messages with the event key.
    while True:
      response = self._Recv()
      err = response[self._ERROR_KEY]
      if err:
        raise errors.HypervisorError("kvm: error executing the %s"
                                     " command: %s (%s, %s):" %
                                     (command,
                                      err[self._ERROR_DESC_KEY],
                                      err[self._ERROR_CLASS_KEY],
                                      err[self._ERROR_DATA_KEY]))

      elif not response[self._EVENT_KEY]:
        return response


class KVMHypervisor(hv_base.BaseHypervisor):
  """KVM hypervisor interface

  """
  CAN_MIGRATE = True

  _ROOT_DIR = pathutils.RUN_DIR + "/kvm-hypervisor"
  _PIDS_DIR = _ROOT_DIR + "/pid" # contains live instances pids
  _UIDS_DIR = _ROOT_DIR + "/uid" # contains instances reserved uids
  _CTRL_DIR = _ROOT_DIR + "/ctrl" # contains instances control sockets
  _CONF_DIR = _ROOT_DIR + "/conf" # contains instances startup data
  _NICS_DIR = _ROOT_DIR + "/nic" # contains instances nic <-> tap associations
  _KEYMAP_DIR = _ROOT_DIR + "/keymap" # contains instances keymaps
  # KVM instances with chroot enabled are started in empty chroot directories.
  _CHROOT_DIR = _ROOT_DIR + "/chroot" # for empty chroot directories
  # After an instance is stopped, its chroot directory is removed.
  # If the chroot directory is not empty, it can't be removed.
  # A non-empty chroot directory indicates a possible security incident.
  # To support forensics, the non-empty chroot directory is quarantined in
  # a separate directory, called 'chroot-quarantine'.
  _CHROOT_QUARANTINE_DIR = _ROOT_DIR + "/chroot-quarantine"
  _DIRS = [_ROOT_DIR, _PIDS_DIR, _UIDS_DIR, _CTRL_DIR, _CONF_DIR, _NICS_DIR,
           _CHROOT_DIR, _CHROOT_QUARANTINE_DIR, _KEYMAP_DIR]

  PARAMETERS = {
    constants.HV_KERNEL_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_INITRD_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_ROOT_PATH: hv_base.NO_CHECK,
    constants.HV_KERNEL_ARGS: hv_base.NO_CHECK,
    constants.HV_ACPI: hv_base.NO_CHECK,
    constants.HV_SERIAL_CONSOLE: hv_base.NO_CHECK,
    constants.HV_VNC_BIND_ADDRESS:
      (False, lambda x: (netutils.IP4Address.IsValid(x) or
                         utils.IsNormAbsPath(x)),
       "the VNC bind address must be either a valid IP address or an absolute"
       " pathname", None, None),
    constants.HV_VNC_TLS: hv_base.NO_CHECK,
    constants.HV_VNC_X509: hv_base.OPT_DIR_CHECK,
    constants.HV_VNC_X509_VERIFY: hv_base.NO_CHECK,
    constants.HV_VNC_PASSWORD_FILE: hv_base.OPT_FILE_CHECK,
    constants.HV_KVM_SPICE_BIND: hv_base.NO_CHECK, # will be checked later
    constants.HV_KVM_SPICE_IP_VERSION:
      (False, lambda x: (x == constants.IFACE_NO_IP_VERSION_SPECIFIED or
                         x in constants.VALID_IP_VERSIONS),
       "the SPICE IP version should be 4 or 6",
       None, None),
    constants.HV_KVM_SPICE_PASSWORD_FILE: hv_base.OPT_FILE_CHECK,
    constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_LOSSLESS_IMG_COMPR_OPTIONS),
    constants.HV_KVM_SPICE_JPEG_IMG_COMPR:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_LOSSY_IMG_COMPR_OPTIONS),
    constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_LOSSY_IMG_COMPR_OPTIONS),
    constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_VIDEO_STREAM_DETECTION_OPTIONS),
    constants.HV_KVM_SPICE_AUDIO_COMPR: hv_base.NO_CHECK,
    constants.HV_KVM_SPICE_USE_TLS: hv_base.NO_CHECK,
    constants.HV_KVM_SPICE_TLS_CIPHERS: hv_base.NO_CHECK,
    constants.HV_KVM_SPICE_USE_VDAGENT: hv_base.NO_CHECK,
    constants.HV_KVM_FLOPPY_IMAGE_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_CDROM_IMAGE_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_KVM_CDROM2_IMAGE_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_BOOT_ORDER:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_BO_TYPES),
    constants.HV_NIC_TYPE:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_NIC_TYPES),
    constants.HV_DISK_TYPE:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_DISK_TYPES),
    constants.HV_KVM_CDROM_DISK_TYPE:
      hv_base.ParamInSet(False, constants.HT_KVM_VALID_DISK_TYPES),
    constants.HV_USB_MOUSE:
      hv_base.ParamInSet(False, constants.HT_KVM_VALID_MOUSE_TYPES),
    constants.HV_KEYMAP: hv_base.NO_CHECK,
    constants.HV_MIGRATION_PORT: hv_base.REQ_NET_PORT_CHECK,
    constants.HV_MIGRATION_BANDWIDTH: hv_base.NO_CHECK,
    constants.HV_MIGRATION_DOWNTIME: hv_base.NO_CHECK,
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    constants.HV_USE_LOCALTIME: hv_base.NO_CHECK,
    constants.HV_DISK_CACHE:
      hv_base.ParamInSet(True, constants.HT_VALID_CACHE_TYPES),
    constants.HV_SECURITY_MODEL:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_SM_TYPES),
    constants.HV_SECURITY_DOMAIN: hv_base.NO_CHECK,
    constants.HV_KVM_FLAG:
      hv_base.ParamInSet(False, constants.HT_KVM_FLAG_VALUES),
    constants.HV_VHOST_NET: hv_base.NO_CHECK,
    constants.HV_KVM_USE_CHROOT: hv_base.NO_CHECK,
    constants.HV_MEM_PATH: hv_base.OPT_DIR_CHECK,
    constants.HV_REBOOT_BEHAVIOR:
      hv_base.ParamInSet(True, constants.REBOOT_BEHAVIORS),
    constants.HV_CPU_MASK: hv_base.OPT_MULTI_CPU_MASK_CHECK,
    constants.HV_CPU_TYPE: hv_base.NO_CHECK
    }

  _MIGRATION_STATUS_RE = re.compile("Migration\s+status:\s+(\w+)",
                                    re.M | re.I)
  _MIGRATION_PROGRESS_RE = \
    re.compile(r"\s*transferred\s+ram:\s+(?P<transferred>\d+)\s+kbytes\s*\n"
               r"\s*remaining\s+ram:\s+(?P<remaining>\d+)\s+kbytes\s*\n"
               r"\s*total\s+ram:\s+(?P<total>\d+)\s+kbytes\s*\n", re.I)

  _MIGRATION_INFO_MAX_BAD_ANSWERS = 5
  _MIGRATION_INFO_RETRY_DELAY = 2

  _VERSION_RE = re.compile(r"\b(\d+)\.(\d+)(\.(\d+))?\b")

  _CPU_INFO_RE = re.compile(r"cpu\s+\#(\d+).*thread_id\s*=\s*(\d+)", re.I)
  _CPU_INFO_CMD = "info cpus"
  _CONT_CMD = "cont"

  ANCILLARY_FILES = [
    _KVM_NETWORK_SCRIPT,
    ]
  ANCILLARY_FILES_OPT = [
    _KVM_NETWORK_SCRIPT,
    ]

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    # Let's make sure the directories we need exist, even if the RUN_DIR lives
    # in a tmpfs filesystem or has been otherwise wiped out.
    dirs = [(dname, constants.RUN_DIRS_MODE) for dname in self._DIRS]
    utils.EnsureDirs(dirs)

  @classmethod
  def _InstancePidFile(cls, instance_name):
    """Returns the instance pidfile.

    """
    return utils.PathJoin(cls._PIDS_DIR, instance_name)

  @classmethod
  def _InstanceUidFile(cls, instance_name):
    """Returns the instance uidfile.

    """
    return utils.PathJoin(cls._UIDS_DIR, instance_name)

  @classmethod
  def _InstancePidInfo(cls, pid):
    """Check pid file for instance information.

    Check that a pid file is associated with an instance, and retrieve
    information from its command line.

    @type pid: string or int
    @param pid: process id of the instance to check
    @rtype: tuple
    @return: (instance_name, memory, vcpus)
    @raise errors.HypervisorError: when an instance cannot be found

    """
    alive = utils.IsProcessAlive(pid)
    if not alive:
      raise errors.HypervisorError("Cannot get info for pid %s" % pid)

    cmdline_file = utils.PathJoin("/proc", str(pid), "cmdline")
    try:
      cmdline = utils.ReadFile(cmdline_file)
    except EnvironmentError, err:
      raise errors.HypervisorError("Can't open cmdline file for pid %s: %s" %
                                   (pid, err))

    instance = None
    memory = 0
    vcpus = 0

    arg_list = cmdline.split("\x00")
    while arg_list:
      arg = arg_list.pop(0)
      if arg == "-name":
        instance = arg_list.pop(0)
      elif arg == "-m":
        memory = int(arg_list.pop(0))
      elif arg == "-smp":
        vcpus = int(arg_list.pop(0))

    if instance is None:
      raise errors.HypervisorError("Pid %s doesn't contain a ganeti kvm"
                                   " instance" % pid)

    return (instance, memory, vcpus)

  def _InstancePidAlive(self, instance_name):
    """Returns the instance pidfile, pid, and liveness.

    @type instance_name: string
    @param instance_name: instance name
    @rtype: tuple
    @return: (pid file name, pid, liveness)

    """
    pidfile = self._InstancePidFile(instance_name)
    pid = utils.ReadPidFile(pidfile)

    alive = False
    try:
      cmd_instance = self._InstancePidInfo(pid)[0]
      alive = (cmd_instance == instance_name)
    except errors.HypervisorError:
      pass

    return (pidfile, pid, alive)

  def _CheckDown(self, instance_name):
    """Raises an error unless the given instance is down.

    """
    alive = self._InstancePidAlive(instance_name)[2]
    if alive:
      raise errors.HypervisorError("Failed to start instance %s: %s" %
                                   (instance_name, "already running"))

  @classmethod
  def _InstanceMonitor(cls, instance_name):
    """Returns the instance monitor socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.monitor" % instance_name)

  @classmethod
  def _InstanceSerial(cls, instance_name):
    """Returns the instance serial socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.serial" % instance_name)

  @classmethod
  def _InstanceQmpMonitor(cls, instance_name):
    """Returns the instance serial QMP socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.qmp" % instance_name)

  @staticmethod
  def _SocatUnixConsoleParams():
    """Returns the correct parameters for socat

    If we have a new-enough socat we can use raw mode with an escape character.

    """
    if constants.SOCAT_USE_ESCAPE:
      return "raw,echo=0,escape=%s" % constants.SOCAT_ESCAPE_CODE
    else:
      return "echo=0,icanon=0"

  @classmethod
  def _InstanceKVMRuntime(cls, instance_name):
    """Returns the instance KVM runtime filename

    """
    return utils.PathJoin(cls._CONF_DIR, "%s.runtime" % instance_name)

  @classmethod
  def _InstanceChrootDir(cls, instance_name):
    """Returns the name of the KVM chroot dir of the instance

    """
    return utils.PathJoin(cls._CHROOT_DIR, instance_name)

  @classmethod
  def _InstanceNICDir(cls, instance_name):
    """Returns the name of the directory holding the tap device files for a
    given instance.

    """
    return utils.PathJoin(cls._NICS_DIR, instance_name)

  @classmethod
  def _InstanceNICFile(cls, instance_name, seq):
    """Returns the name of the file containing the tap device for a given NIC

    """
    return utils.PathJoin(cls._InstanceNICDir(instance_name), str(seq))

  @classmethod
  def _InstanceKeymapFile(cls, instance_name):
    """Returns the name of the file containing the keymap for a given instance

    """
    return utils.PathJoin(cls._KEYMAP_DIR, instance_name)

  @classmethod
  def _TryReadUidFile(cls, uid_file):
    """Try to read a uid file

    """
    if os.path.exists(uid_file):
      try:
        uid = int(utils.ReadOneLineFile(uid_file))
        return uid
      except EnvironmentError:
        logging.warning("Can't read uid file", exc_info=True)
      except (TypeError, ValueError):
        logging.warning("Can't parse uid file contents", exc_info=True)
    return None

  @classmethod
  def _RemoveInstanceRuntimeFiles(cls, pidfile, instance_name):
    """Removes an instance's rutime sockets/files/dirs.

    """
    utils.RemoveFile(pidfile)
    utils.RemoveFile(cls._InstanceMonitor(instance_name))
    utils.RemoveFile(cls._InstanceSerial(instance_name))
    utils.RemoveFile(cls._InstanceQmpMonitor(instance_name))
    utils.RemoveFile(cls._InstanceKVMRuntime(instance_name))
    utils.RemoveFile(cls._InstanceKeymapFile(instance_name))
    uid_file = cls._InstanceUidFile(instance_name)
    uid = cls._TryReadUidFile(uid_file)
    utils.RemoveFile(uid_file)
    if uid is not None:
      uidpool.ReleaseUid(uid)
    try:
      shutil.rmtree(cls._InstanceNICDir(instance_name))
    except OSError, err:
      if err.errno != errno.ENOENT:
        raise
    try:
      chroot_dir = cls._InstanceChrootDir(instance_name)
      utils.RemoveDir(chroot_dir)
    except OSError, err:
      if err.errno == errno.ENOTEMPTY:
        # The chroot directory is expected to be empty, but it isn't.
        new_chroot_dir = tempfile.mkdtemp(dir=cls._CHROOT_QUARANTINE_DIR,
                                          prefix="%s-%s-" %
                                          (instance_name,
                                           utils.TimestampForFilename()))
        logging.warning("The chroot directory of instance %s can not be"
                        " removed as it is not empty. Moving it to the"
                        " quarantine instead. Please investigate the"
                        " contents (%s) and clean up manually",
                        instance_name, new_chroot_dir)
        utils.RenameFile(chroot_dir, new_chroot_dir)
      else:
        raise

  @staticmethod
  def _ConfigureNIC(instance, seq, nic, tap):
    """Run the network configuration script for a specified NIC

    @param instance: instance we're acting on
    @type instance: instance object
    @param seq: nic sequence number
    @type seq: int
    @param nic: nic we're acting on
    @type nic: nic object
    @param tap: the host's tap interface this NIC corresponds to
    @type tap: str

    """
    if instance.tags:
      tags = " ".join(instance.tags)
    else:
      tags = ""

    env = {
      "PATH": "%s:/sbin:/usr/sbin" % os.environ["PATH"],
      "INSTANCE": instance.name,
      "MAC": nic.mac,
      "MODE": nic.nicparams[constants.NIC_MODE],
      "INTERFACE": tap,
      "INTERFACE_INDEX": str(seq),
      "TAGS": tags,
    }

    if nic.ip:
      env["IP"] = nic.ip

    if nic.nicparams[constants.NIC_LINK]:
      env["LINK"] = nic.nicparams[constants.NIC_LINK]

    if nic.network:
      env["NETWORK"] = nic.network

    if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
      env["BRIDGE"] = nic.nicparams[constants.NIC_LINK]

    result = utils.RunCmd([pathutils.KVM_IFUP, tap], env=env)
    if result.failed:
      raise errors.HypervisorError("Failed to configure interface %s: %s."
                                   " Network configuration script output: %s" %
                                   (tap, result.fail_reason, result.output))

  @staticmethod
  def _VerifyAffinityPackage():
    if affinity is None:
      raise errors.HypervisorError("affinity Python package not"
                                   " found; cannot use CPU pinning under KVM")

  @staticmethod
  def _BuildAffinityCpuMask(cpu_list):
    """Create a CPU mask suitable for sched_setaffinity from a list of
    CPUs.

    See man taskset for more info on sched_setaffinity masks.
    For example: [ 0, 2, 5, 6 ] will return 101 (0x65, 0..01100101).

    @type cpu_list: list of int
    @param cpu_list: list of physical CPU numbers to map to vCPUs in order
    @rtype: int
    @return: a bit mask of CPU affinities

    """
    if cpu_list == constants.CPU_PINNING_OFF:
      return constants.CPU_PINNING_ALL_KVM
    else:
      return sum(2 ** cpu for cpu in cpu_list)

  @classmethod
  def _AssignCpuAffinity(cls, cpu_mask, process_id, thread_dict):
    """Change CPU affinity for running VM according to given CPU mask.

    @param cpu_mask: CPU mask as given by the user. e.g. "0-2,4:all:1,3"
    @type cpu_mask: string
    @param process_id: process ID of KVM process. Used to pin entire VM
                       to physical CPUs.
    @type process_id: int
    @param thread_dict: map of virtual CPUs to KVM thread IDs
    @type thread_dict: dict int:int

    """
    # Convert the string CPU mask to a list of list of int's
    cpu_list = utils.ParseMultiCpuMask(cpu_mask)

    if len(cpu_list) == 1:
      all_cpu_mapping = cpu_list[0]
      if all_cpu_mapping == constants.CPU_PINNING_OFF:
        # If CPU pinning has 1 entry that's "all", then do nothing
        pass
      else:
        # If CPU pinning has one non-all entry, map the entire VM to
        # one set of physical CPUs
        cls._VerifyAffinityPackage()
        affinity.set_process_affinity_mask(
          process_id, cls._BuildAffinityCpuMask(all_cpu_mapping))
    else:
      # The number of vCPUs mapped should match the number of vCPUs
      # reported by KVM. This was already verified earlier, so
      # here only as a sanity check.
      assert len(thread_dict) == len(cpu_list)
      cls._VerifyAffinityPackage()

      # For each vCPU, map it to the proper list of physical CPUs
      for vcpu, i in zip(cpu_list, range(len(cpu_list))):
        affinity.set_process_affinity_mask(thread_dict[i],
                                           cls._BuildAffinityCpuMask(vcpu))

  def _GetVcpuThreadIds(self, instance_name):
    """Get a mapping of vCPU no. to thread IDs for the instance

    @type instance_name: string
    @param instance_name: instance in question
    @rtype: dictionary of int:int
    @return: a dictionary mapping vCPU numbers to thread IDs

    """
    result = {}
    output = self._CallMonitorCommand(instance_name, self._CPU_INFO_CMD)
    for line in output.stdout.splitlines():
      match = self._CPU_INFO_RE.search(line)
      if not match:
        continue
      grp = map(int, match.groups())
      result[grp[0]] = grp[1]

    return result

  def _ExecuteCpuAffinity(self, instance_name, cpu_mask):
    """Complete CPU pinning.

    @type instance_name: string
    @param instance_name: name of instance
    @type cpu_mask: string
    @param cpu_mask: CPU pinning mask as entered by user

    """
    # Get KVM process ID, to be used if need to pin entire VM
    _, pid, _ = self._InstancePidAlive(instance_name)
    # Get vCPU thread IDs, to be used if need to pin vCPUs separately
    thread_dict = self._GetVcpuThreadIds(instance_name)
    # Run CPU pinning, based on configured mask
    self._AssignCpuAffinity(cpu_mask, pid, thread_dict)

  def ListInstances(self):
    """Get the list of running instances.

    We can do this by listing our live instances directory and
    checking whether the associated kvm process is still alive.

    """
    result = []
    for name in os.listdir(self._PIDS_DIR):
      if self._InstancePidAlive(name)[2]:
        result.append(name)
    return result

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @rtype: tuple of strings
    @return: (name, id, memory, vcpus, stat, times)

    """
    _, pid, alive = self._InstancePidAlive(instance_name)
    if not alive:
      return None

    _, memory, vcpus = self._InstancePidInfo(pid)
    istat = "---b-"
    times = "0"

    try:
      qmp = QmpConnection(self._InstanceQmpMonitor(instance_name))
      qmp.connect()
      vcpus = len(qmp.Execute("query-cpus")[qmp.RETURN_KEY])
      # Will fail if ballooning is not enabled, but we can then just resort to
      # the value above.
      mem_bytes = qmp.Execute("query-balloon")[qmp.RETURN_KEY][qmp.ACTUAL_KEY]
      memory = mem_bytes / 1048576
    except errors.HypervisorError:
      pass

    return (instance_name, pid, memory, vcpus, istat, times)

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    data = []
    for name in os.listdir(self._PIDS_DIR):
      try:
        info = self.GetInstanceInfo(name)
      except errors.HypervisorError:
        # Ignore exceptions due to instances being shut down
        continue
      if info:
        data.append(info)
    return data

  def _GenerateKVMRuntime(self, instance, block_devices, startup_paused):
    """Generate KVM information to start an instance.

    @attention: this function must not have any side-effects; for
        example, it must not write to the filesystem, or read values
        from the current system the are expected to differ between
        nodes, since it is only run once at instance startup;
        actions/kvm arguments that can vary between systems should be
        done in L{_ExecuteKVMRuntime}

    """
    # pylint: disable=R0914,R0915
    _, v_major, v_min, _ = self._GetKVMVersion()

    pidfile = self._InstancePidFile(instance.name)
    kvm = constants.KVM_PATH
    kvm_cmd = [kvm]
    # used just by the vnc server, if enabled
    kvm_cmd.extend(["-name", instance.name])
    kvm_cmd.extend(["-m", instance.beparams[constants.BE_MAXMEM]])
    kvm_cmd.extend(["-smp", instance.beparams[constants.BE_VCPUS]])
    kvm_cmd.extend(["-pidfile", pidfile])
    kvm_cmd.extend(["-balloon", "virtio"])
    kvm_cmd.extend(["-daemonize"])
    if not instance.hvparams[constants.HV_ACPI]:
      kvm_cmd.extend(["-no-acpi"])
    if instance.hvparams[constants.HV_REBOOT_BEHAVIOR] == \
        constants.INSTANCE_REBOOT_EXIT:
      kvm_cmd.extend(["-no-reboot"])

    hvp = instance.hvparams
    kernel_path = hvp[constants.HV_KERNEL_PATH]
    if kernel_path:
      boot_disk = boot_cdrom = boot_floppy = boot_network = False
    else:
      boot_disk = hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_DISK
      boot_cdrom = hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_CDROM
      boot_floppy = hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_FLOPPY
      boot_network = hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_NETWORK

    self.ValidateParameters(hvp)

    if startup_paused:
      kvm_cmd.extend([_KVM_START_PAUSED_FLAG])

    if hvp[constants.HV_KVM_FLAG] == constants.HT_KVM_ENABLED:
      kvm_cmd.extend(["-enable-kvm"])
    elif hvp[constants.HV_KVM_FLAG] == constants.HT_KVM_DISABLED:
      kvm_cmd.extend(["-disable-kvm"])

    if boot_network:
      kvm_cmd.extend(["-boot", "n"])

    # whether this is an older KVM version that uses the boot=on flag
    # on devices
    needs_boot_flag = (v_major, v_min) < (0, 14)

    disk_type = hvp[constants.HV_DISK_TYPE]
    if disk_type == constants.HT_DISK_PARAVIRTUAL:
      if_val = ",if=virtio"
    else:
      if_val = ",if=%s" % disk_type
    # Cache mode
    disk_cache = hvp[constants.HV_DISK_CACHE]
    if instance.disk_template in constants.DTS_EXT_MIRROR:
      if disk_cache != "none":
        # TODO: make this a hard error, instead of a silent overwrite
        logging.warning("KVM: overriding disk_cache setting '%s' with 'none'"
                        " to prevent shared storage corruption on migration",
                        disk_cache)
      cache_val = ",cache=none"
    elif disk_cache != constants.HT_CACHE_DEFAULT:
      cache_val = ",cache=%s" % disk_cache
    else:
      cache_val = ""
    for cfdev, dev_path in block_devices:
      if cfdev.mode != constants.DISK_RDWR:
        raise errors.HypervisorError("Instance has read-only disks which"
                                     " are not supported by KVM")
      # TODO: handle FD_LOOP and FD_BLKTAP (?)
      boot_val = ""
      if boot_disk:
        kvm_cmd.extend(["-boot", "c"])
        boot_disk = False
        if needs_boot_flag and disk_type != constants.HT_DISK_IDE:
          boot_val = ",boot=on"

      drive_val = "file=%s,format=raw%s%s%s" % (dev_path, if_val, boot_val,
                                                cache_val)
      kvm_cmd.extend(["-drive", drive_val])

    #Now we can specify a different device type for CDROM devices.
    cdrom_disk_type = hvp[constants.HV_KVM_CDROM_DISK_TYPE]
    if not cdrom_disk_type:
      cdrom_disk_type = disk_type

    iso_image = hvp[constants.HV_CDROM_IMAGE_PATH]
    if iso_image:
      options = ",format=raw,media=cdrom"
      # set cdrom 'if' type
      if boot_cdrom:
        actual_cdrom_type = constants.HT_DISK_IDE
      elif cdrom_disk_type == constants.HT_DISK_PARAVIRTUAL:
        actual_cdrom_type = "virtio"
      else:
        actual_cdrom_type = cdrom_disk_type
      if_val = ",if=%s" % actual_cdrom_type
      # set boot flag, if needed
      boot_val = ""
      if boot_cdrom:
        kvm_cmd.extend(["-boot", "d"])
        if needs_boot_flag:
          boot_val = ",boot=on"
      # and finally build the entire '-drive' value
      drive_val = "file=%s%s%s%s" % (iso_image, options, if_val, boot_val)
      kvm_cmd.extend(["-drive", drive_val])

    iso_image2 = hvp[constants.HV_KVM_CDROM2_IMAGE_PATH]
    if iso_image2:
      options = ",format=raw,media=cdrom"
      if cdrom_disk_type == constants.HT_DISK_PARAVIRTUAL:
        if_val = ",if=virtio"
      else:
        if_val = ",if=%s" % cdrom_disk_type
      drive_val = "file=%s%s%s" % (iso_image2, options, if_val)
      kvm_cmd.extend(["-drive", drive_val])

    floppy_image = hvp[constants.HV_KVM_FLOPPY_IMAGE_PATH]
    if floppy_image:
      options = ",format=raw,media=disk"
      if boot_floppy:
        kvm_cmd.extend(["-boot", "a"])
        options = "%s,boot=on" % options
      if_val = ",if=floppy"
      options = "%s%s" % (options, if_val)
      drive_val = "file=%s%s" % (floppy_image, options)
      kvm_cmd.extend(["-drive", drive_val])

    if kernel_path:
      kvm_cmd.extend(["-kernel", kernel_path])
      initrd_path = hvp[constants.HV_INITRD_PATH]
      if initrd_path:
        kvm_cmd.extend(["-initrd", initrd_path])
      root_append = ["root=%s" % hvp[constants.HV_ROOT_PATH],
                     hvp[constants.HV_KERNEL_ARGS]]
      if hvp[constants.HV_SERIAL_CONSOLE]:
        root_append.append("console=ttyS0,38400")
      kvm_cmd.extend(["-append", " ".join(root_append)])

    mem_path = hvp[constants.HV_MEM_PATH]
    if mem_path:
      kvm_cmd.extend(["-mem-path", mem_path, "-mem-prealloc"])

    monitor_dev = ("unix:%s,server,nowait" %
                   self._InstanceMonitor(instance.name))
    kvm_cmd.extend(["-monitor", monitor_dev])
    if hvp[constants.HV_SERIAL_CONSOLE]:
      serial_dev = ("unix:%s,server,nowait" %
                    self._InstanceSerial(instance.name))
      kvm_cmd.extend(["-serial", serial_dev])
    else:
      kvm_cmd.extend(["-serial", "none"])

    mouse_type = hvp[constants.HV_USB_MOUSE]
    vnc_bind_address = hvp[constants.HV_VNC_BIND_ADDRESS]
    spice_bind = hvp[constants.HV_KVM_SPICE_BIND]
    spice_ip_version = None

    if mouse_type:
      kvm_cmd.extend(["-usb"])
      kvm_cmd.extend(["-usbdevice", mouse_type])
    elif vnc_bind_address:
      kvm_cmd.extend(["-usbdevice", constants.HT_MOUSE_TABLET])

    if vnc_bind_address:
      if netutils.IP4Address.IsValid(vnc_bind_address):
        if instance.network_port > constants.VNC_BASE_PORT:
          display = instance.network_port - constants.VNC_BASE_PORT
          if vnc_bind_address == constants.IP4_ADDRESS_ANY:
            vnc_arg = ":%d" % (display)
          else:
            vnc_arg = "%s:%d" % (vnc_bind_address, display)
        else:
          logging.error("Network port is not a valid VNC display (%d < %d)."
                        " Not starting VNC", instance.network_port,
                        constants.VNC_BASE_PORT)
          vnc_arg = "none"

        # Only allow tls and other option when not binding to a file, for now.
        # kvm/qemu gets confused otherwise about the filename to use.
        vnc_append = ""
        if hvp[constants.HV_VNC_TLS]:
          vnc_append = "%s,tls" % vnc_append
          if hvp[constants.HV_VNC_X509_VERIFY]:
            vnc_append = "%s,x509verify=%s" % (vnc_append,
                                               hvp[constants.HV_VNC_X509])
          elif hvp[constants.HV_VNC_X509]:
            vnc_append = "%s,x509=%s" % (vnc_append,
                                         hvp[constants.HV_VNC_X509])
        if hvp[constants.HV_VNC_PASSWORD_FILE]:
          vnc_append = "%s,password" % vnc_append

        vnc_arg = "%s%s" % (vnc_arg, vnc_append)

      else:
        vnc_arg = "unix:%s/%s.vnc" % (vnc_bind_address, instance.name)

      kvm_cmd.extend(["-vnc", vnc_arg])
    elif spice_bind:
      # FIXME: this is wrong here; the iface ip address differs
      # between systems, so it should be done in _ExecuteKVMRuntime
      if netutils.IsValidInterface(spice_bind):
        # The user specified a network interface, we have to figure out the IP
        # address.
        addresses = netutils.GetInterfaceIpAddresses(spice_bind)
        spice_ip_version = hvp[constants.HV_KVM_SPICE_IP_VERSION]

        # if the user specified an IP version and the interface does not
        # have that kind of IP addresses, throw an exception
        if spice_ip_version != constants.IFACE_NO_IP_VERSION_SPECIFIED:
          if not addresses[spice_ip_version]:
            raise errors.HypervisorError("spice: unable to get an IPv%s address"
                                         " for %s" % (spice_ip_version,
                                                      spice_bind))

        # the user did not specify an IP version, we have to figure it out
        elif (addresses[constants.IP4_VERSION] and
              addresses[constants.IP6_VERSION]):
          # we have both ipv4 and ipv6, let's use the cluster default IP
          # version
          cluster_family = ssconf.SimpleStore().GetPrimaryIPFamily()
          spice_ip_version = \
            netutils.IPAddress.GetVersionFromAddressFamily(cluster_family)
        elif addresses[constants.IP4_VERSION]:
          spice_ip_version = constants.IP4_VERSION
        elif addresses[constants.IP6_VERSION]:
          spice_ip_version = constants.IP6_VERSION
        else:
          raise errors.HypervisorError("spice: unable to get an IP address"
                                       " for %s" % (spice_bind))

        spice_address = addresses[spice_ip_version][0]

      else:
        # spice_bind is known to be a valid IP address, because
        # ValidateParameters checked it.
        spice_address = spice_bind

      spice_arg = "addr=%s" % spice_address
      if hvp[constants.HV_KVM_SPICE_USE_TLS]:
        spice_arg = ("%s,tls-port=%s,x509-cacert-file=%s" %
                     (spice_arg, instance.network_port,
                      pathutils.SPICE_CACERT_FILE))
        spice_arg = ("%s,x509-key-file=%s,x509-cert-file=%s" %
                     (spice_arg, pathutils.SPICE_CERT_FILE,
                      pathutils.SPICE_CERT_FILE))
        tls_ciphers = hvp[constants.HV_KVM_SPICE_TLS_CIPHERS]
        if tls_ciphers:
          spice_arg = "%s,tls-ciphers=%s" % (spice_arg, tls_ciphers)
      else:
        spice_arg = "%s,port=%s" % (spice_arg, instance.network_port)

      if not hvp[constants.HV_KVM_SPICE_PASSWORD_FILE]:
        spice_arg = "%s,disable-ticketing" % spice_arg

      if spice_ip_version:
        spice_arg = "%s,ipv%s" % (spice_arg, spice_ip_version)

      # Image compression options
      img_lossless = hvp[constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR]
      img_jpeg = hvp[constants.HV_KVM_SPICE_JPEG_IMG_COMPR]
      img_zlib_glz = hvp[constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR]
      if img_lossless:
        spice_arg = "%s,image-compression=%s" % (spice_arg, img_lossless)
      if img_jpeg:
        spice_arg = "%s,jpeg-wan-compression=%s" % (spice_arg, img_jpeg)
      if img_zlib_glz:
        spice_arg = "%s,zlib-glz-wan-compression=%s" % (spice_arg, img_zlib_glz)

      # Video stream detection
      video_streaming = hvp[constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION]
      if video_streaming:
        spice_arg = "%s,streaming-video=%s" % (spice_arg, video_streaming)

      # Audio compression, by default in qemu-kvm it is on
      if not hvp[constants.HV_KVM_SPICE_AUDIO_COMPR]:
        spice_arg = "%s,playback-compression=off" % spice_arg
      if not hvp[constants.HV_KVM_SPICE_USE_VDAGENT]:
        spice_arg = "%s,agent-mouse=off" % spice_arg
      else:
        # Enable the spice agent communication channel between the host and the
        # agent.
        kvm_cmd.extend(["-device", "virtio-serial-pci"])
        kvm_cmd.extend(["-device", "virtserialport,chardev=spicechannel0,"
                                                   "name=com.redhat.spice.0"])
        kvm_cmd.extend(["-chardev", "spicevmc,id=spicechannel0,name=vdagent"])

      logging.info("KVM: SPICE will listen on port %s", instance.network_port)
      kvm_cmd.extend(["-spice", spice_arg])

      # Tell kvm to use the paravirtualized graphic card, optimized for SPICE
      kvm_cmd.extend(["-vga", "qxl"])

    else:
      kvm_cmd.extend(["-nographic"])

    if hvp[constants.HV_USE_LOCALTIME]:
      kvm_cmd.extend(["-localtime"])

    if hvp[constants.HV_KVM_USE_CHROOT]:
      kvm_cmd.extend(["-chroot", self._InstanceChrootDir(instance.name)])

    # Add qemu-KVM -cpu param
    if hvp[constants.HV_CPU_TYPE]:
      kvm_cmd.extend(["-cpu", hvp[constants.HV_CPU_TYPE]])

    # Save the current instance nics, but defer their expansion as parameters,
    # as we'll need to generate executable temp files for them.
    kvm_nics = instance.nics
    hvparams = hvp

    return (kvm_cmd, kvm_nics, hvparams)

  def _WriteKVMRuntime(self, instance_name, data):
    """Write an instance's KVM runtime

    """
    try:
      utils.WriteFile(self._InstanceKVMRuntime(instance_name),
                      data=data)
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to save KVM runtime file: %s" % err)

  def _ReadKVMRuntime(self, instance_name):
    """Read an instance's KVM runtime

    """
    try:
      file_content = utils.ReadFile(self._InstanceKVMRuntime(instance_name))
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to load KVM runtime file: %s" % err)
    return file_content

  def _SaveKVMRuntime(self, instance, kvm_runtime):
    """Save an instance's KVM runtime

    """
    kvm_cmd, kvm_nics, hvparams = kvm_runtime
    serialized_nics = [nic.ToDict() for nic in kvm_nics]
    serialized_form = serializer.Dump((kvm_cmd, serialized_nics, hvparams))
    self._WriteKVMRuntime(instance.name, serialized_form)

  def _LoadKVMRuntime(self, instance, serialized_runtime=None):
    """Load an instance's KVM runtime

    """
    if not serialized_runtime:
      serialized_runtime = self._ReadKVMRuntime(instance.name)
    loaded_runtime = serializer.Load(serialized_runtime)
    kvm_cmd, serialized_nics, hvparams = loaded_runtime
    kvm_nics = [objects.NIC.FromDict(snic) for snic in serialized_nics]
    return (kvm_cmd, kvm_nics, hvparams)

  def _RunKVMCmd(self, name, kvm_cmd, tap_fds=None):
    """Run the KVM cmd and check for errors

    @type name: string
    @param name: instance name
    @type kvm_cmd: list of strings
    @param kvm_cmd: runcmd input for kvm
    @type tap_fds: list of int
    @param tap_fds: fds of tap devices opened by Ganeti

    """
    try:
      result = utils.RunCmd(kvm_cmd, noclose_fds=tap_fds)
    finally:
      for fd in tap_fds:
        utils_wrapper.CloseFdNoError(fd)

    if result.failed:
      raise errors.HypervisorError("Failed to start instance %s: %s (%s)" %
                                   (name, result.fail_reason, result.output))
    if not self._InstancePidAlive(name)[2]:
      raise errors.HypervisorError("Failed to start instance %s" % name)

  def _ExecuteKVMRuntime(self, instance, kvm_runtime, incoming=None):
    """Execute a KVM cmd, after completing it with some last minute data.

    @type incoming: tuple of strings
    @param incoming: (target_host_ip, port)

    """
    # Small _ExecuteKVMRuntime hv parameters programming howto:
    #  - conf_hvp contains the parameters as configured on ganeti. they might
    #    have changed since the instance started; only use them if the change
    #    won't affect the inside of the instance (which hasn't been rebooted).
    #  - up_hvp contains the parameters as they were when the instance was
    #    started, plus any new parameter which has been added between ganeti
    #    versions: it is paramount that those default to a value which won't
    #    affect the inside of the instance as well.
    conf_hvp = instance.hvparams
    name = instance.name
    self._CheckDown(name)

    temp_files = []

    kvm_cmd, kvm_nics, up_hvp = kvm_runtime
    up_hvp = objects.FillDict(conf_hvp, up_hvp)

    _, v_major, v_min, _ = self._GetKVMVersion()

    # We know it's safe to run as a different user upon migration, so we'll use
    # the latest conf, from conf_hvp.
    security_model = conf_hvp[constants.HV_SECURITY_MODEL]
    if security_model == constants.HT_SM_USER:
      kvm_cmd.extend(["-runas", conf_hvp[constants.HV_SECURITY_DOMAIN]])

    keymap = conf_hvp[constants.HV_KEYMAP]
    if keymap:
      keymap_path = self._InstanceKeymapFile(name)
      # If a keymap file is specified, KVM won't use its internal defaults. By
      # first including the "en-us" layout, an error on loading the actual
      # layout (e.g. because it can't be found) won't lead to a non-functional
      # keyboard. A keyboard with incorrect keys is still better than none.
      utils.WriteFile(keymap_path, data="include en-us\ninclude %s\n" % keymap)
      kvm_cmd.extend(["-k", keymap_path])

    # We have reasons to believe changing something like the nic driver/type
    # upon migration won't exactly fly with the instance kernel, so for nic
    # related parameters we'll use up_hvp
    tapfds = []
    taps = []
    if not kvm_nics:
      kvm_cmd.extend(["-net", "none"])
    else:
      vnet_hdr = False
      tap_extra = ""
      nic_type = up_hvp[constants.HV_NIC_TYPE]
      if nic_type == constants.HT_NIC_PARAVIRTUAL:
        # From version 0.12.0, kvm uses a new sintax for network configuration.
        if (v_major, v_min) >= (0, 12):
          nic_model = "virtio-net-pci"
          vnet_hdr = True
        else:
          nic_model = "virtio"

        if up_hvp[constants.HV_VHOST_NET]:
          # vhost_net is only available from version 0.13.0 or newer
          if (v_major, v_min) >= (0, 13):
            tap_extra = ",vhost=on"
          else:
            raise errors.HypervisorError("vhost_net is configured"
                                         " but it is not available")
      else:
        nic_model = nic_type

      for nic_seq, nic in enumerate(kvm_nics):
        tapname, tapfd = _OpenTap(vnet_hdr)
        tapfds.append(tapfd)
        taps.append(tapname)
        if (v_major, v_min) >= (0, 12):
          nic_val = "%s,mac=%s,netdev=netdev%s" % (nic_model, nic.mac, nic_seq)
          tap_val = "type=tap,id=netdev%s,fd=%d%s" % (nic_seq, tapfd, tap_extra)
          kvm_cmd.extend(["-netdev", tap_val, "-device", nic_val])
        else:
          nic_val = "nic,vlan=%s,macaddr=%s,model=%s" % (nic_seq,
                                                         nic.mac, nic_model)
          tap_val = "tap,vlan=%s,fd=%d" % (nic_seq, tapfd)
          kvm_cmd.extend(["-net", tap_val, "-net", nic_val])

    if incoming:
      target, port = incoming
      kvm_cmd.extend(["-incoming", "tcp:%s:%s" % (target, port)])

    # Changing the vnc password doesn't bother the guest that much. At most it
    # will surprise people who connect to it. Whether positively or negatively
    # it's debatable.
    vnc_pwd_file = conf_hvp[constants.HV_VNC_PASSWORD_FILE]
    vnc_pwd = None
    if vnc_pwd_file:
      try:
        vnc_pwd = utils.ReadOneLineFile(vnc_pwd_file, strict=True)
      except EnvironmentError, err:
        raise errors.HypervisorError("Failed to open VNC password file %s: %s"
                                     % (vnc_pwd_file, err))

    if conf_hvp[constants.HV_KVM_USE_CHROOT]:
      utils.EnsureDirs([(self._InstanceChrootDir(name),
                         constants.SECURE_DIR_MODE)])

    # Automatically enable QMP if version is >= 0.14
    if (v_major, v_min) >= (0, 14):
      logging.debug("Enabling QMP")
      kvm_cmd.extend(["-qmp", "unix:%s,server,nowait" %
                      self._InstanceQmpMonitor(instance.name)])

    # Configure the network now for starting instances and bridged interfaces,
    # during FinalizeMigration for incoming instances' routed interfaces
    for nic_seq, nic in enumerate(kvm_nics):
      if (incoming and
          nic.nicparams[constants.NIC_MODE] != constants.NIC_MODE_BRIDGED):
        continue
      self._ConfigureNIC(instance, nic_seq, nic, taps[nic_seq])

    # CPU affinity requires kvm to start paused, so we set this flag if the
    # instance is not already paused and if we are not going to accept a
    # migrating instance. In the latter case, pausing is not needed.
    start_kvm_paused = not (_KVM_START_PAUSED_FLAG in kvm_cmd) and not incoming
    if start_kvm_paused:
      kvm_cmd.extend([_KVM_START_PAUSED_FLAG])

    # Note: CPU pinning is using up_hvp since changes take effect
    # during instance startup anyway, and to avoid problems when soft
    # rebooting the instance.
    cpu_pinning = False
    if up_hvp.get(constants.HV_CPU_MASK, None):
      cpu_pinning = True

    if security_model == constants.HT_SM_POOL:
      ss = ssconf.SimpleStore()
      uid_pool = uidpool.ParseUidPool(ss.GetUidPool(), separator="\n")
      all_uids = set(uidpool.ExpandUidPool(uid_pool))
      uid = uidpool.RequestUnusedUid(all_uids)
      try:
        username = pwd.getpwuid(uid.GetUid()).pw_name
        kvm_cmd.extend(["-runas", username])
        self._RunKVMCmd(name, kvm_cmd, tapfds)
      except:
        uidpool.ReleaseUid(uid)
        raise
      else:
        uid.Unlock()
        utils.WriteFile(self._InstanceUidFile(name), data=uid.AsStr())
    else:
      self._RunKVMCmd(name, kvm_cmd, tapfds)

    utils.EnsureDirs([(self._InstanceNICDir(instance.name),
                     constants.RUN_DIRS_MODE)])
    for nic_seq, tap in enumerate(taps):
      utils.WriteFile(self._InstanceNICFile(instance.name, nic_seq),
                      data=tap)

    if vnc_pwd:
      change_cmd = "change vnc password %s" % vnc_pwd
      self._CallMonitorCommand(instance.name, change_cmd)

    # Setting SPICE password. We are not vulnerable to malicious passwordless
    # connection attempts because SPICE by default does not allow connections
    # if neither a password nor the "disable_ticketing" options are specified.
    # As soon as we send the password via QMP, that password is a valid ticket
    # for connection.
    spice_password_file = conf_hvp[constants.HV_KVM_SPICE_PASSWORD_FILE]
    if spice_password_file:
      spice_pwd = ""
      try:
        spice_pwd = utils.ReadOneLineFile(spice_password_file, strict=True)
      except EnvironmentError, err:
        raise errors.HypervisorError("Failed to open SPICE password file %s: %s"
                                     % (spice_password_file, err))

      qmp = QmpConnection(self._InstanceQmpMonitor(instance.name))
      qmp.connect()
      arguments = {
          "protocol": "spice",
          "password": spice_pwd,
      }
      qmp.Execute("set_password", arguments)

    for filename in temp_files:
      utils.RemoveFile(filename)

    # If requested, set CPU affinity and resume instance execution
    if cpu_pinning:
      self._ExecuteCpuAffinity(instance.name, up_hvp[constants.HV_CPU_MASK])

    start_memory = self._InstanceStartupMemory(instance)
    if start_memory < instance.beparams[constants.BE_MAXMEM]:
      self.BalloonInstanceMemory(instance, start_memory)

    if start_kvm_paused:
      # To control CPU pinning, ballooning, and vnc/spice passwords
      # the VM was started in a frozen state. If freezing was not
      # explicitly requested resume the vm status.
      self._CallMonitorCommand(instance.name, self._CONT_CMD)

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    """
    self._CheckDown(instance.name)
    kvm_runtime = self._GenerateKVMRuntime(instance, block_devices,
                                           startup_paused)
    self._SaveKVMRuntime(instance, kvm_runtime)
    self._ExecuteKVMRuntime(instance, kvm_runtime)

  def _CallMonitorCommand(self, instance_name, command):
    """Invoke a command on the instance monitor.

    """
    socat = ("echo %s | %s STDIO UNIX-CONNECT:%s" %
             (utils.ShellQuote(command),
              constants.SOCAT_PATH,
              utils.ShellQuote(self._InstanceMonitor(instance_name))))
    result = utils.RunCmd(socat)
    if result.failed:
      msg = ("Failed to send command '%s' to instance %s."
             " output: %s, error: %s, fail_reason: %s" %
             (command, instance_name,
              result.stdout, result.stderr, result.fail_reason))
      raise errors.HypervisorError(msg)

    return result

  @classmethod
  def _ParseKVMVersion(cls, text):
    """Parse the KVM version from the --help output.

    @type text: string
    @param text: output of kvm --help
    @return: (version, v_maj, v_min, v_rev)
    @raise errors.HypervisorError: when the KVM version cannot be retrieved

    """
    match = cls._VERSION_RE.search(text.splitlines()[0])
    if not match:
      raise errors.HypervisorError("Unable to get KVM version")

    v_all = match.group(0)
    v_maj = int(match.group(1))
    v_min = int(match.group(2))
    if match.group(4):
      v_rev = int(match.group(4))
    else:
      v_rev = 0
    return (v_all, v_maj, v_min, v_rev)

  @classmethod
  def _GetKVMVersion(cls):
    """Return the installed KVM version.

    @return: (version, v_maj, v_min, v_rev)
    @raise errors.HypervisorError: when the KVM version cannot be retrieved

    """
    result = utils.RunCmd([constants.KVM_PATH, "--help"])
    if result.failed:
      raise errors.HypervisorError("Unable to get KVM version")
    return cls._ParseKVMVersion(result.output)

  def StopInstance(self, instance, force=False, retry=False, name=None):
    """Stop an instance.

    """
    if name is not None and not force:
      raise errors.HypervisorError("Cannot shutdown cleanly by name only")
    if name is None:
      name = instance.name
      acpi = instance.hvparams[constants.HV_ACPI]
    else:
      acpi = False
    _, pid, alive = self._InstancePidAlive(name)
    if pid > 0 and alive:
      if force or not acpi:
        utils.KillProcess(pid)
      else:
        self._CallMonitorCommand(name, "system_powerdown")

  def CleanupInstance(self, instance_name):
    """Cleanup after a stopped instance

    """
    pidfile, pid, alive = self._InstancePidAlive(instance_name)
    if pid > 0 and alive:
      raise errors.HypervisorError("Cannot cleanup a live instance")
    self._RemoveInstanceRuntimeFiles(pidfile, instance_name)

  def RebootInstance(self, instance):
    """Reboot an instance.

    """
    # For some reason if we do a 'send-key ctrl-alt-delete' to the control
    # socket the instance will stop, but now power up again. So we'll resort
    # to shutdown and restart.
    _, _, alive = self._InstancePidAlive(instance.name)
    if not alive:
      raise errors.HypervisorError("Failed to reboot instance %s:"
                                   " not running" % instance.name)
    # StopInstance will delete the saved KVM runtime so:
    # ...first load it...
    kvm_runtime = self._LoadKVMRuntime(instance)
    # ...now we can safely call StopInstance...
    if not self.StopInstance(instance):
      self.StopInstance(instance, force=True)
    # ...and finally we can save it again, and execute it...
    self._SaveKVMRuntime(instance, kvm_runtime)
    self._ExecuteKVMRuntime(instance, kvm_runtime)

  def MigrationInfo(self, instance):
    """Get instance information to perform a migration.

    @type instance: L{objects.Instance}
    @param instance: instance to be migrated
    @rtype: string
    @return: content of the KVM runtime file

    """
    return self._ReadKVMRuntime(instance.name)

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string
    @param info: content of the KVM runtime file on the source node
    @type target: string
    @param target: target host (usually ip), on this node

    """
    kvm_runtime = self._LoadKVMRuntime(instance, serialized_runtime=info)
    incoming_address = (target, instance.hvparams[constants.HV_MIGRATION_PORT])
    self._ExecuteKVMRuntime(instance, kvm_runtime, incoming=incoming_address)

  def FinalizeMigrationDst(self, instance, info, success):
    """Finalize the instance migration on the target node.

    Stop the incoming mode KVM.

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being finalized

    """
    if success:
      kvm_runtime = self._LoadKVMRuntime(instance, serialized_runtime=info)
      kvm_nics = kvm_runtime[1]

      for nic_seq, nic in enumerate(kvm_nics):
        if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
          # Bridged interfaces have already been configured
          continue
        try:
          tap = utils.ReadFile(self._InstanceNICFile(instance.name, nic_seq))
        except EnvironmentError, err:
          logging.warning("Failed to find host interface for %s NIC #%d: %s",
                          instance.name, nic_seq, str(err))
          continue
        try:
          self._ConfigureNIC(instance, nic_seq, nic, tap)
        except errors.HypervisorError, err:
          logging.warning(str(err))

      self._WriteKVMRuntime(instance.name, info)
    else:
      self.StopInstance(instance, force=True)

  def MigrateInstance(self, instance, target, live):
    """Migrate an instance to a target node.

    The migration will not be attempted if the instance is not
    currently running.

    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: ip address of the target node
    @type live: boolean
    @param live: perform a live migration

    """
    instance_name = instance.name
    port = instance.hvparams[constants.HV_MIGRATION_PORT]
    _, _, alive = self._InstancePidAlive(instance_name)
    if not alive:
      raise errors.HypervisorError("Instance not running, cannot migrate")

    if not live:
      self._CallMonitorCommand(instance_name, "stop")

    migrate_command = ("migrate_set_speed %dm" %
                       instance.hvparams[constants.HV_MIGRATION_BANDWIDTH])
    self._CallMonitorCommand(instance_name, migrate_command)

    migrate_command = ("migrate_set_downtime %dms" %
                       instance.hvparams[constants.HV_MIGRATION_DOWNTIME])
    self._CallMonitorCommand(instance_name, migrate_command)

    migrate_command = "migrate -d tcp:%s:%s" % (target, port)
    self._CallMonitorCommand(instance_name, migrate_command)

  def FinalizeMigrationSource(self, instance, success, live):
    """Finalize the instance migration on the source node.

    @type instance: L{objects.Instance}
    @param instance: the instance that was migrated
    @type success: bool
    @param success: whether the migration succeeded or not
    @type live: bool
    @param live: whether the user requested a live migration or not

    """
    if success:
      pidfile, pid, _ = self._InstancePidAlive(instance.name)
      utils.KillProcess(pid)
      self._RemoveInstanceRuntimeFiles(pidfile, instance.name)
    elif live:
      self._CallMonitorCommand(instance.name, self._CONT_CMD)

  def GetMigrationStatus(self, instance):
    """Get the migration status

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    info_command = "info migrate"
    for _ in range(self._MIGRATION_INFO_MAX_BAD_ANSWERS):
      result = self._CallMonitorCommand(instance.name, info_command)
      match = self._MIGRATION_STATUS_RE.search(result.stdout)
      if not match:
        if not result.stdout:
          logging.info("KVM: empty 'info migrate' result")
        else:
          logging.warning("KVM: unknown 'info migrate' result: %s",
                          result.stdout)
      else:
        status = match.group(1)
        if status in constants.HV_KVM_MIGRATION_VALID_STATUSES:
          migration_status = objects.MigrationStatus(status=status)
          match = self._MIGRATION_PROGRESS_RE.search(result.stdout)
          if match:
            migration_status.transferred_ram = match.group("transferred")
            migration_status.total_ram = match.group("total")

          return migration_status

        logging.warning("KVM: unknown migration status '%s'", status)

      time.sleep(self._MIGRATION_INFO_RETRY_DELAY)

    return objects.MigrationStatus(status=constants.HV_MIGRATION_FAILED)

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    self._CallMonitorCommand(instance.name, "balloon %d" % mem)

  def GetNodeInfo(self):
    """Return information about the node.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available
          - hv_version: the hypervisor version in the form (major, minor,
                        revision)

    """
    result = self.GetLinuxNodeInfo()
    _, v_major, v_min, v_rev = self._GetKVMVersion()
    result[constants.HV_NODEINFO_KEY_VERSION] = (v_major, v_min, v_rev)
    return result

  @classmethod
  def GetInstanceConsole(cls, instance, hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    if hvparams[constants.HV_SERIAL_CONSOLE]:
      cmd = [pathutils.KVM_CONSOLE_WRAPPER,
             constants.SOCAT_PATH, utils.ShellQuote(instance.name),
             utils.ShellQuote(cls._InstanceMonitor(instance.name)),
             "STDIO,%s" % cls._SocatUnixConsoleParams(),
             "UNIX-CONNECT:%s" % cls._InstanceSerial(instance.name)]
      return objects.InstanceConsole(instance=instance.name,
                                     kind=constants.CONS_SSH,
                                     host=instance.primary_node,
                                     user=constants.SSH_CONSOLE_USER,
                                     command=cmd)

    vnc_bind_address = hvparams[constants.HV_VNC_BIND_ADDRESS]
    if vnc_bind_address and instance.network_port > constants.VNC_BASE_PORT:
      display = instance.network_port - constants.VNC_BASE_PORT
      return objects.InstanceConsole(instance=instance.name,
                                     kind=constants.CONS_VNC,
                                     host=vnc_bind_address,
                                     port=instance.network_port,
                                     display=display)

    spice_bind = hvparams[constants.HV_KVM_SPICE_BIND]
    if spice_bind:
      return objects.InstanceConsole(instance=instance.name,
                                     kind=constants.CONS_SPICE,
                                     host=spice_bind,
                                     port=instance.network_port)

    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_MESSAGE,
                                   message=("No serial shell for instance %s" %
                                            instance.name))

  def Verify(self):
    """Verify the hypervisor.

    Check that the binary exists.

    """
    if not os.path.exists(constants.KVM_PATH):
      return "The kvm binary ('%s') does not exist." % constants.KVM_PATH
    if not os.path.exists(constants.SOCAT_PATH):
      return "The socat binary ('%s') does not exist." % constants.SOCAT_PATH

  @classmethod
  def CheckParameterSyntax(cls, hvparams):
    """Check the given parameters for validity.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    super(KVMHypervisor, cls).CheckParameterSyntax(hvparams)

    kernel_path = hvparams[constants.HV_KERNEL_PATH]
    if kernel_path:
      if not hvparams[constants.HV_ROOT_PATH]:
        raise errors.HypervisorError("Need a root partition for the instance,"
                                     " if a kernel is defined")

    if (hvparams[constants.HV_VNC_X509_VERIFY] and
        not hvparams[constants.HV_VNC_X509]):
      raise errors.HypervisorError("%s must be defined, if %s is" %
                                   (constants.HV_VNC_X509,
                                    constants.HV_VNC_X509_VERIFY))

    boot_order = hvparams[constants.HV_BOOT_ORDER]
    if (boot_order == constants.HT_BO_CDROM and
        not hvparams[constants.HV_CDROM_IMAGE_PATH]):
      raise errors.HypervisorError("Cannot boot from cdrom without an"
                                   " ISO path")

    security_model = hvparams[constants.HV_SECURITY_MODEL]
    if security_model == constants.HT_SM_USER:
      if not hvparams[constants.HV_SECURITY_DOMAIN]:
        raise errors.HypervisorError("A security domain (user to run kvm as)"
                                     " must be specified")
    elif (security_model == constants.HT_SM_NONE or
          security_model == constants.HT_SM_POOL):
      if hvparams[constants.HV_SECURITY_DOMAIN]:
        raise errors.HypervisorError("Cannot have a security domain when the"
                                     " security model is 'none' or 'pool'")

    spice_bind = hvparams[constants.HV_KVM_SPICE_BIND]
    spice_ip_version = hvparams[constants.HV_KVM_SPICE_IP_VERSION]
    if spice_bind:
      if spice_ip_version != constants.IFACE_NO_IP_VERSION_SPECIFIED:
        # if an IP version is specified, the spice_bind parameter must be an
        # IP of that family
        if (netutils.IP4Address.IsValid(spice_bind) and
            spice_ip_version != constants.IP4_VERSION):
          raise errors.HypervisorError("spice: got an IPv4 address (%s), but"
                                       " the specified IP version is %s" %
                                       (spice_bind, spice_ip_version))

        if (netutils.IP6Address.IsValid(spice_bind) and
            spice_ip_version != constants.IP6_VERSION):
          raise errors.HypervisorError("spice: got an IPv6 address (%s), but"
                                       " the specified IP version is %s" %
                                       (spice_bind, spice_ip_version))
    else:
      # All the other SPICE parameters depend on spice_bind being set. Raise an
      # error if any of them is set without it.
      spice_additional_params = frozenset([
        constants.HV_KVM_SPICE_IP_VERSION,
        constants.HV_KVM_SPICE_PASSWORD_FILE,
        constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR,
        constants.HV_KVM_SPICE_JPEG_IMG_COMPR,
        constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR,
        constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION,
        constants.HV_KVM_SPICE_USE_TLS,
        ])
      for param in spice_additional_params:
        if hvparams[param]:
          raise errors.HypervisorError("spice: %s requires %s to be set" %
                                       (param, constants.HV_KVM_SPICE_BIND))

  @classmethod
  def ValidateParameters(cls, hvparams):
    """Check the given parameters for validity.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    super(KVMHypervisor, cls).ValidateParameters(hvparams)

    security_model = hvparams[constants.HV_SECURITY_MODEL]
    if security_model == constants.HT_SM_USER:
      username = hvparams[constants.HV_SECURITY_DOMAIN]
      try:
        pwd.getpwnam(username)
      except KeyError:
        raise errors.HypervisorError("Unknown security domain user %s"
                                     % username)

    spice_bind = hvparams[constants.HV_KVM_SPICE_BIND]
    if spice_bind:
      # only one of VNC and SPICE can be used currently.
      if hvparams[constants.HV_VNC_BIND_ADDRESS]:
        raise errors.HypervisorError("both SPICE and VNC are configured, but"
                                     " only one of them can be used at a"
                                     " given time.")

      # KVM version should be >= 0.14.0
      _, v_major, v_min, _ = cls._GetKVMVersion()
      if (v_major, v_min) < (0, 14):
        raise errors.HypervisorError("spice is configured, but it is not"
                                     " available in versions of KVM < 0.14")

      # if spice_bind is not an IP address, it must be a valid interface
      bound_to_addr = (netutils.IP4Address.IsValid(spice_bind)
                       or netutils.IP6Address.IsValid(spice_bind))
      if not bound_to_addr and not netutils.IsValidInterface(spice_bind):
        raise errors.HypervisorError("spice: the %s parameter must be either"
                                     " a valid IP address or interface name" %
                                     constants.HV_KVM_SPICE_BIND)

  @classmethod
  def PowercycleNode(cls):
    """KVM powercycle, just a wrapper over Linux powercycle.

    """
    cls.LinuxPowercycle()
