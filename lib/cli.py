#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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
import errno
import itertools
import shlex
from cStringIO import StringIO

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import opcodes
import ganeti.rpc.errors as rpcerr
import ganeti.rpc.node as rpc
from ganeti import ssh
from ganeti import compat
from ganeti import netutils
from ganeti import qlang
from ganeti import objects
from ganeti import pathutils
from ganeti import serializer

from ganeti.runtime import (GetClient)

from optparse import (OptionParser, TitledHelpFormatter,
                      Option, OptionValueError)


__all__ = [
  # Command line options
  "ABSOLUTE_OPT",
  "ADD_UIDS_OPT",
  "ADD_RESERVED_IPS_OPT",
  "ALLOCATABLE_OPT",
  "ALLOC_POLICY_OPT",
  "ALL_OPT",
  "ALLOW_FAILOVER_OPT",
  "AUTO_PROMOTE_OPT",
  "AUTO_REPLACE_OPT",
  "BACKEND_OPT",
  "BLK_OS_OPT",
  "CAPAB_MASTER_OPT",
  "CAPAB_VM_OPT",
  "CLEANUP_OPT",
  "CLUSTER_DOMAIN_SECRET_OPT",
  "CONFIRM_OPT",
  "CP_SIZE_OPT",
  "DEBUG_OPT",
  "DEBUG_SIMERR_OPT",
  "DISKIDX_OPT",
  "DISK_OPT",
  "DISK_PARAMS_OPT",
  "DISK_TEMPLATE_OPT",
  "DRAINED_OPT",
  "DRY_RUN_OPT",
  "DRBD_HELPER_OPT",
  "DST_NODE_OPT",
  "EARLY_RELEASE_OPT",
  "ENABLED_HV_OPT",
  "ENABLED_DISK_TEMPLATES_OPT",
  "ERROR_CODES_OPT",
  "FAILURE_ONLY_OPT",
  "FIELDS_OPT",
  "FILESTORE_DIR_OPT",
  "FILESTORE_DRIVER_OPT",
  "FORCE_FILTER_OPT",
  "FORCE_OPT",
  "FORCE_VARIANT_OPT",
  "GATEWAY_OPT",
  "GATEWAY6_OPT",
  "GLOBAL_FILEDIR_OPT",
  "HID_OS_OPT",
  "GLOBAL_GLUSTER_FILEDIR_OPT",
  "GLOBAL_SHARED_FILEDIR_OPT",
  "HOTPLUG_OPT",
  "HOTPLUG_IF_POSSIBLE_OPT",
  "HVLIST_OPT",
  "HVOPTS_OPT",
  "HYPERVISOR_OPT",
  "IALLOCATOR_OPT",
  "DEFAULT_IALLOCATOR_OPT",
  "DEFAULT_IALLOCATOR_PARAMS_OPT",
  "IDENTIFY_DEFAULTS_OPT",
  "IGNORE_CONSIST_OPT",
  "IGNORE_ERRORS_OPT",
  "IGNORE_FAILURES_OPT",
  "IGNORE_OFFLINE_OPT",
  "IGNORE_REMOVE_FAILURES_OPT",
  "IGNORE_SECONDARIES_OPT",
  "IGNORE_SIZE_OPT",
  "INCLUDEDEFAULTS_OPT",
  "INTERVAL_OPT",
  "INSTANCE_COMMUNICATION_OPT",
  "MAC_PREFIX_OPT",
  "MAINTAIN_NODE_HEALTH_OPT",
  "MASTER_NETDEV_OPT",
  "MASTER_NETMASK_OPT",
  "MC_OPT",
  "MIGRATION_MODE_OPT",
  "MODIFY_ETCHOSTS_OPT",
  "NET_OPT",
  "NETWORK_OPT",
  "NETWORK6_OPT",
  "NEW_CLUSTER_CERT_OPT",
  "NEW_NODE_CERT_OPT",
  "NEW_CLUSTER_DOMAIN_SECRET_OPT",
  "NEW_CONFD_HMAC_KEY_OPT",
  "NEW_RAPI_CERT_OPT",
  "NEW_PRIMARY_OPT",
  "NEW_SECONDARY_OPT",
  "NEW_SPICE_CERT_OPT",
  "NIC_PARAMS_OPT",
  "NOCONFLICTSCHECK_OPT",
  "NODE_FORCE_JOIN_OPT",
  "NODE_LIST_OPT",
  "NODE_PLACEMENT_OPT",
  "NODEGROUP_OPT",
  "NODE_PARAMS_OPT",
  "NODE_POWERED_OPT",
  "NOHDR_OPT",
  "NOIPCHECK_OPT",
  "NO_INSTALL_OPT",
  "NONAMECHECK_OPT",
  "NOMODIFY_ETCHOSTS_OPT",
  "NOMODIFY_SSH_SETUP_OPT",
  "NONICS_OPT",
  "NONLIVE_OPT",
  "NONPLUS1_OPT",
  "NORUNTIME_CHGS_OPT",
  "NOSHUTDOWN_OPT",
  "NOSTART_OPT",
  "NOSSH_KEYCHECK_OPT",
  "NOVOTING_OPT",
  "NO_REMEMBER_OPT",
  "NWSYNC_OPT",
  "OFFLINE_INST_OPT",
  "ONLINE_INST_OPT",
  "ON_PRIMARY_OPT",
  "ON_SECONDARY_OPT",
  "OFFLINE_OPT",
  "OSPARAMS_OPT",
  "OSPARAMS_PRIVATE_OPT",
  "OSPARAMS_SECRET_OPT",
  "OS_OPT",
  "OS_SIZE_OPT",
  "OOB_TIMEOUT_OPT",
  "POWER_DELAY_OPT",
  "PREALLOC_WIPE_DISKS_OPT",
  "PRIMARY_IP_VERSION_OPT",
  "PRIMARY_ONLY_OPT",
  "PRINT_JOBID_OPT",
  "PRIORITY_OPT",
  "RAPI_CERT_OPT",
  "READD_OPT",
  "REASON_OPT",
  "REBOOT_TYPE_OPT",
  "REMOVE_INSTANCE_OPT",
  "REMOVE_RESERVED_IPS_OPT",
  "REMOVE_UIDS_OPT",
  "RESERVED_LVS_OPT",
  "RQL_OPT",
  "RUNTIME_MEM_OPT",
  "ROMAN_OPT",
  "SECONDARY_IP_OPT",
  "SECONDARY_ONLY_OPT",
  "SELECT_OS_OPT",
  "SEP_OPT",
  "SHOWCMD_OPT",
  "SHOW_MACHINE_OPT",
  "COMPRESS_OPT",
  "SHUTDOWN_TIMEOUT_OPT",
  "SINGLE_NODE_OPT",
  "SPECS_CPU_COUNT_OPT",
  "SPECS_DISK_COUNT_OPT",
  "SPECS_DISK_SIZE_OPT",
  "SPECS_MEM_SIZE_OPT",
  "SPECS_NIC_COUNT_OPT",
  "SPLIT_ISPECS_OPTS",
  "IPOLICY_STD_SPECS_OPT",
  "IPOLICY_DISK_TEMPLATES",
  "IPOLICY_VCPU_RATIO",
  "SPICE_CACERT_OPT",
  "SPICE_CERT_OPT",
  "SRC_DIR_OPT",
  "SRC_NODE_OPT",
  "SUBMIT_OPT",
  "SUBMIT_OPTS",
  "STARTUP_PAUSED_OPT",
  "STATIC_OPT",
  "SYNC_OPT",
  "TAG_ADD_OPT",
  "TAG_SRC_OPT",
  "TIMEOUT_OPT",
  "TO_GROUP_OPT",
  "UIDPOOL_OPT",
  "USEUNITS_OPT",
  "USE_EXTERNAL_MIP_SCRIPT",
  "USE_REPL_NET_OPT",
  "VERBOSE_OPT",
  "VG_NAME_OPT",
  "WFSYNC_OPT",
  "YES_DOIT_OPT",
  "DISK_STATE_OPT",
  "HV_STATE_OPT",
  "IGNORE_IPOLICY_OPT",
  "INSTANCE_POLICY_OPTS",
  # Generic functions for CLI programs
  "ConfirmOperation",
  "CreateIPolicyFromOpts",
  "GenericMain",
  "GenericInstanceCreate",
  "GenericList",
  "GenericListFields",
  "GetClient",
  "GetOnlineNodes",
  "GetNodesSshPorts",
  "JobExecutor",
  "JobSubmittedException",
  "ParseTimespec",
  "RunWhileClusterStopped",
  "SubmitOpCode",
  "SubmitOpCodeToDrainedQueue",
  "SubmitOrSend",
  "UsesRPC",
  # Formatting functions
  "ToStderr", "ToStdout",
  "FormatError",
  "FormatQueryResult",
  "FormatParamsDictInfo",
  "FormatPolicyInfo",
  "PrintIPolicyCommand",
  "PrintGenericInfo",
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
  "ARGS_MANY_GROUPS",
  "ARGS_MANY_NETWORKS",
  "ARGS_NONE",
  "ARGS_ONE_INSTANCE",
  "ARGS_ONE_NODE",
  "ARGS_ONE_GROUP",
  "ARGS_ONE_OS",
  "ARGS_ONE_NETWORK",
  "ArgChoice",
  "ArgCommand",
  "ArgFile",
  "ArgGroup",
  "ArgHost",
  "ArgInstance",
  "ArgJobId",
  "ArgNetwork",
  "ArgNode",
  "ArgOs",
  "ArgExtStorage",
  "ArgSuggest",
  "ArgUnknown",
  "OPT_COMPL_INST_ADD_NODES",
  "OPT_COMPL_MANY_NODES",
  "OPT_COMPL_ONE_IALLOCATOR",
  "OPT_COMPL_ONE_INSTANCE",
  "OPT_COMPL_ONE_NODE",
  "OPT_COMPL_ONE_NODEGROUP",
  "OPT_COMPL_ONE_NETWORK",
  "OPT_COMPL_ONE_OS",
  "OPT_COMPL_ONE_EXTSTORAGE",
  "cli_option",
  "FixHvParams",
  "SplitNodeOption",
  "CalculateOSNames",
  "ParseFields",
  "COMMON_CREATE_OPTS",
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

# Query result status for clients
(QR_NORMAL,
 QR_UNKNOWN,
 QR_INCOMPLETE) = range(3)

#: Maximum batch size for ChooseJob
_CHOOSE_BATCH = 25


# constants used to create InstancePolicy dictionary
TISPECS_GROUP_TYPES = {
  constants.ISPECS_MIN: constants.VTYPE_INT,
  constants.ISPECS_MAX: constants.VTYPE_INT,
  }

TISPECS_CLUSTER_TYPES = {
  constants.ISPECS_MIN: constants.VTYPE_INT,
  constants.ISPECS_MAX: constants.VTYPE_INT,
  constants.ISPECS_STD: constants.VTYPE_INT,
  }

#: User-friendly names for query2 field types
_QFT_NAMES = {
  constants.QFT_UNKNOWN: "Unknown",
  constants.QFT_TEXT: "Text",
  constants.QFT_BOOL: "Boolean",
  constants.QFT_NUMBER: "Number",
  constants.QFT_UNIT: "Storage size",
  constants.QFT_TIMESTAMP: "Timestamp",
  constants.QFT_OTHER: "Custom",
  }


class _Argument:
  def __init__(self, min=0, max=None): # pylint: disable=W0622
    self.min = min
    self.max = max

  def __repr__(self):
    return ("<%s min=%s max=%s>" %
            (self.__class__.__name__, self.min, self.max))


class ArgSuggest(_Argument):
  """Suggesting argument.

  Value can be any of the ones passed to the constructor.

  """
  # pylint: disable=W0622
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


class ArgNetwork(_Argument):
  """Network argument.

  """


class ArgGroup(_Argument):
  """Node group argument.

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


class ArgExtStorage(_Argument):
  """ExtStorage argument.

  """


ARGS_NONE = []
ARGS_MANY_INSTANCES = [ArgInstance()]
ARGS_MANY_NETWORKS = [ArgNetwork()]
ARGS_MANY_NODES = [ArgNode()]
ARGS_MANY_GROUPS = [ArgGroup()]
ARGS_ONE_INSTANCE = [ArgInstance(min=1, max=1)]
ARGS_ONE_NETWORK = [ArgNetwork(min=1, max=1)]
ARGS_ONE_NODE = [ArgNode(min=1, max=1)]
# TODO
ARGS_ONE_GROUP = [ArgGroup(min=1, max=1)]
ARGS_ONE_OS = [ArgOs(min=1, max=1)]


def _ExtractTagsObject(opts, args):
  """Extract the tag type object.

  Note that this function will modify its args parameter.

  """
  if not hasattr(opts, "tag_type"):
    raise errors.ProgrammerError("tag_type not passed to _ExtractTagsObject")
  kind = opts.tag_type
  if kind == constants.TAG_CLUSTER:
    retval = kind, ""
  elif kind in (constants.TAG_NODEGROUP,
                constants.TAG_NODE,
                constants.TAG_NETWORK,
                constants.TAG_INSTANCE):
    if not args:
      raise errors.OpPrereqError("no arguments passed to the command",
                                 errors.ECODE_INVAL)
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
  cl = GetClient(query=True)
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
    raise errors.OpPrereqError("No tags to be added", errors.ECODE_INVAL)
  op = opcodes.OpTagsSet(kind=kind, name=name, tags=args)
  SubmitOrSend(op, opts)


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
    raise errors.OpPrereqError("No tags to be removed", errors.ECODE_INVAL)
  op = opcodes.OpTagsDel(kind=kind, name=name, tags=args)
  SubmitOrSend(op, opts)


def check_unit(option, opt, value): # pylint: disable=W0613
  """OptParsers custom converter for units.

  """
  try:
    return utils.ParseUnit(value)
  except errors.UnitParseError, err:
    raise OptionValueError("option %s: %s" % (opt, err))


def _SplitKeyVal(opt, data, parse_prefixes):
  """Convert a KeyVal string into a dict.

  This function will convert a key=val[,...] string into a dict. Empty
  values will be converted specially: keys which have the prefix 'no_'
  will have the value=False and the prefix stripped, keys with the prefix
  "-" will have value=None and the prefix stripped, and the others will
  have value=True.

  @type opt: string
  @param opt: a string holding the option name for which we process the
      data, used in building error messages
  @type data: string
  @param data: a string of the format key=val,key=val,...
  @type parse_prefixes: bool
  @param parse_prefixes: whether to handle prefixes specially
  @rtype: dict
  @return: {key=val, key=val}
  @raises errors.ParameterError: if there are duplicate keys

  """
  kv_dict = {}
  if data:
    for elem in utils.UnescapeAndSplit(data, sep=","):
      if "=" in elem:
        key, val = elem.split("=", 1)
      elif parse_prefixes:
        if elem.startswith(NO_PREFIX):
          key, val = elem[len(NO_PREFIX):], False
        elif elem.startswith(UN_PREFIX):
          key, val = elem[len(UN_PREFIX):], None
        else:
          key, val = elem, True
      else:
        raise errors.ParameterError("Missing value for key '%s' in option %s" %
                                    (elem, opt))
      if key in kv_dict:
        raise errors.ParameterError("Duplicate key '%s' in option %s" %
                                    (key, opt))
      kv_dict[key] = val
  return kv_dict


def _SplitIdentKeyVal(opt, value, parse_prefixes):
  """Helper function to parse "ident:key=val,key=val" options.

  @type opt: string
  @param opt: option name, used in error messages
  @type value: string
  @param value: expected to be in the format "ident:key=val,key=val,..."
  @type parse_prefixes: bool
  @param parse_prefixes: whether to handle prefixes specially (see
      L{_SplitKeyVal})
  @rtype: tuple
  @return: (ident, {key=val, key=val})
  @raises errors.ParameterError: in case of duplicates or other parsing errors

  """
  if ":" not in value:
    ident, rest = value, ""
  else:
    ident, rest = value.split(":", 1)

  if parse_prefixes and ident.startswith(NO_PREFIX):
    if rest:
      msg = "Cannot pass options when removing parameter groups: %s" % value
      raise errors.ParameterError(msg)
    retval = (ident[len(NO_PREFIX):], False)
  elif (parse_prefixes and ident.startswith(UN_PREFIX) and
        (len(ident) <= len(UN_PREFIX) or not ident[len(UN_PREFIX)].isdigit())):
    if rest:
      msg = "Cannot pass options when removing parameter groups: %s" % value
      raise errors.ParameterError(msg)
    retval = (ident[len(UN_PREFIX):], None)
  else:
    kv_dict = _SplitKeyVal(opt, rest, parse_prefixes)
    retval = (ident, kv_dict)
  return retval


def check_ident_key_val(option, opt, value):  # pylint: disable=W0613
  """Custom parser for ident:key=val,key=val options.

  This will store the parsed values as a tuple (ident, {key: val}). As such,
  multiple uses of this option via action=append is possible.

  """
  return _SplitIdentKeyVal(opt, value, True)


def check_key_val(option, opt, value):  # pylint: disable=W0613
  """Custom parser class for key=val,key=val options.

  This will store the parsed values as a dict {key: val}.

  """
  return _SplitKeyVal(opt, value, True)


def check_key_private_val(option, opt, value):  # pylint: disable=W0613
  """Custom parser class for private and secret key=val,key=val options.

  This will store the parsed values as a dict {key: val}.

  """
  return serializer.PrivateDict(_SplitKeyVal(opt, value, True))


def _SplitListKeyVal(opt, value):
  retval = {}
  for elem in value.split("/"):
    if not elem:
      raise errors.ParameterError("Empty section in option '%s'" % opt)
    (ident, valdict) = _SplitIdentKeyVal(opt, elem, False)
    if ident in retval:
      msg = ("Duplicated parameter '%s' in parsing %s: %s" %
             (ident, opt, elem))
      raise errors.ParameterError(msg)
    retval[ident] = valdict
  return retval


def check_multilist_ident_key_val(_, opt, value):
  """Custom parser for "ident:key=val,key=val/ident:key=val//ident:.." options.

  @rtype: list of dictionary
  @return: [{ident: {key: val, key: val}, ident: {key: val}}, {ident:..}]

  """
  retval = []
  for line in value.split("//"):
    retval.append(_SplitListKeyVal(opt, line))
  return retval


def check_bool(option, opt, value): # pylint: disable=W0613
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


def check_list(option, opt, value): # pylint: disable=W0613
  """Custom parser for comma-separated lists.

  """
  # we have to make this explicit check since "".split(",") is [""],
  # not an empty list :(
  if not value:
    return []
  else:
    return utils.UnescapeAndSplit(value)


def check_maybefloat(option, opt, value): # pylint: disable=W0613
  """Custom parser for float numbers which might be also defaults.

  """
  value = value.lower()

  if value == constants.VALUE_DEFAULT:
    return value
  else:
    return float(value)


# completion_suggestion is normally a list. Using numeric values not evaluating
# to False for dynamic completion.
(OPT_COMPL_MANY_NODES,
 OPT_COMPL_ONE_NODE,
 OPT_COMPL_ONE_INSTANCE,
 OPT_COMPL_ONE_OS,
 OPT_COMPL_ONE_EXTSTORAGE,
 OPT_COMPL_ONE_IALLOCATOR,
 OPT_COMPL_ONE_NETWORK,
 OPT_COMPL_INST_ADD_NODES,
 OPT_COMPL_ONE_NODEGROUP) = range(100, 109)

OPT_COMPL_ALL = compat.UniqueFrozenset([
  OPT_COMPL_MANY_NODES,
  OPT_COMPL_ONE_NODE,
  OPT_COMPL_ONE_INSTANCE,
  OPT_COMPL_ONE_OS,
  OPT_COMPL_ONE_EXTSTORAGE,
  OPT_COMPL_ONE_IALLOCATOR,
  OPT_COMPL_ONE_NETWORK,
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
    "multilistidentkeyval",
    "identkeyval",
    "keyval",
    "keyprivateval",
    "unit",
    "bool",
    "list",
    "maybefloat",
    )
  TYPE_CHECKER = Option.TYPE_CHECKER.copy()
  TYPE_CHECKER["multilistidentkeyval"] = check_multilist_ident_key_val
  TYPE_CHECKER["identkeyval"] = check_ident_key_val
  TYPE_CHECKER["keyval"] = check_key_val
  TYPE_CHECKER["keyprivateval"] = check_key_private_val
  TYPE_CHECKER["unit"] = check_unit
  TYPE_CHECKER["bool"] = check_bool
  TYPE_CHECKER["list"] = check_list
  TYPE_CHECKER["maybefloat"] = check_maybefloat


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
                          dest="units", choices=("h", "m", "g", "t"),
                          help="Specify units for output (one of h/m/g/t)")

FIELDS_OPT = cli_option("-o", "--output", dest="output", action="store",
                        type="string", metavar="FIELDS",
                        help="Comma separated list of output fields")

FORCE_OPT = cli_option("-f", "--force", dest="force", action="store_true",
                       default=False, help="Force the operation")

CONFIRM_OPT = cli_option("--yes", dest="confirm", action="store_true",
                         default=False, help="Do not require confirmation")

IGNORE_OFFLINE_OPT = cli_option("--ignore-offline", dest="ignore_offline",
                                  action="store_true", default=False,
                                  help=("Ignore offline nodes and do as much"
                                        " as possible"))

TAG_ADD_OPT = cli_option("--tags", dest="tags",
                         default=None, help="Comma-separated list of instance"
                                            " tags")

TAG_SRC_OPT = cli_option("--from", dest="tags_source",
                         default=None, help="File with tag names")

SUBMIT_OPT = cli_option("--submit", dest="submit_only",
                        default=False, action="store_true",
                        help=("Submit the job and return the job ID, but"
                              " don't wait for the job to finish"))

PRINT_JOBID_OPT = cli_option("--print-jobid", dest="print_jobid",
                             default=False, action="store_true",
                             help=("Additionally print the job as first line"
                                   " on stdout (for scripting)."))

SYNC_OPT = cli_option("--sync", dest="do_locking",
                      default=False, action="store_true",
                      help=("Grab locks while doing the queries"
                            " in order to ensure more consistent results"))

DRY_RUN_OPT = cli_option("--dry-run", default=False,
                         action="store_true",
                         help=("Do not execute the operation, just run the"
                               " check steps and verify if it could be"
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

WFSYNC_OPT = cli_option("--wait-for-sync", dest="wait_for_sync",
                        default=False, action="store_true",
                        help="Wait for disks to sync")

ONLINE_INST_OPT = cli_option("--online", dest="online_inst",
                             action="store_true", default=False,
                             help="Enable offline instance")

OFFLINE_INST_OPT = cli_option("--offline", dest="offline_inst",
                              action="store_true", default=False,
                              help="Disable down instance")

DISK_TEMPLATE_OPT = cli_option("-t", "--disk-template", dest="disk_template",
                               help=("Custom disk setup (%s)" %
                                     utils.CommaJoin(constants.DISK_TEMPLATES)),
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
                                  default=None, metavar="<DRIVER>",
                                  choices=list(constants.FILE_DRIVER))

IALLOCATOR_OPT = cli_option("-I", "--iallocator", metavar="<NAME>",
                            help="Select nodes for the instance automatically"
                            " using the <NAME> iallocator plugin",
                            default=None, type="string",
                            completion_suggest=OPT_COMPL_ONE_IALLOCATOR)

DEFAULT_IALLOCATOR_OPT = cli_option("-I", "--default-iallocator",
                                    metavar="<NAME>",
                                    help="Set the default instance"
                                    " allocator plugin",
                                    default=None, type="string",
                                    completion_suggest=OPT_COMPL_ONE_IALLOCATOR)

DEFAULT_IALLOCATOR_PARAMS_OPT = cli_option("--default-iallocator-params",
                                           dest="default_iallocator_params",
                                           help="iallocator template"
                                           " parameters, in the format"
                                           " template:option=value,"
                                           " option=value,...",
                                           type="keyval",
                                           default={})

OS_OPT = cli_option("-o", "--os-type", dest="os", help="What OS to run",
                    metavar="<os>",
                    completion_suggest=OPT_COMPL_ONE_OS)

OSPARAMS_OPT = cli_option("-O", "--os-parameters", dest="osparams",
                          type="keyval", default={},
                          help="OS parameters")

OSPARAMS_PRIVATE_OPT = cli_option("--os-parameters-private",
                                  dest="osparams_private",
                                  type="keyprivateval",
                                  default=serializer.PrivateDict(),
                                  help="Private OS parameters"
                                       " (won't be logged)")

OSPARAMS_SECRET_OPT = cli_option("--os-parameters-secret",
                                 dest="osparams_secret",
                                 type="keyprivateval",
                                 default=serializer.PrivateDict(),
                                 help="Secret OS parameters (won't be logged or"
                                      " saved; you must supply these for every"
                                      " operation.)")

FORCE_VARIANT_OPT = cli_option("--force-variant", dest="force_variant",
                               action="store_true", default=False,
                               help="Force an unknown variant")

NO_INSTALL_OPT = cli_option("--no-install", dest="no_install",
                            action="store_true", default=False,
                            help="Do not install the OS (will"
                            " enable no-start)")

NORUNTIME_CHGS_OPT = cli_option("--no-runtime-changes",
                                dest="allow_runtime_chgs",
                                default=True, action="store_false",
                                help="Don't allow runtime changes")

BACKEND_OPT = cli_option("-B", "--backend-parameters", dest="beparams",
                         type="keyval", default={},
                         help="Backend parameters")

HVOPTS_OPT = cli_option("-H", "--hypervisor-parameters", type="keyval",
                        default={}, dest="hvparams",
                        help="Hypervisor parameters")

DISK_PARAMS_OPT = cli_option("-D", "--disk-parameters", dest="diskparams",
                             help="Disk template parameters, in the format"
                             " template:option=value,option=value,...",
                             type="identkeyval", action="append", default=[])

SPECS_MEM_SIZE_OPT = cli_option("--specs-mem-size", dest="ispecs_mem_size",
                                 type="keyval", default={},
                                 help="Memory size specs: list of key=value,"
                                " where key is one of min, max, std"
                                 " (in MB or using a unit)")

SPECS_CPU_COUNT_OPT = cli_option("--specs-cpu-count", dest="ispecs_cpu_count",
                                 type="keyval", default={},
                                 help="CPU count specs: list of key=value,"
                                 " where key is one of min, max, std")

SPECS_DISK_COUNT_OPT = cli_option("--specs-disk-count",
                                  dest="ispecs_disk_count",
                                  type="keyval", default={},
                                  help="Disk count specs: list of key=value,"
                                  " where key is one of min, max, std")

SPECS_DISK_SIZE_OPT = cli_option("--specs-disk-size", dest="ispecs_disk_size",
                                 type="keyval", default={},
                                 help="Disk size specs: list of key=value,"
                                 " where key is one of min, max, std"
                                 " (in MB or using a unit)")

SPECS_NIC_COUNT_OPT = cli_option("--specs-nic-count", dest="ispecs_nic_count",
                                 type="keyval", default={},
                                 help="NIC count specs: list of key=value,"
                                 " where key is one of min, max, std")

IPOLICY_BOUNDS_SPECS_STR = "--ipolicy-bounds-specs"
IPOLICY_BOUNDS_SPECS_OPT = cli_option(IPOLICY_BOUNDS_SPECS_STR,
                                      dest="ipolicy_bounds_specs",
                                      type="multilistidentkeyval", default=None,
                                      help="Complete instance specs limits")

IPOLICY_STD_SPECS_STR = "--ipolicy-std-specs"
IPOLICY_STD_SPECS_OPT = cli_option(IPOLICY_STD_SPECS_STR,
                                   dest="ipolicy_std_specs",
                                   type="keyval", default=None,
                                   help="Complte standard instance specs")

IPOLICY_DISK_TEMPLATES = cli_option("--ipolicy-disk-templates",
                                    dest="ipolicy_disk_templates",
                                    type="list", default=None,
                                    help="Comma-separated list of"
                                    " enabled disk templates")

IPOLICY_VCPU_RATIO = cli_option("--ipolicy-vcpu-ratio",
                                 dest="ipolicy_vcpu_ratio",
                                 type="maybefloat", default=None,
                                 help="The maximum allowed vcpu-to-cpu ratio")

IPOLICY_SPINDLE_RATIO = cli_option("--ipolicy-spindle-ratio",
                                   dest="ipolicy_spindle_ratio",
                                   type="maybefloat", default=None,
                                   help=("The maximum allowed instances to"
                                         " spindle ratio"))

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

ALLOW_FAILOVER_OPT = cli_option("--allow-failover",
                                dest="allow_failover",
                                action="store_true", default=False,
                                help="If migration is not possible fallback to"
                                     " failover")

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

NODEGROUP_OPT_NAME = "--node-group"
NODEGROUP_OPT = cli_option("-g", NODEGROUP_OPT_NAME,
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
                         help="Instead of performing the migration/failover,"
                         " try to recover from a failed cleanup. This is safe"
                         " to run even if the instance is healthy, but it"
                         " will create extra replication traffic and "
                         " disrupt briefly the replication (like during the"
                         " migration/failover")

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

DST_NODE_OPT = cli_option("-n", "--target-node", dest="dst_node",
                               help="Specifies the new node for the instance",
                               metavar="NODE", default=None,
                               completion_suggest=OPT_COMPL_ONE_NODE)

NEW_SECONDARY_OPT = cli_option("-n", "--new-secondary", dest="dst_node",
                               help="Specifies the new secondary node",
                               metavar="NODE", default=None,
                               completion_suggest=OPT_COMPL_ONE_NODE)

NEW_PRIMARY_OPT = cli_option("--new-primary", dest="new_primary_node",
                             help="Specifies the new primary node",
                             metavar="<node>", default=None,
                             completion_suggest=OPT_COMPL_ONE_NODE)

ON_PRIMARY_OPT = cli_option("-p", "--on-primary", dest="on_primary",
                            default=False, action="store_true",
                            help="Replace the disk(s) on the primary"
                                 " node (applies only to internally mirrored"
                                 " disk templates, e.g. %s)" %
                                 utils.CommaJoin(constants.DTS_INT_MIRROR))

ON_SECONDARY_OPT = cli_option("-s", "--on-secondary", dest="on_secondary",
                              default=False, action="store_true",
                              help="Replace the disk(s) on the secondary"
                                   " node (applies only to internally mirrored"
                                   " disk templates, e.g. %s)" %
                                   utils.CommaJoin(constants.DTS_INT_MIRROR))

AUTO_PROMOTE_OPT = cli_option("--auto-promote", dest="auto_promote",
                              default=False, action="store_true",
                              help="Lock all nodes and auto-promote as needed"
                              " to MC status")

AUTO_REPLACE_OPT = cli_option("-a", "--auto", dest="auto",
                              default=False, action="store_true",
                              help="Automatically replace faulty disks"
                                   " (applies only to internally mirrored"
                                   " disk templates, e.g. %s)" %
                                   utils.CommaJoin(constants.DTS_INT_MIRROR))

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

NODE_FORCE_JOIN_OPT = cli_option("--force-join", dest="force_join",
                                 default=False, action="store_true",
                                 help="Force the joining of a node")

MC_OPT = cli_option("-C", "--master-candidate", dest="master_candidate",
                    type="bool", default=None, metavar=_YORNO,
                    help="Set the master_candidate flag on the node")

OFFLINE_OPT = cli_option("-O", "--offline", dest="offline", metavar=_YORNO,
                         type="bool", default=None,
                         help=("Set the offline flag on the node"
                               " (cluster does not communicate with offline"
                               " nodes)"))

DRAINED_OPT = cli_option("-D", "--drained", dest="drained", metavar=_YORNO,
                         type="bool", default=None,
                         help=("Set the drained flag on the node"
                               " (excluded from allocation operations)"))

CAPAB_MASTER_OPT = cli_option("--master-capable", dest="master_capable",
                              type="bool", default=None, metavar=_YORNO,
                              help="Set the master_capable flag on the node")

CAPAB_VM_OPT = cli_option("--vm-capable", dest="vm_capable",
                          type="bool", default=None, metavar=_YORNO,
                          help="Set the vm_capable flag on the node")

ALLOCATABLE_OPT = cli_option("--allocatable", dest="allocatable",
                             type="bool", default=None, metavar=_YORNO,
                             help="Set the allocatable flag on a volume")

ENABLED_HV_OPT = cli_option("--enabled-hypervisors",
                            dest="enabled_hypervisors",
                            help="Comma-separated list of hypervisors",
                            type="string", default=None)

ENABLED_DISK_TEMPLATES_OPT = cli_option("--enabled-disk-templates",
                                        dest="enabled_disk_templates",
                                        help="Comma-separated list of "
                                             "disk templates",
                                        type="string", default=None)

NIC_PARAMS_OPT = cli_option("-N", "--nic-parameters", dest="nicparams",
                            type="keyval", default={},
                            help="NIC parameters")

CP_SIZE_OPT = cli_option("-C", "--candidate-pool-size", default=None,
                         dest="candidate_pool_size", type="int",
                         help="Set the candidate pool size")

RQL_OPT = cli_option("--max-running-jobs", dest="max_running_jobs",
                     type="int", help="Set the maximal number of jobs to "
                                      "run simultaneously")

VG_NAME_OPT = cli_option("--vg-name", dest="vg_name",
                         help=("Enables LVM and specifies the volume group"
                               " name (cluster-wide) for disk allocation"
                               " [%s]" % constants.DEFAULT_VG),
                         metavar="VG", default=None)

YES_DOIT_OPT = cli_option("--yes-do-it", "--ya-rly", dest="yes_do_it",
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
                               " on which the master IP address will be added"
                               " (cluster init default: %s)" %
                               constants.DEFAULT_BRIDGE,
                               metavar="NETDEV",
                               default=None)

MASTER_NETMASK_OPT = cli_option("--master-netmask", dest="master_netmask",
                                help="Specify the netmask of the master IP",
                                metavar="NETMASK",
                                default=None)

USE_EXTERNAL_MIP_SCRIPT = cli_option("--use-external-mip-script",
                                     dest="use_external_mip_script",
                                     help="Specify whether to run a"
                                     " user-provided script for the master"
                                     " IP address turnup and"
                                     " turndown operations",
                                     type="bool", metavar=_YORNO, default=None)

GLOBAL_FILEDIR_OPT = cli_option("--file-storage-dir", dest="file_storage_dir",
                                help="Specify the default directory (cluster-"
                                "wide) for storing the file-based disks [%s]" %
                                pathutils.DEFAULT_FILE_STORAGE_DIR,
                                metavar="DIR",
                                default=None)

GLOBAL_SHARED_FILEDIR_OPT = cli_option(
  "--shared-file-storage-dir",
  dest="shared_file_storage_dir",
  help="Specify the default directory (cluster-wide) for storing the"
  " shared file-based disks [%s]" %
  pathutils.DEFAULT_SHARED_FILE_STORAGE_DIR,
  metavar="SHAREDDIR", default=None)

GLOBAL_GLUSTER_FILEDIR_OPT = cli_option(
  "--gluster-storage-dir",
  dest="gluster_storage_dir",
  help="Specify the default directory (cluster-wide) for mounting Gluster"
  " file systems [%s]" %
  pathutils.DEFAULT_GLUSTER_STORAGE_DIR,
  metavar="GLUSTERDIR",
  default=pathutils.DEFAULT_GLUSTER_STORAGE_DIR)

NOMODIFY_ETCHOSTS_OPT = cli_option("--no-etc-hosts", dest="modify_etc_hosts",
                                   help="Don't modify %s" % pathutils.ETC_HOSTS,
                                   action="store_false", default=True)

MODIFY_ETCHOSTS_OPT = \
 cli_option("--modify-etc-hosts", dest="modify_etc_hosts", metavar=_YORNO,
            default=None, type="bool",
            help="Defines whether the cluster should autonomously modify"
            " and keep in sync the /etc/hosts file of the nodes")

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

COMPRESS_OPT = cli_option("--compress", dest="compress",
                          default=constants.IEC_NONE,
                          help="The compression mode to use",
                          choices=list(constants.IEC_ALL))

SHUTDOWN_TIMEOUT_OPT = cli_option("--shutdown-timeout",
                                  dest="shutdown_timeout", type="int",
                                  default=constants.DEFAULT_SHUTDOWN_TIMEOUT,
                                  help="Maximum time to wait for instance"
                                  " shutdown")

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

NEW_NODE_CERT_OPT = cli_option(
  "--new-node-certificates", dest="new_node_cert", default=False,
  action="store_true", help="Generate new node certificates (for all nodes)")

RAPI_CERT_OPT = cli_option("--rapi-certificate", dest="rapi_cert",
                           default=None,
                           help="File containing new RAPI certificate")

NEW_RAPI_CERT_OPT = cli_option("--new-rapi-certificate", dest="new_rapi_cert",
                               default=None, action="store_true",
                               help=("Generate a new self-signed RAPI"
                                     " certificate"))

SPICE_CERT_OPT = cli_option("--spice-certificate", dest="spice_cert",
                            default=None,
                            help="File containing new SPICE certificate")

SPICE_CACERT_OPT = cli_option("--spice-ca-certificate", dest="spice_cacert",
                              default=None,
                              help="File containing the certificate of the CA"
                              " which signed the SPICE certificate")

NEW_SPICE_CERT_OPT = cli_option("--new-spice-certificate",
                                dest="new_spice_cert", default=None,
                                action="store_true",
                                help=("Generate a new self-signed SPICE"
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

PRIMARY_IP_VERSION_OPT = \
    cli_option("--primary-ip-version", default=constants.IP4_VERSION,
               action="store", dest="primary_ip_version",
               metavar="%d|%d" % (constants.IP4_VERSION,
                                  constants.IP6_VERSION),
               help="Cluster-wide IP version for primary IP")

SHOW_MACHINE_OPT = cli_option("-M", "--show-machine-names", default=False,
                              action="store_true",
                              help="Show machine name for every line in output")

FAILURE_ONLY_OPT = cli_option("--failure-only", default=False,
                              action="store_true",
                              help=("Hide successful results and show failures"
                                    " only (determined by the exit code)"))

REASON_OPT = cli_option("--reason", default=None,
                        help="The reason for executing the command")


def _PriorityOptionCb(option, _, value, parser):
  """Callback for processing C{--priority} option.

  """
  value = _PRIONAME_TO_VALUE[value]

  setattr(parser.values, option.dest, value)


PRIORITY_OPT = cli_option("--priority", default=None, dest="priority",
                          metavar="|".join(name for name, _ in _PRIORITY_NAMES),
                          choices=_PRIONAME_TO_VALUE.keys(),
                          action="callback", type="choice",
                          callback=_PriorityOptionCb,
                          help="Priority for opcode processing")

HID_OS_OPT = cli_option("--hidden", dest="hidden",
                        type="bool", default=None, metavar=_YORNO,
                        help="Sets the hidden flag on the OS")

BLK_OS_OPT = cli_option("--blacklisted", dest="blacklisted",
                        type="bool", default=None, metavar=_YORNO,
                        help="Sets the blacklisted flag on the OS")

PREALLOC_WIPE_DISKS_OPT = cli_option("--prealloc-wipe-disks", default=None,
                                     type="bool", metavar=_YORNO,
                                     dest="prealloc_wipe_disks",
                                     help=("Wipe disks prior to instance"
                                           " creation"))

NODE_PARAMS_OPT = cli_option("--node-parameters", dest="ndparams",
                             type="keyval", default=None,
                             help="Node parameters")

ALLOC_POLICY_OPT = cli_option("--alloc-policy", dest="alloc_policy",
                              action="store", metavar="POLICY", default=None,
                              help="Allocation policy for the node group")

NODE_POWERED_OPT = cli_option("--node-powered", default=None,
                              type="bool", metavar=_YORNO,
                              dest="node_powered",
                              help="Specify if the SoR for node is powered")

OOB_TIMEOUT_OPT = cli_option("--oob-timeout", dest="oob_timeout", type="int",
                             default=constants.OOB_TIMEOUT,
                             help="Maximum time to wait for out-of-band helper")

POWER_DELAY_OPT = cli_option("--power-delay", dest="power_delay", type="float",
                             default=constants.OOB_POWER_DELAY,
                             help="Time in seconds to wait between power-ons")

FORCE_FILTER_OPT = cli_option("-F", "--filter", dest="force_filter",
                              action="store_true", default=False,
                              help=("Whether command argument should be treated"
                                    " as filter"))

NO_REMEMBER_OPT = cli_option("--no-remember",
                             dest="no_remember",
                             action="store_true", default=False,
                             help="Perform but do not record the change"
                             " in the configuration")

PRIMARY_ONLY_OPT = cli_option("-p", "--primary-only",
                              default=False, action="store_true",
                              help="Evacuate primary instances only")

SECONDARY_ONLY_OPT = cli_option("-s", "--secondary-only",
                                default=False, action="store_true",
                                help="Evacuate secondary instances only"
                                     " (applies only to internally mirrored"
                                     " disk templates, e.g. %s)" %
                                     utils.CommaJoin(constants.DTS_INT_MIRROR))

STARTUP_PAUSED_OPT = cli_option("--paused", dest="startup_paused",
                                action="store_true", default=False,
                                help="Pause instance at startup")

TO_GROUP_OPT = cli_option("--to", dest="to", metavar="<group>",
                          help="Destination node group (name or uuid)",
                          default=None, action="append",
                          completion_suggest=OPT_COMPL_ONE_NODEGROUP)

IGNORE_ERRORS_OPT = cli_option("-I", "--ignore-errors", default=[],
                               action="append", dest="ignore_errors",
                               choices=list(constants.CV_ALL_ECODES_STRINGS),
                               help="Error code to be ignored")

DISK_STATE_OPT = cli_option("--disk-state", default=[], dest="disk_state",
                            action="append",
                            help=("Specify disk state information in the"
                                  " format"
                                  " storage_type/identifier:option=value,...;"
                                  " note this is unused for now"),
                            type="identkeyval")

HV_STATE_OPT = cli_option("--hypervisor-state", default=[], dest="hv_state",
                          action="append",
                          help=("Specify hypervisor state information in the"
                                " format hypervisor:option=value,...;"
                                " note this is unused for now"),
                          type="identkeyval")

IGNORE_IPOLICY_OPT = cli_option("--ignore-ipolicy", dest="ignore_ipolicy",
                                action="store_true", default=False,
                                help="Ignore instance policy violations")

RUNTIME_MEM_OPT = cli_option("-m", "--runtime-memory", dest="runtime_mem",
                             help="Sets the instance's runtime memory,"
                             " ballooning it up or down to the new value",
                             default=None, type="unit", metavar="<size>")

ABSOLUTE_OPT = cli_option("--absolute", dest="absolute",
                          action="store_true", default=False,
                          help="Marks the grow as absolute instead of the"
                          " (default) relative mode")

NETWORK_OPT = cli_option("--network",
                         action="store", default=None, dest="network",
                         help="IP network in CIDR notation")

GATEWAY_OPT = cli_option("--gateway",
                         action="store", default=None, dest="gateway",
                         help="IP address of the router (gateway)")

ADD_RESERVED_IPS_OPT = cli_option("--add-reserved-ips",
                                  action="store", default=None,
                                  dest="add_reserved_ips",
                                  help="Comma-separated list of"
                                  " reserved IPs to add")

REMOVE_RESERVED_IPS_OPT = cli_option("--remove-reserved-ips",
                                     action="store", default=None,
                                     dest="remove_reserved_ips",
                                     help="Comma-delimited list of"
                                     " reserved IPs to remove")

NETWORK6_OPT = cli_option("--network6",
                          action="store", default=None, dest="network6",
                          help="IP network in CIDR notation")

GATEWAY6_OPT = cli_option("--gateway6",
                          action="store", default=None, dest="gateway6",
                          help="IP6 address of the router (gateway)")

NOCONFLICTSCHECK_OPT = cli_option("--no-conflicts-check",
                                  dest="conflicts_check",
                                  default=True,
                                  action="store_false",
                                  help="Don't check for conflicting IPs")

INCLUDEDEFAULTS_OPT = cli_option("--include-defaults", dest="include_defaults",
                                 default=False, action="store_true",
                                 help="Include default values")

HOTPLUG_OPT = cli_option("--hotplug", dest="hotplug",
                         action="store_true", default=False,
                         help="Hotplug supported devices (NICs and Disks)")

HOTPLUG_IF_POSSIBLE_OPT = cli_option("--hotplug-if-possible",
                                     dest="hotplug_if_possible",
                                     action="store_true", default=False,
                                     help="Hotplug devices in case"
                                          " hotplug is supported")

INSTANCE_COMMUNICATION_OPT = \
    cli_option("-c", "--communication",
               default=False,
               dest="instance_communication",
               help=constants.INSTANCE_COMMUNICATION_DOC,
               type="bool")

#: Options provided by all commands
COMMON_OPTS = [DEBUG_OPT, REASON_OPT]

# options related to asynchronous job handling

SUBMIT_OPTS = [
  SUBMIT_OPT,
  PRINT_JOBID_OPT,
  ]

# common options for creating instances. add and import then add their own
# specific ones.
COMMON_CREATE_OPTS = [
  BACKEND_OPT,
  DISK_OPT,
  DISK_TEMPLATE_OPT,
  FILESTORE_DIR_OPT,
  FILESTORE_DRIVER_OPT,
  HYPERVISOR_OPT,
  IALLOCATOR_OPT,
  NET_OPT,
  NODE_PLACEMENT_OPT,
  NOIPCHECK_OPT,
  NOCONFLICTSCHECK_OPT,
  NONAMECHECK_OPT,
  NONICS_OPT,
  NWSYNC_OPT,
  OSPARAMS_OPT,
  OS_SIZE_OPT,
  SUBMIT_OPT,
  PRINT_JOBID_OPT,
  TAG_ADD_OPT,
  DRY_RUN_OPT,
  PRIORITY_OPT,
  ]

# common instance policy options
INSTANCE_POLICY_OPTS = [
  IPOLICY_BOUNDS_SPECS_OPT,
  IPOLICY_DISK_TEMPLATES,
  IPOLICY_VCPU_RATIO,
  IPOLICY_SPINDLE_RATIO,
  ]

# instance policy split specs options
SPLIT_ISPECS_OPTS = [
  SPECS_CPU_COUNT_OPT,
  SPECS_DISK_COUNT_OPT,
  SPECS_DISK_SIZE_OPT,
  SPECS_MEM_SIZE_OPT,
  SPECS_NIC_COUNT_OPT,
  ]


class _ShowUsage(Exception):
  """Exception class for L{_ParseArgs}.

  """
  def __init__(self, exit_error):
    """Initializes instances of this class.

    @type exit_error: bool
    @param exit_error: Whether to report failure on exit

    """
    Exception.__init__(self)
    self.exit_error = exit_error


class _ShowVersion(Exception):
  """Exception class for L{_ParseArgs}.

  """


def _ParseArgs(binary, argv, commands, aliases, env_override):
  """Parser for the command line arguments.

  This function parses the arguments and returns the function which
  must be executed together with its (modified) arguments.

  @param binary: Script name
  @param argv: Command line arguments
  @param commands: Dictionary containing command definitions
  @param aliases: dictionary with command aliases {"alias": "target", ...}
  @param env_override: list of env variables allowed for default args
  @raise _ShowUsage: If usage description should be shown
  @raise _ShowVersion: If version should be shown

  """
  assert not (env_override - set(commands))
  assert not (set(aliases.keys()) & set(commands.keys()))

  if len(argv) > 1:
    cmd = argv[1]
  else:
    # No option or command given
    raise _ShowUsage(exit_error=True)

  if cmd == "--version":
    raise _ShowVersion()
  elif cmd == "--help":
    raise _ShowUsage(exit_error=False)
  elif not (cmd in commands or cmd in aliases):
    raise _ShowUsage(exit_error=True)

  # get command, unalias it, and look it up in commands
  if cmd in aliases:
    if aliases[cmd] not in commands:
      raise errors.ProgrammerError("Alias '%s' maps to non-existing"
                                   " command '%s'" % (cmd, aliases[cmd]))

    cmd = aliases[cmd]

  if cmd in env_override:
    args_env_name = ("%s_%s" % (binary.replace("-", "_"), cmd)).upper()
    env_args = os.environ.get(args_env_name)
    if env_args:
      argv = utils.InsertAtPos(argv, 2, shlex.split(env_args))

  func, args_def, parser_opts, usage, description = commands[cmd]
  parser = OptionParser(option_list=parser_opts + COMMON_OPTS,
                        description=description,
                        formatter=TitledHelpFormatter(),
                        usage="%%prog %s %s" % (cmd, usage))
  parser.disable_interspersed_args()
  options, args = parser.parse_args(args=argv[2:])

  if not _CheckArguments(cmd, args_def, args):
    return None, None, None

  return func, options, args


def _FormatUsage(binary, commands):
  """Generates a nice description of all commands.

  @param binary: Script name
  @param commands: Dictionary containing command definitions

  """
  # compute the max line length for cmd + usage
  mlen = min(60, max(map(len, commands)))

  yield "Usage: %s {command} [options...] [argument...]" % binary
  yield "%s <command> --help to see details, or man %s" % (binary, binary)
  yield ""
  yield "Commands:"

  # and format a nice command list
  for (cmd, (_, _, _, _, help_text)) in sorted(commands.items()):
    help_lines = textwrap.wrap(help_text, 79 - 3 - mlen)
    yield " %-*s - %s" % (mlen, cmd, help_lines.pop(0))
    for line in help_lines:
      yield " %-*s   %s" % (mlen, "", line)

  yield ""


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
  if value and ":" in value:
    return value.split(":", 1)
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
    return ["%s+%s" % (os_name, v) for v in os_variants]
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
    choices = [("y", True, "Perform the operation"),
               ("n", False, "Do not perform the operation")]
  if not choices or not isinstance(choices, list):
    raise errors.ProgrammerError("Invalid choices argument to AskUser")
  for entry in choices:
    if not isinstance(entry, tuple) or len(entry) < 3 or entry[0] == "?":
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
    chars.append("?")
    maps = dict([(entry[0], entry[1]) for entry in choices])
    while True:
      f.write(text)
      f.write("\n")
      f.write("/".join(chars))
      f.write(": ")
      line = f.readline(2).strip().lower()
      if line in maps:
        answer = maps[line]
        break
      elif line == "?":
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

    elif status == constants.JOB_STATUS_WAITING and not self.notified_waitlock:
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
  if hasattr(opts, "print_jobid") and opts.print_jobid:
    ToStdout("%d" % job_id)

  op_results = PollJob(job_id, cl=cl, feedback_fn=feedback_fn,
                       reporter=reporter)

  return op_results[0]


def SubmitOpCodeToDrainedQueue(op):
  """Forcefully insert a job in the queue, even if it is drained.

  """
  cl = GetClient()
  job_id = cl.SubmitJobToDrainedQueue([op])
  op_results = PollJob(job_id, cl=cl)
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
    if opts.print_jobid:
      ToStdout("%d" % job_id)
    raise JobSubmittedException(job_id)
  else:
    return SubmitOpCode(op, cl=cl, feedback_fn=feedback_fn, opts=opts)


def _InitReasonTrail(op, opts):
  """Builds the first part of the reason trail

  Builds the initial part of the reason trail, adding the user provided reason
  (if it exists) and the name of the command starting the operation.

  @param op: the opcode the reason trail will be added to
  @param opts: the command line options selected by the user

  """
  assert len(sys.argv) >= 2
  trail = []

  if opts.reason:
    trail.append((constants.OPCODE_REASON_SRC_USER,
                  opts.reason,
                  utils.EpochNano()))

  binary = os.path.basename(sys.argv[0])
  source = "%s:%s" % (constants.OPCODE_REASON_SRC_CLIENT, binary)
  command = sys.argv[1]
  trail.append((source, command, utils.EpochNano()))
  op.reason = trail


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
      op.priority = options.priority
    _InitReasonTrail(op, options)


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
  elif isinstance(err, rpcerr.NoMasterError):
    if err.args[0] == pathutils.MASTER_SOCKET:
      daemon = "the master daemon"
    elif err.args[0] == pathutils.QUERY_SOCKET:
      daemon = "the config daemon"
    else:
      daemon = "socket '%s'" % str(err.args[0])
    obuf.write("Cannot communicate with %s.\nIs the process running"
               " and listening for connections?" % daemon)
  elif isinstance(err, rpcerr.TimeoutError):
    obuf.write("Timeout while talking to the master daemon. Jobs might have"
               " been submitted and will continue to run even if the call"
               " timed out. Useful commands in this situation are \"gnt-job"
               " list\", \"gnt-job cancel\" and \"gnt-job watch\". Error:\n")
    obuf.write(msg)
  elif isinstance(err, rpcerr.PermissionError):
    obuf.write("It seems you don't have permissions to connect to the"
               " master daemon.\nPlease retry as a different user.")
  elif isinstance(err, rpcerr.ProtocolError):
    obuf.write("Unhandled protocol error while talking to the master daemon:\n"
               "%s" % msg)
  elif isinstance(err, errors.JobLost):
    obuf.write("Error checking job status: %s" % msg)
  elif isinstance(err, errors.QueryFilterParseError):
    obuf.write("Error while parsing query filter: %s\n" % err.args[0])
    obuf.write("\n".join(err.GetDetails()))
  elif isinstance(err, errors.GenericError):
    obuf.write("Unhandled Ganeti error: %s" % msg)
  elif isinstance(err, JobSubmittedException):
    obuf.write("JobID: %s\n" % err.args[0])
    retcode = 0
  else:
    obuf.write("Unhandled exception: %s" % msg)
  return retcode, obuf.getvalue().rstrip("\n")


def GenericMain(commands, override=None, aliases=None,
                env_override=frozenset()):
  """Generic main function for all the gnt-* commands.

  @param commands: a dictionary with a special structure, see the design doc
                   for command line handling.
  @param override: if not None, we expect a dictionary with keys that will
                   override command line options; this can be used to pass
                   options from the scripts to generic functions
  @param aliases: dictionary with command aliases {'alias': 'target, ...}
  @param env_override: list of environment names which are allowed to submit
                       default args for commands

  """
  # save the program name and the entire command line for later logging
  if sys.argv:
    binary = os.path.basename(sys.argv[0])
    if not binary:
      binary = sys.argv[0]

    if len(sys.argv) >= 2:
      logname = utils.ShellQuoteArgs([binary, sys.argv[1]])
    else:
      logname = binary

    cmdline = utils.ShellQuoteArgs([binary] + sys.argv[1:])
  else:
    binary = "<unknown program>"
    cmdline = "<unknown>"

  if aliases is None:
    aliases = {}

  try:
    (func, options, args) = _ParseArgs(binary, sys.argv, commands, aliases,
                                       env_override)
  except _ShowVersion:
    ToStdout("%s (ganeti %s) %s", binary, constants.VCS_VERSION,
             constants.RELEASE_VERSION)
    return constants.EXIT_SUCCESS
  except _ShowUsage, err:
    for line in _FormatUsage(binary, commands):
      ToStdout(line)

    if err.exit_error:
      return constants.EXIT_FAILURE
    else:
      return constants.EXIT_SUCCESS
  except errors.ParameterError, err:
    result, err_msg = FormatError(err)
    ToStderr(err_msg)
    return 1

  if func is None: # parse error
    return 1

  if override is not None:
    for key, val in override.iteritems():
      setattr(options, key, val)

  utils.SetupLogging(pathutils.LOG_COMMANDS, logname, debug=options.debug,
                     stderr_logging=True)

  logging.debug("Command line: %s", cmdline)

  try:
    result = func(options, args)
  except (errors.GenericError, rpcerr.ProtocolError,
          JobSubmittedException), err:
    result, err_msg = FormatError(err)
    logging.exception("Error during command processing")
    ToStderr(err_msg)
  except KeyboardInterrupt:
    result = constants.EXIT_FAILURE
    ToStderr("Aborted. Note that if the operation created any jobs, they"
             " might have been submitted and"
             " will continue to run in the background.")
  except IOError, err:
    if err.errno == errno.EPIPE:
      # our terminal went away, we'll exit
      sys.exit(constants.EXIT_FAILURE)
    else:
      raise

  return result


def ParseNicOption(optvalue):
  """Parses the value of the --net option(s).

  """
  try:
    nic_max = max(int(nidx[0]) + 1 for nidx in optvalue)
  except (TypeError, ValueError), err:
    raise errors.OpPrereqError("Invalid NIC index passed: %s" % str(err),
                               errors.ECODE_INVAL)

  nics = [{}] * nic_max
  for nidx, ndict in optvalue:
    nidx = int(nidx)

    if not isinstance(ndict, dict):
      raise errors.OpPrereqError("Invalid nic/%d value: expected dict,"
                                 " got %s" % (nidx, ndict), errors.ECODE_INVAL)

    utils.ForceDictType(ndict, constants.INIC_PARAMS_TYPES)

    nics[nidx] = ndict

  return nics


def FixHvParams(hvparams):
  # In Ganeti 2.8.4 the separator for the usb_devices hvparam was changed from
  # comma to space because commas cannot be accepted on the command line
  # (they already act as the separator between different hvparams). Still,
  # RAPI should be able to accept commas for backwards compatibility.
  # Therefore, we convert spaces into commas here, and we keep the old
  # parsing logic everywhere else.
  try:
    new_usb_devices = hvparams[constants.HV_USB_DEVICES].replace(" ", ",")
    hvparams[constants.HV_USB_DEVICES] = new_usb_devices
  except KeyError:
    #No usb_devices, no modification required
    pass


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
                                 " information passed", errors.ECODE_INVAL)
    disks = []
  else:
    if (not opts.disks and not opts.sd_size
        and mode == constants.INSTANCE_CREATE):
      raise errors.OpPrereqError("No disk information specified",
                                 errors.ECODE_INVAL)
    if opts.disks and opts.sd_size is not None:
      raise errors.OpPrereqError("Please use either the '--disk' or"
                                 " '-s' option", errors.ECODE_INVAL)
    if opts.sd_size is not None:
      opts.disks = [(0, {constants.IDISK_SIZE: opts.sd_size})]

    if opts.disks:
      try:
        disk_max = max(int(didx[0]) + 1 for didx in opts.disks)
      except ValueError, err:
        raise errors.OpPrereqError("Invalid disk index passed: %s" % str(err),
                                   errors.ECODE_INVAL)
      disks = [{}] * disk_max
    else:
      disks = []
    for didx, ddict in opts.disks:
      didx = int(didx)
      if not isinstance(ddict, dict):
        msg = "Invalid disk/%d value: expected dict, got %s" % (didx, ddict)
        raise errors.OpPrereqError(msg, errors.ECODE_INVAL)
      elif constants.IDISK_SIZE in ddict:
        if constants.IDISK_ADOPT in ddict:
          raise errors.OpPrereqError("Only one of 'size' and 'adopt' allowed"
                                     " (disk %d)" % didx, errors.ECODE_INVAL)
        try:
          ddict[constants.IDISK_SIZE] = \
            utils.ParseUnit(ddict[constants.IDISK_SIZE])
        except ValueError, err:
          raise errors.OpPrereqError("Invalid disk size for disk %d: %s" %
                                     (didx, err), errors.ECODE_INVAL)
      elif constants.IDISK_ADOPT in ddict:
        if constants.IDISK_SPINDLES in ddict:
          raise errors.OpPrereqError("spindles is not a valid option when"
                                     " adopting a disk", errors.ECODE_INVAL)
        if mode == constants.INSTANCE_IMPORT:
          raise errors.OpPrereqError("Disk adoption not allowed for instance"
                                     " import", errors.ECODE_INVAL)
        ddict[constants.IDISK_SIZE] = 0
      else:
        raise errors.OpPrereqError("Missing size or adoption source for"
                                   " disk %d" % didx, errors.ECODE_INVAL)
      if constants.IDISK_SPINDLES in ddict:
        ddict[constants.IDISK_SPINDLES] = int(ddict[constants.IDISK_SPINDLES])

      disks[didx] = ddict

  if opts.tags is not None:
    tags = opts.tags.split(",")
  else:
    tags = []

  utils.ForceDictType(opts.beparams, constants.BES_PARAMETER_COMPAT)
  utils.ForceDictType(hvparams, constants.HVS_PARAMETER_TYPES)
  FixHvParams(hvparams)

  if mode == constants.INSTANCE_CREATE:
    start = opts.start
    os_type = opts.os
    force_variant = opts.force_variant
    src_node = None
    src_path = None
    no_install = opts.no_install
    identify_defaults = False
    compress = constants.IEC_NONE
    instance_communication = opts.instance_communication
  elif mode == constants.INSTANCE_IMPORT:
    start = False
    os_type = None
    force_variant = False
    src_node = opts.src_node
    src_path = opts.src_dir
    no_install = None
    identify_defaults = opts.identify_defaults
    compress = opts.compress
    instance_communication = False
  else:
    raise errors.ProgrammerError("Invalid creation mode %s" % mode)

  op = opcodes.OpInstanceCreate(instance_name=instance,
                                disks=disks,
                                disk_template=opts.disk_template,
                                nics=nics,
                                conflicts_check=opts.conflicts_check,
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
                                osparams_private=opts.osparams_private,
                                osparams_secret=opts.osparams_secret,
                                mode=mode,
                                start=start,
                                os_type=os_type,
                                force_variant=force_variant,
                                src_node=src_node,
                                src_path=src_path,
                                compress=compress,
                                tags=tags,
                                no_install=no_install,
                                identify_defaults=identify_defaults,
                                ignore_ipolicy=opts.ignore_ipolicy,
                                instance_communication=instance_communication)

  SubmitOrSend(op, opts)
  return 0


class _RunWhileClusterStoppedHelper:
  """Helper class for L{RunWhileClusterStopped} to simplify state management

  """
  def __init__(self, feedback_fn, cluster_name, master_node,
               online_nodes, ssh_ports):
    """Initializes this class.

    @type feedback_fn: callable
    @param feedback_fn: Feedback function
    @type cluster_name: string
    @param cluster_name: Cluster name
    @type master_node: string
    @param master_node Master node name
    @type online_nodes: list
    @param online_nodes: List of names of online nodes
    @type ssh_ports: list
    @param ssh_ports: List of SSH ports of online nodes

    """
    self.feedback_fn = feedback_fn
    self.cluster_name = cluster_name
    self.master_node = master_node
    self.online_nodes = online_nodes
    self.ssh_ports = dict(zip(online_nodes, ssh_ports))

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
      result = self.ssh.Run(node_name, constants.SSH_LOGIN_USER,
                            utils.ShellQuoteArgs(cmd),
                            port=self.ssh_ports[node_name])

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
    watcher_block = utils.FileLock.Open(pathutils.WATCHER_LOCK_FILE)
    try:
      # TODO: Currently, this just blocks. There's no timeout.
      # TODO: Should it be a shared lock?
      watcher_block.Exclusive(blocking=True)

      # Stop master daemons, so that no new jobs can come in and all running
      # ones are finished
      self.feedback_fn("Stopping master daemons")
      self._RunCmd(None, [pathutils.DAEMON_UTIL, "stop-master"])
      try:
        # Stop daemons on all nodes
        for node_name in self.online_nodes:
          self.feedback_fn("Stopping daemons on %s" % node_name)
          self._RunCmd(node_name, [pathutils.DAEMON_UTIL, "stop-all"])

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
          self._RunCmd(node_name, [pathutils.DAEMON_UTIL, "start-all"])
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
  # Query client
  qcl = GetClient(query=True)

  (cluster_name, master_node) = \
    cl.QueryConfigValues(["cluster_name", "master_node"])

  online_nodes = GetOnlineNodes([], cl=qcl)
  ssh_ports = GetNodesSshPorts(online_nodes, qcl)

  # Don't keep a reference to the client. The master daemon will go away.
  del cl
  del qcl

  assert master_node in online_nodes

  return _RunWhileClusterStoppedHelper(feedback_fn, cluster_name, master_node,
                                       online_nodes, ssh_ports).Call(fn, *args)


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

  numfields = utils.FieldSet(*numfields)   # pylint: disable=W0142
  unitfields = utils.FieldSet(*unitfields) # pylint: disable=W0142

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
    format_str = " ".join(format_fields)
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
      line = ["-" for _ in fields]
    for idx in range(len(fields)):
      if separator is None:
        args.append(mlens[idx])
      args.append(line[idx])
    result.append(format_str % tuple(args))

  return result


def _FormatBool(value):
  """Formats a boolean value as a string.

  """
  if value:
    return "Y"
  return "N"


#: Default formatting for query results; (callback, align right)
_DEFAULT_FORMAT_QUERY = {
  constants.QFT_TEXT: (str, False),
  constants.QFT_BOOL: (_FormatBool, False),
  constants.QFT_NUMBER: (str, True),
  constants.QFT_TIMESTAMP: (utils.FormatTime, False),
  constants.QFT_OTHER: (str, False),
  constants.QFT_UNKNOWN: (str, False),
  }


def _GetColumnFormatter(fdef, override, unit):
  """Returns formatting function for a field.

  @type fdef: L{objects.QueryFieldDefinition}
  @type override: dict
  @param override: Dictionary for overriding field formatting functions,
    indexed by field name, contents like L{_DEFAULT_FORMAT_QUERY}
  @type unit: string
  @param unit: Unit used for formatting fields of type L{constants.QFT_UNIT}
  @rtype: tuple; (callable, bool)
  @return: Returns the function to format a value (takes one parameter) and a
    boolean for aligning the value on the right-hand side

  """
  fmt = override.get(fdef.name, None)
  if fmt is not None:
    return fmt

  assert constants.QFT_UNIT not in _DEFAULT_FORMAT_QUERY

  if fdef.kind == constants.QFT_UNIT:
    # Can't keep this information in the static dictionary
    return (lambda value: utils.FormatUnit(value, unit), True)

  fmt = _DEFAULT_FORMAT_QUERY.get(fdef.kind, None)
  if fmt is not None:
    return fmt

  raise NotImplementedError("Can't format column type '%s'" % fdef.kind)


class _QueryColumnFormatter:
  """Callable class for formatting fields of a query.

  """
  def __init__(self, fn, status_fn, verbose):
    """Initializes this class.

    @type fn: callable
    @param fn: Formatting function
    @type status_fn: callable
    @param status_fn: Function to report fields' status
    @type verbose: boolean
    @param verbose: whether to use verbose field descriptions or not

    """
    self._fn = fn
    self._status_fn = status_fn
    self._verbose = verbose

  def __call__(self, data):
    """Returns a field's string representation.

    """
    (status, value) = data

    # Report status
    self._status_fn(status)

    if status == constants.RS_NORMAL:
      return self._fn(value)

    assert value is None, \
           "Found value %r for abnormal status %s" % (value, status)

    return FormatResultError(status, self._verbose)


def FormatResultError(status, verbose):
  """Formats result status other than L{constants.RS_NORMAL}.

  @param status: The result status
  @type verbose: boolean
  @param verbose: Whether to return the verbose text
  @return: Text of result status

  """
  assert status != constants.RS_NORMAL, \
         "FormatResultError called with status equal to constants.RS_NORMAL"
  try:
    (verbose_text, normal_text) = constants.RSS_DESCRIPTION[status]
  except KeyError:
    raise NotImplementedError("Unknown status %s" % status)
  else:
    if verbose:
      return verbose_text
    return normal_text


def FormatQueryResult(result, unit=None, format_override=None, separator=None,
                      header=False, verbose=False):
  """Formats data in L{objects.QueryResponse}.

  @type result: L{objects.QueryResponse}
  @param result: result of query operation
  @type unit: string
  @param unit: Unit used for formatting fields of type L{constants.QFT_UNIT},
    see L{utils.text.FormatUnit}
  @type format_override: dict
  @param format_override: Dictionary for overriding field formatting functions,
    indexed by field name, contents like L{_DEFAULT_FORMAT_QUERY}
  @type separator: string or None
  @param separator: String used to separate fields
  @type header: bool
  @param header: Whether to output header row
  @type verbose: boolean
  @param verbose: whether to use verbose field descriptions or not

  """
  if unit is None:
    if separator:
      unit = "m"
    else:
      unit = "h"

  if format_override is None:
    format_override = {}

  stats = dict.fromkeys(constants.RS_ALL, 0)

  def _RecordStatus(status):
    if status in stats:
      stats[status] += 1

  columns = []
  for fdef in result.fields:
    assert fdef.title and fdef.name
    (fn, align_right) = _GetColumnFormatter(fdef, format_override, unit)
    columns.append(TableColumn(fdef.title,
                               _QueryColumnFormatter(fn, _RecordStatus,
                                                     verbose),
                               align_right))

  table = FormatTable(result.data, columns, header, separator)

  # Collect statistics
  assert len(stats) == len(constants.RS_ALL)
  assert compat.all(count >= 0 for count in stats.values())

  # Determine overall status. If there was no data, unknown fields must be
  # detected via the field definitions.
  if (stats[constants.RS_UNKNOWN] or
      (not result.data and _GetUnknownFields(result.fields))):
    status = QR_UNKNOWN
  elif compat.any(count > 0 for key, count in stats.items()
                  if key != constants.RS_NORMAL):
    status = QR_INCOMPLETE
  else:
    status = QR_NORMAL

  return (status, table)


def _GetUnknownFields(fdefs):
  """Returns list of unknown fields included in C{fdefs}.

  @type fdefs: list of L{objects.QueryFieldDefinition}

  """
  return [fdef for fdef in fdefs
          if fdef.kind == constants.QFT_UNKNOWN]


def _WarnUnknownFields(fdefs):
  """Prints a warning to stderr if a query included unknown fields.

  @type fdefs: list of L{objects.QueryFieldDefinition}

  """
  unknown = _GetUnknownFields(fdefs)
  if unknown:
    ToStderr("Warning: Queried for unknown fields %s",
             utils.CommaJoin(fdef.name for fdef in unknown))
    return True

  return False


def GenericList(resource, fields, names, unit, separator, header, cl=None,
                format_override=None, verbose=False, force_filter=False,
                namefield=None, qfilter=None, isnumeric=False):
  """Generic implementation for listing all items of a resource.

  @param resource: One of L{constants.QR_VIA_LUXI}
  @type fields: list of strings
  @param fields: List of fields to query for
  @type names: list of strings
  @param names: Names of items to query for
  @type unit: string or None
  @param unit: Unit used for formatting fields of type L{constants.QFT_UNIT} or
    None for automatic choice (human-readable for non-separator usage,
    otherwise megabytes); this is a one-letter string
  @type separator: string or None
  @param separator: String used to separate fields
  @type header: bool
  @param header: Whether to show header row
  @type force_filter: bool
  @param force_filter: Whether to always treat names as filter
  @type format_override: dict
  @param format_override: Dictionary for overriding field formatting functions,
    indexed by field name, contents like L{_DEFAULT_FORMAT_QUERY}
  @type verbose: boolean
  @param verbose: whether to use verbose field descriptions or not
  @type namefield: string
  @param namefield: Name of field to use for simple filters (see
    L{qlang.MakeFilter} for details)
  @type qfilter: list or None
  @param qfilter: Query filter (in addition to names)
  @param isnumeric: bool
  @param isnumeric: Whether the namefield's type is numeric, and therefore
    any simple filters built by namefield should use integer values to
    reflect that

  """
  if not names:
    names = None

  namefilter = qlang.MakeFilter(names, force_filter, namefield=namefield,
                                isnumeric=isnumeric)

  if qfilter is None:
    qfilter = namefilter
  elif namefilter is not None:
    qfilter = [qlang.OP_AND, namefilter, qfilter]

  if cl is None:
    cl = GetClient()

  response = cl.Query(resource, fields, qfilter)

  found_unknown = _WarnUnknownFields(response.fields)

  (status, data) = FormatQueryResult(response, unit=unit, separator=separator,
                                     header=header,
                                     format_override=format_override,
                                     verbose=verbose)

  for line in data:
    ToStdout(line)

  assert ((found_unknown and status == QR_UNKNOWN) or
          (not found_unknown and status != QR_UNKNOWN))

  if status == QR_UNKNOWN:
    return constants.EXIT_UNKNOWN_FIELD

  # TODO: Should the list command fail if not all data could be collected?
  return constants.EXIT_SUCCESS


def _FieldDescValues(fdef):
  """Helper function for L{GenericListFields} to get query field description.

  @type fdef: L{objects.QueryFieldDefinition}
  @rtype: list

  """
  return [
    fdef.name,
    _QFT_NAMES.get(fdef.kind, fdef.kind),
    fdef.title,
    fdef.doc,
    ]


def GenericListFields(resource, fields, separator, header, cl=None):
  """Generic implementation for listing fields for a resource.

  @param resource: One of L{constants.QR_VIA_LUXI}
  @type fields: list of strings
  @param fields: List of fields to query for
  @type separator: string or None
  @param separator: String used to separate fields
  @type header: bool
  @param header: Whether to show header row

  """
  if cl is None:
    cl = GetClient()

  if not fields:
    fields = None

  response = cl.QueryFields(resource, fields)

  found_unknown = _WarnUnknownFields(response.fields)

  columns = [
    TableColumn("Name", str, False),
    TableColumn("Type", str, False),
    TableColumn("Title", str, False),
    TableColumn("Description", str, False),
    ]

  rows = map(_FieldDescValues, response.fields)

  for line in FormatTable(rows, columns, header, separator):
    ToStdout(line)

  if found_unknown:
    return constants.EXIT_UNKNOWN_FIELD

  return constants.EXIT_SUCCESS


class TableColumn:
  """Describes a column for L{FormatTable}.

  """
  def __init__(self, title, fn, align_right):
    """Initializes this class.

    @type title: string
    @param title: Column title
    @type fn: callable
    @param fn: Formatting function
    @type align_right: bool
    @param align_right: Whether to align values on the right-hand side

    """
    self.title = title
    self.format = fn
    self.align_right = align_right


def _GetColFormatString(width, align_right):
  """Returns the format string for a field.

  """
  if align_right:
    sign = ""
  else:
    sign = "-"

  return "%%%s%ss" % (sign, width)


def FormatTable(rows, columns, header, separator):
  """Formats data as a table.

  @type rows: list of lists
  @param rows: Row data, one list per row
  @type columns: list of L{TableColumn}
  @param columns: Column descriptions
  @type header: bool
  @param header: Whether to show header row
  @type separator: string or None
  @param separator: String used to separate columns

  """
  if header:
    data = [[col.title for col in columns]]
    colwidth = [len(col.title) for col in columns]
  else:
    data = []
    colwidth = [0 for _ in columns]

  # Format row data
  for row in rows:
    assert len(row) == len(columns)

    formatted = [col.format(value) for value, col in zip(row, columns)]

    if separator is None:
      # Update column widths
      for idx, (oldwidth, value) in enumerate(zip(colwidth, formatted)):
        # Modifying a list's items while iterating is fine
        colwidth[idx] = max(oldwidth, len(value))

    data.append(formatted)

  if separator is not None:
    # Return early if a separator is used
    return [separator.join(row) for row in data]

  if columns and not columns[-1].align_right:
    # Avoid unnecessary spaces at end of line
    colwidth[-1] = 0

  # Build format string
  fmt = " ".join([_GetColFormatString(width, col.align_right)
                  for col, width in zip(columns, colwidth)])

  return [fmt % tuple(row) for row in data]


def FormatTimestamp(ts):
  """Formats a given timestamp.

  @type ts: timestamp
  @param ts: a timeval-type timestamp, a tuple of seconds and microseconds

  @rtype: string
  @return: a string with the formatted timestamp

  """
  if not isinstance(ts, (tuple, list)) or len(ts) != 2:
    return "?"

  (sec, usecs) = ts
  return utils.FormatTime(sec, usecs=usecs)


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
    raise errors.OpPrereqError("Empty time specification passed",
                               errors.ECODE_INVAL)
  suffix_map = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    }
  if value[-1] not in suffix_map:
    try:
      value = int(value)
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid time specification '%s'" % value,
                                 errors.ECODE_INVAL)
  else:
    multiplier = suffix_map[value[-1]]
    value = value[:-1]
    if not value: # no data left after stripping the suffix
      raise errors.OpPrereqError("Invalid time specification (only"
                                 " suffix passed)", errors.ECODE_INVAL)
    try:
      value = int(value) * multiplier
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid time specification '%s'" % value,
                                 errors.ECODE_INVAL)
  return value


def GetOnlineNodes(nodes, cl=None, nowarn=False, secondary_ips=False,
                   filter_master=False, nodegroup=None):
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
  @type nodegroup: string
  @param nodegroup: If set, only return nodes in this node group

  """
  if cl is None:
    cl = GetClient(query=True)

  qfilter = []

  if nodes:
    qfilter.append(qlang.MakeSimpleFilter("name", nodes))

  if nodegroup is not None:
    qfilter.append([qlang.OP_OR, [qlang.OP_EQUAL, "group", nodegroup],
                                 [qlang.OP_EQUAL, "group.uuid", nodegroup]])

  if filter_master:
    qfilter.append([qlang.OP_NOT, [qlang.OP_TRUE, "master"]])

  if qfilter:
    if len(qfilter) > 1:
      final_filter = [qlang.OP_AND] + qfilter
    else:
      assert len(qfilter) == 1
      final_filter = qfilter[0]
  else:
    final_filter = None

  result = cl.Query(constants.QR_NODE, ["name", "offline", "sip"], final_filter)

  def _IsOffline(row):
    (_, (_, offline), _) = row
    return offline

  def _GetName(row):
    ((_, name), _, _) = row
    return name

  def _GetSip(row):
    (_, _, (_, sip)) = row
    return sip

  (offline, online) = compat.partition(result.data, _IsOffline)

  if offline and not nowarn:
    ToStderr("Note: skipping offline node(s): %s" %
             utils.CommaJoin(map(_GetName, offline)))

  if secondary_ips:
    fn = _GetSip
  else:
    fn = _GetName

  return map(fn, online)


def GetNodesSshPorts(nodes, cl):
  """Retrieves SSH ports of given nodes.

  @param nodes: the names of nodes
  @type nodes: a list of strings
  @param cl: a client to use for the query
  @type cl: L{Client}
  @return: the list of SSH ports corresponding to the nodes
  @rtype: a list of tuples
  """
  return map(lambda t: t[0],
             cl.QueryNodes(names=nodes,
                           fields=["ndp/ssh_port"],
                           use_locking=False))


def _ToStream(stream, txt, *args):
  """Write a message to a stream, bypassing the logging system

  @type stream: file object
  @param stream: the file to which we should write
  @type txt: str
  @param txt: the message

  """
  try:
    if args:
      args = tuple(args)
      stream.write(txt % args)
    else:
      stream.write(txt)
    stream.write("\n")
    stream.flush()
  except IOError, err:
    if err.errno == errno.EPIPE:
      # our terminal went away, we'll exit
      sys.exit(constants.EXIT_FAILURE)
    else:
      raise


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
    self._counter = itertools.count()

  @staticmethod
  def _IfName(name, fmt):
    """Helper function for formatting name.

    """
    if name:
      return fmt % name

    return ""

  def QueueJob(self, name, *ops):
    """Record a job for later submit.

    @type name: string
    @param name: a description of the job, will be used in WaitJobSet

    """
    SetGenericOpcodeOpts(ops, self.opts)
    self.queue.append((self._counter.next(), name, ops))

  def AddJobId(self, name, status, job_id):
    """Adds a job ID to the internal queue.

    """
    self.jobs.append((self._counter.next(), status, job_id, name))

  def SubmitPending(self, each=False):
    """Submit all pending jobs.

    """
    if each:
      results = []
      for (_, _, ops) in self.queue:
        # SubmitJob will remove the success status, but raise an exception if
        # the submission fails, so we'll notice that anyway.
        results.append([True, self.cl.SubmitJob(ops)[0]])
    else:
      results = self.cl.SubmitManyJobs([ops for (_, _, ops) in self.queue])
    for ((status, data), (idx, name, _)) in zip(results, self.queue):
      self.jobs.append((idx, status, data, name))

  def _ChooseJob(self):
    """Choose a non-waiting/queued job to poll next.

    """
    assert self.jobs, "_ChooseJob called with empty job list"

    result = self.cl.QueryJobs([i[2] for i in self.jobs[:_CHOOSE_BATCH]],
                               ["status"])
    assert result

    for job_data, status in zip(self.jobs, result):
      if (isinstance(status, list) and status and
          status[0] in (constants.JOB_STATUS_QUEUED,
                        constants.JOB_STATUS_WAITING,
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
      ToStderr("Failed to submit job%s: %s", self._IfName(name, " for %s"), jid)
      results.append((idx, False, jid))

    while self.jobs:
      (idx, _, jid, name) = self._ChooseJob()
      ToStdout("Waiting for job %s%s ...", jid, self._IfName(name, " for %s"))
      try:
        job_result = PollJob(jid, cl=self.cl, feedback_fn=self.feedback_fn)
        success = True
      except errors.JobLost, err:
        _, job_result = FormatError(err)
        ToStderr("Job %s%s has been archived, cannot check its result",
                 jid, self._IfName(name, " for %s"))
        success = False
      except (errors.GenericError, rpcerr.ProtocolError), err:
        _, job_result = FormatError(err)
        success = False
        # the error message will always be shown, verbose or not
        ToStderr("Job %s%s has failed: %s",
                 jid, self._IfName(name, " for %s"), job_result)

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


def FormatParamsDictInfo(param_dict, actual):
  """Formats a parameter dictionary.

  @type param_dict: dict
  @param param_dict: the own parameters
  @type actual: dict
  @param actual: the current parameter set (including defaults)
  @rtype: dict
  @return: dictionary where the value of each parameter is either a fully
      formatted string or a dictionary containing formatted strings

  """
  ret = {}
  for (key, data) in actual.items():
    if isinstance(data, dict) and data:
      ret[key] = FormatParamsDictInfo(param_dict.get(key, {}), data)
    else:
      ret[key] = str(param_dict.get(key, "default (%s)" % data))
  return ret


def _FormatListInfoDefault(data, def_data):
  if data is not None:
    ret = utils.CommaJoin(data)
  else:
    ret = "default (%s)" % utils.CommaJoin(def_data)
  return ret


def FormatPolicyInfo(custom_ipolicy, eff_ipolicy, iscluster):
  """Formats an instance policy.

  @type custom_ipolicy: dict
  @param custom_ipolicy: own policy
  @type eff_ipolicy: dict
  @param eff_ipolicy: effective policy (including defaults); ignored for
      cluster
  @type iscluster: bool
  @param iscluster: the policy is at cluster level
  @rtype: list of pairs
  @return: formatted data, suitable for L{PrintGenericInfo}

  """
  if iscluster:
    eff_ipolicy = custom_ipolicy

  minmax_out = []
  custom_minmax = custom_ipolicy.get(constants.ISPECS_MINMAX)
  if custom_minmax:
    for (k, minmax) in enumerate(custom_minmax):
      minmax_out.append([
        ("%s/%s" % (key, k),
         FormatParamsDictInfo(minmax[key], minmax[key]))
        for key in constants.ISPECS_MINMAX_KEYS
        ])
  else:
    for (k, minmax) in enumerate(eff_ipolicy[constants.ISPECS_MINMAX]):
      minmax_out.append([
        ("%s/%s" % (key, k),
         FormatParamsDictInfo({}, minmax[key]))
        for key in constants.ISPECS_MINMAX_KEYS
        ])
  ret = [("bounds specs", minmax_out)]

  if iscluster:
    stdspecs = custom_ipolicy[constants.ISPECS_STD]
    ret.append(
      (constants.ISPECS_STD,
       FormatParamsDictInfo(stdspecs, stdspecs))
      )

  ret.append(
    ("allowed disk templates",
     _FormatListInfoDefault(custom_ipolicy.get(constants.IPOLICY_DTS),
                            eff_ipolicy[constants.IPOLICY_DTS]))
    )
  ret.extend([
    (key, str(custom_ipolicy.get(key, "default (%s)" % eff_ipolicy[key])))
    for key in constants.IPOLICY_PARAMETERS
    ])
  return ret


def _PrintSpecsParameters(buf, specs):
  values = ("%s=%s" % (par, val) for (par, val) in sorted(specs.items()))
  buf.write(",".join(values))


def PrintIPolicyCommand(buf, ipolicy, isgroup):
  """Print the command option used to generate the given instance policy.

  Currently only the parts dealing with specs are supported.

  @type buf: StringIO
  @param buf: stream to write into
  @type ipolicy: dict
  @param ipolicy: instance policy
  @type isgroup: bool
  @param isgroup: whether the policy is at group level

  """
  if not isgroup:
    stdspecs = ipolicy.get("std")
    if stdspecs:
      buf.write(" %s " % IPOLICY_STD_SPECS_STR)
      _PrintSpecsParameters(buf, stdspecs)
  minmaxes = ipolicy.get("minmax", [])
  first = True
  for minmax in minmaxes:
    minspecs = minmax.get("min")
    maxspecs = minmax.get("max")
    if minspecs and maxspecs:
      if first:
        buf.write(" %s " % IPOLICY_BOUNDS_SPECS_STR)
        first = False
      else:
        buf.write("//")
      buf.write("min:")
      _PrintSpecsParameters(buf, minspecs)
      buf.write("/max:")
      _PrintSpecsParameters(buf, maxspecs)


def ConfirmOperation(names, list_type, text, extra=""):
  """Ask the user to confirm an operation on a list of list_type.

  This function is used to request confirmation for doing an operation
  on a given list of list_type.

  @type names: list
  @param names: the list of names that we display when
      we ask for confirmation
  @type list_type: str
  @param list_type: Human readable name for elements in the list (e.g. nodes)
  @type text: str
  @param text: the operation that the user should confirm
  @rtype: boolean
  @return: True or False depending on user's confirmation.

  """
  count = len(names)
  msg = ("The %s will operate on %d %s.\n%s"
         "Do you want to continue?" % (text, count, list_type, extra))
  affected = (("\nAffected %s:\n" % list_type) +
              "\n".join(["  %s" % name for name in names]))

  choices = [("y", True, "Yes, execute the %s" % text),
             ("n", False, "No, abort the %s" % text)]

  if count > 20:
    choices.insert(1, ("v", "v", "View the list of affected %s" % list_type))
    question = msg
  else:
    question = msg + affected

  choice = AskUser(question, choices)
  if choice == "v":
    choices.pop(1)
    choice = AskUser(msg + affected, choices)
  return choice


def _MaybeParseUnit(elements):
  """Parses and returns an array of potential values with units.

  """
  parsed = {}
  for k, v in elements.items():
    if v == constants.VALUE_DEFAULT:
      parsed[k] = v
    else:
      parsed[k] = utils.ParseUnit(v)
  return parsed


def _InitISpecsFromSplitOpts(ipolicy, ispecs_mem_size, ispecs_cpu_count,
                             ispecs_disk_count, ispecs_disk_size,
                             ispecs_nic_count, group_ipolicy, fill_all):
  try:
    if ispecs_mem_size:
      ispecs_mem_size = _MaybeParseUnit(ispecs_mem_size)
    if ispecs_disk_size:
      ispecs_disk_size = _MaybeParseUnit(ispecs_disk_size)
  except (TypeError, ValueError, errors.UnitParseError), err:
    raise errors.OpPrereqError("Invalid disk (%s) or memory (%s) size"
                               " in policy: %s" %
                               (ispecs_disk_size, ispecs_mem_size, err),
                               errors.ECODE_INVAL)

  # prepare ipolicy dict
  ispecs_transposed = {
    constants.ISPEC_MEM_SIZE: ispecs_mem_size,
    constants.ISPEC_CPU_COUNT: ispecs_cpu_count,
    constants.ISPEC_DISK_COUNT: ispecs_disk_count,
    constants.ISPEC_DISK_SIZE: ispecs_disk_size,
    constants.ISPEC_NIC_COUNT: ispecs_nic_count,
    }

  # first, check that the values given are correct
  if group_ipolicy:
    forced_type = TISPECS_GROUP_TYPES
  else:
    forced_type = TISPECS_CLUSTER_TYPES
  for specs in ispecs_transposed.values():
    assert type(specs) is dict
    utils.ForceDictType(specs, forced_type)

  # then transpose
  ispecs = {
    constants.ISPECS_MIN: {},
    constants.ISPECS_MAX: {},
    constants.ISPECS_STD: {},
    }
  for (name, specs) in ispecs_transposed.iteritems():
    assert name in constants.ISPECS_PARAMETERS
    for key, val in specs.items(): # {min: .. ,max: .., std: ..}
      assert key in ispecs
      ispecs[key][name] = val
  minmax_out = {}
  for key in constants.ISPECS_MINMAX_KEYS:
    if fill_all:
      minmax_out[key] = \
        objects.FillDict(constants.ISPECS_MINMAX_DEFAULTS[key], ispecs[key])
    else:
      minmax_out[key] = ispecs[key]
  ipolicy[constants.ISPECS_MINMAX] = [minmax_out]
  if fill_all:
    ipolicy[constants.ISPECS_STD] = \
        objects.FillDict(constants.IPOLICY_DEFAULTS[constants.ISPECS_STD],
                         ispecs[constants.ISPECS_STD])
  else:
    ipolicy[constants.ISPECS_STD] = ispecs[constants.ISPECS_STD]


def _ParseSpecUnit(spec, keyname):
  ret = spec.copy()
  for k in [constants.ISPEC_DISK_SIZE, constants.ISPEC_MEM_SIZE]:
    if k in ret:
      try:
        ret[k] = utils.ParseUnit(ret[k])
      except (TypeError, ValueError, errors.UnitParseError), err:
        raise errors.OpPrereqError(("Invalid parameter %s (%s) in %s instance"
                                    " specs: %s" % (k, ret[k], keyname, err)),
                                   errors.ECODE_INVAL)
  return ret


def _ParseISpec(spec, keyname, required):
  ret = _ParseSpecUnit(spec, keyname)
  utils.ForceDictType(ret, constants.ISPECS_PARAMETER_TYPES)
  missing = constants.ISPECS_PARAMETERS - frozenset(ret.keys())
  if required and missing:
    raise errors.OpPrereqError("Missing parameters in ipolicy spec %s: %s" %
                               (keyname, utils.CommaJoin(missing)),
                               errors.ECODE_INVAL)
  return ret


def _GetISpecsInAllowedValues(minmax_ispecs, allowed_values):
  ret = None
  if (minmax_ispecs and allowed_values and len(minmax_ispecs) == 1 and
      len(minmax_ispecs[0]) == 1):
    for (key, spec) in minmax_ispecs[0].items():
      # This loop is executed exactly once
      if key in allowed_values and not spec:
        ret = key
  return ret


def _InitISpecsFromFullOpts(ipolicy_out, minmax_ispecs, std_ispecs,
                            group_ipolicy, allowed_values):
  found_allowed = _GetISpecsInAllowedValues(minmax_ispecs, allowed_values)
  if found_allowed is not None:
    ipolicy_out[constants.ISPECS_MINMAX] = found_allowed
  elif minmax_ispecs is not None:
    minmax_out = []
    for mmpair in minmax_ispecs:
      mmpair_out = {}
      for (key, spec) in mmpair.items():
        if key not in constants.ISPECS_MINMAX_KEYS:
          msg = "Invalid key in bounds instance specifications: %s" % key
          raise errors.OpPrereqError(msg, errors.ECODE_INVAL)
        mmpair_out[key] = _ParseISpec(spec, key, True)
      minmax_out.append(mmpair_out)
    ipolicy_out[constants.ISPECS_MINMAX] = minmax_out
  if std_ispecs is not None:
    assert not group_ipolicy # This is not an option for gnt-group
    ipolicy_out[constants.ISPECS_STD] = _ParseISpec(std_ispecs, "std", False)


def CreateIPolicyFromOpts(ispecs_mem_size=None,
                          ispecs_cpu_count=None,
                          ispecs_disk_count=None,
                          ispecs_disk_size=None,
                          ispecs_nic_count=None,
                          minmax_ispecs=None,
                          std_ispecs=None,
                          ipolicy_disk_templates=None,
                          ipolicy_vcpu_ratio=None,
                          ipolicy_spindle_ratio=None,
                          group_ipolicy=False,
                          allowed_values=None,
                          fill_all=False):
  """Creation of instance policy based on command line options.

  @param fill_all: whether for cluster policies we should ensure that
    all values are filled

  """
  assert not (fill_all and allowed_values)

  split_specs = (ispecs_mem_size or ispecs_cpu_count or ispecs_disk_count or
                 ispecs_disk_size or ispecs_nic_count)
  if (split_specs and (minmax_ispecs is not None or std_ispecs is not None)):
    raise errors.OpPrereqError("A --specs-xxx option cannot be specified"
                               " together with any --ipolicy-xxx-specs option",
                               errors.ECODE_INVAL)

  ipolicy_out = objects.MakeEmptyIPolicy()
  if split_specs:
    assert fill_all
    _InitISpecsFromSplitOpts(ipolicy_out, ispecs_mem_size, ispecs_cpu_count,
                             ispecs_disk_count, ispecs_disk_size,
                             ispecs_nic_count, group_ipolicy, fill_all)
  elif (minmax_ispecs is not None or std_ispecs is not None):
    _InitISpecsFromFullOpts(ipolicy_out, minmax_ispecs, std_ispecs,
                            group_ipolicy, allowed_values)

  if ipolicy_disk_templates is not None:
    if allowed_values and ipolicy_disk_templates in allowed_values:
      ipolicy_out[constants.IPOLICY_DTS] = ipolicy_disk_templates
    else:
      ipolicy_out[constants.IPOLICY_DTS] = list(ipolicy_disk_templates)
  if ipolicy_vcpu_ratio is not None:
    ipolicy_out[constants.IPOLICY_VCPU_RATIO] = ipolicy_vcpu_ratio
  if ipolicy_spindle_ratio is not None:
    ipolicy_out[constants.IPOLICY_SPINDLE_RATIO] = ipolicy_spindle_ratio

  assert not (frozenset(ipolicy_out.keys()) - constants.IPOLICY_ALL_KEYS)

  if not group_ipolicy and fill_all:
    ipolicy_out = objects.FillIPolicy(constants.IPOLICY_DEFAULTS, ipolicy_out)

  return ipolicy_out


def _SerializeGenericInfo(buf, data, level, afterkey=False):
  """Formatting core of L{PrintGenericInfo}.

  @param buf: (string) stream to accumulate the result into
  @param data: data to format
  @type level: int
  @param level: depth in the data hierarchy, used for indenting
  @type afterkey: bool
  @param afterkey: True when we are in the middle of a line after a key (used
      to properly add newlines or indentation)

  """
  baseind = "  "
  if isinstance(data, dict):
    if not data:
      buf.write("\n")
    else:
      if afterkey:
        buf.write("\n")
        doindent = True
      else:
        doindent = False
      for key in sorted(data):
        if doindent:
          buf.write(baseind * level)
        else:
          doindent = True
        buf.write(key)
        buf.write(": ")
        _SerializeGenericInfo(buf, data[key], level + 1, afterkey=True)
  elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], tuple):
    # list of tuples (an ordered dictionary)
    if afterkey:
      buf.write("\n")
      doindent = True
    else:
      doindent = False
    for (key, val) in data:
      if doindent:
        buf.write(baseind * level)
      else:
        doindent = True
      buf.write(key)
      buf.write(": ")
      _SerializeGenericInfo(buf, val, level + 1, afterkey=True)
  elif isinstance(data, list):
    if not data:
      buf.write("\n")
    else:
      if afterkey:
        buf.write("\n")
        doindent = True
      else:
        doindent = False
      for item in data:
        if doindent:
          buf.write(baseind * level)
        else:
          doindent = True
        buf.write("-")
        buf.write(baseind[1:])
        _SerializeGenericInfo(buf, item, level + 1)
  else:
    # This branch should be only taken for strings, but it's practically
    # impossible to guarantee that no other types are produced somewhere
    buf.write(str(data))
    buf.write("\n")


def PrintGenericInfo(data):
  """Print information formatted according to the hierarchy.

  The output is a valid YAML string.

  @param data: the data to print. It's a hierarchical structure whose elements
      can be:
        - dictionaries, where keys are strings and values are of any of the
          types listed here
        - lists of pairs (key, value), where key is a string and value is of
          any of the types listed here; it's a way to encode ordered
          dictionaries
        - lists of any of the types listed here
        - strings

  """
  buf = StringIO()
  _SerializeGenericInfo(buf, data, 0)
  ToStdout(buf.getvalue().rstrip("\n"))
