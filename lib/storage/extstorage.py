#
#

# Copyright (C) 2014 Google Inc.
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
  def __init__(self, unique_id, children, size, params, dyn_params, *args):
    """Attaches to an extstorage block device.

    """
    super(ExtStorageDevice, self).__init__(unique_id, children, size, params,
                                           dyn_params, *args)
    (self.name, self.uuid) = args

    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    self.driver, self.vol_name = unique_id
    self.ext_params = params

    self.major = self.minor = None
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, *args):
    """Create a new extstorage device.

    Provision a new volume using an extstorage provider, which will
    then be mapped to a block device.

    """
    (name, uuid) = args

    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise errors.ProgrammerError("Invalid configuration data %s" %
                                   str(unique_id))
    if excl_stor:
      raise errors.ProgrammerError("extstorage device requested with"
                                   " exclusive_storage")

    # Call the External Storage's create script,
    # to provision a new Volume inside the External Storage
    _ExtStorageAction(constants.ES_ACTION_CREATE, unique_id,
                      params, size=str(size), name=name, uuid=uuid)

    return ExtStorageDevice(unique_id, children, size, params, dyn_params,
                            *args)

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

  def Attach(self):
    """Attach to an existing extstorage device.

    This method maps the extstorage volume that matches our name with
    a corresponding block device and then attaches to this device.

    """
    self.attached = False

    # Call the External Storage's attach script,
    # to attach an existing Volume to a block device under /dev
    self.dev_path = _ExtStorageAction(constants.ES_ACTION_ATTACH,
                                      self.unique_id, self.ext_params,
                                      name=self.name, uuid=self.uuid)

    try:
      st = os.stat(self.dev_path)
    except OSError, err:
      logging.error("Error stat()'ing %s: %s", self.dev_path, str(err))
      return False

    if not stat.S_ISBLK(st.st_mode):
      logging.error("%s is not a block device", self.dev_path)
      return False

    self.major = os.major(st.st_rdev)
    self.minor = os.minor(st.st_rdev)
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

  def Open(self, force=False):
    """Make the device ready for I/O.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    pass

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
                      self.ext_params, size=str(self.size), grow=str(new_size),
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


def _ExtStorageAction(action, unique_id, ext_params,
                      size=None, grow=None, metadata=None,
                      name=None, uuid=None):
  """Take an External Storage action.

  Take an External Storage action concerning or affecting
  a specific Volume inside the External Storage.

  @type action: string
  @param action: which action to perform. One of:
                 create / remove / grow / attach / detach
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
                                      grow, metadata, name, uuid)

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

  # Run the external script
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
      lines = result.output[-20:]

    base.ThrowError("External storage's %s script failed (%s), last"
                    " lines of output:\n%s",
                    action, result.fail_reason, "\n".join(lines))

  if action == constants.ES_ACTION_ATTACH:
    return result.stdout


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

  # ES Files dictionary, we will populate it with the absolute path
  # names; if the value is True, then it is a required file, otherwise
  # an optional one
  es_files = dict.fromkeys(constants.ES_SCRIPTS, True)

  es_files[constants.ES_PARAMETERS_FILE] = True

  for (filename, _) in es_files.items():
    es_files[filename] = utils.PathJoin(es_dir, filename)

    try:
      st = os.stat(es_files[filename])
    except EnvironmentError, err:
      return False, ("File '%s' under path '%s' is missing (%s)" %
                     (filename, es_dir, utils.ErrnoOrStr(err)))

    if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
      return False, ("File '%s' under path '%s' is not a regular file" %
                     (filename, es_dir))

    if filename in constants.ES_SCRIPTS:
      if stat.S_IMODE(st.st_mode) & stat.S_IXUSR != stat.S_IXUSR:
        return False, ("File '%s' under path '%s' is not executable" %
                       (filename, es_dir))

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
                       supported_parameters=parameters)
  return True, es_obj


def _ExtStorageEnvironment(unique_id, ext_params,
                           size=None, grow=None, metadata=None,
                           name=None, uuid=None):
  """Calculate the environment for an External Storage script.

  @type unique_id: tuple (driver, vol_name)
  @param unique_id: ExtStorage pool and name of the Volume
  @type ext_params: dict
  @param ext_params: the EXT parameters
  @type size: string
  @param size: size of the Volume (in mebibytes)
  @type grow: string
  @param grow: new size of Volume after grow (in mebibytes)
  @type metadata: string
  @param metadata: metadata info of the Volume
  @type name: string
  @param name: name of the Volume (objects.Disk.name)
  @type uuid: string
  @param uuid: uuid of the Volume (objects.Disk.uuid)
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
    result["VOL_SIZE"] = size

  if grow is not None:
    result["VOL_NEW_SIZE"] = grow

  if metadata is not None:
    result["VOL_METADATA"] = metadata

  if name is not None:
    result["VOL_CNAME"] = name

  if uuid is not None:
    result["VOL_UUID"] = uuid

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
