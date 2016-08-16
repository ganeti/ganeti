#
#

# Copyright (C) 2014 Google Inc.
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


"""ExtStorage Interface related functionality

"""

import re
import stat
import os
import logging

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import objects
from ganeti import pathutils
from ganeti.storage import base


class ExtStorageDevice(base.BlockDev):
  """A block device provided by an ExtStorage Provider.

  This class implements the External Storage Interface, which means
  handling of the externally provided block devices.

  """
  def __init__(self, unique_id, children, size, params, dyn_params, **kwargs):
    """Attaches to an extstorage block device.

    """
    super(ExtStorageDevice, self).__init__(unique_id, children, size, params,
                                           dyn_params, **kwargs)
    self.name = kwargs["name"]
    self.uuid = kwargs["uuid"]

    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    self.driver, self.vol_name = unique_id
    self.ext_params = params

    self.major = self.minor = None
    self.uris = []
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, **kwargs):
    """Create a new extstorage device.

    Provision a new volume using an extstorage provider, which will
    then be mapped to a block device.

    """

    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise errors.ProgrammerError("Invalid configuration data %s" %
                                   str(unique_id))
    if excl_stor:
      raise errors.ProgrammerError("extstorage device requested with"
                                   " exclusive_storage")

    # Call the External Storage's create script,
    # to provision a new Volume inside the External Storage
    _ExtStorageAction(constants.ES_ACTION_CREATE, unique_id,
                      params, size=size, name=kwargs["name"],
                      uuid=kwargs["uuid"])

    return ExtStorageDevice(unique_id, children, size, params, dyn_params,
                            **kwargs)

  def Remove(self):
    """Remove the extstorage device.

    """
    if not self.minor and not self.Attach():
      # The extstorage device doesn't exist.
      return

    # First shutdown the device (remove mappings).
    self.Shutdown()

    # Call the External Storage's remove script,
    # to remove the Volume from the External Storage
    _ExtStorageAction(constants.ES_ACTION_REMOVE, self.unique_id,
                      self.ext_params, name=self.name, uuid=self.uuid)

  def Rename(self, new_id):
    """Rename this device.

    """
    pass

  def Attach(self, **kwargs):
    """Attach to an existing extstorage device.

    This method maps the extstorage volume that matches our name with
    a corresponding block device and then attaches to this device.

    """
    self.attached = False

    # Call the External Storage's attach script,
    # to attach an existing Volume to a block device under /dev
    result = _ExtStorageAction(constants.ES_ACTION_ATTACH,
                               self.unique_id, self.ext_params,
                               name=self.name, uuid=self.uuid)

    # Attach script returns the block device path and optionally
    # the URIs to be used for userspace access (one URI for
    # each hypervisor supported).
    # If the provider doesn't support userspace access, then
    # the 'uris' variable will be an empty list.
    result = result.split("\n")
    self.dev_path = result[0]
    self.uris = result[1:]

    if not self.dev_path:
      logging.info("A local block device is not available")
      self.dev_path = None
      if not self.uris:
        logging.error("Neither a block device nor a userspace URI is available")
        return False

      self.attached = True
      return True

    # Verify that dev_path exists and is a block device
    try:
      st = os.stat(self.dev_path)
    except OSError, err:
      logging.error("Error stat()'ing %s: %s", self.dev_path, str(err))
      return False

    if not stat.S_ISBLK(st.st_mode):
      logging.error("%s is not a block device", self.dev_path)
      return False

    self.major = os.major(st.st_rdev)
    self.minor = utils.osminor(st.st_rdev)
    self.attached = True

    return True

  def Assemble(self):
    """Assemble the device.

    """
    pass

  def Shutdown(self):
    """Shutdown the device.

    """
    if not self.minor and not self.Attach():
      # The extstorage device doesn't exist.
      return

    # Call the External Storage's detach script,
    # to detach an existing Volume from it's block device under /dev
    _ExtStorageAction(constants.ES_ACTION_DETACH, self.unique_id,
                      self.ext_params, name=self.name, uuid=self.uuid)

    self.minor = None
    self.dev_path = None

  def Open(self, force=False, exclusive=True):
    """Make the device ready for I/O.

    """
    _ExtStorageAction(constants.ES_ACTION_OPEN, self.unique_id,
                      self.ext_params,
                      name=self.name, uuid=self.uuid,
                      exclusive=exclusive)

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    _ExtStorageAction(constants.ES_ACTION_CLOSE, self.unique_id,
                      self.ext_params,
                      name=self.name, uuid=self.uuid)

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the Volume.

    @type amount: integer
    @param amount: the amount (in mebibytes) to grow with
    @type dryrun: boolean
    @param dryrun: whether to execute the operation in simulation mode
        only, without actually increasing the size

    """
    if not backingstore:
      return
    if not self.Attach():
      base.ThrowError("Can't attach to extstorage device during Grow()")

    if dryrun:
      # we do not support dry runs of resize operations for now.
      return

    new_size = self.size + amount

    # Call the External Storage's grow script,
    # to grow an existing Volume inside the External Storage
    _ExtStorageAction(constants.ES_ACTION_GROW, self.unique_id,
                      self.ext_params, size=self.size, grow=new_size,
                      name=self.name, uuid=self.uuid)

  def SetInfo(self, text):
    """Update metadata with info text.

    """
    # Replace invalid characters
    text = re.sub("^[^A-Za-z0-9_+.]", "_", text)
    text = re.sub("[^-A-Za-z0-9_+.]", "_", text)

    # Only up to 128 characters are allowed
    text = text[:128]

    # Call the External Storage's setinfo script,
    # to set metadata for an existing Volume inside the External Storage
    _ExtStorageAction(constants.ES_ACTION_SETINFO, self.unique_id,
                      self.ext_params, metadata=text,
                      name=self.name, uuid=self.uuid)

  def GetUserspaceAccessUri(self, hypervisor):
    """Generate KVM userspace URIs to be used as `-drive file` settings.

    @see: L{base.BlockDev.GetUserspaceAccessUri}

    """
    if not self.Attach():
      base.ThrowError("Can't attach to ExtStorage device")

    # If the provider supports userspace access, the attach script has
    # returned a list of URIs prefixed with the corresponding hypervisor.
    prefix = hypervisor.lower() + ":"
    for uri in self.uris:
      if uri[:len(prefix)].lower() == prefix:
        return uri[len(prefix):]

    base.ThrowError("Userspace access is not supported by the '%s'"
                    " ExtStorage provider for the '%s' hypervisor"
                    % (self.driver, hypervisor))

  def Snapshot(self, snap_name=None, snap_size=None):
    """Take a snapshot of the block device.

    """
    provider, vol_name = self.unique_id
    if not snap_name:
      snap_name = vol_name + ".snap"
    if not snap_size:
      snap_size = self.size

    _ExtStorageAction(constants.ES_ACTION_SNAPSHOT, self.unique_id,
                      self.ext_params, snap_name=snap_name, snap_size=snap_size)

    return (provider, snap_name)


def _ExtStorageAction(action, unique_id, ext_params,
                      size=None, grow=None, metadata=None,
                      name=None, uuid=None,
                      snap_name=None, snap_size=None,
                      exclusive=None):
  """Take an External Storage action.

  Take an External Storage action concerning or affecting
  a specific Volume inside the External Storage.

  @type action: string
  @param action: which action to perform. One of:
                 create / remove / grow / attach / detach / snapshot
  @type unique_id: tuple (driver, vol_name)
  @param unique_id: a tuple containing the type of ExtStorage (driver)
                    and the Volume name
  @type ext_params: dict
  @param ext_params: ExtStorage parameters
  @type size: integer
  @param size: the size of the Volume in mebibytes
  @type grow: integer
  @param grow: the new size in mebibytes (after grow)
  @type metadata: string
  @param metadata: metadata info of the Volume, for use by the provider
  @type name: string
  @param name: name of the Volume (objects.Disk.name)
  @type uuid: string
  @type snap_size: integer
  @param snap_size: the size of the snapshot
  @type snap_name: string
  @param snap_name: the name of the snapshot
  @type exclusive: boolean
  @param exclusive: Whether the Volume will be opened exclusively or not
  @param uuid: uuid of the Volume (objects.Disk.uuid)
  @rtype: None or a block device path (during attach)

  """
  driver, vol_name = unique_id

  # Create an External Storage instance of type `driver'
  status, inst_es = ExtStorageFromDisk(driver)
  if not status:
    base.ThrowError("%s" % inst_es)

  # Create the basic environment for the driver's scripts
  create_env = _ExtStorageEnvironment(unique_id, ext_params, size,
                                      grow, metadata, name, uuid,
                                      snap_name, snap_size,
                                      exclusive)

  # Do not use log file for action `attach' as we need
  # to get the output from RunResult
  # TODO: find a way to have a log file for attach too
  logfile = None
  if action is not constants.ES_ACTION_ATTACH:
    logfile = _VolumeLogName(action, driver, vol_name)

  # Make sure the given action results in a valid script
  if action not in constants.ES_SCRIPTS:
    base.ThrowError("Action '%s' doesn't result in a valid ExtStorage script" %
                    action)

  # Find out which external script to run according the given action
  script_name = action + "_script"
  script = getattr(inst_es, script_name)

  # Here script is either a valid file path or None if the script is optional
  if not script:
    logging.info("Optional action '%s' is not supported by provider '%s',"
                 " skipping", action, driver)
    return

  # Run the external script
  # pylint: disable=E1103
  result = utils.RunCmd([script], env=create_env,
                        cwd=inst_es.path, output=logfile,)
  if result.failed:
    logging.error("External storage's %s command '%s' returned"
                  " error: %s, logfile: %s, output: %s",
                  action, result.cmd, result.fail_reason,
                  logfile, result.output)

    # If logfile is 'None' (during attach), it breaks TailFile
    # TODO: have a log file for attach too
    if action is not constants.ES_ACTION_ATTACH:
      lines = [utils.SafeEncode(val)
               for val in utils.TailFile(logfile, lines=20)]
    else:
      lines = result.output.splitlines()[-20:]

    base.ThrowError("External storage's %s script failed (%s), last"
                    " lines of output:\n%s",
                    action, result.fail_reason, "\n".join(lines))

  if action == constants.ES_ACTION_ATTACH:
    return result.stdout


def _CheckExtStorageFile(base_dir, filename, required):
  """Check prereqs for an ExtStorage file.

  Check if file exists, if it is a regular file and in case it is
  one of extstorage scripts if it is executable.

  @type base_dir: string
  @param base_dir: Base directory containing ExtStorage installations.
  @type filename: string
  @param filename: The basename of the ExtStorage file.
  @type required: bool
  @param required: Whether the file is required or not.

  @rtype: String
  @return: The file path if the file is found and is valid,
           None if the file is not found and not required.

  @raises BlockDeviceError: In case prereqs are not met
    (found and not valid/executable, not found and required)

  """

  file_path = utils.PathJoin(base_dir, filename)
  try:
    st = os.stat(file_path)
  except EnvironmentError, err:
    if not required:
      logging.info("Optional file '%s' under path '%s' is missing",
                   filename, base_dir)
      return None

    base.ThrowError("File '%s' under path '%s' is missing (%s)" %
                    (filename, base_dir, utils.ErrnoOrStr(err)))

  if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
    base.ThrowError("File '%s' under path '%s' is not a regular file" %
                    (filename, base_dir))

  if filename in constants.ES_SCRIPTS:
    if stat.S_IMODE(st.st_mode) & stat.S_IXUSR != stat.S_IXUSR:
      base.ThrowError("File '%s' under path '%s' is not executable" %
                      (filename, base_dir))

  return file_path


def ExtStorageFromDisk(name, base_dir=None):
  """Create an ExtStorage instance from disk.

  This function will return an ExtStorage instance
  if the given name is a valid ExtStorage name.

  @type base_dir: string
  @keyword base_dir: Base directory containing ExtStorage installations.
                     Defaults to a search in all the ES_SEARCH_PATH dirs.
  @rtype: tuple
  @return: True and the ExtStorage instance if we find a valid one, or
      False and the diagnose message on error

  """
  if base_dir is None:
    es_base_dir = pathutils.ES_SEARCH_PATH
  else:
    es_base_dir = [base_dir]

  es_dir = utils.FindFile(name, es_base_dir, os.path.isdir)

  if es_dir is None:
    return False, ("Directory for External Storage Provider %s not"
                   " found in search path" % name)

  # ES Files dictionary: this will be populated later with the absolute path
  # names for each script; currently we denote for each script if it is
  # required (True) or optional (False)
  es_files = dict.fromkeys(constants.ES_SCRIPTS, True)

  # Let the snapshot, open, and close scripts be optional
  # for backwards compatibility
  es_files[constants.ES_SCRIPT_SNAPSHOT] = False
  es_files[constants.ES_SCRIPT_OPEN] = False
  es_files[constants.ES_SCRIPT_CLOSE] = False

  es_files[constants.ES_PARAMETERS_FILE] = True

  for (filename, required) in es_files.items():
    try:
      # Here we actually fill the dict with the ablsolute path name for each
      # script or None, depending on the corresponding checks. See the
      # function's docstrings for more on these checks.
      es_files[filename] = _CheckExtStorageFile(es_dir, filename, required)
    except errors.BlockDeviceError, err:
      return False, str(err)

  parameters = []
  if constants.ES_PARAMETERS_FILE in es_files:
    parameters_file = es_files[constants.ES_PARAMETERS_FILE]
    try:
      parameters = utils.ReadFile(parameters_file).splitlines()
    except EnvironmentError, err:
      return False, ("Error while reading the EXT parameters file at %s: %s" %
                     (parameters_file, utils.ErrnoOrStr(err)))
    parameters = [v.split(None, 1) for v in parameters]

  es_obj = \
    objects.ExtStorage(name=name, path=es_dir,
                       create_script=es_files[constants.ES_SCRIPT_CREATE],
                       remove_script=es_files[constants.ES_SCRIPT_REMOVE],
                       grow_script=es_files[constants.ES_SCRIPT_GROW],
                       attach_script=es_files[constants.ES_SCRIPT_ATTACH],
                       detach_script=es_files[constants.ES_SCRIPT_DETACH],
                       setinfo_script=es_files[constants.ES_SCRIPT_SETINFO],
                       verify_script=es_files[constants.ES_SCRIPT_VERIFY],
                       snapshot_script=es_files[constants.ES_SCRIPT_SNAPSHOT],
                       open_script=es_files[constants.ES_SCRIPT_OPEN],
                       close_script=es_files[constants.ES_SCRIPT_CLOSE],
                       supported_parameters=parameters)
  return True, es_obj


def _ExtStorageEnvironment(unique_id, ext_params,
                           size=None, grow=None, metadata=None,
                           name=None, uuid=None,
                           snap_name=None, snap_size=None,
                           exclusive=None):
  """Calculate the environment for an External Storage script.

  @type unique_id: tuple (driver, vol_name)
  @param unique_id: ExtStorage pool and name of the Volume
  @type ext_params: dict
  @param ext_params: the EXT parameters
  @type size: integer
  @param size: size of the Volume (in mebibytes)
  @type grow: integer
  @param grow: new size of Volume after grow (in mebibytes)
  @type metadata: string
  @param metadata: metadata info of the Volume
  @type name: string
  @param name: name of the Volume (objects.Disk.name)
  @type uuid: string
  @param uuid: uuid of the Volume (objects.Disk.uuid)
  @type snap_size: integer
  @param snap_size: the size of the snapshot
  @type snap_name: string
  @param snap_name: the name of the snapshot
  @type exclusive: boolean
  @param exclusive: Whether the Volume will be opened exclusively or not
  @rtype: dict
  @return: dict of environment variables

  """
  vol_name = unique_id[1]

  result = {}
  result["VOL_NAME"] = vol_name

  # EXT params
  for pname, pvalue in ext_params.items():
    result["EXTP_%s" % pname.upper()] = str(pvalue)

  if size is not None:
    result["VOL_SIZE"] = str(size)

  if grow is not None:
    result["VOL_NEW_SIZE"] = str(grow)

  if metadata is not None:
    result["VOL_METADATA"] = metadata

  if name is not None:
    result["VOL_CNAME"] = name

  if uuid is not None:
    result["VOL_UUID"] = uuid

  if snap_name is not None:
    result["VOL_SNAPSHOT_NAME"] = snap_name

  if snap_size is not None:
    result["VOL_SNAPSHOT_SIZE"] = str(snap_size)

  if exclusive is not None:
    result["VOL_OPEN_EXCLUSIVE"] = str(exclusive)

  return result


def _VolumeLogName(kind, es_name, volume):
  """Compute the ExtStorage log filename for a given Volume and operation.

  @type kind: string
  @param kind: the operation type (e.g. create, remove etc.)
  @type es_name: string
  @param es_name: the ExtStorage name
  @type volume: string
  @param volume: the name of the Volume inside the External Storage

  """
  # Check if the extstorage log dir is a valid dir
  if not os.path.isdir(pathutils.LOG_ES_DIR):
    base.ThrowError("Cannot find log directory: %s", pathutils.LOG_ES_DIR)

  # TODO: Use tempfile.mkstemp to create unique filename
  basename = ("%s-%s-%s-%s.log" %
              (kind, es_name, volume, utils.TimestampForFilename()))
  return utils.PathJoin(pathutils.LOG_ES_DIR, basename)
