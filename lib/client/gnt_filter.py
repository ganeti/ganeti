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

"""Job filter rule commands"""

# pylint: disable=W0401,W0614
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)

from ganeti.cli import *
from ganeti import constants
from ganeti import utils


#: default list of fields for L{ListFilters}
_LIST_DEF_FIELDS = ["uuid", "watermark", "priority",
                    "predicates", "action", "reason_trail"]


def AddFilter(opts, args):
  """Add a job filter rule.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  assert args == []

  reason = []
  if opts.reason:
    reason = [(constants.OPCODE_REASON_SRC_USER,
               opts.reason,
               utils.EpochNano())]

  cl = GetClient()
  result = cl.ReplaceFilter(None, opts.priority, opts.predicates, opts.action,
                            reason)

  print result  # Prints the UUID of the replaced/created filter


def ListFilters(opts, args):
  """List job filter rules and their properties.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: filters to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  desired_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)
  cl = GetClient()
  return GenericList(constants.QR_FILTER, desired_fields, args, None,
                     opts.separator, not opts.no_headers,
                     verbose=opts.verbose, cl=cl, namefield="uuid")


def ListFilterFields(opts, args):
  """List filter rule fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  return GenericListFields(constants.QR_FILTER, args, opts.separator,
                           not opts.no_headers, cl=cl)


def ReplaceFilter(opts, args):
  """Replaces a job filter rule with the given UUID, or creates it, if it
  doesn't exist already.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the UUID of the filter

  @rtype: int
  @return: the desired exit code

  """
  (uuid,) = args

  reason = []
  if opts.reason:
    reason = [(constants.OPCODE_REASON_SRC_USER,
               opts.reason,
               utils.EpochNano())]

  cl = GetClient()
  result = cl.ReplaceFilter(uuid,
                            priority=opts.priority,
                            predicates=opts.predicates,
                            action=opts.action,
                            reason=reason)

  print result  # Prints the UUID of the replaced/created filter
  return 0


def ShowFilter(_, args):
  """Show filter rule details.

  @type args: list
  @param args: should either be an empty list, in which case
      we show information about all filters, or should contain
      a list of filter UUIDs to be queried for information
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  result = cl.QueryFilters(fields=["uuid", "watermark", "priority",
                                   "predicates", "action", "reason_trail"],
                           uuids=args)

  for (uuid, watermark, priority, predicates, action, reason_trail) in result:
    ToStdout("UUID: %s", uuid)
    ToStdout("  Watermark: %s", watermark)
    ToStdout("  Priority: %s", priority)
    ToStdout("  Predicates: %s", predicates)
    ToStdout("  Action: %s", action)
    ToStdout("  Reason trail: %s", reason_trail)

  return 0


def DeleteFilter(_, args):
  """Remove a job filter rule.

  @type args: list
  @param args: a list of length 1 with the UUID of the filter to remove
  @rtype: int
  @return: the desired exit code

  """
  (uuid,) = args
  cl = GetClient()
  result = cl.DeleteFilter(uuid)
  assert result is None
  return 0


FILTER_PRIORITY_OPT = \
    cli_option("--priority",
               dest="priority", action="store", default=0, type="int",
               help="Priority for filter processing")

FILTER_PREDICATES_OPT = \
    cli_option("--predicates",
               dest="predicates", action="store", default=[], type="json",
               help="List of predicates in the Ganeti query language,"
                    " given as a JSON list.")

FILTER_ACTION_OPT = \
    cli_option("--action",
               dest="action", action="store", default="CONTINUE",
               type="filteraction",
               help="The effect of the filter. Can be one of 'ACCEPT',"
                    " 'PAUSE', 'REJECT', 'CONTINUE' and '[RATE_LIMIT, n]',"
                    " where n is a positive integer.")


commands = {
  "add": (
    AddFilter, ARGS_NONE,
    [FILTER_PRIORITY_OPT, FILTER_PREDICATES_OPT, FILTER_ACTION_OPT],
    "",
    "Adds a new filter rule"),
  "list": (
    ListFilters, ARGS_MANY_FILTERS,
    [NOHDR_OPT, SEP_OPT, FIELDS_OPT, VERBOSE_OPT],
    "[<filter_uuid>...]",
    "Lists the job filter rules. The available fields can be shown"
    " using the \"list-fields\" command (see the man page for details)."
    " The default list is (in order): %s." % utils.CommaJoin(_LIST_DEF_FIELDS)),
  "list-fields": (
    ListFilterFields, [ArgUnknown()],
    [NOHDR_OPT, SEP_OPT],
    "[fields...]",
    "Lists all available fields for filters"),
  "info": (
    ShowFilter, ARGS_MANY_FILTERS,
    [],
    "[<filter_uuid>...]",
    "Shows information about the filter(s)"),
  "replace": (
    ReplaceFilter, ARGS_ONE_FILTER,
    [FILTER_PRIORITY_OPT, FILTER_PREDICATES_OPT, FILTER_ACTION_OPT],
    "<filter_uuid>",
    "Replaces a filter"),
  "delete": (
    DeleteFilter, ARGS_ONE_FILTER,
    [],
    "<filter_uuid>",
    "Removes a filter"),
}


def Main():
  return GenericMain(commands)
