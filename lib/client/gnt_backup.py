#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2013 Google Inc.
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

"""Backup related commands"""

# pylint: disable=W0401,W0613,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0613: Unused argument, since all functions follow the same API
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-backup

from ganeti.cli import *
from ganeti import opcodes
from ganeti import constants
from ganeti import errors
from ganeti import qlang


_LIST_DEF_FIELDS = ["node", "export"]


def PrintExportList(opts, args):
  """Prints a list of all the exported system images.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)

  qfilter = qlang.MakeSimpleFilter("node", opts.nodes)

  cl = GetClient()

  return GenericList(constants.QR_EXPORT, selected_fields, None, opts.units,
                     opts.separator, not opts.no_headers,
                     verbose=opts.verbose, qfilter=qfilter, cl=cl)


def ListExportFields(opts, args):
  """List export fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  return GenericListFields(constants.QR_EXPORT, args, opts.separator,
                           not opts.no_headers, cl=cl)


def ExportInstance(opts, args):
  """Export an instance to an image in the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name
      of the instance to be exported
  @rtype: int
  @return: the desired exit code

  """
  ignore_remove_failures = opts.ignore_remove_failures

  if not opts.node:
    raise errors.OpPrereqError("Target node must be specified",
                               errors.ECODE_INVAL)

  op = opcodes.OpBackupExport(
    instance_name=args[0],
    target_node=opts.node,
    compress=opts.transport_compression,
    shutdown=opts.shutdown,
    shutdown_timeout=opts.shutdown_timeout,
    remove_instance=opts.remove_instance,
    ignore_remove_failures=ignore_remove_failures,
    zero_free_space=opts.zero_free_space,
    zeroing_timeout_fixed=opts.zeroing_timeout_fixed,
    zeroing_timeout_per_mib=opts.zeroing_timeout_per_mib,
    long_sleep=opts.long_sleep
  )

  SubmitOrSend(op, opts)
  return 0


def ImportInstance(opts, args):
  """Add an instance to the cluster.

  This is just a wrapper over GenericInstanceCreate.

  """
  return GenericInstanceCreate(constants.INSTANCE_IMPORT, opts, args)


def RemoveExport(opts, args):
  """Remove an export from the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the name of the
      instance whose backup should be removed
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpBackupRemove(instance_name=args[0])

  SubmitOrSend(op, opts)
  return 0


# this is defined separately due to readability only
import_opts = [
  IDENTIFY_DEFAULTS_OPT,
  SRC_DIR_OPT,
  SRC_NODE_OPT,
  COMPRESS_OPT,
  IGNORE_IPOLICY_OPT,
  HELPER_STARTUP_TIMEOUT_OPT,
  HELPER_SHUTDOWN_TIMEOUT_OPT,
  ]


commands = {
  "list": (
    PrintExportList, ARGS_NONE,
    [NODE_LIST_OPT, NOHDR_OPT, SEP_OPT, USEUNITS_OPT, FIELDS_OPT, VERBOSE_OPT],
    "", "Lists instance exports available in the ganeti cluster"),
  "list-fields": (
    ListExportFields, [ArgUnknown()],
    [NOHDR_OPT, SEP_OPT],
    "[fields...]",
    "Lists all available fields for exports"),
  "export": (
    ExportInstance, ARGS_ONE_INSTANCE,
    [FORCE_OPT, SINGLE_NODE_OPT, TRANSPORT_COMPRESSION_OPT, NOSHUTDOWN_OPT,
     SHUTDOWN_TIMEOUT_OPT, REMOVE_INSTANCE_OPT, IGNORE_REMOVE_FAILURES_OPT,
     DRY_RUN_OPT, PRIORITY_OPT, ZERO_FREE_SPACE_OPT, ZEROING_TIMEOUT_FIXED_OPT,
     ZEROING_TIMEOUT_PER_MIB_OPT, LONG_SLEEP_OPT] + SUBMIT_OPTS,
    "-n <target_node> [opts...] <name>",
    "Exports an instance to an image"),
  "import": (
    ImportInstance, ARGS_ONE_INSTANCE, COMMON_CREATE_OPTS + import_opts,
    "[...] -t disk-type -n node[:secondary-node] <name>",
    "Imports an instance from an exported image"),
  "remove": (
    RemoveExport, [ArgUnknown(min=1, max=1)],
    [DRY_RUN_OPT, PRIORITY_OPT] + SUBMIT_OPTS,
    "<name>", "Remove exports of named instance from the filesystem."),
  }


def Main():
  return GenericMain(commands)
