#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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


"""Module containing Ganeti's command line parsing options"""

import re

from optparse import (Option, OptionValueError)

import json
import sys
import textwrap

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import compat
from ganeti import pathutils
from ganeti import serializer


__all__ = [
  "ABSOLUTE_OPT",
  "ADD_RESERVED_IPS_OPT",
  "ADD_UIDS_OPT",
  "ALL_OPT",
  "ALLOC_POLICY_OPT",
  "ALLOCATABLE_OPT",
  "ALLOW_FAILOVER_OPT",
  "AUTO_PROMOTE_OPT",
  "AUTO_REPLACE_OPT",
  "BACKEND_OPT",
  "BLK_OS_OPT",
  "CAPAB_MASTER_OPT",
  "CAPAB_VM_OPT",
  "CLEANUP_OPT",
  "cli_option",
  "CLUSTER_DOMAIN_SECRET_OPT",
  "COMMIT_OPT",
  "COMMON_CREATE_OPTS",
  "COMMON_OPTS",
  "COMPRESS_OPT",
  "COMPRESSION_TOOLS_OPT",
  "CONFIRM_OPT",
  "CP_SIZE_OPT",
  "DEBUG_OPT",
  "DEBUG_SIMERR_OPT",
  "DEFAULT_IALLOCATOR_OPT",
  "DEFAULT_IALLOCATOR_PARAMS_OPT",
  "DISK_OPT",
  "DISK_PARAMS_OPT",
  "DISK_STATE_OPT",
  "DISK_TEMPLATE_OPT",
  "DISKIDX_OPT",
  "DRAINED_OPT",
  "DRBD_HELPER_OPT",
  "DRY_RUN_OPT",
  "DST_NODE_OPT",
  "EARLY_RELEASE_OPT",
  "ENABLED_DATA_COLLECTORS_OPT",
  "ENABLED_DISK_TEMPLATES_OPT",
  "ENABLED_HV_OPT",
  "ENABLED_USER_SHUTDOWN_OPT",
  "ERROR_CODES_OPT",
  "EXT_PARAMS_OPT",
  "FAILURE_ONLY_OPT",
  "FIELDS_OPT",
  "FILESTORE_DIR_OPT",
  "FILESTORE_DRIVER_OPT",
  "FORCE_FAILOVER_OPT",
  "FORCE_FILTER_OPT",
  "FORCE_OPT",
  "FORCE_VARIANT_OPT",
  "FORTHCOMING_OPT",
  "GATEWAY6_OPT",
  "GATEWAY_OPT",
  "GLOBAL_FILEDIR_OPT",
  "GLOBAL_GLUSTER_FILEDIR_OPT",
  "GLOBAL_SHARED_FILEDIR_OPT",
  "HELPER_SHUTDOWN_TIMEOUT_OPT",
  "HELPER_STARTUP_TIMEOUT_OPT",
  "HID_OS_OPT",
  "NOHOTPLUG_OPT",
  "HV_STATE_OPT",
  "HVLIST_OPT",
  "HVOPTS_OPT",
  "HYPERVISOR_OPT",
  "IALLOCATOR_OPT",
  "IDENTIFY_DEFAULTS_OPT",
  "IGNORE_CONSIST_OPT",
  "IGNORE_ERRORS_OPT",
  "IGNORE_FAILURES_OPT",
  "IGNORE_HVVERSIONS_OPT",
  "IGNORE_IPOLICY_OPT",
  "IGNORE_OFFLINE_OPT",
  "IGNORE_REMOVE_FAILURES_OPT",
  "IGNORE_SECONDARIES_OPT",
  "IGNORE_SOFT_ERRORS_OPT",
  "IGNORE_SIZE_OPT",
  "INCLUDEDEFAULTS_OPT",
  "INSTALL_IMAGE_OPT",
  "INSTANCE_COMMUNICATION_NETWORK_OPT",
  "INSTANCE_COMMUNICATION_OPT",
  "INSTANCE_POLICY_OPTS",
  "INTERVAL_OPT",
  "IPOLICY_BOUNDS_SPECS_STR",
  "IPOLICY_DISK_TEMPLATES",
  "IPOLICY_SPINDLE_RATIO",
  "IPOLICY_STD_SPECS_OPT",
  "IPOLICY_STD_SPECS_STR",
  "IPOLICY_VCPU_RATIO",
  "LONG_SLEEP_OPT",
  "MAC_PREFIX_OPT",
  "MAINTAIN_NODE_HEALTH_OPT",
  "MASTER_NETDEV_OPT",
  "MASTER_NETMASK_OPT",
  "MAX_TRACK_OPT",
  "MC_OPT",
  "MIGRATION_MODE_OPT",
  "MODIFY_ETCHOSTS_OPT",
  "NET_OPT",
  "NETWORK6_OPT",
  "NETWORK_OPT",
  "NEW_CLUSTER_CERT_OPT",
  "NEW_CLUSTER_DOMAIN_SECRET_OPT",
  "NEW_CONFD_HMAC_KEY_OPT",
  "NEW_NODE_CERT_OPT",
  "NEW_PRIMARY_OPT",
  "NEW_RAPI_CERT_OPT",
  "NEW_SECONDARY_OPT",
  "NEW_SPICE_CERT_OPT",
  "NEW_SSH_KEY_OPT",
  "NIC_PARAMS_OPT",
  "NO_INSTALL_OPT",
  "NO_REMEMBER_OPT",
  "NOCONFLICTSCHECK_OPT",
  "NODE_FORCE_JOIN_OPT",
  "NODE_LIST_OPT",
  "NODE_PARAMS_OPT",
  "NODE_PLACEMENT_OPT",
  "NODE_POWERED_OPT",
  "NODEGROUP_OPT",
  "NODEGROUP_OPT_NAME",
  "NOHDR_OPT",
  "IPCHECK_OPT",
  "NOIPCHECK_OPT",
  "NAMECHECK_OPT",
  "NONAMECHECK_OPT",
  "NOMODIFY_ETCHOSTS_OPT",
  "NOMODIFY_SSH_SETUP_OPT",
  "NONICS_OPT",
  "NONLIVE_OPT",
  "NONPLUS1_OPT",
  "NORUNTIME_CHGS_OPT",
  "NOSHUTDOWN_OPT",
  "NOSSH_KEYCHECK_OPT",
  "NOSTART_OPT",
  "NOVOTING_OPT",
  "NWSYNC_OPT",
  "OFFLINE_INST_OPT",
  "OFFLINE_OPT",
  "ON_PRIMARY_OPT",
  "ON_SECONDARY_OPT",
  "ONLINE_INST_OPT",
  "OOB_TIMEOUT_OPT",
  "OPT_COMPL_ALL",
  "OPT_COMPL_INST_ADD_NODES",
  "OPT_COMPL_MANY_NODES",
  "OPT_COMPL_ONE_EXTSTORAGE",
  "OPT_COMPL_ONE_FILTER",
  "OPT_COMPL_ONE_IALLOCATOR",
  "OPT_COMPL_ONE_INSTANCE",
  "OPT_COMPL_ONE_NETWORK",
  "OPT_COMPL_ONE_NODE",
  "OPT_COMPL_ONE_NODEGROUP",
  "OPT_COMPL_ONE_OS",
  "OS_OPT",
  "OS_SIZE_OPT",
  "OSPARAMS_OPT",
  "OSPARAMS_PRIVATE_OPT",
  "OSPARAMS_SECRET_OPT",
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
  "ROMAN_OPT",
  "RQL_OPT",
  "RUNTIME_MEM_OPT",
  "SECONDARY_IP_OPT",
  "SECONDARY_ONLY_OPT",
  "SELECT_OS_OPT",
  "SEP_OPT",
  "SEQUENTIAL_OPT",
  "SHOW_MACHINE_OPT",
  "SHOWCMD_OPT",
  "SHUTDOWN_TIMEOUT_OPT",
  "SINGLE_NODE_OPT",
  "SPECS_CPU_COUNT_OPT",
  "SPECS_DISK_COUNT_OPT",
  "SPECS_DISK_SIZE_OPT",
  "SPECS_MEM_SIZE_OPT",
  "SPECS_NIC_COUNT_OPT",
  "SPICE_CACERT_OPT",
  "SPICE_CERT_OPT",
  "SPLIT_ISPECS_OPTS",
  "SRC_DIR_OPT",
  "SRC_NODE_OPT",
  "SSH_KEY_BITS_OPT",
  "SSH_KEY_TYPE_OPT",
  "STARTUP_PAUSED_OPT",
  "STATIC_OPT",
  "SUBMIT_OPT",
  "SUBMIT_OPTS",
  "SYNC_OPT",
  "TAG_ADD_OPT",
  "TAG_SRC_OPT",
  "TIMEOUT_OPT",
  "TO_GROUP_OPT",
  "TRANSPORT_COMPRESSION_OPT",
  "UIDPOOL_OPT",
  "USE_EXTERNAL_MIP_SCRIPT",
  "USE_REPL_NET_OPT",
  "USEUNITS_OPT",
  "VERBOSE_OPT",
  "VERIFY_CLUTTER_OPT",
  "VG_NAME_OPT",
  "WFSYNC_OPT",
  "YES_DOIT_OPT",
  "ZERO_FREE_SPACE_OPT",
  "ZEROING_IMAGE_OPT",
  "ZEROING_TIMEOUT_FIXED_OPT",
  "ZEROING_TIMEOUT_PER_MIB_OPT",
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


def check_unit(option, opt, value): # pylint: disable=W0613
  """OptParsers custom converter for units.

  """
  try:
    return utils.ParseUnit(value)
  except errors.UnitParseError as err:
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


def check_json(option, opt, value): # pylint: disable=W0613
  """Custom parser for JSON arguments.

  Takes a string containing JSON, returns a Python object.

  """
  return json.loads(value)


def check_filteraction(option, opt, value): # pylint: disable=W0613
  """Custom parser for filter rule actions.

  Takes a string, returns an action as a Python object (list or string).

  The string "RATE_LIMIT n" becomes `["RATE_LIMIT", n]`.
  All other strings stay as they are.

  """
  match = re.match(r"RATE_LIMIT\s+(\d+)", value)
  if match:
    n = int(match.group(1))
    return ["RATE_LIMIT", n]
  else:
    return value


# completion_suggestion is normally a list. Using numeric values not evaluating
# to False for dynamic completion.
(OPT_COMPL_MANY_NODES,
 OPT_COMPL_ONE_NODE,
 OPT_COMPL_ONE_INSTANCE,
 OPT_COMPL_ONE_OS,
 OPT_COMPL_ONE_EXTSTORAGE,
 OPT_COMPL_ONE_FILTER,
 OPT_COMPL_ONE_IALLOCATOR,
 OPT_COMPL_ONE_NETWORK,
 OPT_COMPL_INST_ADD_NODES,
 OPT_COMPL_ONE_NODEGROUP) = range(100, 110)

OPT_COMPL_ALL = compat.UniqueFrozenset([
  OPT_COMPL_MANY_NODES,
  OPT_COMPL_ONE_NODE,
  OPT_COMPL_ONE_INSTANCE,
  OPT_COMPL_ONE_OS,
  OPT_COMPL_ONE_EXTSTORAGE,
  OPT_COMPL_ONE_FILTER,
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
    "json",
    "filteraction",
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
  TYPE_CHECKER["json"] = check_json
  TYPE_CHECKER["filteraction"] = check_filteraction


# optparse.py sets make_option, so we do it for our own option class, too
cli_option = CliOption # pylint: disable=C0103


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

IGNORE_SOFT_ERRORS_OPT = cli_option("--ignore-soft-errors",
                                    dest="ignore_soft_errors",
                                    action="store_true", default=False,
                                    help=("Tell htools to ignore any soft"
                                          " errors like N+1 violations"))

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

SEQUENTIAL_OPT = cli_option("--sequential", dest="sequential",
                            default=False, action="store_true",
                            help=("Execute all resulting jobs sequentially"))

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

EXT_PARAMS_OPT = cli_option("-e", "--ext-params", dest="ext_params",
                            default={}, type="keyval",
                            help="Parameters for ExtStorage template"
                            " conversions in the format:"
                            " provider=prvdr[,param1=val1,param2=val2,...]")

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
                                           default=None)

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
                                   help="Complete standard instance specs")

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

IPCHECK_OPT = cli_option("--ip-check", dest="ip_check", default=False,
                           action="store_true",
                           help="Check that the instance's IP is alive (ping)")

def WarnDeprecatedOption(option, opt_str, value, parser):
  """Callback for processing deprecated options.

  """
  msg = textwrap.fill(option.help, subsequent_indent="    ")
  print("Warning: %s: %s" % (opt_str, msg), file=sys.stderr)

NOIPCHECK_OPT = cli_option("--no-ip-check",
                           action="callback", callback=WarnDeprecatedOption,
                           help="This option is deprecated/without any"
                           " effect. IP check is now disabled by default."
                           " Use --ip-check for connection test.")

NAMECHECK_OPT = cli_option("--name-check", dest="name_check",
                             default=False, action="store_true",
                             help="Check that the instance's name is"
                             " resolvable")

NONAMECHECK_OPT = cli_option("--no-name-check",
                             action="callback", callback=WarnDeprecatedOption,
                             help="This option is deprecated/without any"
                             " effect. Name check is now disabled by default."
                             " Use --name-check for resolving names.")

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
                                " the secondary. The source node must be "
                                "marked offline first for this to succeed.")

IGNORE_HVVERSIONS_OPT = cli_option("--ignore-hvversions",
                                   dest="ignore_hvversions",
                                   action="store_true", default=False,
                                   help="Ignore incompatible hypervisor"
                                   " versions between source and target")

ALLOW_FAILOVER_OPT = cli_option("--allow-failover",
                                dest="allow_failover",
                                action="store_true", default=False,
                                help="If migration is not possible fallback to"
                                     " failover")

FORCE_FAILOVER_OPT = cli_option("--force-failover",
                                dest="force_failover",
                                action="store_true", default=False,
                                help="Do not use migration, always use"
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

FORTHCOMING_OPT = cli_option("--forthcoming", dest="forthcoming",
                             action="store_true", default=False,
                             help="Only reserve resources, but do not"
                                  " create the instance yet")

COMMIT_OPT = cli_option("--commit", dest="commit",
                        action="store_true", default=False,
                        help="The instance is already reserved and should"
                             " be committed now")

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

ENABLED_USER_SHUTDOWN_OPT = cli_option("--user-shutdown",
                                       default=None,
                                       dest="enabled_user_shutdown",
                                       help="Whether user shutdown is enabled",
                                       type="bool")

NIC_PARAMS_OPT = cli_option("-N", "--nic-parameters", dest="nicparams",
                            type="keyval", default={},
                            help="NIC parameters")

CP_SIZE_OPT = cli_option("-C", "--candidate-pool-size", default=None,
                         dest="candidate_pool_size", type="int",
                         help="Set the candidate pool size")

RQL_OPT = cli_option("--max-running-jobs", dest="max_running_jobs",
                     type="int", help="Set the maximal number of jobs to "
                                      "run simultaneously")

MAX_TRACK_OPT = cli_option("--max-tracked-jobs", dest="max_tracked_jobs",
                           type="int", help="Set the maximal number of jobs to "
                                            "be tracked simultaneously for "
                                            "scheduling")

COMPRESSION_TOOLS_OPT = \
    cli_option("--compression-tools",
               dest="compression_tools", type="string", default=None,
               help="Comma-separated list of compression tools which are"
                    " allowed to be used by Ganeti in various operations")

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
                         help="Maximum time (in minutes) to wait")

COMPRESS_OPT = cli_option("--compress", dest="compress",
                          type="string", default=constants.IEC_NONE,
                          help="The compression mode to use")

TRANSPORT_COMPRESSION_OPT = \
    cli_option("--transport-compression", dest="transport_compression",
               type="string", default=constants.IEC_NONE,
               help="The compression mode to use during transport")

SHUTDOWN_TIMEOUT_OPT = cli_option("--shutdown-timeout",
                                  dest="shutdown_timeout", type="int",
                                  default=constants.DEFAULT_SHUTDOWN_TIMEOUT,
                                  help="Maximum time (in minutes) to wait for"
                                  " instance shutdown")

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

NEW_SSH_KEY_OPT = cli_option(
  "--new-ssh-keys", dest="new_ssh_keys", default=False,
  action="store_true", help="Generate new node SSH keys (for all nodes)")

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

REASON_OPT = cli_option("--reason", default=[],
                        help="The reason for executing the command")


def _PriorityOptionCb(option, _, value, parser):
  """Callback for processing C{--priority} option.

  """
  value = _PRIONAME_TO_VALUE[value]

  setattr(parser.values, option.dest, value)


PRIORITY_OPT = cli_option("--priority", default=None, dest="priority",
                          metavar="|".join(name for name, _ in _PRIORITY_NAMES),
                          choices=list(_PRIONAME_TO_VALUE),
                          action="callback", type="choice",
                          callback=_PriorityOptionCb,
                          help="Priority for opcode processing")

OPPORTUNISTIC_OPT = cli_option("--opportunistic-locking",
                               dest="opportunistic_locking",
                               action="store_true", default=False,
                               help="Opportunistically acquire locks")

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

NOHOTPLUG_OPT = cli_option("--no-hotplug", dest="hotplug",
                         action="store_false", default=True,
                         help="Hotplug supported devices (NICs and Disks)")

INSTALL_IMAGE_OPT = \
    cli_option("--install-image",
               dest="install_image",
               action="store",
               type="string",
               default=None,
               help="The OS image to use for running the OS scripts safely")

INSTANCE_COMMUNICATION_OPT = \
    cli_option("-c", "--communication",
               dest="instance_communication",
               help=constants.INSTANCE_COMMUNICATION_DOC,
               type="bool")

INSTANCE_COMMUNICATION_NETWORK_OPT = \
    cli_option("--instance-communication-network",
               dest="instance_communication_network",
               type="string",
               help="Set the network name for instance communication")

ZEROING_IMAGE_OPT = \
    cli_option("--zeroing-image",
               dest="zeroing_image", action="store", default=None,
               help="The OS image to use to zero instance disks")

ZERO_FREE_SPACE_OPT = \
    cli_option("--zero-free-space",
               dest="zero_free_space", action="store_true", default=False,
               help="Whether to zero the free space on the disks of the "
                    "instance prior to the export")

HELPER_STARTUP_TIMEOUT_OPT = \
    cli_option("--helper-startup-timeout",
               dest="helper_startup_timeout", action="store", type="int",
               help="Startup timeout for the helper VM")

HELPER_SHUTDOWN_TIMEOUT_OPT = \
    cli_option("--helper-shutdown-timeout",
               dest="helper_shutdown_timeout", action="store", type="int",
               help="Shutdown timeout for the helper VM")

ZEROING_TIMEOUT_FIXED_OPT = \
    cli_option("--zeroing-timeout-fixed",
               dest="zeroing_timeout_fixed", action="store", type="int",
               help="The fixed amount of time to wait before assuming that the "
                    "zeroing failed")

ZEROING_TIMEOUT_PER_MIB_OPT = \
    cli_option("--zeroing-timeout-per-mib",
               dest="zeroing_timeout_per_mib", action="store", type="float",
               help="The amount of time to wait per MiB of data to zero, in "
                    "addition to the fixed timeout")

ENABLED_DATA_COLLECTORS_OPT = \
    cli_option("--enabled-data-collectors",
               dest="enabled_data_collectors", type="keyval",
               default={},
               help="Deactivate or reactivate a data collector for reporting, "
               "in the format collector=bool, where collector is one of %s."
               % ", ".join(constants.DATA_COLLECTOR_NAMES))

VERIFY_CLUTTER_OPT = cli_option(
    "--verify-ssh-clutter", default=False, dest="verify_clutter",
    help="Verify that Ganeti did not clutter"
    " up the 'authorized_keys' file", action="store_true")

LONG_SLEEP_OPT = cli_option(
    "--long-sleep", default=False, dest="long_sleep",
    help="Allow long shutdowns when backing up instances", action="store_true")

SSH_KEY_TYPE_OPT = \
    cli_option("--ssh-key-type", default=None,
               choices=list(constants.SSHK_ALL), dest="ssh_key_type",
               help="Type of SSH key deployed by Ganeti for cluster actions")

SSH_KEY_BITS_OPT = \
    cli_option("--ssh-key-bits", default=None,
               type="int", dest="ssh_key_bits",
               help="Length of SSH keys generated by Ganeti, in bits")


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
  NODEGROUP_OPT,
  IPCHECK_OPT,
  NOIPCHECK_OPT,
  NAMECHECK_OPT,
  NONAMECHECK_OPT,
  NOCONFLICTSCHECK_OPT,
  NONICS_OPT,
  NWSYNC_OPT,
  OSPARAMS_OPT,
  OSPARAMS_PRIVATE_OPT,
  OSPARAMS_SECRET_OPT,
  OS_SIZE_OPT,
  OPPORTUNISTIC_OPT,
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
