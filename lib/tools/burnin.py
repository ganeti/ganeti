#!/usr/bin/python3
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""Burnin program

"""

from __future__ import print_function

import sys
import optparse
import time
import socket
import urllib.request, urllib.parse, urllib.error
import random
import string # pylint: disable=W0402
from functools import reduce
from itertools import islice, cycle
from io import StringIO
from operator import or_

from ganeti import opcodes
from ganeti import constants
from ganeti import cli
from ganeti import errors
from ganeti import utils
from ganeti import hypervisor
from ganeti import compat
from ganeti import pathutils

from ganeti.confd import client as confd_client
from ganeti.runtime import (GetClient)


USAGE = ("\tburnin -o OS_NAME [options...] instance_name ...")

MAX_RETRIES = 3
LOG_HEADERS = {
  0: "- ",
  1: "* ",
  2: "",
  }

#: Disk templates supporting a single node
_SINGLE_NODE_DISK_TEMPLATES = compat.UniqueFrozenset([
  constants.DT_DISKLESS,
  constants.DT_PLAIN,
  constants.DT_FILE,
  constants.DT_SHARED_FILE,
  constants.DT_EXT,
  constants.DT_RBD,
  constants.DT_GLUSTER
  ])

_SUPPORTED_DISK_TEMPLATES = compat.UniqueFrozenset([
  constants.DT_DISKLESS,
  constants.DT_DRBD8,
  constants.DT_EXT,
  constants.DT_FILE,
  constants.DT_PLAIN,
  constants.DT_RBD,
  constants.DT_SHARED_FILE,
  constants.DT_GLUSTER
  ])

#: Disk templates for which import/export is tested
_IMPEXP_DISK_TEMPLATES = (_SUPPORTED_DISK_TEMPLATES - frozenset([
  constants.DT_DISKLESS,
  constants.DT_FILE,
  constants.DT_SHARED_FILE,
  constants.DT_GLUSTER
  ]))


class InstanceDown(Exception):
  """The checked instance was not up"""


class BurninFailure(Exception):
  """Failure detected during burning"""


def Usage():
  """Shows program usage information and exits the program."""

  print("Usage:", file=sys.stderr)
  print(USAGE, file=sys.stderr)
  sys.exit(2)


def Log(msg, *args, **kwargs):
  """Simple function that prints out its argument.

  """
  if args:
    msg = msg % args
  indent = kwargs.get("indent", 0)
  sys.stdout.write("%*s%s%s\n" % (2 * indent, "",
                                  LOG_HEADERS.get(indent, "  "), msg))
  sys.stdout.flush()


def Err(msg, exit_code=1):
  """Simple error logging that prints to stderr.

  """
  sys.stderr.write(msg + "\n")
  sys.stderr.flush()
  sys.exit(exit_code)


def RandomString(size=8, chars=string.ascii_uppercase + string.digits):
  return ''.join(random.choice(chars) for x in range(size))


class SimpleOpener(urllib.request.FancyURLopener):
  """A simple url opener"""
  # pylint: disable=W0221

  def prompt_user_passwd(self, host, realm, clear_cache=0):
    """No-interaction version of prompt_user_passwd."""
    # we follow parent class' API
    # pylint: disable=W0613
    return None, None

  def http_error_default(self, url, fp, errcode, errmsg, headers):
    """Custom error handling"""
    # make sure sockets are not left in CLOSE_WAIT, this is similar
    # but with a different exception to the BasicURLOpener class
    _ = fp.read() # throw away data
    fp.close()
    raise InstanceDown("HTTP error returned: code %s, msg %s" %
                       (errcode, errmsg))


OPTIONS = [
  cli.cli_option("-o", "--os", dest="os", default=None,
                 help="OS to use during burnin",
                 metavar="<OS>",
                 completion_suggest=cli.OPT_COMPL_ONE_OS),
  cli.HYPERVISOR_OPT,
  cli.OSPARAMS_OPT,
  cli.cli_option("--disk-size", dest="disk_size",
                 help="Disk size (determines disk count)",
                 default="1G", type="string", metavar="<size,size,...>",
                 completion_suggest=("512M 1G 4G 1G,256M"
                                     " 4G,1G,1G 10G").split()),
  cli.cli_option("--disk-growth", dest="disk_growth", help="Disk growth",
                 default="128m", type="string", metavar="<size,size,...>"),
  cli.cli_option("--mem-size", dest="mem_size", help="Memory size",
                 default=None, type="unit", metavar="<size>",
                 completion_suggest=("128M 256M 512M 1G 4G 8G"
                                     " 12G 16G").split()),
  cli.cli_option("--maxmem-size", dest="maxmem_size", help="Max Memory size",
                 default=256, type="unit", metavar="<size>",
                 completion_suggest=("128M 256M 512M 1G 4G 8G"
                                     " 12G 16G").split()),
  cli.cli_option("--minmem-size", dest="minmem_size", help="Min Memory size",
                 default=128, type="unit", metavar="<size>",
                 completion_suggest=("128M 256M 512M 1G 4G 8G"
                                     " 12G 16G").split()),
  cli.cli_option("--vcpu-count", dest="vcpu_count", help="VCPU count",
                 default=3, type="unit", metavar="<count>",
                 completion_suggest=("1 2 3 4").split()),
  cli.DEBUG_OPT,
  cli.VERBOSE_OPT,
  cli.IPCHECK_OPT,
  cli.NAMECHECK_OPT,
  cli.EARLY_RELEASE_OPT,
  cli.cli_option("--no-replace1", dest="do_replace1",
                 help="Skip disk replacement with the same secondary",
                 action="store_false", default=True),
  cli.cli_option("--no-replace2", dest="do_replace2",
                 help="Skip disk replacement with a different secondary",
                 action="store_false", default=True),
  cli.cli_option("--no-failover", dest="do_failover",
                 help="Skip instance failovers", action="store_false",
                 default=True),
  cli.cli_option("--no-migrate", dest="do_migrate",
                 help="Skip instance live migration",
                 action="store_false", default=True),
  cli.cli_option("--no-move", dest="do_move",
                 help="Skip instance moves", action="store_false",
                 default=True),
  cli.cli_option("--no-importexport", dest="do_importexport",
                 help="Skip instance export/import", action="store_false",
                 default=True),
  cli.cli_option("--no-startstop", dest="do_startstop",
                 help="Skip instance stop/start", action="store_false",
                 default=True),
  cli.cli_option("--no-reinstall", dest="do_reinstall",
                 help="Skip instance reinstall", action="store_false",
                 default=True),
  cli.cli_option("--no-reboot", dest="do_reboot",
                 help="Skip instance reboot", action="store_false",
                 default=True),
  cli.cli_option("--no-renamesame", dest="do_renamesame",
                 help="Skip instance rename to same name", action="store_false",
                 default=True),
  cli.cli_option("--reboot-types", dest="reboot_types",
                 help="Specify the reboot types", default=None),
  cli.cli_option("--no-activate-disks", dest="do_activate_disks",
                 help="Skip disk activation/deactivation",
                 action="store_false", default=True),
  cli.cli_option("--no-add-disks", dest="do_addremove_disks",
                 help="Skip disk addition/removal",
                 action="store_false", default=True),
  cli.cli_option("--no-add-nics", dest="do_addremove_nics",
                 help="Skip NIC addition/removal",
                 action="store_false", default=True),
  cli.cli_option("--no-nics", dest="nics",
                 help="No network interfaces", action="store_const",
                 const=[], default=[{}]),
  cli.cli_option("--no-confd", dest="do_confd_tests",
                 help="Skip confd queries",
                 action="store_false", default=True),
  cli.cli_option("--rename", dest="rename", default=None,
                 help=("Give one unused instance name which is taken"
                       " to start the renaming sequence"),
                 metavar="<instance_name>"),
  cli.cli_option("-t", "--disk-template", dest="disk_template",
                 choices=list(_SUPPORTED_DISK_TEMPLATES),
                 default=constants.DT_DRBD8,
                 help=("Disk template (default %s, otherwise one of %s)" %
                       (constants.DT_DRBD8,
                        utils.CommaJoin(_SUPPORTED_DISK_TEMPLATES)))),
  cli.cli_option("-n", "--nodes", dest="nodes", default="",
                 help=("Comma separated list of nodes to perform"
                       " the burnin on (defaults to all nodes)"),
                 completion_suggest=cli.OPT_COMPL_MANY_NODES),
  cli.cli_option("-I", "--iallocator", dest="iallocator",
                 default=None, type="string",
                 help=("Perform the allocation using an iallocator"
                       " instead of fixed node spread (node restrictions no"
                       " longer apply, therefore -n/--nodes must not be"
                       " used"),
                 completion_suggest=cli.OPT_COMPL_ONE_IALLOCATOR),
  cli.cli_option("-p", "--parallel", default=False, action="store_true",
                 dest="parallel",
                 help=("Enable parallelization of some operations in"
                       " order to speed burnin or to test granular locking")),
  cli.cli_option("--net-timeout", default=15, type="int",
                 dest="net_timeout",
                 help=("The instance check network timeout in seconds"
                       " (defaults to 15 seconds)"),
                 completion_suggest="15 60 300 900".split()),
  cli.cli_option("-C", "--http-check", default=False, action="store_true",
                 dest="http_check",
                 help=("Enable checking of instance status via http,"
                       " looking for /hostname.txt that should contain the"
                       " name of the instance")),
  cli.cli_option("-K", "--keep-instances", default=False,
                 action="store_true",
                 dest="keep_instances",
                 help=("Leave instances on the cluster after burnin,"
                       " for investigation in case of errors or simply"
                       " to use them")),
  cli.REASON_OPT,
  ]

# Mainly used for bash completion
ARGUMENTS = [cli.ArgInstance(min=1)]


def _DoCheckInstances(fn):
  """Decorator for checking instances.

  """
  def wrapper(self, *args, **kwargs):
    val = fn(self, *args, **kwargs)
    for instance in self.instances:
      self._CheckInstanceAlive(instance) # pylint: disable=W0212
    return val

  return wrapper


def _DoBatch(retry):
  """Decorator for possible batch operations.

  Must come after the _DoCheckInstances decorator (if any).

  @param retry: whether this is a retryable batch, will be
      passed to StartBatch

  """
  def wrap(fn):
    def batched(self, *args, **kwargs):
      self.StartBatch(retry)
      val = fn(self, *args, **kwargs)
      self.CommitQueue()
      return val
    return batched

  return wrap


class FeedbackAccumulator(object):
  """Feedback accumulator class."""

  _feed_buf = StringIO()
  opts = None

  def ClearFeedbackBuf(self):
    """Clear the feedback buffer."""
    self._feed_buf.truncate(0)

  def GetFeedbackBuf(self):
    """Return the contents of the buffer."""
    return self._feed_buf.getvalue()

  def Feedback(self, msg):
    """Acumulate feedback in our buffer."""
    formatted_msg = "%s %s" % (time.ctime(utils.MergeTime(msg[0])), msg[2])
    self._feed_buf.write(formatted_msg + "\n")
    if self.opts.verbose:
      Log(formatted_msg, indent=3)


class JobHandler(FeedbackAccumulator):
  """Class for handling Ganeti jobs."""

  queued_ops = []
  queue_retry = False

  def __init__(self):
    self.cl = cli.GetClient()

  def MaybeRetry(self, retry_count, msg, fn, *args):
    """Possibly retry a given function execution.

    @type retry_count: int
    @param retry_count: retry counter:
        - 0: non-retryable action
        - 1: last retry for a retryable action
        - MAX_RETRIES: original try for a retryable action
    @type msg: str
    @param msg: the kind of the operation
    @type fn: callable
    @param fn: the function to be called

    """
    try:
      val = fn(*args)
      if retry_count > 0 and retry_count < MAX_RETRIES:
        Log("Idempotent %s succeeded after %d retries",
            msg, MAX_RETRIES - retry_count)
      return val
    except Exception as err: # pylint: disable=W0703
      if retry_count == 0:
        Log("Non-idempotent %s failed, aborting", msg)
        raise
      elif retry_count == 1:
        Log("Idempotent %s repeated failure, aborting", msg)
        raise
      else:
        Log("Idempotent %s failed, retry #%d/%d: %s",
            msg, MAX_RETRIES - retry_count + 1, MAX_RETRIES, err)
        self.MaybeRetry(retry_count - 1, msg, fn, *args)

  def _ExecOp(self, *ops):
    """Execute one or more opcodes and manage the exec buffer.

    @return: if only opcode has been passed, we return its result;
        otherwise we return the list of results

    """
    job_id = cli.SendJob(ops, cl=self.cl)
    results = cli.PollJob(job_id, cl=self.cl, feedback_fn=self.Feedback)
    if len(ops) == 1:
      return results[0]
    else:
      return results

  def ExecOp(self, retry, *ops):
    """Execute one or more opcodes and manage the exec buffer.

    @return: if only opcode has been passed, we return its result;
        otherwise we return the list of results

    """
    if retry:
      rval = MAX_RETRIES
    else:
      rval = 0
    cli.SetGenericOpcodeOpts(ops, self.opts)
    return self.MaybeRetry(rval, "opcode", self._ExecOp, *ops)

  def ExecOrQueue(self, name, ops, post_process=None):
    """Execute an opcode and manage the exec buffer."""
    if self.opts.parallel:
      cli.SetGenericOpcodeOpts(ops, self.opts)
      self.queued_ops.append((ops, name, post_process))
    else:
      val = self.ExecOp(self.queue_retry, *ops)
      if post_process is not None:
        post_process()
      return val

  def StartBatch(self, retry):
    """Start a new batch of jobs.

    @param retry: whether this is a retryable batch

    """
    self.queued_ops = []
    self.queue_retry = retry

  def CommitQueue(self):
    """Execute all submitted opcodes in case of parallel burnin"""
    if not self.opts.parallel or not self.queued_ops:
      return

    if self.queue_retry:
      rval = MAX_RETRIES
    else:
      rval = 0

    try:
      results = self.MaybeRetry(rval, "jobset", self.ExecJobSet,
                                self.queued_ops)
    finally:
      self.queued_ops = []
    return results

  def ExecJobSet(self, jobs):
    """Execute a set of jobs and return once all are done.

    The method will return the list of results, if all jobs are
    successful. Otherwise, OpExecError will be raised from within
    cli.py.

    """
    self.ClearFeedbackBuf()
    jex = cli.JobExecutor(cl=self.cl, feedback_fn=self.Feedback)
    for ops, name, _ in jobs:
      jex.QueueJob(name, *ops)
    try:
      results = jex.GetResults()
    except Exception as err: # pylint: disable=W0703
      Log("Jobs failed: %s", err)
      raise BurninFailure()

    fail = False
    val = []
    for (_, name, post_process), (success, result) in zip(jobs, results):
      if success:
        if post_process:
          try:
            post_process()
          except Exception as err: # pylint: disable=W0703
            Log("Post process call for job %s failed: %s", name, err)
            fail = True
        val.append(result)
      else:
        fail = True

    if fail:
      raise BurninFailure()

    return val


class Burner(JobHandler):
  """Burner class."""

  def __init__(self):
    """Constructor."""
    super(Burner, self).__init__()

    self.url_opener = SimpleOpener()
    self.nodes = []
    self.instances = []
    self.to_rem = []
    self.disk_count = self.disk_growth = self.disk_size = None
    self.hvp = self.bep = None
    self.ParseOptions()
    self.disk_nodes = {}
    self.instance_nodes = {}
    self.GetState()
    self.confd_reply = None

  def ParseOptions(self):
    """Parses the command line options.

    In case of command line errors, it will show the usage and exit the
    program.

    """
    parser = optparse.OptionParser(usage="\n%s" % USAGE,
                                   version=("%%prog (ganeti) %s" %
                                            constants.RELEASE_VERSION),
                                   option_list=OPTIONS)

    options, args = parser.parse_args()
    if len(args) < 1 or options.os is None:
      Usage()

    if options.mem_size:
      options.maxmem_size = options.mem_size
      options.minmem_size = options.mem_size
    elif options.minmem_size > options.maxmem_size:
      Err("Maximum memory lower than minimum memory")

    if options.disk_template not in _SUPPORTED_DISK_TEMPLATES:
      Err("Unknown or unsupported disk template '%s'" % options.disk_template)

    if options.disk_template == constants.DT_DISKLESS:
      disk_size = disk_growth = []
      options.do_addremove_disks = False
    else:
      disk_size = [utils.ParseUnit(v) for v in options.disk_size.split(",")]
      disk_growth = [utils.ParseUnit(v)
                     for v in options.disk_growth.split(",")]
      if len(disk_growth) != len(disk_size):
        Err("Wrong disk sizes/growth combination")
    if ((disk_size and options.disk_template == constants.DT_DISKLESS) or
        (not disk_size and options.disk_template != constants.DT_DISKLESS)):
      Err("Wrong disk count/disk template combination")

    self.disk_size = disk_size
    self.disk_growth = disk_growth
    self.disk_count = len(disk_size)

    if options.nodes and options.iallocator:
      Err("Give either the nodes option or the iallocator option, not both")

    if options.http_check and not options.name_check:
      Err("Can't enable HTTP checks without name checks")

    self.opts = options
    self.instances = args
    self.bep = {
      constants.BE_MINMEM: options.minmem_size,
      constants.BE_MAXMEM: options.maxmem_size,
      constants.BE_VCPUS: options.vcpu_count,
      }

    self.hypervisor = None
    self.hvp = {}
    if options.hypervisor:
      self.hypervisor, self.hvp = options.hypervisor

    if options.reboot_types is None:
      options.reboot_types = constants.REBOOT_TYPES
    else:
      options.reboot_types = options.reboot_types.split(",")
      rt_diff = set(options.reboot_types).difference(constants.REBOOT_TYPES)
      if rt_diff:
        Err("Invalid reboot types specified: %s" % utils.CommaJoin(rt_diff))

    socket.setdefaulttimeout(options.net_timeout)

  def GetState(self):
    """Read the cluster state from the master daemon."""
    if self.opts.nodes:
      names = self.opts.nodes.split(",")
    else:
      names = []
    try:
      qcl = GetClient()
      result = qcl.QueryNodes(names, ["name", "offline", "drained"], False)
    except errors.GenericError as err:
      err_code, msg = cli.FormatError(err)
      Err(msg, exit_code=err_code)
    finally:
      qcl.Close()
    self.nodes = [data[0] for data in result if not (data[1] or data[2])]

    op_diagnose = opcodes.OpOsDiagnose(output_fields=["name",
                                                      "variants",
                                                      "hidden"],
                                       names=[])
    result = self.ExecOp(True, op_diagnose)

    if not result:
      Err("Can't get the OS list")

    found = False
    for (name, variants, _) in result:
      if self.opts.os in cli.CalculateOSNames(name, variants):
        found = True
        break

    if not found:
      Err("OS '%s' not found" % self.opts.os)

    cluster_info = self.cl.QueryClusterInfo()
    self.cluster_info = cluster_info
    if not self.cluster_info:
      Err("Can't get cluster info")

    default_nic_params = self.cluster_info["nicparams"][constants.PP_DEFAULT]
    self.cluster_default_nicparams = default_nic_params
    if self.hypervisor is None:
      self.hypervisor = self.cluster_info["default_hypervisor"]
    self.hv_can_migrate = \
      hypervisor.GetHypervisorClass(self.hypervisor).CAN_MIGRATE

  def FindMatchingDisk(self, instance):
    """Find a disk whose nodes match the instance's disk nodes."""
    instance_nodes = self.instance_nodes[instance]
    for disk, disk_nodes in self.disk_nodes.items():
      if instance_nodes == disk_nodes:
        # Erase that disk from the dictionary so that we don't pick it again.
        del self.disk_nodes[disk]
        return disk
    Err("Couldn't find matching detached disk for instance %s" % instance)

  @_DoCheckInstances
  @_DoBatch(False)
  def BurnCreateInstances(self):
    """Create the given instances.

    """
    self.to_rem = []
    mytor = zip(cycle(self.nodes),
                 islice(cycle(self.nodes), 1, None),
                 self.instances)

    Log("Creating instances")
    for pnode, snode, instance in mytor:
      Log("instance %s", instance, indent=1)
      if self.opts.iallocator:
        pnode = snode = None
        msg = "with iallocator %s" % self.opts.iallocator
      elif self.opts.disk_template not in constants.DTS_INT_MIRROR:
        snode = None
        msg = "on %s" % pnode
      else:
        msg = "on %s, %s" % (pnode, snode)

      Log(msg, indent=2)

      op = opcodes.OpInstanceCreate(instance_name=instance,
                                    disks=[{"size": size}
                                           for size in self.disk_size],
                                    disk_template=self.opts.disk_template,
                                    nics=self.opts.nics,
                                    mode=constants.INSTANCE_CREATE,
                                    os_type=self.opts.os,
                                    pnode=pnode,
                                    snode=snode,
                                    start=True,
                                    ip_check=self.opts.ip_check,
                                    name_check=self.opts.name_check,
                                    wait_for_sync=True,
                                    file_driver="loop",
                                    file_storage_dir=None,
                                    iallocator=self.opts.iallocator,
                                    beparams=self.bep,
                                    hvparams=self.hvp,
                                    hypervisor=self.hypervisor,
                                    osparams=self.opts.osparams,
                                    )
      # NB the i=instance default param is needed here so the lambda captures
      # the variable. See https://docs.python.org/2/faq/programming.html#id11
      rm_inst = lambda i=instance: self.to_rem.append(i) # pylint: disable=C0322
      self.ExecOrQueue(instance, [op], post_process=rm_inst)

  @_DoBatch(False)
  def BurnModifyRuntimeMemory(self):
    """Alter the runtime memory."""
    Log("Setting instance runtime memory")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      tgt_mem = self.bep[constants.BE_MINMEM]
      op = opcodes.OpInstanceSetParams(instance_name=instance,
                                       runtime_mem=tgt_mem)
      Log("Set memory to %s MB", tgt_mem, indent=2)
      self.ExecOrQueue(instance, [op])

  @_DoBatch(False)
  def BurnGrowDisks(self):
    """Grow both the os and the swap disks by the requested amount, if any."""
    Log("Growing disks")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      for idx, growth in enumerate(self.disk_growth):
        if growth > 0:
          op = opcodes.OpInstanceGrowDisk(instance_name=instance, disk=idx,
                                          amount=growth, wait_for_sync=True,
                                          ignore_ipolicy=True)
          Log("increase disk/%s by %s MB", idx, growth, indent=2)
          self.ExecOrQueue(instance, [op])

  @_DoBatch(True)
  def BurnReplaceDisks1D8(self):
    """Replace disks on primary and secondary for drbd8."""
    Log("Replacing disks on the same nodes")
    early_release = self.opts.early_release
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      ops = []
      for mode in constants.REPLACE_DISK_SEC, constants.REPLACE_DISK_PRI:
        op = opcodes.OpInstanceReplaceDisks(instance_name=instance,
                                            mode=mode,
                                            disks=list(range(self.disk_count)),
                                            early_release=early_release)
        Log("run %s", mode, indent=2)
        ops.append(op)
      self.ExecOrQueue(instance, ops)

  @_DoBatch(True)
  def BurnReplaceDisks2(self):
    """Replace secondary node."""
    Log("Changing the secondary node")
    mode = constants.REPLACE_DISK_CHG

    mytor = zip(islice(cycle(self.nodes), 2, None),
                 self.instances)
    for tnode, instance in mytor:
      Log("instance %s", instance, indent=1)
      if self.opts.iallocator:
        tnode = None
        msg = "with iallocator %s" % self.opts.iallocator
      else:
        msg = tnode
      op = opcodes.OpInstanceReplaceDisks(instance_name=instance,
                                          mode=mode,
                                          remote_node=tnode,
                                          iallocator=self.opts.iallocator,
                                          disks=[],
                                          early_release=self.opts.early_release)
      Log("run %s %s", mode, msg, indent=2)
      self.ExecOrQueue(instance, [op])

  @_DoCheckInstances
  @_DoBatch(False)
  def BurnFailover(self):
    """Failover the instances."""
    Log("Failing over instances")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op = opcodes.OpInstanceFailover(instance_name=instance,
                                      ignore_consistency=False)
      self.ExecOrQueue(instance, [op])

  @_DoCheckInstances
  @_DoBatch(False)
  def BurnMove(self):
    """Move the instances."""
    Log("Moving instances")
    mytor = zip(islice(cycle(self.nodes), 1, None),
                 self.instances)
    for tnode, instance in mytor:
      Log("instance %s", instance, indent=1)
      op = opcodes.OpInstanceMove(instance_name=instance,
                                  target_node=tnode)
      self.ExecOrQueue(instance, [op])

  @_DoBatch(False)
  def BurnMigrate(self):
    """Migrate the instances."""
    Log("Migrating instances")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op1 = opcodes.OpInstanceMigrate(instance_name=instance, mode=None,
                                      cleanup=False)

      op2 = opcodes.OpInstanceMigrate(instance_name=instance, mode=None,
                                      cleanup=True)
      Log("migration and migration cleanup", indent=2)
      self.ExecOrQueue(instance, [op1, op2])

  @_DoCheckInstances
  @_DoBatch(False)
  def BurnImportExport(self):
    """Export the instance, delete it, and import it back.

    """
    Log("Exporting and re-importing instances")
    mytor = zip(cycle(self.nodes),
                 islice(cycle(self.nodes), 1, None),
                 islice(cycle(self.nodes), 2, None),
                 self.instances)

    qcl = GetClient()
    for pnode, snode, enode, instance in mytor:
      Log("instance %s", instance, indent=1)
      # read the full name of the instance
      (full_name, ) = qcl.QueryInstances([instance], ["name"], False)[0]

      if self.opts.iallocator:
        pnode = snode = None
        import_log_msg = ("import from %s"
                          " with iallocator %s" %
                          (enode, self.opts.iallocator))
      elif self.opts.disk_template not in constants.DTS_INT_MIRROR:
        snode = None
        import_log_msg = ("import from %s to %s" %
                          (enode, pnode))
      else:
        import_log_msg = ("import from %s to %s, %s" %
                          (enode, pnode, snode))

      exp_op = opcodes.OpBackupExport(instance_name=instance,
                                      target_node=enode,
                                      mode=constants.EXPORT_MODE_LOCAL,
                                      shutdown=True)
      rem_op = opcodes.OpInstanceRemove(instance_name=instance,
                                        ignore_failures=True)
      imp_dir = utils.PathJoin(pathutils.EXPORT_DIR, full_name)
      imp_op = opcodes.OpInstanceCreate(instance_name=instance,
                                        disks=[{"size": size}
                                               for size in self.disk_size],
                                        disk_template=self.opts.disk_template,
                                        nics=self.opts.nics,
                                        mode=constants.INSTANCE_IMPORT,
                                        src_node=enode,
                                        src_path=imp_dir,
                                        pnode=pnode,
                                        snode=snode,
                                        start=True,
                                        ip_check=self.opts.ip_check,
                                        name_check=self.opts.name_check,
                                        wait_for_sync=True,
                                        file_storage_dir=None,
                                        file_driver="loop",
                                        iallocator=self.opts.iallocator,
                                        beparams=self.bep,
                                        hvparams=self.hvp,
                                        osparams=self.opts.osparams,
                                        )

      erem_op = opcodes.OpBackupRemove(instance_name=instance)

      Log("export to node %s", enode, indent=2)
      Log("remove instance", indent=2)
      Log(import_log_msg, indent=2)
      Log("remove export", indent=2)
      self.ExecOrQueue(instance, [exp_op, rem_op, imp_op, erem_op])
    qcl.Close()

  @staticmethod
  def StopInstanceOp(instance):
    """Stop given instance."""
    return opcodes.OpInstanceShutdown(instance_name=instance)

  @staticmethod
  def StartInstanceOp(instance):
    """Start given instance."""
    return opcodes.OpInstanceStartup(instance_name=instance, force=False)

  @staticmethod
  def RenameInstanceOp(instance, instance_new, name_check, ip_check):
    """Rename instance."""
    return opcodes.OpInstanceRename(instance_name=instance,
                                    new_name=instance_new,
                                    name_check=name_check,
                                    ip_check=ip_check)

  @_DoCheckInstances
  @_DoBatch(True)
  def BurnStopStart(self):
    """Stop/start the instances."""
    Log("Stopping and starting instances")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op1 = self.StopInstanceOp(instance)
      op2 = self.StartInstanceOp(instance)
      self.ExecOrQueue(instance, [op1, op2])

  @_DoBatch(False)
  def BurnRemove(self):
    """Remove the instances."""
    Log("Removing instances")
    for instance in self.to_rem:
      Log("instance %s", instance, indent=1)
      op = opcodes.OpInstanceRemove(instance_name=instance,
                                    ignore_failures=True)
      self.ExecOrQueue(instance, [op])

  def BurnRename(self, name_check, ip_check):
    """Rename the instances.

    Note that this function will not execute in parallel, since we
    only have one target for rename.

    """
    Log("Renaming instances")
    rename = self.opts.rename
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op_stop1 = self.StopInstanceOp(instance)
      op_stop2 = self.StopInstanceOp(rename)
      op_rename1 = self.RenameInstanceOp(instance, rename, name_check, ip_check)
      op_rename2 = self.RenameInstanceOp(rename, instance, name_check, ip_check)
      op_start1 = self.StartInstanceOp(rename)
      op_start2 = self.StartInstanceOp(instance)
      self.ExecOp(False, op_stop1, op_rename1, op_start1)
      self._CheckInstanceAlive(rename)
      self.ExecOp(False, op_stop2, op_rename2, op_start2)
      self._CheckInstanceAlive(instance)

  @_DoCheckInstances
  @_DoBatch(True)
  def BurnReinstall(self):
    """Reinstall the instances."""
    Log("Reinstalling instances")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op1 = self.StopInstanceOp(instance)
      op2 = opcodes.OpInstanceReinstall(instance_name=instance)
      Log("reinstall without passing the OS", indent=2)
      op3 = opcodes.OpInstanceReinstall(instance_name=instance,
                                        os_type=self.opts.os)
      Log("reinstall specifying the OS", indent=2)
      op4 = self.StartInstanceOp(instance)
      self.ExecOrQueue(instance, [op1, op2, op3, op4])

  @_DoCheckInstances
  @_DoBatch(True)
  def BurnReboot(self):
    """Reboot the instances."""
    Log("Rebooting instances")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      ops = []
      for reboot_type in self.opts.reboot_types:
        op = opcodes.OpInstanceReboot(instance_name=instance,
                                      reboot_type=reboot_type,
                                      ignore_secondaries=False)
        Log("reboot with type '%s'", reboot_type, indent=2)
        ops.append(op)
      self.ExecOrQueue(instance, ops)

  @_DoCheckInstances
  @_DoBatch(True)
  def BurnRenameSame(self, name_check, ip_check):
    """Rename the instances to their own name."""
    Log("Renaming the instances to their own name")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op1 = self.StopInstanceOp(instance)
      op2 = self.RenameInstanceOp(instance, instance, name_check, ip_check)
      Log("rename to the same name", indent=2)
      op4 = self.StartInstanceOp(instance)
      self.ExecOrQueue(instance, [op1, op2, op4])

  @_DoCheckInstances
  @_DoBatch(True)
  def BurnActivateDisks(self):
    """Activate and deactivate disks of the instances."""
    Log("Activating/deactivating disks")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op_start = self.StartInstanceOp(instance)
      op_act = opcodes.OpInstanceActivateDisks(instance_name=instance)
      op_deact = opcodes.OpInstanceDeactivateDisks(instance_name=instance)
      op_stop = self.StopInstanceOp(instance)
      Log("activate disks when online", indent=2)
      Log("activate disks when offline", indent=2)
      Log("deactivate disks (when offline)", indent=2)
      self.ExecOrQueue(instance, [op_act, op_stop, op_act, op_deact, op_start])

  @_DoBatch(False)
  def BurnAddRemoveNICs(self):
    """Add, change and remove an extra NIC for the instances."""
    Log("Adding and removing NICs")
    for instance in self.instances:
      Log("instance %s", instance, indent=1)
      op_add = opcodes.OpInstanceSetParams(
        instance_name=instance, nics=[(constants.DDM_ADD, {})])
      op_chg = opcodes.OpInstanceSetParams(
        instance_name=instance, nics=[(constants.DDM_MODIFY,
                                       -1, {"mac": constants.VALUE_GENERATE})])
      op_rem = opcodes.OpInstanceSetParams(
        instance_name=instance, nics=[(constants.DDM_REMOVE, {})])
      Log("adding a NIC", indent=2)
      Log("changing a NIC", indent=2)
      Log("removing last NIC", indent=2)
      self.ExecOrQueue(instance, [op_add, op_chg, op_rem])

  def ConfdCallback(self, reply):
    """Callback for confd queries"""
    if reply.type == confd_client.UPCALL_REPLY:
      if reply.server_reply.status != constants.CONFD_REPL_STATUS_OK:
        Err("Query %s gave non-ok status %s: %s" % (reply.orig_request,
                                                    reply.server_reply.status,
                                                    reply.server_reply))
      if reply.orig_request.type == constants.CONFD_REQ_PING:
        Log("Ping: OK", indent=1)
      elif reply.orig_request.type == constants.CONFD_REQ_CLUSTER_MASTER:
        if reply.server_reply.answer == self.cluster_info["master"]:
          Log("Master: OK", indent=1)
        else:
          Err("Master: wrong: %s" % reply.server_reply.answer)
      elif reply.orig_request.type == constants.CONFD_REQ_NODE_ROLE_BYNAME:
        if reply.server_reply.answer == constants.CONFD_NODE_ROLE_MASTER:
          Log("Node role for master: OK", indent=1)
        else:
          Err("Node role for master: wrong: %s" % reply.server_reply.answer)
      elif reply.orig_request.type == constants.CONFD_REQ_INSTANCE_DISKS:
        self.confd_reply = reply.server_reply.answer

  def DoConfdRequestReply(self, req):
    self.confd_counting_callback.RegisterQuery(req.rsalt)
    self.confd_client.SendRequest(req, async_=False)
    while not self.confd_counting_callback.AllAnswered():
      if not self.confd_client.ReceiveReply():
        Err("Did not receive all expected confd replies")
        break

  def BurnConfd(self):
    """Run confd queries for our instances.

    The following confd queries are tested:
      - CONFD_REQ_PING: simple ping
      - CONFD_REQ_CLUSTER_MASTER: cluster master
      - CONFD_REQ_NODE_ROLE_BYNAME: node role, for the master

    """
    Log("Checking confd results")

    filter_callback = confd_client.ConfdFilterCallback(self.ConfdCallback)
    counting_callback = confd_client.ConfdCountingCallback(filter_callback)
    self.confd_counting_callback = counting_callback

    self.confd_client = confd_client.GetConfdClient(counting_callback)

    req = confd_client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
    self.DoConfdRequestReply(req)

    req = confd_client.ConfdClientRequest(
      type=constants.CONFD_REQ_CLUSTER_MASTER)
    self.DoConfdRequestReply(req)

    req = confd_client.ConfdClientRequest(
        type=constants.CONFD_REQ_NODE_ROLE_BYNAME,
        query=self.cluster_info["master"])
    self.DoConfdRequestReply(req)

  @_DoCheckInstances
  @_DoBatch(False)
  def BurnAddDisks(self):
    """Add an extra disk to every instance and then detach it."""
    Log("Adding and detaching disks")

    # Instantiate a Confd client
    filter_callback = confd_client.ConfdFilterCallback(self.ConfdCallback)
    counting_callback = confd_client.ConfdCountingCallback(filter_callback)
    self.confd_counting_callback = counting_callback
    self.confd_client = confd_client.GetConfdClient(counting_callback)

    # Iterate all instances, start them, add a disk with a unique name and
    # detach it. Do all disk operations with hotplugging (if possible).
    for instance in self.instances:
      Log("instance %s", instance, indent=1)

      # Fetch disk info for an instance from the confd. The result of the query
      # will be stored in the confd_reply attribute of Burner.
      req = (confd_client.ConfdClientRequest(
        type=constants.CONFD_REQ_INSTANCE_DISKS, query=instance))
      self.DoConfdRequestReply(req)

      disk_name = RandomString()

      nodes = [set(disk["nodes"]) for disk in self.confd_reply]
      nodes = reduce(or_, nodes)
      self.instance_nodes[instance] = nodes
      self.disk_nodes[disk_name] = nodes

      op_stop = self.StopInstanceOp(instance)
      op_add = opcodes.OpInstanceSetParams(
        instance_name=instance,
        disks=[(constants.DDM_ADD, {"size": self.disk_size[0],
                                    "name": disk_name})])
      op_detach = opcodes.OpInstanceSetParams(
        instance_name=instance,
        disks=[(constants.DDM_DETACH, {})])
      op_start = self.StartInstanceOp(instance)
      Log("adding a disk with name %s" % disk_name, indent=2)
      Log("detaching last disk", indent=2)
      self.ExecOrQueue(instance, [op_start, op_add, op_detach, op_stop,
                                  op_start])

  @_DoCheckInstances
  @_DoBatch(False)
  def BurnRemoveDisks(self):
    """Attach a previously detached disk to an instance and then remove it."""
    Log("Attaching and removing disks")

    # Iterate all instances in random order, attach the detached disks, remove
    # them and then restart the instances. Do all disk operation with
    # hotplugging (if possible).
    instances_copy = list(self.instances)
    random.shuffle(instances_copy)
    for instance in instances_copy:
      Log("instance %s", instance, indent=1)

      disk_name = self.FindMatchingDisk(instance)
      op_attach = opcodes.OpInstanceSetParams(
        instance_name=instance,
        disks=[(constants.DDM_ATTACH, {"name": disk_name})])
      op_rem = opcodes.OpInstanceSetParams(
        instance_name=instance,
        disks=[(constants.DDM_REMOVE, {})])
      op_stop = self.StopInstanceOp(instance)
      op_start = self.StartInstanceOp(instance)
      Log("attaching a disk with name %s" % disk_name, indent=2)
      Log("removing last disk", indent=2)
      self.ExecOrQueue(instance, [op_attach, op_rem, op_stop, op_start])

    # Disk nodes are useful only for this test.
    del self.disk_nodes
    del self.instance_nodes

  def _CheckInstanceAlive(self, instance):
    """Check if an instance is alive by doing http checks.

    This will try to retrieve the url on the instance /hostname.txt
    and check that it contains the hostname of the instance. In case
    we get ECONNREFUSED, we retry up to the net timeout seconds, for
    any other error we abort.

    """
    if not self.opts.http_check:
      return
    end_time = time.time() + self.opts.net_timeout
    url = None
    while time.time() < end_time and url is None:
      try:
        url = self.url_opener.open("http://%s/hostname.txt" % instance)
      except IOError:
        # here we can have connection refused, no route to host, etc.
        time.sleep(1)
    if url is None:
      raise InstanceDown(instance, "Cannot contact instance")
    hostname = url.read().strip()
    url.close()
    if hostname != instance:
      raise InstanceDown(instance, ("Hostname mismatch, expected %s, got %s" %
                                    (instance, hostname)))

  def BurninCluster(self):
    """Test a cluster intensively.

    This will create instances and then start/stop/failover them.
    It is safe for existing instances but could impact performance.

    """

    Log("Testing global parameters")

    if (len(self.nodes) == 1 and
        self.opts.disk_template not in _SINGLE_NODE_DISK_TEMPLATES):
      Err("When one node is available/selected the disk template must"
          " be one of %s" % utils.CommaJoin(_SINGLE_NODE_DISK_TEMPLATES))

    has_err = True
    try:
      self.BurnCreateInstances()

      if self.opts.do_startstop:
        self.BurnStopStart()

      if self.bep[constants.BE_MINMEM] < self.bep[constants.BE_MAXMEM]:
        self.BurnModifyRuntimeMemory()

      if self.opts.do_replace1 and \
           self.opts.disk_template in constants.DTS_INT_MIRROR:
        self.BurnReplaceDisks1D8()
      if (self.opts.do_replace2 and len(self.nodes) > 2 and
          self.opts.disk_template in constants.DTS_INT_MIRROR):
        self.BurnReplaceDisks2()

      if (self.opts.disk_template in constants.DTS_GROWABLE and
          compat.any(n > 0 for n in self.disk_growth)):
        self.BurnGrowDisks()

      if self.opts.do_failover and \
           self.opts.disk_template in constants.DTS_MIRRORED:
        self.BurnFailover()

      if self.opts.do_migrate:
        if self.opts.disk_template not in constants.DTS_MIRRORED:
          Log("Skipping migration (disk template %s does not support it)",
              self.opts.disk_template)
        elif not self.hv_can_migrate:
          Log("Skipping migration (hypervisor %s does not support it)",
              self.hypervisor)
        else:
          self.BurnMigrate()

      if (self.opts.do_move and len(self.nodes) > 1 and
          self.opts.disk_template in [constants.DT_PLAIN, constants.DT_FILE]):
        self.BurnMove()

      if (self.opts.do_importexport and
          self.opts.disk_template in _IMPEXP_DISK_TEMPLATES):
        self.BurnImportExport()

      if self.opts.do_reinstall:
        self.BurnReinstall()

      if self.opts.do_reboot:
        self.BurnReboot()

      if self.opts.do_renamesame:
        self.BurnRenameSame(self.opts.name_check, self.opts.ip_check)

      if self.opts.do_confd_tests:
        self.BurnConfd()

      default_nic_mode = self.cluster_default_nicparams[constants.NIC_MODE]
      # Don't add/remove nics in routed mode, as we would need an ip to add
      # them with
      if self.opts.do_addremove_nics:
        if default_nic_mode == constants.NIC_MODE_BRIDGED:
          self.BurnAddRemoveNICs()
        else:
          Log("Skipping nic add/remove as the cluster is not in bridged mode")

      if self.opts.do_activate_disks:
        self.BurnActivateDisks()

      if self.opts.do_addremove_disks:
        self.BurnAddDisks()
        self.BurnRemoveDisks()

      if self.opts.rename:
        self.BurnRename(self.opts.name_check, self.opts.ip_check)

      has_err = False
    finally:
      if has_err:
        Log("Error detected: opcode buffer follows:\n\n")
        Log(self.GetFeedbackBuf())
        Log("\n\n")
      if not self.opts.keep_instances:
        try:
          self.BurnRemove()
        except Exception as err:  # pylint: disable=W0703
          if has_err: # already detected errors, so errors in removal
                      # are quite expected
            Log("Note: error detected during instance remove: %s", err)
          else: # non-expected error
            raise

    return constants.EXIT_SUCCESS


def Main():
  """Main function.

  """
  utils.SetupLogging(pathutils.LOG_BURNIN, sys.argv[0],
                     debug=False, stderr_logging=True)

  return Burner().BurninCluster()
