#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010 Google Inc.
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


"""Module dealing with command line parsing"""


import sys
import textwrap
import os.path
import time
import logging
from cStringIO import StringIO

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import opcodes
from ganeti import luxi
from ganeti import ssconf
from ganeti import rpc
from ganeti import ssh
from ganeti import compat
from ganeti import netutils

from optparse import (OptionParser, TitledHelpFormatter,
                      Option, OptionValueError)


__all__ = [
  # Command line options
  "ADD_UIDS_OPT",
  "ALLOCATABLE_OPT",
  "ALL_OPT",
  "AUTO_PROMOTE_OPT",
  "AUTO_REPLACE_OPT",
  "BACKEND_OPT",
  "BLK_OS_OPT",
  "CLEANUP_OPT",
  "CLUSTER_DOMAIN_SECRET_OPT",
  "CONFIRM_OPT",
  "CP_SIZE_OPT",
  "DEBUG_OPT",
  "DEBUG_SIMERR_OPT",
  "DISKIDX_OPT",
  "DISK_OPT",
  "DISK_TEMPLATE_OPT",
  "DRAINED_OPT",
  "DRY_RUN_OPT",
  "DRBD_HELPER_OPT",
  "EARLY_RELEASE_OPT",
  "ENABLED_HV_OPT",
  "ERROR_CODES_OPT",
  "FIELDS_OPT",
  "FILESTORE_DIR_OPT",
  "FILESTORE_DRIVER_OPT",
  "FORCE_OPT",
  "FORCE_VARIANT_OPT",
  "GLOBAL_FILEDIR_OPT",
  "HID_OS_OPT",
  "HVLIST_OPT",
  "HVOPTS_OPT",
  "HYPERVISOR_OPT",
  "IALLOCATOR_OPT",
  "DEFAULT_IALLOCATOR_OPT",
  "IDENTIFY_DEFAULTS_OPT",
  "IGNORE_CONSIST_OPT",
  "IGNORE_FAILURES_OPT",
  "IGNORE_REMOVE_FAILURES_OPT",
  "IGNORE_SECONDARIES_OPT",
  "IGNORE_SIZE_OPT",
  "INTERVAL_OPT",
  "MAC_PREFIX_OPT",
  "MAINTAIN_NODE_HEALTH_OPT",
  "MASTER_NETDEV_OPT",
  "MC_OPT",
  "MIGRATION_MODE_OPT",
  "NET_OPT",
  "NEW_CLUSTER_CERT_OPT",
  "NEW_CLUSTER_DOMAIN_SECRET_OPT",
  "NEW_CONFD_HMAC_KEY_OPT",
  "NEW_RAPI_CERT_OPT",
  "NEW_SECONDARY_OPT",
  "NIC_PARAMS_OPT",
  "NODE_LIST_OPT",
  "NODE_PLACEMENT_OPT",
  "NODEGROUP_OPT",
  "NODRBD_STORAGE_OPT",
  "NOHDR_OPT",
  "NOIPCHECK_OPT",
  "NO_INSTALL_OPT",
  "NONAMECHECK_OPT",
  "NOLVM_STORAGE_OPT",
  "NOMODIFY_ETCHOSTS_OPT",
  "NOMODIFY_SSH_SETUP_OPT",
  "NONICS_OPT",
  "NONLIVE_OPT",
  "NONPLUS1_OPT",
  "NOSHUTDOWN_OPT",
  "NOSTART_OPT",
  "NOSSH_KEYCHECK_OPT",
  "NOVOTING_OPT",
  "NWSYNC_OPT",
  "ON_PRIMARY_OPT",
  "ON_SECONDARY_OPT",
  "OFFLINE_OPT",
  "OSPARAMS_OPT",
  "OS_OPT",
  "OS_SIZE_OPT",
  "PRIMARY_IP_VERSION_OPT",
  "PRIORITY_OPT",
  "RAPI_CERT_OPT",
  "READD_OPT",
  "REBOOT_TYPE_OPT",
  "REMOVE_INSTANCE_OPT",
  "REMOVE_UIDS_OPT",
  "RESERVED_LVS_OPT",
  "ROMAN_OPT",
  "SECONDARY_IP_OPT",
  "SELECT_OS_OPT",
  "SEP_OPT",
  "SHOWCMD_OPT",
  "SHUTDOWN_TIMEOUT_OPT",
  "SINGLE_NODE_OPT",
  "SRC_DIR_OPT",
  "SRC_NODE_OPT",
  "SUBMIT_OPT",
  "STATIC_OPT",
  "SYNC_OPT",
  "TAG_SRC_OPT",
  "TIMEOUT_OPT",
  "UIDPOOL_OPT",
  "USEUNITS_OPT",
  "USE_REPL_NET_OPT",
  "VERBOSE_OPT",
  "VG_NAME_OPT",
  "YES_DOIT_OPT",
  # Generic functions for CLI programs
  "GenericMain",
  "GenericInstanceCreate",
  "GetClient",
  "GetOnlineNodes",
  "JobExecutor",
  "JobSubmittedException",
  "ParseTimespec",
  "RunWhileClusterStopped",
  "SubmitOpCode",
  "SubmitOrSend",
  "UsesRPC",
  # Formatting functions
  "ToStderr", "ToStdout",
  "FormatError",
  "GenerateTable",
  "AskUser",
  "FormatTimestamp",
  "FormatLogMessage",
  # Tags functions
  "ListTags",
  "AddTags",
  "RemoveTags",
  # command line options support infrastructure
  "ARGS_MANY_INSTANCES",
  "ARGS_MANY_NODES",
  "ARGS_NONE",
  "ARGS_ONE_INSTANCE",
  "ARGS_ONE_NODE",
  "ARGS_ONE_OS",
  "ArgChoice",
  "ArgCommand",
  "ArgFile",
  "ArgHost",
  "ArgInstance",
  "ArgJobId",
  "ArgNode",
  "ArgOs",
  "ArgSuggest",
  "ArgUnknown",
  "OPT_COMPL_INST_ADD_NODES",
  "OPT_COMPL_MANY_NODES",
  "OPT_COMPL_ONE_IALLOCATOR",
  "OPT_COMPL_ONE_INSTANCE",
  "OPT_COMPL_ONE_NODE",
  "OPT_COMPL_ONE_NODEGROUP",
  "OPT_COMPL_ONE_OS",
  "cli_option",
  "SplitNodeOption",
  "CalculateOSNames",
  "ParseFields",
  ]

NO_PREFIX = "no_"
UN_PREFIX = "-"

#: Priorities (sorted)
_PRIORITY_NAMES = [
  ("low", constants.OP_PRIO_LOW),
  ("normal", constants.OP_PRIO_NORMAL),
  ("high", constants.OP_PRIO_HIGH),
  ]

#: Priority dictionary for easier lookup
# TODO: Replace this and _PRIORITY_NAMES with a single sorted dictionary once
# we migrate to Python 2.6
_PRIONAME_TO_VALUE = dict(_PRIORITY_NAMES)


class _Argument:
  def __init__(self, min=0, max=None): # pylint: disable-msg=W0622
    self.min = min
    self.max = max

  def __repr__(self):
    return ("<%s min=%s max=%s>" %
            (self.__class__.__name__, self.min, self.max))


class ArgSuggest(_Argument):
  """Suggesting argument.

  Value can be any of the ones passed to the constructor.

  """
  # pylint: disable-msg=W0622
  def __init__(self, min=0, max=None, choices=None):
    _Argument.__init__(self, min=min, max=max)
    self.choices = choices

  def __repr__(self):
    return ("<%s min=%s max=%s choices=%r>" %
            (self.__class__.__name__, self.min, self.max, self.choices))


class ArgChoice(ArgSuggest):
  """Choice argument.

  Value can be any of the ones passed to the constructor. Like L{ArgSuggest},
  but value must be one of the choices.

  """


class ArgUnknown(_Argument):
  """Unknown argument to program (e.g. determined at runtime).

  """


class ArgInstance(_Argument):
  """Instances argument.

  """


class ArgNode(_Argument):
  """Node argument.

  """

class ArgJobId(_Argument):
  """Job ID argument.

  """


class ArgFile(_Argument):
  """File path argument.

  """


class ArgCommand(_Argument):
  """Command argument.

  """


class ArgHost(_Argument):
  """Host argument.

  """


class ArgOs(_Argument):
  """OS argument.

  """


ARGS_NONE = []
ARGS_MANY_INSTANCES = [ArgInstance()]
ARGS_MANY_NODES = [ArgNode()]
ARGS_ONE_INSTANCE = [ArgInstance(min=1, max=1)]
ARGS_ONE_NODE = [ArgNode(min=1, max=1)]
ARGS_ONE_OS = [ArgOs(min=1, max=1)]


def _ExtractTagsObject(opts, args):
  """Extract the tag type object.

  Note that this function will modify its args parameter.

  """
  if not hasattr(opts, "tag_type"):
    raise errors.ProgrammerError("tag_type not passed to _ExtractTagsObject")
  kind = opts.tag_type
  if kind == constants.TAG_CLUSTER:
    retval = kind, kind
  elif kind == constants.TAG_NODE or kind == constants.TAG_INSTANCE:
    if not args:
      raise errors.OpPrereqError("no arguments passed to the command")
    name = args.pop(0)
    retval = kind, name
  else:
    raise errors.ProgrammerError("Unhandled tag type '%s'" % kind)
  return retval


def _ExtendTags(opts, args):
  """Extend the args if a source file has been given.

  This function will extend the tags with the contents of the file
  passed in the 'tags_source' attribute of the opts parameter. A file
  named '-' will be replaced by stdin.

  """
  fname = opts.tags_source
  if fname is None:
    return
  if fname == "-":
    new_fh = sys.stdin
  else:
    new_fh = open(fname, "r")
  new_data = []
  try:
    # we don't use the nice 'new_data = [line.strip() for line in fh]'
    # because of python bug 1633941
    while True:
      line = new_fh.readline()
      if not line:
        break
      new_data.append(line.strip())
  finally:
    new_fh.close()
  args.extend(new_data)


def ListTags(opts, args):
  """List the tags on a given object.

  This is a generic implementation that knows how to deal with all
  three cases of tag objects (cluster, node, instance). The opts
  argument is expected to contain a tag_type field denoting what
  object type we work on.

  """
  kind, name = _ExtractTagsObject(opts, args)
  cl = GetClient()
  result = cl.QueryTags(kind, name)
  result = list(result)
  result.sort()
  for tag in result:
    ToStdout(tag)


def AddTags(opts, args):
  """Add tags on a given object.

  This is a generic implementation that knows how to deal with all
  three cases of tag objects (cluster, node, instance). The opts
  argument is expected to contain a tag_type field denoting what
  object type we work on.

  """
  kind, name = _ExtractTagsObject(opts, args)
  _ExtendTags(opts, args)
  if not args:
    raise errors.OpPrereqError("No tags to be added")
  op = opcodes.OpAddTags(kind=kind, name=name, tags=args)
  SubmitOpCode(op, opts=opts)


def RemoveTags(opts, args):
  """Remove tags from a given object.

  This is a generic implementation that knows how to deal with all
  three cases of tag objects (cluster, node, instance). The opts
  argument is expected to contain a tag_type field denoting what
  object type we work on.

  """
  kind, name = _ExtractTagsObject(opts, args)
  _ExtendTags(opts, args)
  if not args:
    raise errors.OpPrereqError("No tags to be removed")
  op = opcodes.OpDelTags(kind=kind, name=name, tags=args)
  SubmitOpCode(op, opts=opts)


def check_unit(option, opt, value): # pylint: disable-msg=W0613
  """OptParsers custom converter for units.

  """
  try:
    return utils.ParseUnit(value)
  except errors.UnitParseError, err:
    raise OptionValueError("option %s: %s" % (opt, err))


def _SplitKeyVal(opt, data):
  """Convert a KeyVal string into a dict.

  This function will convert a key=val[,...] string into a dict. Empty
  values will be converted specially: keys which have the prefix 'no_'
  will have the value=False and the prefix stripped, the others will
  have value=True.

  @type opt: string
  @param opt: a string holding the option name for which we process the
      data, used in building error messages
  @type data: string
  @param data: a string of the format key=val,key=val,...
  @rtype: dict
  @return: {key=val, key=val}
  @raises errors.ParameterError: if there are duplicate keys

  """
  kv_dict = {}
  if data:
    for elem in utils.UnescapeAndSplit(data, sep=","):
      if "=" in elem:
        key, val = elem.split("=", 1)
      else:
        if elem.startswith(NO_PREFIX):
          key, val = elem[len(NO_PREFIX):], False
        elif elem.startswith(UN_PREFIX):
          key, val = elem[len(UN_PREFIX):], None
        else:
          key, val = elem, True
      if key in kv_dict:
        raise errors.ParameterError("Duplicate key '%s' in option %s" %
                                    (key, opt))
      kv_dict[key] = val
  return kv_dict


def check_ident_key_val(option, opt, value):  # pylint: disable-msg=W0613
  """Custom parser for ident:key=val,key=val options.

  This will store the parsed values as a tuple (ident, {key: val}). As such,
  multiple uses of this option via action=append is possible.

  """
  if ":" not in value:
    ident, rest = value, ''
  else:
    ident, rest = value.split(":", 1)

  if ident.startswith(NO_PREFIX):
    if rest:
      msg = "Cannot pass options when removing parameter groups: %s" % value
      raise errors.ParameterError(msg)
    retval = (ident[len(NO_PREFIX):], False)
  elif ident.startswith(UN_PREFIX):
    if rest:
      msg = "Cannot pass options when removing parameter groups: %s" % value
      raise errors.ParameterError(msg)
    retval = (ident[len(UN_PREFIX):], None)
  else:
    kv_dict = _SplitKeyVal(opt, rest)
    retval = (ident, kv_dict)
  return retval


def check_key_val(option, opt, value):  # pylint: disable-msg=W0613
  """Custom parser class for key=val,key=val options.

  This will store the parsed values as a dict {key: val}.

  """
  return _SplitKeyVal(opt, value)


def check_bool(option, opt, value): # pylint: disable-msg=W0613
  """Custom parser for yes/no options.

  This will store the parsed value as either True or False.

  """
  value = value.lower()
  if value == constants.VALUE_FALSE or value == "no":
    return False
  elif value == constants.VALUE_TRUE or value == "yes":
    return True
  else:
    raise errors.ParameterError("Invalid boolean value '%s'" % value)


# completion_suggestion is normally a list. Using numeric values not evaluating
# to False for dynamic completion.
(OPT_COMPL_MANY_NODES,
 OPT_COMPL_ONE_NODE,
 OPT_COMPL_ONE_INSTANCE,
 OPT_COMPL_ONE_OS,
 OPT_COMPL_ONE_IALLOCATOR,
 OPT_COMPL_INST_ADD_NODES,
 OPT_COMPL_ONE_NODEGROUP) = range(100, 107)

OPT_COMPL_ALL = frozenset([
  OPT_COMPL_MANY_NODES,
  OPT_COMPL_ONE_NODE,
  OPT_COMPL_ONE_INSTANCE,
  OPT_COMPL_ONE_OS,
  OPT_COMPL_ONE_IALLOCATOR,
  OPT_COMPL_INST_ADD_NODES,
  OPT_COMPL_ONE_NODEGROUP,
  ])


class CliOption(Option):
  """Custom option class for optparse.

  """
  ATTRS = Option.ATTRS + [
    "completion_suggest",
    ]
  TYPES = Option.TYPES + (
    "identkeyval",
    "keyval",
    "unit",
    "bool",
    )
  TYPE_CHECKER = Option.TYPE_CHECKER.copy()
  TYPE_CHECKER["identkeyval"] = check_ident_key_val
  TYPE_CHECKER["keyval"] = check_key_val
  TYPE_CHECKER["unit"] = check_unit
  TYPE_CHECKER["bool"] = check_bool


# optparse.py sets make_option, so we do it for our own option class, too
cli_option = CliOption


_YORNO = "yes|no"

DEBUG_OPT = cli_option("-d", "--debug", default=0, action="count",
                       help="Increase debugging level")

NOHDR_OPT = cli_option("--no-headers", default=False,
                       action="store_true", dest="no_headers",
                       help="Don't display column headers")

SEP_OPT = cli_option("--separator", default=None,
                     action="store", dest="separator",
                     help=("Separator between output fields"
                           " (defaults to one space)"))

USEUNITS_OPT = cli_option("--units", default=None,
                          dest="units", choices=('h', 'm', 'g', 't'),
                          help="Specify units for output (one of hmgt)")

FIELDS_OPT = cli_option("-o", "--output", dest="output", action="store",
                        type="string", metavar="FIELDS",
                        help="Comma separated list of output fields")

FORCE_OPT = cli_option("-f", "--force", dest="force", action="store_true",
                       default=False, help="Force the operation")

CONFIRM_OPT = cli_option("--yes", dest="confirm", action="store_true",
                         default=False, help="Do not require confirmation")

TAG_SRC_OPT = cli_option("--from", dest="tags_source",
                         default=None, help="File with tag names")

SUBMIT_OPT = cli_option("--submit", dest="submit_only",
                        default=False, action="store_true",
                        help=("Submit the job and return the job ID, but"
                              " don't wait for the job to finish"))

SYNC_OPT = cli_option("--sync", dest="do_locking",
                      default=False, action="store_true",
                      help=("Grab locks while doing the queries"
                            " in order to ensure more consistent results"))

DRY_RUN_OPT = cli_option("--dry-run", default=False,
                         action="store_true",
                         help=("Do not execute the operation, just run the"
                               " check steps and verify it it could be"
                               " executed"))

VERBOSE_OPT = cli_option("-v", "--verbose", default=False,
                         action="store_true",
                         help="Increase the verbosity of the operation")

DEBUG_SIMERR_OPT = cli_option("--debug-simulate-errors", default=False,
                              action="store_true", dest="simulate_errors",
                              help="Debugging option that makes the operation"
                              " treat most runtime checks as failed")

NWSYNC_OPT = cli_option("--no-wait-for-sync", dest="wait_for_sync",
                        default=True, action="store_false",
                        help="Don't wait for sync (DANGEROUS!)")

DISK_TEMPLATE_OPT = cli_option("-t", "--disk-template", dest="disk_template",
                               help="Custom disk setup (diskless, file,"
                               " plain or drbd)",
                               default=None, metavar="TEMPL",
                               choices=list(constants.DISK_TEMPLATES))

NONICS_OPT = cli_option("--no-nics", default=False, action="store_true",
                        help="Do not create any network cards for"
                        " the instance")

FILESTORE_DIR_OPT = cli_option("--file-storage-dir", dest="file_storage_dir",
                               help="Relative path under default cluster-wide"
                               " file storage dir to store file-based disks",
                               default=None, metavar="<DIR>")

FILESTORE_DRIVER_OPT = cli_option("--file-driver", dest="file_driver",
                                  help="Driver to use for image files",
                                  default="loop", metavar="<DRIVER>",
                                  choices=list(constants.FILE_DRIVER))

IALLOCATOR_OPT = cli_option("-I", "--iallocator", metavar="<NAME>",
                            help="Select nodes for the instance automatically"
                            " using the <NAME> iallocator plugin",
                            default=None, type="string",
                            completion_suggest=OPT_COMPL_ONE_IALLOCATOR)

DEFAULT_IALLOCATOR_OPT = cli_option("-I", "--default-iallocator",
                            metavar="<NAME>",
                            help="Set the default instance allocator plugin",
                            default=None, type="string",
                            completion_suggest=OPT_COMPL_ONE_IALLOCATOR)

OS_OPT = cli_option("-o", "--os-type", dest="os", help="What OS to run",
                    metavar="<os>",
                    completion_suggest=OPT_COMPL_ONE_OS)

OSPARAMS_OPT = cli_option("-O", "--os-parameters", dest="osparams",
                         type="keyval", default={},
                         help="OS parameters")

FORCE_VARIANT_OPT = cli_option("--force-variant", dest="force_variant",
                               action="store_true", default=False,
                               help="Force an unknown variant")

NO_INSTALL_OPT = cli_option("--no-install", dest="no_install",
                            action="store_true", default=False,
                            help="Do not install the OS (will"
                            " enable no-start)")

BACKEND_OPT = cli_option("-B", "--backend-parameters", dest="beparams",
                         type="keyval", default={},
                         help="Backend parameters")

HVOPTS_OPT =  cli_option("-H", "--hypervisor-parameters", type="keyval",
                         default={}, dest="hvparams",
                         help="Hypervisor parameters")

HYPERVISOR_OPT = cli_option("-H", "--hypervisor-parameters", dest="hypervisor",
                            help="Hypervisor and hypervisor options, in the"
                            " format hypervisor:option=value,option=value,...",
                            default=None, type="identkeyval")

HVLIST_OPT = cli_option("-H", "--hypervisor-parameters", dest="hvparams",
                        help="Hypervisor and hypervisor options, in the"
                        " format hypervisor:option=value,option=value,...",
                        default=[], action="append", type="identkeyval")

NOIPCHECK_OPT = cli_option("--no-ip-check", dest="ip_check", default=True,
                           action="store_false",
                           help="Don't check that the instance's IP"
                           " is alive")

NONAMECHECK_OPT = cli_option("--no-name-check", dest="name_check",
                             default=True, action="store_false",
                             help="Don't check that the instance's name"
                             " is resolvable")

NET_OPT = cli_option("--net",
                     help="NIC parameters", default=[],
                     dest="nics", action="append", type="identkeyval")

DISK_OPT = cli_option("--disk", help="Disk parameters", default=[],
                      dest="disks", action="append", type="identkeyval")

DISKIDX_OPT = cli_option("--disks", dest="disks", default=None,
                         help="Comma-separated list of disks"
                         " indices to act on (e.g. 0,2) (optional,"
                         " defaults to all disks)")

OS_SIZE_OPT = cli_option("-s", "--os-size", dest="sd_size",
                         help="Enforces a single-disk configuration using the"
                         " given disk size, in MiB unless a suffix is used",
                         default=None, type="unit", metavar="<size>")

IGNORE_CONSIST_OPT = cli_option("--ignore-consistency",
                                dest="ignore_consistency",
                                action="store_true", default=False,
                                help="Ignore the consistency of the disks on"
                                " the secondary")

NONLIVE_OPT = cli_option("--non-live", dest="live",
                         default=True, action="store_false",
                         help="Do a non-live migration (this usually means"
                         " freeze the instance, save the state, transfer and"
                         " only then resume running on the secondary node)")

MIGRATION_MODE_OPT = cli_option("--migration-mode", dest="migration_mode",
                                default=None,
                                choices=list(constants.HT_MIGRATION_MODES),
                                help="Override default migration mode (choose"
                                " either live or non-live")

NODE_PLACEMENT_OPT = cli_option("-n", "--node", dest="node",
                                help="Target node and optional secondary node",
                                metavar="<pnode>[:<snode>]",
                                completion_suggest=OPT_COMPL_INST_ADD_NODES)

NODE_LIST_OPT = cli_option("-n", "--node", dest="nodes", default=[],
                           action="append", metavar="<node>",
                           help="Use only this node (can be used multiple"
                           " times, if not given defaults to all nodes)",
                           completion_suggest=OPT_COMPL_ONE_NODE)

NODEGROUP_OPT = cli_option("-g", "--nodegroup",
                           dest="nodegroup",
                           help="Node group (name or uuid)",
                           metavar="<nodegroup>",
                           default=None, type="string",
                           completion_suggest=OPT_COMPL_ONE_NODEGROUP)

SINGLE_NODE_OPT = cli_option("-n", "--node", dest="node", help="Target node",
                             metavar="<node>",
                             completion_suggest=OPT_COMPL_ONE_NODE)

NOSTART_OPT = cli_option("--no-start", dest="start", default=True,
                         action="store_false",
                         help="Don't start the instance after creation")

SHOWCMD_OPT = cli_option("--show-cmd", dest="show_command",
                         action="store_true", default=False,
                         help="Show command instead of executing it")

CLEANUP_OPT = cli_option("--cleanup", dest="cleanup",
                         default=False, action="store_true",
                         help="Instead of performing the migration, try to"
                         " recover from a failed cleanup. This is safe"
                         " to run even if the instance is healthy, but it"
                         " will create extra replication traffic and "
                         " disrupt briefly the replication (like during the"
                         " migration")

STATIC_OPT = cli_option("-s", "--static", dest="static",
                        action="store_true", default=False,
                        help="Only show configuration data, not runtime data")

ALL_OPT = cli_option("--all", dest="show_all",
                     default=False, action="store_true",
                     help="Show info on all instances on the cluster."
                     " This can take a long time to run, use wisely")

SELECT_OS_OPT = cli_option("--select-os", dest="select_os",
                           action="store_true", default=False,
                           help="Interactive OS reinstall, lists available"
                           " OS templates for selection")

IGNORE_FAILURES_OPT = cli_option("--ignore-failures", dest="ignore_failures",
                                 action="store_true", default=False,
                                 help="Remove the instance from the cluster"
                                 " configuration even if there are failures"
                                 " during the removal process")

IGNORE_REMOVE_FAILURES_OPT = cli_option("--ignore-remove-failures",
                                        dest="ignore_remove_failures",
                                        action="store_true", default=False,
                                        help="Remove the instance from the"
                                        " cluster configuration even if there"
                                        " are failures during the removal"
                                        " process")

REMOVE_INSTANCE_OPT = cli_option("--remove-instance", dest="remove_instance",
                                 action="store_true", default=False,
                                 help="Remove the instance from the cluster")

NEW_SECONDARY_OPT = cli_option("-n", "--new-secondary", dest="dst_node",
                               help="Specifies the new secondary node",
                               metavar="NODE", default=None,
                               completion_suggest=OPT_COMPL_ONE_NODE)

ON_PRIMARY_OPT = cli_option("-p", "--on-primary", dest="on_primary",
                            default=False, action="store_true",
                            help="Replace the disk(s) on the primary"
                            " node (only for the drbd template)")

ON_SECONDARY_OPT = cli_option("-s", "--on-secondary", dest="on_secondary",
                              default=False, action="store_true",
                              help="Replace the disk(s) on the secondary"
                              " node (only for the drbd template)")

AUTO_PROMOTE_OPT = cli_option("--auto-promote", dest="auto_promote",
                              default=False, action="store_true",
                              help="Lock all nodes and auto-promote as needed"
                              " to MC status")

AUTO_REPLACE_OPT = cli_option("-a", "--auto", dest="auto",
                              default=False, action="store_true",
                              help="Automatically replace faulty disks"
                              " (only for the drbd template)")

IGNORE_SIZE_OPT = cli_option("--ignore-size", dest="ignore_size",
                             default=False, action="store_true",
                             help="Ignore current recorded size"
                             " (useful for forcing activation when"
                             " the recorded size is wrong)")

SRC_NODE_OPT = cli_option("--src-node", dest="src_node", help="Source node",
                          metavar="<node>",
                          completion_suggest=OPT_COMPL_ONE_NODE)

SRC_DIR_OPT = cli_option("--src-dir", dest="src_dir", help="Source directory",
                         metavar="<dir>")

SECONDARY_IP_OPT = cli_option("-s", "--secondary-ip", dest="secondary_ip",
                              help="Specify the secondary ip for the node",
                              metavar="ADDRESS", default=None)

READD_OPT = cli_option("--readd", dest="readd",
                       default=False, action="store_true",
                       help="Readd old node after replacing it")

NOSSH_KEYCHECK_OPT = cli_option("--no-ssh-key-check", dest="ssh_key_check",
                                default=True, action="store_false",
                                help="Disable SSH key fingerprint checking")


MC_OPT = cli_option("-C", "--master-candidate", dest="master_candidate",
                    type="bool", default=None, metavar=_YORNO,
                    help="Set the master_candidate flag on the node")

OFFLINE_OPT = cli_option("-O", "--offline", dest="offline", metavar=_YORNO,
                         type="bool", default=None,
                         help="Set the offline flag on the node")

DRAINED_OPT = cli_option("-D", "--drained", dest="drained", metavar=_YORNO,
                         type="bool", default=None,
                         help="Set the drained flag on the node")

ALLOCATABLE_OPT = cli_option("--allocatable", dest="allocatable",
                             type="bool", default=None, metavar=_YORNO,
                             help="Set the allocatable flag on a volume")

NOLVM_STORAGE_OPT = cli_option("--no-lvm-storage", dest="lvm_storage",
                               help="Disable support for lvm based instances"
                               " (cluster-wide)",
                               action="store_false", default=True)

ENABLED_HV_OPT = cli_option("--enabled-hypervisors",
                            dest="enabled_hypervisors",
                            help="Comma-separated list of hypervisors",
                            type="string", default=None)

NIC_PARAMS_OPT = cli_option("-N", "--nic-parameters", dest="nicparams",
                            type="keyval", default={},
                            help="NIC parameters")

CP_SIZE_OPT = cli_option("-C", "--candidate-pool-size", default=None,
                         dest="candidate_pool_size", type="int",
                         help="Set the candidate pool size")

VG_NAME_OPT = cli_option("-g", "--vg-name", dest="vg_name",
                         help="Enables LVM and specifies the volume group"
                         " name (cluster-wide) for disk allocation [xenvg]",
                         metavar="VG", default=None)

YES_DOIT_OPT = cli_option("--yes-do-it", dest="yes_do_it",
                          help="Destroy cluster", action="store_true")

NOVOTING_OPT = cli_option("--no-voting", dest="no_voting",
                          help="Skip node agreement check (dangerous)",
                          action="store_true", default=False)

MAC_PREFIX_OPT = cli_option("-m", "--mac-prefix", dest="mac_prefix",
                            help="Specify the mac prefix for the instance IP"
                            " addresses, in the format XX:XX:XX",
                            metavar="PREFIX",
                            default=None)

MASTER_NETDEV_OPT = cli_option("--master-netdev", dest="master_netdev",
                               help="Specify the node interface (cluster-wide)"
                               " on which the master IP address will be added "
                               " [%s]" % constants.DEFAULT_BRIDGE,
                               metavar="NETDEV",
                               default=constants.DEFAULT_BRIDGE)

GLOBAL_FILEDIR_OPT = cli_option("--file-storage-dir", dest="file_storage_dir",
                                help="Specify the default directory (cluster-"
                                "wide) for storing the file-based disks [%s]" %
                                constants.DEFAULT_FILE_STORAGE_DIR,
                                metavar="DIR",
                                default=constants.DEFAULT_FILE_STORAGE_DIR)

NOMODIFY_ETCHOSTS_OPT = cli_option("--no-etc-hosts", dest="modify_etc_hosts",
                                   help="Don't modify /etc/hosts",
                                   action="store_false", default=True)

NOMODIFY_SSH_SETUP_OPT = cli_option("--no-ssh-init", dest="modify_ssh_setup",
                                    help="Don't initialize SSH keys",
                                    action="store_false", default=True)

ERROR_CODES_OPT = cli_option("--error-codes", dest="error_codes",
                             help="Enable parseable error messages",
                             action="store_true", default=False)

NONPLUS1_OPT = cli_option("--no-nplus1-mem", dest="skip_nplusone_mem",
                          help="Skip N+1 memory redundancy tests",
                          action="store_true", default=False)

REBOOT_TYPE_OPT = cli_option("-t", "--type", dest="reboot_type",
                             help="Type of reboot: soft/hard/full",
                             default=constants.INSTANCE_REBOOT_HARD,
                             metavar="<REBOOT>",
                             choices=list(constants.REBOOT_TYPES))

IGNORE_SECONDARIES_OPT = cli_option("--ignore-secondaries",
                                    dest="ignore_secondaries",
                                    default=False, action="store_true",
                                    help="Ignore errors from secondaries")

NOSHUTDOWN_OPT = cli_option("--noshutdown", dest="shutdown",
                            action="store_false", default=True,
                            help="Don't shutdown the instance (unsafe)")

TIMEOUT_OPT = cli_option("--timeout", dest="timeout", type="int",
                         default=constants.DEFAULT_SHUTDOWN_TIMEOUT,
                         help="Maximum time to wait")

SHUTDOWN_TIMEOUT_OPT = cli_option("--shutdown-timeout",
                         dest="shutdown_timeout", type="int",
                         default=constants.DEFAULT_SHUTDOWN_TIMEOUT,
                         help="Maximum time to wait for instance shutdown")

INTERVAL_OPT = cli_option("--interval", dest="interval", type="int",
                          default=None,
                          help=("Number of seconds between repetions of the"
                                " command"))

EARLY_RELEASE_OPT = cli_option("--early-release",
                               dest="early_release", default=False,
                               action="store_true",
                               help="Release the locks on the secondary"
                               " node(s) early")

NEW_CLUSTER_CERT_OPT = cli_option("--new-cluster-certificate",
                                  dest="new_cluster_cert",
                                  default=False, action="store_true",
                                  help="Generate a new cluster certificate")

RAPI_CERT_OPT = cli_option("--rapi-certificate", dest="rapi_cert",
                           default=None,
                           help="File containing new RAPI certificate")

NEW_RAPI_CERT_OPT = cli_option("--new-rapi-certificate", dest="new_rapi_cert",
                               default=None, action="store_true",
                               help=("Generate a new self-signed RAPI"
                                     " certificate"))

NEW_CONFD_HMAC_KEY_OPT = cli_option("--new-confd-hmac-key",
                                    dest="new_confd_hmac_key",
                                    default=False, action="store_true",
                                    help=("Create a new HMAC key for %s" %
                                          constants.CONFD))

CLUSTER_DOMAIN_SECRET_OPT = cli_option("--cluster-domain-secret",
                                       dest="cluster_domain_secret",
                                       default=None,
                                       help=("Load new new cluster domain"
                                             " secret from file"))

NEW_CLUSTER_DOMAIN_SECRET_OPT = cli_option("--new-cluster-domain-secret",
                                           dest="new_cluster_domain_secret",
                                           default=False, action="store_true",
                                           help=("Create a new cluster domain"
                                                 " secret"))

USE_REPL_NET_OPT = cli_option("--use-replication-network",
                              dest="use_replication_network",
                              help="Whether to use the replication network"
                              " for talking to the nodes",
                              action="store_true", default=False)

MAINTAIN_NODE_HEALTH_OPT = \
    cli_option("--maintain-node-health", dest="maintain_node_health",
               metavar=_YORNO, default=None, type="bool",
               help="Configure the cluster to automatically maintain node"
               " health, by shutting down unknown instances, shutting down"
               " unknown DRBD devices, etc.")

IDENTIFY_DEFAULTS_OPT = \
    cli_option("--identify-defaults", dest="identify_defaults",
               default=False, action="store_true",
               help="Identify which saved instance parameters are equal to"
               " the current cluster defaults and set them as such, instead"
               " of marking them as overridden")

UIDPOOL_OPT = cli_option("--uid-pool", default=None,
                         action="store", dest="uid_pool",
                         help=("A list of user-ids or user-id"
                               " ranges separated by commas"))

ADD_UIDS_OPT = cli_option("--add-uids", default=None,
                          action="store", dest="add_uids",
                          help=("A list of user-ids or user-id"
                                " ranges separated by commas, to be"
                                " added to the user-id pool"))

REMOVE_UIDS_OPT = cli_option("--remove-uids", default=None,
                             action="store", dest="remove_uids",
                             help=("A list of user-ids or user-id"
                                   " ranges separated by commas, to be"
                                   " removed from the user-id pool"))

RESERVED_LVS_OPT = cli_option("--reserved-lvs", default=None,
                             action="store", dest="reserved_lvs",
                             help=("A comma-separated list of reserved"
                                   " logical volumes names, that will be"
                                   " ignored by cluster verify"))

ROMAN_OPT = cli_option("--roman",
                       dest="roman_integers", default=False,
                       action="store_true",
                       help="Use roman numbers for positive integers")

DRBD_HELPER_OPT = cli_option("--drbd-usermode-helper", dest="drbd_helper",
                             action="store", default=None,
                             help="Specifies usermode helper for DRBD")

NODRBD_STORAGE_OPT = cli_option("--no-drbd-storage", dest="drbd_storage",
                                action="store_false", default=True,
                                help="Disable support for DRBD")

PRIMARY_IP_VERSION_OPT = \
    cli_option("--primary-ip-version", default=constants.IP4_VERSION,
               action="store", dest="primary_ip_version",
               metavar="%d|%d" % (constants.IP4_VERSION,
                                  constants.IP6_VERSION),
               help="Cluster-wide IP version for primary IP")

PRIORITY_OPT = cli_option("--priority", default=None, dest="priority",
                          metavar="|".join(name for name, _ in _PRIORITY_NAMES),
                          choices=_PRIONAME_TO_VALUE.keys(),
                          help="Priority for opcode processing")

HID_OS_OPT = cli_option("--hidden", dest="hidden",
                        type="bool", default=None, metavar=_YORNO,
                        help="Sets the hidden flag on the OS")

BLK_OS_OPT = cli_option("--blacklisted", dest="blacklisted",
                        type="bool", default=None, metavar=_YORNO,
                        help="Sets the blacklisted flag on the OS")


#: Options provided by all commands
COMMON_OPTS = [DEBUG_OPT]


def _ParseArgs(argv, commands, aliases):
  """Parser for the command line arguments.

  This function parses the arguments and returns the function which
  must be executed together with its (modified) arguments.

  @param argv: the command line
  @param commands: dictionary with special contents, see the design
      doc for cmdline handling
  @param aliases: dictionary with command aliases {'alias': 'target, ...}

  """
  if len(argv) == 0:
    binary = "<command>"
  else:
    binary = argv[0].split("/")[-1]

  if len(argv) > 1 and argv[1] == "--version":
    ToStdout("%s (ganeti %s) %s", binary, constants.VCS_VERSION,
             constants.RELEASE_VERSION)
    # Quit right away. That way we don't have to care about this special
    # argument. optparse.py does it the same.
    sys.exit(0)

  if len(argv) < 2 or not (argv[1] in commands or
                           argv[1] in aliases):
    # let's do a nice thing
    sortedcmds = commands.keys()
    sortedcmds.sort()

    ToStdout("Usage: %s {command} [options...] [argument...]", binary)
    ToStdout("%s <command> --help to see details, or man %s", binary, binary)
    ToStdout("")

    # compute the max line length for cmd + usage
    mlen = max([len(" %s" % cmd) for cmd in commands])
    mlen = min(60, mlen) # should not get here...

    # and format a nice command list
    ToStdout("Commands:")
    for cmd in sortedcmds:
      cmdstr = " %s" % (cmd,)
      help_text = commands[cmd][4]
      help_lines = textwrap.wrap(help_text, 79 - 3 - mlen)
      ToStdout("%-*s - %s", mlen, cmdstr, help_lines.pop(0))
      for line in help_lines:
        ToStdout("%-*s   %s", mlen, "", line)

    ToStdout("")

    return None, None, None

  # get command, unalias it, and look it up in commands
  cmd = argv.pop(1)
  if cmd in aliases:
    if cmd in commands:
      raise errors.ProgrammerError("Alias '%s' overrides an existing"
                                   " command" % cmd)

    if aliases[cmd] not in commands:
      raise errors.ProgrammerError("Alias '%s' maps to non-existing"
                                   " command '%s'" % (cmd, aliases[cmd]))

    cmd = aliases[cmd]

  func, args_def, parser_opts, usage, description = commands[cmd]
  parser = OptionParser(option_list=parser_opts + COMMON_OPTS,
                        description=description,
                        formatter=TitledHelpFormatter(),
                        usage="%%prog %s %s" % (cmd, usage))
  parser.disable_interspersed_args()
  options, args = parser.parse_args()

  if not _CheckArguments(cmd, args_def, args):
    return None, None, None

  return func, options, args


def _CheckArguments(cmd, args_def, args):
  """Verifies the arguments using the argument definition.

  Algorithm:

    1. Abort with error if values specified by user but none expected.

    1. For each argument in definition

      1. Keep running count of minimum number of values (min_count)
      1. Keep running count of maximum number of values (max_count)
      1. If it has an unlimited number of values

        1. Abort with error if it's not the last argument in the definition

    1. If last argument has limited number of values

      1. Abort with error if number of values doesn't match or is too large

    1. Abort with error if user didn't pass enough values (min_count)

  """
  if args and not args_def:
    ToStderr("Error: Command %s expects no arguments", cmd)
    return False

  min_count = None
  max_count = None
  check_max = None

  last_idx = len(args_def) - 1

  for idx, arg in enumerate(args_def):
    if min_count is None:
      min_count = arg.min
    elif arg.min is not None:
      min_count += arg.min

    if max_count is None:
      max_count = arg.max
    elif arg.max is not None:
      max_count += arg.max

    if idx == last_idx:
      check_max = (arg.max is not None)

    elif arg.max is None:
      raise errors.ProgrammerError("Only the last argument can have max=None")

  if check_max:
    # Command with exact number of arguments
    if (min_count is not None and max_count is not None and
        min_count == max_count and len(args) != min_count):
      ToStderr("Error: Command %s expects %d argument(s)", cmd, min_count)
      return False

    # Command with limited number of arguments
    if max_count is not None and len(args) > max_count:
      ToStderr("Error: Command %s expects only %d argument(s)",
               cmd, max_count)
      return False

  # Command with some required arguments
  if min_count is not None and len(args) < min_count:
    ToStderr("Error: Command %s expects at least %d argument(s)",
             cmd, min_count)
    return False

  return True


def SplitNodeOption(value):
  """Splits the value of a --node option.

  """
  if value and ':' in value:
    return value.split(':', 1)
  else:
    return (value, None)


def CalculateOSNames(os_name, os_variants):
  """Calculates all the names an OS can be called, according to its variants.

  @type os_name: string
  @param os_name: base name of the os
  @type os_variants: list or None
  @param os_variants: list of supported variants
  @rtype: list
  @return: list of valid names

  """
  if os_variants:
    return ['%s+%s' % (os_name, v) for v in os_variants]
  else:
    return [os_name]


def ParseFields(selected, default):
  """Parses the values of "--field"-like options.

  @type selected: string or None
  @param selected: User-selected options
  @type default: list
  @param default: Default fields

  """
  if selected is None:
    return default

  if selected.startswith("+"):
    return default + selected[1:].split(",")

  return selected.split(",")


UsesRPC = rpc.RunWithRPC


def AskUser(text, choices=None):
  """Ask the user a question.

  @param text: the question to ask

  @param choices: list with elements tuples (input_char, return_value,
      description); if not given, it will default to: [('y', True,
      'Perform the operation'), ('n', False, 'Do no do the operation')];
      note that the '?' char is reserved for help

  @return: one of the return values from the choices list; if input is
      not possible (i.e. not running with a tty, we return the last
      entry from the list

  """
  if choices is None:
    choices = [('y', True, 'Perform the operation'),
               ('n', False, 'Do not perform the operation')]
  if not choices or not isinstance(choices, list):
    raise errors.ProgrammerError("Invalid choices argument to AskUser")
  for entry in choices:
    if not isinstance(entry, tuple) or len(entry) < 3 or entry[0] == '?':
      raise errors.ProgrammerError("Invalid choices element to AskUser")

  answer = choices[-1][1]
  new_text = []
  for line in text.splitlines():
    new_text.append(textwrap.fill(line, 70, replace_whitespace=False))
  text = "\n".join(new_text)
  try:
    f = file("/dev/tty", "a+")
  except IOError:
    return answer
  try:
    chars = [entry[0] for entry in choices]
    chars[-1] = "[%s]" % chars[-1]
    chars.append('?')
    maps = dict([(entry[0], entry[1]) for entry in choices])
    while True:
      f.write(text)
      f.write('\n')
      f.write("/".join(chars))
      f.write(": ")
      line = f.readline(2).strip().lower()
      if line in maps:
        answer = maps[line]
        break
      elif line == '?':
        for entry in choices:
          f.write(" %s - %s\n" % (entry[0], entry[2]))
        f.write("\n")
        continue
  finally:
    f.close()
  return answer


class JobSubmittedException(Exception):
  """Job was submitted, client should exit.

  This exception has one argument, the ID of the job that was
  submitted. The handler should print this ID.

  This is not an error, just a structured way to exit from clients.

  """


def SendJob(ops, cl=None):
  """Function to submit an opcode without waiting for the results.

  @type ops: list
  @param ops: list of opcodes
  @type cl: luxi.Client
  @param cl: the luxi client to use for communicating with the master;
             if None, a new client will be created

  """
  if cl is None:
    cl = GetClient()

  job_id = cl.SubmitJob(ops)

  return job_id


def GenericPollJob(job_id, cbs, report_cbs):
  """Generic job-polling function.

  @type job_id: number
  @param job_id: Job ID
  @type cbs: Instance of L{JobPollCbBase}
  @param cbs: Data callbacks
  @type report_cbs: Instance of L{JobPollReportCbBase}
  @param report_cbs: Reporting callbacks

  """
  prev_job_info = None
  prev_logmsg_serial = None

  status = None

  while True:
    result = cbs.WaitForJobChangeOnce(job_id, ["status"], prev_job_info,
                                      prev_logmsg_serial)
    if not result:
      # job not found, go away!
      raise errors.JobLost("Job with id %s lost" % job_id)

    if result == constants.JOB_NOTCHANGED:
      report_cbs.ReportNotChanged(job_id, status)

      # Wait again
      continue

    # Split result, a tuple of (field values, log entries)
    (job_info, log_entries) = result
    (status, ) = job_info

    if log_entries:
      for log_entry in log_entries:
        (serial, timestamp, log_type, message) = log_entry
        report_cbs.ReportLogMessage(job_id, serial, timestamp,
                                    log_type, message)
        prev_logmsg_serial = max(prev_logmsg_serial, serial)

    # TODO: Handle canceled and archived jobs
    elif status in (constants.JOB_STATUS_SUCCESS,
                    constants.JOB_STATUS_ERROR,
                    constants.JOB_STATUS_CANCELING,
                    constants.JOB_STATUS_CANCELED):
      break

    prev_job_info = job_info

  jobs = cbs.QueryJobs([job_id], ["status", "opstatus", "opresult"])
  if not jobs:
    raise errors.JobLost("Job with id %s lost" % job_id)

  status, opstatus, result = jobs[0]

  if status == constants.JOB_STATUS_SUCCESS:
    return result

  if status in (constants.JOB_STATUS_CANCELING, constants.JOB_STATUS_CANCELED):
    raise errors.OpExecError("Job was canceled")

  has_ok = False
  for idx, (status, msg) in enumerate(zip(opstatus, result)):
    if status == constants.OP_STATUS_SUCCESS:
      has_ok = True
    elif status == constants.OP_STATUS_ERROR:
      errors.MaybeRaise(msg)

      if has_ok:
        raise errors.OpExecError("partial failure (opcode %d): %s" %
                                 (idx, msg))

      raise errors.OpExecError(str(msg))

  # default failure mode
  raise errors.OpExecError(result)


class JobPollCbBase:
  """Base class for L{GenericPollJob} callbacks.

  """
  def __init__(self):
    """Initializes this class.

    """

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial):
    """Waits for changes on a job.

    """
    raise NotImplementedError()

  def QueryJobs(self, job_ids, fields):
    """Returns the selected fields for the selected job IDs.

    @type job_ids: list of numbers
    @param job_ids: Job IDs
    @type fields: list of strings
    @param fields: Fields

    """
    raise NotImplementedError()


class JobPollReportCbBase:
  """Base class for L{GenericPollJob} reporting callbacks.

  """
  def __init__(self):
    """Initializes this class.

    """

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    raise NotImplementedError()

  def ReportNotChanged(self, job_id, status):
    """Called for if a job hasn't changed in a while.

    @type job_id: number
    @param job_id: Job ID
    @type status: string or None
    @param status: Job status if available

    """
    raise NotImplementedError()


class _LuxiJobPollCb(JobPollCbBase):
  def __init__(self, cl):
    """Initializes this class.

    """
    JobPollCbBase.__init__(self)
    self.cl = cl

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial):
    """Waits for changes on a job.

    """
    return self.cl.WaitForJobChangeOnce(job_id, fields,
                                        prev_job_info, prev_log_serial)

  def QueryJobs(self, job_ids, fields):
    """Returns the selected fields for the selected job IDs.

    """
    return self.cl.QueryJobs(job_ids, fields)


class FeedbackFnJobPollReportCb(JobPollReportCbBase):
  def __init__(self, feedback_fn):
    """Initializes this class.

    """
    JobPollReportCbBase.__init__(self)

    self.feedback_fn = feedback_fn

    assert callable(feedback_fn)

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    self.feedback_fn((timestamp, log_type, log_msg))

  def ReportNotChanged(self, job_id, status):
    """Called if a job hasn't changed in a while.

    """
    # Ignore


class StdioJobPollReportCb(JobPollReportCbBase):
  def __init__(self):
    """Initializes this class.

    """
    JobPollReportCbBase.__init__(self)

    self.notified_queued = False
    self.notified_waitlock = False

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    ToStdout("%s %s", time.ctime(utils.MergeTime(timestamp)),
             FormatLogMessage(log_type, log_msg))

  def ReportNotChanged(self, job_id, status):
    """Called if a job hasn't changed in a while.

    """
    if status is None:
      return

    if status == constants.JOB_STATUS_QUEUED and not self.notified_queued:
      ToStderr("Job %s is waiting in queue", job_id)
      self.notified_queued = True

    elif status == constants.JOB_STATUS_WAITLOCK and not self.notified_waitlock:
      ToStderr("Job %s is trying to acquire all necessary locks", job_id)
      self.notified_waitlock = True


def FormatLogMessage(log_type, log_msg):
  """Formats a job message according to its type.

  """
  if log_type != constants.ELOG_MESSAGE:
    log_msg = str(log_msg)

  return utils.SafeEncode(log_msg)


def PollJob(job_id, cl=None, feedback_fn=None, reporter=None):
  """Function to poll for the result of a job.

  @type job_id: job identified
  @param job_id: the job to poll for results
  @type cl: luxi.Client
  @param cl: the luxi client to use for communicating with the master;
             if None, a new client will be created

  """
  if cl is None:
    cl = GetClient()

  if reporter is None:
    if feedback_fn:
      reporter = FeedbackFnJobPollReportCb(feedback_fn)
    else:
      reporter = StdioJobPollReportCb()
  elif feedback_fn:
    raise errors.ProgrammerError("Can't specify reporter and feedback function")

  return GenericPollJob(job_id, _LuxiJobPollCb(cl), reporter)


def SubmitOpCode(op, cl=None, feedback_fn=None, opts=None, reporter=None):
  """Legacy function to submit an opcode.

  This is just a simple wrapper over the construction of the processor
  instance. It should be extended to better handle feedback and
  interaction functions.

  """
  if cl is None:
    cl = GetClient()

  SetGenericOpcodeOpts([op], opts)

  job_id = SendJob([op], cl=cl)

  op_results = PollJob(job_id, cl=cl, feedback_fn=feedback_fn,
                       reporter=reporter)

  return op_results[0]


def SubmitOrSend(op, opts, cl=None, feedback_fn=None):
  """Wrapper around SubmitOpCode or SendJob.

  This function will decide, based on the 'opts' parameter, whether to
  submit and wait for the result of the opcode (and return it), or
  whether to just send the job and print its identifier. It is used in
  order to simplify the implementation of the '--submit' option.

  It will also process the opcodes if we're sending the via SendJob
  (otherwise SubmitOpCode does it).

  """
  if opts and opts.submit_only:
    job = [op]
    SetGenericOpcodeOpts(job, opts)
    job_id = SendJob(job, cl=cl)
    raise JobSubmittedException(job_id)
  else:
    return SubmitOpCode(op, cl=cl, feedback_fn=feedback_fn, opts=opts)


def SetGenericOpcodeOpts(opcode_list, options):
  """Processor for generic options.

  This function updates the given opcodes based on generic command
  line options (like debug, dry-run, etc.).

  @param opcode_list: list of opcodes
  @param options: command line options or None
  @return: None (in-place modification)

  """
  if not options:
    return
  for op in opcode_list:
    op.debug_level = options.debug
    if hasattr(options, "dry_run"):
      op.dry_run = options.dry_run
    if getattr(options, "priority", None) is not None:
      op.priority = _PRIONAME_TO_VALUE[options.priority]


def GetClient():
  # TODO: Cache object?
  try:
    client = luxi.Client()
  except luxi.NoMasterError:
    ss = ssconf.SimpleStore()

    # Try to read ssconf file
    try:
      ss.GetMasterNode()
    except errors.ConfigurationError:
      raise errors.OpPrereqError("Cluster not initialized or this machine is"
                                 " not part of a cluster")

    master, myself = ssconf.GetMasterAndMyself(ss=ss)
    if master != myself:
      raise errors.OpPrereqError("This is not the master node, please connect"
                                 " to node '%s' and rerun the command" %
                                 master)
    raise
  return client


def FormatError(err):
  """Return a formatted error message for a given error.

  This function takes an exception instance and returns a tuple
  consisting of two values: first, the recommended exit code, and
  second, a string describing the error message (not
  newline-terminated).

  """
  retcode = 1
  obuf = StringIO()
  msg = str(err)
  if isinstance(err, errors.ConfigurationError):
    txt = "Corrupt configuration file: %s" % msg
    logging.error(txt)
    obuf.write(txt + "\n")
    obuf.write("Aborting.")
    retcode = 2
  elif isinstance(err, errors.HooksAbort):
    obuf.write("Failure: hooks execution failed:\n")
    for node, script, out in err.args[0]:
      if out:
        obuf.write("  node: %s, script: %s, output: %s\n" %
                   (node, script, out))
      else:
        obuf.write("  node: %s, script: %s (no output)\n" %
                   (node, script))
  elif isinstance(err, errors.HooksFailure):
    obuf.write("Failure: hooks general failure: %s" % msg)
  elif isinstance(err, errors.ResolverError):
    this_host = netutils.Hostname.GetSysName()
    if err.args[0] == this_host:
      msg = "Failure: can't resolve my own hostname ('%s')"
    else:
      msg = "Failure: can't resolve hostname '%s'"
    obuf.write(msg % err.args[0])
  elif isinstance(err, errors.OpPrereqError):
    if len(err.args) == 2:
      obuf.write("Failure: prerequisites not met for this"
               " operation:\nerror type: %s, error details:\n%s" %
                 (err.args[1], err.args[0]))
    else:
      obuf.write("Failure: prerequisites not met for this"
                 " operation:\n%s" % msg)
  elif isinstance(err, errors.OpExecError):
    obuf.write("Failure: command execution error:\n%s" % msg)
  elif isinstance(err, errors.TagError):
    obuf.write("Failure: invalid tag(s) given:\n%s" % msg)
  elif isinstance(err, errors.JobQueueDrainError):
    obuf.write("Failure: the job queue is marked for drain and doesn't"
               " accept new requests\n")
  elif isinstance(err, errors.JobQueueFull):
    obuf.write("Failure: the job queue is full and doesn't accept new"
               " job submissions until old jobs are archived\n")
  elif isinstance(err, errors.TypeEnforcementError):
    obuf.write("Parameter Error: %s" % msg)
  elif isinstance(err, errors.ParameterError):
    obuf.write("Failure: unknown/wrong parameter name '%s'" % msg)
  elif isinstance(err, luxi.NoMasterError):
    obuf.write("Cannot communicate with the master daemon.\nIs it running"
               " and listening for connections?")
  elif isinstance(err, luxi.TimeoutError):
    obuf.write("Timeout while talking to the master daemon. Error:\n"
               "%s" % msg)
  elif isinstance(err, luxi.PermissionError):
    obuf.write("It seems you don't have permissions to connect to the"
               " master daemon.\nPlease retry as a different user.")
  elif isinstance(err, luxi.ProtocolError):
    obuf.write("Unhandled protocol error while talking to the master daemon:\n"
               "%s" % msg)
  elif isinstance(err, errors.JobLost):
    obuf.write("Error checking job status: %s" % msg)
  elif isinstance(err, errors.GenericError):
    obuf.write("Unhandled Ganeti error: %s" % msg)
  elif isinstance(err, JobSubmittedException):
    obuf.write("JobID: %s\n" % err.args[0])
    retcode = 0
  else:
    obuf.write("Unhandled exception: %s" % msg)
  return retcode, obuf.getvalue().rstrip('\n')


def GenericMain(commands, override=None, aliases=None):
  """Generic main function for all the gnt-* commands.

  Arguments:
    - commands: a dictionary with a special structure, see the design doc
                for command line handling.
    - override: if not None, we expect a dictionary with keys that will
                override command line options; this can be used to pass
                options from the scripts to generic functions
    - aliases: dictionary with command aliases {'alias': 'target, ...}

  """
  # save the program name and the entire command line for later logging
  if sys.argv:
    binary = os.path.basename(sys.argv[0]) or sys.argv[0]
    if len(sys.argv) >= 2:
      binary += " " + sys.argv[1]
      old_cmdline = " ".join(sys.argv[2:])
    else:
      old_cmdline = ""
  else:
    binary = "<unknown program>"
    old_cmdline = ""

  if aliases is None:
    aliases = {}

  try:
    func, options, args = _ParseArgs(sys.argv, commands, aliases)
  except errors.ParameterError, err:
    result, err_msg = FormatError(err)
    ToStderr(err_msg)
    return 1

  if func is None: # parse error
    return 1

  if override is not None:
    for key, val in override.iteritems():
      setattr(options, key, val)

  utils.SetupLogging(constants.LOG_COMMANDS, debug=options.debug,
                     stderr_logging=True, program=binary)

  if old_cmdline:
    logging.info("run with arguments '%s'", old_cmdline)
  else:
    logging.info("run with no arguments")

  try:
    result = func(options, args)
  except (errors.GenericError, luxi.ProtocolError,
          JobSubmittedException), err:
    result, err_msg = FormatError(err)
    logging.exception("Error during command processing")
    ToStderr(err_msg)

  return result


def ParseNicOption(optvalue):
  """Parses the value of the --net option(s).

  """
  try:
    nic_max = max(int(nidx[0]) + 1 for nidx in optvalue)
  except (TypeError, ValueError), err:
    raise errors.OpPrereqError("Invalid NIC index passed: %s" % str(err))

  nics = [{}] * nic_max
  for nidx, ndict in optvalue:
    nidx = int(nidx)

    if not isinstance(ndict, dict):
      raise errors.OpPrereqError("Invalid nic/%d value: expected dict,"
                                 " got %s" % (nidx, ndict))

    utils.ForceDictType(ndict, constants.INIC_PARAMS_TYPES)

    nics[nidx] = ndict

  return nics


def GenericInstanceCreate(mode, opts, args):
  """Add an instance to the cluster via either creation or import.

  @param mode: constants.INSTANCE_CREATE or constants.INSTANCE_IMPORT
  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the new instance name
  @rtype: int
  @return: the desired exit code

  """
  instance = args[0]

  (pnode, snode) = SplitNodeOption(opts.node)

  hypervisor = None
  hvparams = {}
  if opts.hypervisor:
    hypervisor, hvparams = opts.hypervisor

  if opts.nics:
    nics = ParseNicOption(opts.nics)
  elif opts.no_nics:
    # no nics
    nics = []
  elif mode == constants.INSTANCE_CREATE:
    # default of one nic, all auto
    nics = [{}]
  else:
    # mode == import
    nics = []

  if opts.disk_template == constants.DT_DISKLESS:
    if opts.disks or opts.sd_size is not None:
      raise errors.OpPrereqError("Diskless instance but disk"
                                 " information passed")
    disks = []
  else:
    if (not opts.disks and not opts.sd_size
        and mode == constants.INSTANCE_CREATE):
      raise errors.OpPrereqError("No disk information specified")
    if opts.disks and opts.sd_size is not None:
      raise errors.OpPrereqError("Please use either the '--disk' or"
                                 " '-s' option")
    if opts.sd_size is not None:
      opts.disks = [(0, {"size": opts.sd_size})]

    if opts.disks:
      try:
        disk_max = max(int(didx[0]) + 1 for didx in opts.disks)
      except ValueError, err:
        raise errors.OpPrereqError("Invalid disk index passed: %s" % str(err))
      disks = [{}] * disk_max
    else:
      disks = []
    for didx, ddict in opts.disks:
      didx = int(didx)
      if not isinstance(ddict, dict):
        msg = "Invalid disk/%d value: expected dict, got %s" % (didx, ddict)
        raise errors.OpPrereqError(msg)
      elif "size" in ddict:
        if "adopt" in ddict:
          raise errors.OpPrereqError("Only one of 'size' and 'adopt' allowed"
                                     " (disk %d)" % didx)
        try:
          ddict["size"] = utils.ParseUnit(ddict["size"])
        except ValueError, err:
          raise errors.OpPrereqError("Invalid disk size for disk %d: %s" %
                                     (didx, err))
      elif "adopt" in ddict:
        if mode == constants.INSTANCE_IMPORT:
          raise errors.OpPrereqError("Disk adoption not allowed for instance"
                                     " import")
        ddict["size"] = 0
      else:
        raise errors.OpPrereqError("Missing size or adoption source for"
                                   " disk %d" % didx)
      disks[didx] = ddict

  utils.ForceDictType(opts.beparams, constants.BES_PARAMETER_TYPES)
  utils.ForceDictType(hvparams, constants.HVS_PARAMETER_TYPES)

  if mode == constants.INSTANCE_CREATE:
    start = opts.start
    os_type = opts.os
    force_variant = opts.force_variant
    src_node = None
    src_path = None
    no_install = opts.no_install
    identify_defaults = False
  elif mode == constants.INSTANCE_IMPORT:
    start = False
    os_type = None
    force_variant = False
    src_node = opts.src_node
    src_path = opts.src_dir
    no_install = None
    identify_defaults = opts.identify_defaults
  else:
    raise errors.ProgrammerError("Invalid creation mode %s" % mode)

  op = opcodes.OpCreateInstance(instance_name=instance,
                                disks=disks,
                                disk_template=opts.disk_template,
                                nics=nics,
                                pnode=pnode, snode=snode,
                                ip_check=opts.ip_check,
                                name_check=opts.name_check,
                                wait_for_sync=opts.wait_for_sync,
                                file_storage_dir=opts.file_storage_dir,
                                file_driver=opts.file_driver,
                                iallocator=opts.iallocator,
                                hypervisor=hypervisor,
                                hvparams=hvparams,
                                beparams=opts.beparams,
                                osparams=opts.osparams,
                                mode=mode,
                                start=start,
                                os_type=os_type,
                                force_variant=force_variant,
                                src_node=src_node,
                                src_path=src_path,
                                no_install=no_install,
                                identify_defaults=identify_defaults)

  SubmitOrSend(op, opts)
  return 0


class _RunWhileClusterStoppedHelper:
  """Helper class for L{RunWhileClusterStopped} to simplify state management

  """
  def __init__(self, feedback_fn, cluster_name, master_node, online_nodes):
    """Initializes this class.

    @type feedback_fn: callable
    @param feedback_fn: Feedback function
    @type cluster_name: string
    @param cluster_name: Cluster name
    @type master_node: string
    @param master_node Master node name
    @type online_nodes: list
    @param online_nodes: List of names of online nodes

    """
    self.feedback_fn = feedback_fn
    self.cluster_name = cluster_name
    self.master_node = master_node
    self.online_nodes = online_nodes

    self.ssh = ssh.SshRunner(self.cluster_name)

    self.nonmaster_nodes = [name for name in online_nodes
                            if name != master_node]

    assert self.master_node not in self.nonmaster_nodes

  def _RunCmd(self, node_name, cmd):
    """Runs a command on the local or a remote machine.

    @type node_name: string
    @param node_name: Machine name
    @type cmd: list
    @param cmd: Command

    """
    if node_name is None or node_name == self.master_node:
      # No need to use SSH
      result = utils.RunCmd(cmd)
    else:
      result = self.ssh.Run(node_name, "root", utils.ShellQuoteArgs(cmd))

    if result.failed:
      errmsg = ["Failed to run command %s" % result.cmd]
      if node_name:
        errmsg.append("on node %s" % node_name)
      errmsg.append(": exitcode %s and error %s" %
                    (result.exit_code, result.output))
      raise errors.OpExecError(" ".join(errmsg))

  def Call(self, fn, *args):
    """Call function while all daemons are stopped.

    @type fn: callable
    @param fn: Function to be called

    """
    # Pause watcher by acquiring an exclusive lock on watcher state file
    self.feedback_fn("Blocking watcher")
    watcher_block = utils.FileLock.Open(constants.WATCHER_STATEFILE)
    try:
      # TODO: Currently, this just blocks. There's no timeout.
      # TODO: Should it be a shared lock?
      watcher_block.Exclusive(blocking=True)

      # Stop master daemons, so that no new jobs can come in and all running
      # ones are finished
      self.feedback_fn("Stopping master daemons")
      self._RunCmd(None, [constants.DAEMON_UTIL, "stop-master"])
      try:
        # Stop daemons on all nodes
        for node_name in self.online_nodes:
          self.feedback_fn("Stopping daemons on %s" % node_name)
          self._RunCmd(node_name, [constants.DAEMON_UTIL, "stop-all"])

        # All daemons are shut down now
        try:
          return fn(self, *args)
        except Exception, err:
          _, errmsg = FormatError(err)
          logging.exception("Caught exception")
          self.feedback_fn(errmsg)
          raise
      finally:
        # Start cluster again, master node last
        for node_name in self.nonmaster_nodes + [self.master_node]:
          self.feedback_fn("Starting daemons on %s" % node_name)
          self._RunCmd(node_name, [constants.DAEMON_UTIL, "start-all"])
    finally:
      # Resume watcher
      watcher_block.Close()


def RunWhileClusterStopped(feedback_fn, fn, *args):
  """Calls a function while all cluster daemons are stopped.

  @type feedback_fn: callable
  @param feedback_fn: Feedback function
  @type fn: callable
  @param fn: Function to be called when daemons are stopped

  """
  feedback_fn("Gathering cluster information")

  # This ensures we're running on the master daemon
  cl = GetClient()

  (cluster_name, master_node) = \
    cl.QueryConfigValues(["cluster_name", "master_node"])

  online_nodes = GetOnlineNodes([], cl=cl)

  # Don't keep a reference to the client. The master daemon will go away.
  del cl

  assert master_node in online_nodes

  return _RunWhileClusterStoppedHelper(feedback_fn, cluster_name, master_node,
                                       online_nodes).Call(fn, *args)


def GenerateTable(headers, fields, separator, data,
                  numfields=None, unitfields=None,
                  units=None):
  """Prints a table with headers and different fields.

  @type headers: dict
  @param headers: dictionary mapping field names to headers for
      the table
  @type fields: list
  @param fields: the field names corresponding to each row in
      the data field
  @param separator: the separator to be used; if this is None,
      the default 'smart' algorithm is used which computes optimal
      field width, otherwise just the separator is used between
      each field
  @type data: list
  @param data: a list of lists, each sublist being one row to be output
  @type numfields: list
  @param numfields: a list with the fields that hold numeric
      values and thus should be right-aligned
  @type unitfields: list
  @param unitfields: a list with the fields that hold numeric
      values that should be formatted with the units field
  @type units: string or None
  @param units: the units we should use for formatting, or None for
      automatic choice (human-readable for non-separator usage, otherwise
      megabytes); this is a one-letter string

  """
  if units is None:
    if separator:
      units = "m"
    else:
      units = "h"

  if numfields is None:
    numfields = []
  if unitfields is None:
    unitfields = []

  numfields = utils.FieldSet(*numfields)   # pylint: disable-msg=W0142
  unitfields = utils.FieldSet(*unitfields) # pylint: disable-msg=W0142

  format_fields = []
  for field in fields:
    if headers and field not in headers:
      # TODO: handle better unknown fields (either revert to old
      # style of raising exception, or deal more intelligently with
      # variable fields)
      headers[field] = field
    if separator is not None:
      format_fields.append("%s")
    elif numfields.Matches(field):
      format_fields.append("%*s")
    else:
      format_fields.append("%-*s")

  if separator is None:
    mlens = [0 for name in fields]
    format_str = ' '.join(format_fields)
  else:
    format_str = separator.replace("%", "%%").join(format_fields)

  for row in data:
    if row is None:
      continue
    for idx, val in enumerate(row):
      if unitfields.Matches(fields[idx]):
        try:
          val = int(val)
        except (TypeError, ValueError):
          pass
        else:
          val = row[idx] = utils.FormatUnit(val, units)
      val = row[idx] = str(val)
      if separator is None:
        mlens[idx] = max(mlens[idx], len(val))

  result = []
  if headers:
    args = []
    for idx, name in enumerate(fields):
      hdr = headers[name]
      if separator is None:
        mlens[idx] = max(mlens[idx], len(hdr))
        args.append(mlens[idx])
      args.append(hdr)
    result.append(format_str % tuple(args))

  if separator is None:
    assert len(mlens) == len(fields)

    if fields and not numfields.Matches(fields[-1]):
      mlens[-1] = 0

  for line in data:
    args = []
    if line is None:
      line = ['-' for _ in fields]
    for idx in range(len(fields)):
      if separator is None:
        args.append(mlens[idx])
      args.append(line[idx])
    result.append(format_str % tuple(args))

  return result


def FormatTimestamp(ts):
  """Formats a given timestamp.

  @type ts: timestamp
  @param ts: a timeval-type timestamp, a tuple of seconds and microseconds

  @rtype: string
  @return: a string with the formatted timestamp

  """
  if not isinstance (ts, (tuple, list)) or len(ts) != 2:
    return '?'
  sec, usec = ts
  return time.strftime("%F %T", time.localtime(sec)) + ".%06d" % usec


def ParseTimespec(value):
  """Parse a time specification.

  The following suffixed will be recognized:

    - s: seconds
    - m: minutes
    - h: hours
    - d: day
    - w: weeks

  Without any suffix, the value will be taken to be in seconds.

  """
  value = str(value)
  if not value:
    raise errors.OpPrereqError("Empty time specification passed")
  suffix_map = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
    }
  if value[-1] not in suffix_map:
    try:
      value = int(value)
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid time specification '%s'" % value)
  else:
    multiplier = suffix_map[value[-1]]
    value = value[:-1]
    if not value: # no data left after stripping the suffix
      raise errors.OpPrereqError("Invalid time specification (only"
                                 " suffix passed)")
    try:
      value = int(value) * multiplier
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid time specification '%s'" % value)
  return value


def GetOnlineNodes(nodes, cl=None, nowarn=False, secondary_ips=False,
                   filter_master=False):
  """Returns the names of online nodes.

  This function will also log a warning on stderr with the names of
  the online nodes.

  @param nodes: if not empty, use only this subset of nodes (minus the
      offline ones)
  @param cl: if not None, luxi client to use
  @type nowarn: boolean
  @param nowarn: by default, this function will output a note with the
      offline nodes that are skipped; if this parameter is True the
      note is not displayed
  @type secondary_ips: boolean
  @param secondary_ips: if True, return the secondary IPs instead of the
      names, useful for doing network traffic over the replication interface
      (if any)
  @type filter_master: boolean
  @param filter_master: if True, do not return the master node in the list
      (useful in coordination with secondary_ips where we cannot check our
      node name against the list)

  """
  if cl is None:
    cl = GetClient()

  if secondary_ips:
    name_idx = 2
  else:
    name_idx = 0

  if filter_master:
    master_node = cl.QueryConfigValues(["master_node"])[0]
    filter_fn = lambda x: x != master_node
  else:
    filter_fn = lambda _: True

  result = cl.QueryNodes(names=nodes, fields=["name", "offline", "sip"],
                         use_locking=False)
  offline = [row[0] for row in result if row[1]]
  if offline and not nowarn:
    ToStderr("Note: skipping offline node(s): %s" % utils.CommaJoin(offline))
  return [row[name_idx] for row in result if not row[1] and filter_fn(row[0])]


def _ToStream(stream, txt, *args):
  """Write a message to a stream, bypassing the logging system

  @type stream: file object
  @param stream: the file to which we should write
  @type txt: str
  @param txt: the message

  """
  if args:
    args = tuple(args)
    stream.write(txt % args)
  else:
    stream.write(txt)
  stream.write('\n')
  stream.flush()


def ToStdout(txt, *args):
  """Write a message to stdout only, bypassing the logging system

  This is just a wrapper over _ToStream.

  @type txt: str
  @param txt: the message

  """
  _ToStream(sys.stdout, txt, *args)


def ToStderr(txt, *args):
  """Write a message to stderr only, bypassing the logging system

  This is just a wrapper over _ToStream.

  @type txt: str
  @param txt: the message

  """
  _ToStream(sys.stderr, txt, *args)


class JobExecutor(object):
  """Class which manages the submission and execution of multiple jobs.

  Note that instances of this class should not be reused between
  GetResults() calls.

  """
  def __init__(self, cl=None, verbose=True, opts=None, feedback_fn=None):
    self.queue = []
    if cl is None:
      cl = GetClient()
    self.cl = cl
    self.verbose = verbose
    self.jobs = []
    self.opts = opts
    self.feedback_fn = feedback_fn

  def QueueJob(self, name, *ops):
    """Record a job for later submit.

    @type name: string
    @param name: a description of the job, will be used in WaitJobSet
    """
    SetGenericOpcodeOpts(ops, self.opts)
    self.queue.append((name, ops))

  def SubmitPending(self, each=False):
    """Submit all pending jobs.

    """
    if each:
      results = []
      for row in self.queue:
        # SubmitJob will remove the success status, but raise an exception if
        # the submission fails, so we'll notice that anyway.
        results.append([True, self.cl.SubmitJob(row[1])])
    else:
      results = self.cl.SubmitManyJobs([row[1] for row in self.queue])
    for (idx, ((status, data), (name, _))) in enumerate(zip(results,
                                                            self.queue)):
      self.jobs.append((idx, status, data, name))

  def _ChooseJob(self):
    """Choose a non-waiting/queued job to poll next.

    """
    assert self.jobs, "_ChooseJob called with empty job list"

    result = self.cl.QueryJobs([i[2] for i in self.jobs], ["status"])
    assert result

    for job_data, status in zip(self.jobs, result):
      if (isinstance(status, list) and status and
          status[0] in (constants.JOB_STATUS_QUEUED,
                        constants.JOB_STATUS_WAITLOCK,
                        constants.JOB_STATUS_CANCELING)):
        # job is still present and waiting
        continue
      # good candidate found (either running job or lost job)
      self.jobs.remove(job_data)
      return job_data

    # no job found
    return self.jobs.pop(0)

  def GetResults(self):
    """Wait for and return the results of all jobs.

    @rtype: list
    @return: list of tuples (success, job results), in the same order
        as the submitted jobs; if a job has failed, instead of the result
        there will be the error message

    """
    if not self.jobs:
      self.SubmitPending()
    results = []
    if self.verbose:
      ok_jobs = [row[2] for row in self.jobs if row[1]]
      if ok_jobs:
        ToStdout("Submitted jobs %s", utils.CommaJoin(ok_jobs))

    # first, remove any non-submitted jobs
    self.jobs, failures = compat.partition(self.jobs, lambda x: x[1])
    for idx, _, jid, name in failures:
      ToStderr("Failed to submit job for %s: %s", name, jid)
      results.append((idx, False, jid))

    while self.jobs:
      (idx, _, jid, name) = self._ChooseJob()
      ToStdout("Waiting for job %s for %s...", jid, name)
      try:
        job_result = PollJob(jid, cl=self.cl, feedback_fn=self.feedback_fn)
        success = True
      except errors.JobLost, err:
        _, job_result = FormatError(err)
        ToStderr("Job %s for %s has been archived, cannot check its result",
                 jid, name)
        success = False
      except (errors.GenericError, luxi.ProtocolError), err:
        _, job_result = FormatError(err)
        success = False
        # the error message will always be shown, verbose or not
        ToStderr("Job %s for %s has failed: %s", jid, name, job_result)

      results.append((idx, success, job_result))

    # sort based on the index, then drop it
    results.sort()
    results = [i[1:] for i in results]

    return results

  def WaitOrShow(self, wait):
    """Wait for job results or only print the job IDs.

    @type wait: boolean
    @param wait: whether to wait or not

    """
    if wait:
      return self.GetResults()
    else:
      if not self.jobs:
        self.SubmitPending()
      for _, status, result, name in self.jobs:
        if status:
          ToStdout("%s: %s", result, name)
        else:
          ToStderr("Failure for %s: %s", name, result)
      return [row[1:3] for row in self.jobs]
