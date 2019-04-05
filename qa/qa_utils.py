#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
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


"""Utilities for QA tests.

"""

from __future__ import print_function

import contextlib
import copy
import datetime
import operator
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import yaml

try:
  import functools
except ImportError as err:
  raise ImportError("Python 2.5 or higher is required: %s" % err)

from ganeti import utils
from ganeti import compat
from ganeti import constants
from ganeti import ht
from ganeti import pathutils
from ganeti import vcluster

import colors
import qa_config
import qa_error

from qa_logging import FormatInfo


_MULTIPLEXERS = {}

#: Unique ID per QA run
_RUN_UUID = utils.NewUUID()

#: Path to the QA query output log file
_QA_OUTPUT = pathutils.GetLogFilename("qa-output")


_RETRIES = 3


(INST_DOWN,
 INST_UP) = range(500, 502)

(FIRST_ARG,
 RETURN_VALUE) = range(1000, 1002)


def _RaiseWithInfo(msg, error_desc):
  """Raises a QA error with the given content, and adds a message if present.

  """
  if msg:
    output = "%s: %s" % (msg, error_desc)
  else:
    output = error_desc
  raise qa_error.Error(output)


def AssertIn(item, sequence, msg=None):
  """Raises an error when item is not in sequence.

  """
  if item not in sequence:
    _RaiseWithInfo(msg, "%r not in %r" % (item, sequence))


def AssertNotIn(item, sequence, msg=None):
  """Raises an error when item is in sequence.

  """
  if item in sequence:
    _RaiseWithInfo(msg, "%r in %r" % (item, sequence))


def AssertEqual(first, second, msg=None):
  """Raises an error when values aren't equal.

  """
  if not first == second:
    _RaiseWithInfo(msg, "%r == %r" % (first, second))


def AssertMatch(string, pattern, msg=None):
  """Raises an error when string doesn't match regexp pattern.

  """
  if not re.match(pattern, string):
    _RaiseWithInfo(msg, "%r doesn't match /%r/" % (string, pattern))


def _GetName(entity, fn):
  """Tries to get name of an entity.

  @type entity: string or dict
  @param fn: Function retrieving name from entity

  """
  if isinstance(entity, str):
    result = entity
  else:
    result = fn(entity)

  if not ht.TNonEmptyString(result):
    raise Exception("Invalid name '%s'" % result)

  return result


def _AssertRetCode(rcode, fail, cmdstr, nodename):
  """Check the return value from a command and possibly raise an exception.

  """
  if fail and rcode == 0:
    raise qa_error.Error("Command '%s' on node %s was expected to fail but"
                         " didn't" % (cmdstr, nodename))
  elif not fail and rcode != 0:
    raise qa_error.Error("Command '%s' on node %s failed, exit code %s" %
                         (cmdstr, nodename, rcode))


def _PrintCommandOutput(stdout, stderr):
  """Prints the output of commands, minimizing wasted space.

  @type stdout: string
  @type stderr: string

  """
  if stdout:
    stdout_clean = stdout.rstrip('\n')
    if stderr:
      print("Stdout was:\n%s" % stdout_clean)
    else:
      print(stdout_clean)

  if stderr:
    print("Stderr was:")
    print(stderr.rstrip('\n'), file=sys.stderr)


def AssertCommand(cmd, fail=False, node=None, log_cmd=True, forward_agent=True,
                  max_seconds=None):
  """Checks that a remote command succeeds.

  @param cmd: either a string (the command to execute) or a list (to
      be converted using L{utils.ShellQuoteArgs} into a string)
  @type fail: boolean or None
  @param fail: if the command is expected to fail instead of succeeding,
               or None if we don't care
  @param node: if passed, it should be the node on which the command
      should be executed, instead of the master node (can be either a
      dict or a string)
  @param log_cmd: if False, the command won't be logged (simply passed to
      StartSSH)
  @type forward_agent: boolean
  @param forward_agent: whether to forward the agent when starting the SSH
                        session or not, sometimes useful for crypto-related
                        operations which can use a key they should not
  @type max_seconds: double
  @param max_seconds: fail if the command takes more than C{max_seconds}
      seconds
  @return: the return code, stdout and stderr of the command
  @raise qa_error.Error: if the command fails when it shouldn't or vice versa

  """
  if node is None:
    node = qa_config.GetMasterNode()

  nodename = _GetName(node, operator.attrgetter("primary"))

  if isinstance(cmd, str):
    cmdstr = cmd
  else:
    cmdstr = utils.ShellQuoteArgs(cmd)

  start = datetime.datetime.now()
  popen = StartSSH(nodename, cmdstr, log_cmd=log_cmd,
                   forward_agent=forward_agent)
  # Run the command
  stdout, stderr = popen.communicate()
  rcode = popen.returncode
  duration_seconds = TimedeltaToTotalSeconds(datetime.datetime.now() - start)

  try:
    if fail is not None:
      _AssertRetCode(rcode, fail, cmdstr, nodename)
  finally:
    if log_cmd:
      _PrintCommandOutput(stdout, stderr)

  if max_seconds is not None:
    if duration_seconds > max_seconds:
      raise qa_error.Error(
        "Cmd '%s' took %f seconds, maximum of %f was exceeded" %
        (cmdstr, duration_seconds, max_seconds))

  return rcode, stdout, stderr


def stdout_of(cmd):
  """Small helper to run a stdout_of.
  Makes sure the stdout_of returns exit code 0.

  @type cmd: list of strings
  @param cmd: the stdout_of to run

  @return: Captured, stripped stdout.
  """
  _, out, _ = AssertCommand(cmd)
  return out.strip()


def AssertRedirectedCommand(cmd, fail=False, node=None, log_cmd=True):
  """Executes a command with redirected output.

  The log will go to the qa-output log file in the ganeti log
  directory on the node where the command is executed. The fail and
  node parameters are passed unchanged to AssertCommand.

  @param cmd: the command to be executed, as a list; a string is not
      supported

  """
  if not isinstance(cmd, list):
    raise qa_error.Error("Non-list passed to AssertRedirectedCommand")
  ofile = utils.ShellQuote(_QA_OUTPUT)
  cmdstr = utils.ShellQuoteArgs(cmd)
  AssertCommand("echo ---- $(date) %s ---- >> %s" % (cmdstr, ofile),
                fail=False, node=node, log_cmd=False)
  return AssertCommand(cmdstr + " >> %s" % ofile,
                       fail=fail, node=node, log_cmd=log_cmd)


def GetSSHCommand(node, cmd, strict=True, opts=None, tty=False,
                  use_multiplexer=True, forward_agent=True):
  """Builds SSH command to be executed.

  @type node: string
  @param node: node the command should run on
  @type cmd: string
  @param cmd: command to be executed in the node; if None or empty
      string, no command will be executed
  @type strict: boolean
  @param strict: whether to enable strict host key checking
  @type opts: list
  @param opts: list of additional options
  @type tty: boolean or None
  @param tty: if we should use tty; if None, will be auto-detected
  @type use_multiplexer: boolean
  @param use_multiplexer: if the multiplexer for the node should be used
  @type forward_agent: boolean
  @param forward_agent: whether to forward the ssh agent or not

  """
  args = ["ssh", "-oEscapeChar=none", "-oBatchMode=yes", "-lroot"]

  if tty is None:
    tty = sys.stdout.isatty()

  if tty:
    args.append("-t")

  # Multiplexers we use right now forward agents, so even if we ought to be
  # using one, ignore it if agent forwarding is disabled.
  if not forward_agent:
    use_multiplexer = False

  args.append("-oStrictHostKeyChecking=%s" % ("yes" if strict else "no", ))
  args.append("-oClearAllForwardings=yes")
  args.append("-oForwardAgent=%s" % ("yes" if forward_agent else "no", ))
  if opts:
    args.extend(opts)
  if node in _MULTIPLEXERS and use_multiplexer:
    spath = _MULTIPLEXERS[node][0]
    args.append("-oControlPath=%s" % spath)
    args.append("-oControlMaster=no")

  (vcluster_master, vcluster_basedir) = \
    qa_config.GetVclusterSettings()

  if vcluster_master:
    args.append(vcluster_master)
    args.append("%s/%s/cmd" % (vcluster_basedir, node))

    if cmd:
      # For virtual clusters the whole command must be wrapped using the "cmd"
      # script, as that script sets a number of environment variables. If the
      # command contains shell meta characters the whole command needs to be
      # quoted.
      args.append(utils.ShellQuote(cmd))
  else:
    args.append(node)

    if cmd:
      args.append(cmd)

  return args


def StartLocalCommand(cmd, _nolog_opts=False, log_cmd=True, **kwargs):
  """Starts a local command.

  """
  if log_cmd:
    if _nolog_opts:
      pcmd = [i for i in cmd if not i.startswith("-")]
    else:
      pcmd = cmd
    print("%s %s" % (colors.colorize("Command:", colors.CYAN),
                     utils.ShellQuoteArgs(pcmd)))
  return subprocess.Popen(cmd, shell=False, **kwargs)


def StartSSH(node, cmd, strict=True, log_cmd=True, forward_agent=True):
  """Starts SSH.

  """
  ssh_command = GetSSHCommand(node, cmd, strict=strict,
                              forward_agent=forward_agent)
  return StartLocalCommand(ssh_command, _nolog_opts=True, log_cmd=log_cmd,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def StartMultiplexer(node):
  """Starts a multiplexer command.

  @param node: the node for which to open the multiplexer

  """
  if node in _MULTIPLEXERS:
    return

  # Note: yes, we only need mktemp, since we'll remove the file anyway
  sname = tempfile.mktemp(prefix="ganeti-qa-multiplexer.")
  utils.RemoveFile(sname)
  opts = ["-N", "-oControlPath=%s" % sname, "-oControlMaster=yes"]
  print("Created socket at %s" % sname)
  child = StartLocalCommand(GetSSHCommand(node, None, opts=opts))
  _MULTIPLEXERS[node] = (sname, child)


def CloseMultiplexers():
  """Closes all current multiplexers and cleans up.

  """
  for node in list(_MULTIPLEXERS):
    (sname, child) = _MULTIPLEXERS.pop(node)
    utils.KillProcess(child.pid, timeout=10, waitpid=True)
    utils.RemoveFile(sname)


def _GetCommandStdout(proc):
  """Extract the stored standard error, print it and return it.

  """
  out = proc.stdout.read()
  sys.stdout.write(out)
  return out


def _NoTimeout(state):
  """False iff the command timed out."""
  rcode, out = state

  return rcode == 0 or not ('TimeoutError' in out or 'timed out' in out)


def GetCommandOutput(node, cmd, tty=False, use_multiplexer=True, log_cmd=True,
                     fail=False):
  """Returns the output of a command executed on the given node.

  @type node: string
  @param node: node the command should run on
  @type cmd: string
  @param cmd: command to be executed in the node (cannot be empty or None)
  @type tty: bool or None
  @param tty: if we should use tty; if None, it will be auto-detected
  @type use_multiplexer: bool
  @param use_multiplexer: if the SSH multiplexer provided by the QA should be
                          used or not
  @type log_cmd: bool
  @param log_cmd: if the command should be logged
  @type fail: bool
  @param fail: whether the command is expected to fail
  """
  assert cmd

  def CallCommand():
    command = GetSSHCommand(node, cmd, tty=tty,
                            use_multiplexer=use_multiplexer)
    p = StartLocalCommand(command, stdout=subprocess.PIPE, log_cmd=log_cmd)
    rcode = p.wait()
    out = _GetCommandStdout(p)
    return rcode, out

  # TODO: make retries configurable
  rcode, out = utils.CountRetry(_NoTimeout, CallCommand, _RETRIES)
  _AssertRetCode(rcode, fail, cmd, node)
  return out


def GetObjectInfo(infocmd):
  """Get and parse information about a Ganeti object.

  @type infocmd: list of strings
  @param infocmd: command to be executed, e.g. ["gnt-cluster", "info"]
  @return: the information parsed, appropriately stored in dictionaries,
      lists...

  """
  master = qa_config.GetMasterNode()
  cmdline = utils.ShellQuoteArgs(infocmd)
  info_out = GetCommandOutput(master.primary, cmdline)
  return yaml.load(info_out)


def UploadFile(node, src):
  """Uploads a file to a node and returns the filename.

  Caller needs to remove the returned file on the node when it's not needed
  anymore.

  """
  # Make sure nobody else has access to it while preserving local permissions
  mode = os.stat(src).st_mode & 0o700

  cmd = ('tmp=$(mktemp --tmpdir gnt.XXXXXX) && '
         'chmod %o "${tmp}" && '
         '[[ -f "${tmp}" ]] && '
         'cat > "${tmp}" && '
         'echo "${tmp}"') % mode

  f = open(src, "r")
  try:
    p = subprocess.Popen(GetSSHCommand(node, cmd), shell=False, stdin=f,
                         stdout=subprocess.PIPE)
    AssertEqual(p.wait(), 0)

    # Return temporary filename
    return _GetCommandStdout(p).strip()
  finally:
    f.close()


def UploadData(node, data, mode=0o600, filename=None):
  """Uploads data to a node and returns the filename.

  Caller needs to remove the returned file on the node when it's not needed
  anymore.

  """
  if filename:
    tmp = "tmp=%s" % utils.ShellQuote(filename)
  else:
    tmp = ('tmp=$(mktemp --tmpdir gnt.XXXXXX) && '
           'chmod %o "${tmp}"') % mode
  cmd = ("%s && "
         "[[ -f \"${tmp}\" ]] && "
         "cat > \"${tmp}\" && "
         "echo \"${tmp}\"") % tmp

  p = subprocess.Popen(GetSSHCommand(node, cmd), shell=False,
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
  p.stdin.write(data)
  p.stdin.close()
  AssertEqual(p.wait(), 0)

  # Return temporary filename
  return _GetCommandStdout(p).strip()


def BackupFile(node, path):
  """Creates a backup of a file on the node and returns the filename.

  Caller needs to remove the returned file on the node when it's not needed
  anymore.

  """
  vpath = MakeNodePath(node, path)

  cmd = ("tmp=$(mktemp .gnt.XXXXXX --tmpdir=$(dirname %s)) && "
         "[[ -f \"$tmp\" ]] && "
         "cp %s $tmp && "
         "echo $tmp") % (utils.ShellQuote(vpath), utils.ShellQuote(vpath))

  # Return temporary filename
  result = GetCommandOutput(node, cmd).strip()

  print("Backup filename: %s" % result)

  return result


@contextlib.contextmanager
def CheckFileUnmodified(node, filename):
  """Checks that the content of a given file remains the same after running a
  wrapped code.

  @type node: string
  @param node: node the command should run on
  @type filename: string
  @param filename: absolute filename to check

  """
  cmd = utils.ShellQuoteArgs(["sha1sum", MakeNodePath(node, filename)])

  def Read():
    return GetCommandOutput(node, cmd).strip()

  # read the configuration
  before = Read()
  yield
  # check that the configuration hasn't changed
  after = Read()
  if before != after:
    raise qa_error.Error("File '%s' has changed unexpectedly on node %s"
                         " during the last operation" % (filename, node))


def ResolveInstanceName(instance):
  """Gets the full name of an instance.

  @type instance: string
  @param instance: Instance name

  """
  info = GetObjectInfo(["gnt-instance", "info", instance])
  return info[0]["Instance name"]


def ResolveNodeName(node):
  """Gets the full name of a node.

  """
  info = GetObjectInfo(["gnt-node", "info", node.primary])
  return info[0]["Node name"]


def GetNodeInstances(node, secondaries=False):
  """Gets a list of instances on a node.

  """
  master = qa_config.GetMasterNode()
  node_name = ResolveNodeName(node)

  # Get list of all instances
  cmd = ["gnt-instance", "list", "--separator=:", "--no-headers",
         "--output=name,pnode,snodes"]
  output = GetCommandOutput(master.primary, utils.ShellQuoteArgs(cmd))

  instances = []
  for line in output.splitlines():
    (name, pnode, snodes) = line.split(":", 2)
    if ((not secondaries and pnode == node_name) or
        (secondaries and node_name in snodes.split(","))):
      instances.append(name)

  return instances


def _SelectQueryFields(rnd, fields):
  """Generates a list of fields for query tests.

  """
  # Create copy for shuffling
  fields = list(fields)
  rnd.shuffle(fields)

  # Check all fields
  yield fields
  yield sorted(fields)

  # Duplicate fields
  yield fields + fields

  # Check small groups of fields
  while fields:
    yield [fields.pop() for _ in range(rnd.randint(2, 10)) if fields]


def _List(listcmd, fields, names):
  """Runs a list command.

  """
  master = qa_config.GetMasterNode()

  cmd = [listcmd, "list", "--separator=|", "--no-headers",
         "--output", ",".join(fields)]

  if names:
    cmd.extend(names)

  return GetCommandOutput(master.primary,
                          utils.ShellQuoteArgs(cmd)).splitlines()


def GenericQueryTest(cmd, fields, namefield="name", test_unknown=True):
  """Runs a number of tests on query commands.

  @param cmd: Command name
  @param fields: List of field names

  """
  rnd = random.Random(hash(cmd))

  fields = list(fields)
  rnd.shuffle(fields)

  # Test a number of field combinations
  for testfields in _SelectQueryFields(rnd, fields):
    AssertRedirectedCommand([cmd, "list", "--output", ",".join(testfields)])

  if namefield is not None:
    namelist_fn = compat.partial(_List, cmd, [namefield])

    # When no names were requested, the list must be sorted
    names = namelist_fn(None)
    AssertEqual(names, utils.NiceSort(names))

    # When requesting specific names, the order must be kept
    revnames = list(reversed(names))
    AssertEqual(namelist_fn(revnames), revnames)

    randnames = list(names)
    rnd.shuffle(randnames)
    AssertEqual(namelist_fn(randnames), randnames)

  if test_unknown:
    # Listing unknown items must fail
    AssertCommand([cmd, "list", "this.name.certainly.does.not.exist"],
                  fail=True)

  # Check exit code for listing unknown field
  rcode, _, _ = AssertRedirectedCommand([cmd, "list",
                                         "--output=field/does/not/exist"],
                                        fail=True)
  AssertEqual(rcode, constants.EXIT_UNKNOWN_FIELD)


def GenericQueryFieldsTest(cmd, fields):
  master = qa_config.GetMasterNode()

  # Listing fields
  AssertRedirectedCommand([cmd, "list-fields"])
  AssertRedirectedCommand([cmd, "list-fields"] + fields)

  # Check listed fields (all, must be sorted)
  realcmd = [cmd, "list-fields", "--separator=|", "--no-headers"]
  output = GetCommandOutput(master.primary,
                            utils.ShellQuoteArgs(realcmd)).splitlines()
  AssertEqual([line.split("|", 1)[0] for line in output],
              utils.NiceSort(fields))

  # Check exit code for listing unknown field
  rcode, _, _ = AssertCommand([cmd, "list-fields", "field/does/not/exist"],
                              fail=True)
  AssertEqual(rcode, constants.EXIT_UNKNOWN_FIELD)


def AddToEtcHosts(hostnames):
  """Adds hostnames to /etc/hosts.

  @param hostnames: List of hostnames first used A records, all other CNAMEs

  """
  master = qa_config.GetMasterNode()
  tmp_hosts = UploadData(master.primary, "", mode=0o644)

  data = []
  for localhost in ("::1", "127.0.0.1"):
    data.append("%s %s" % (localhost, " ".join(hostnames)))

  try:
    AssertCommand("{ cat %s && echo -e '%s'; } > %s && mv %s %s" %
                  (utils.ShellQuote(pathutils.ETC_HOSTS),
                   "\\n".join(data),
                   utils.ShellQuote(tmp_hosts),
                   utils.ShellQuote(tmp_hosts),
                   utils.ShellQuote(pathutils.ETC_HOSTS)))
  except Exception:
    AssertCommand(["rm", "-f", tmp_hosts])
    raise


def RemoveFromEtcHosts(hostnames):
  """Remove hostnames from /etc/hosts.

  @param hostnames: List of hostnames first used A records, all other CNAMEs

  """
  master = qa_config.GetMasterNode()
  tmp_hosts = UploadData(master.primary, "", mode=0o644)
  quoted_tmp_hosts = utils.ShellQuote(tmp_hosts)

  sed_data = " ".join(hostnames)
  try:
    AssertCommand((r"sed -e '/^\(::1\|127\.0\.0\.1\)\s\+%s/d' %s > %s"
                   r" && mv %s %s") %
                   (sed_data, utils.ShellQuote(pathutils.ETC_HOSTS),
                    quoted_tmp_hosts, quoted_tmp_hosts,
                    utils.ShellQuote(pathutils.ETC_HOSTS)))
  except Exception:
    AssertCommand(["rm", "-f", tmp_hosts])
    raise


def RunInstanceCheck(instance, running):
  """Check if instance is running or not.

  """
  instance_name = _GetName(instance, operator.attrgetter("name"))

  script = qa_config.GetInstanceCheckScript()
  if not script:
    return

  master_node = qa_config.GetMasterNode()

  # Build command to connect to master node
  master_ssh = GetSSHCommand(master_node.primary, "--")

  if running:
    running_shellval = "1"
    running_text = ""
  else:
    running_shellval = ""
    running_text = "not "

  print(FormatInfo("Checking if instance '%s' is %srunning" %
                   (instance_name, running_text)))

  args = [script, instance_name]
  env = {
    "PATH": constants.HOOKS_PATH,
    "RUN_UUID": _RUN_UUID,
    "MASTER_SSH": utils.ShellQuoteArgs(master_ssh),
    "INSTANCE_NAME": instance_name,
    "INSTANCE_RUNNING": running_shellval,
    }

  result = os.spawnve(os.P_WAIT, script, args, env)
  if result != 0:
    raise qa_error.Error("Instance check failed with result %s" % result)


def _InstanceCheckInner(expected, instarg, args, result):
  """Helper function used by L{InstanceCheck}.

  """
  if instarg == FIRST_ARG:
    instance = args[0]
  elif instarg == RETURN_VALUE:
    instance = result
  else:
    raise Exception("Invalid value '%s' for instance argument" % instarg)

  if expected in (INST_DOWN, INST_UP):
    RunInstanceCheck(instance, (expected == INST_UP))
  elif expected is not None:
    raise Exception("Invalid value '%s'" % expected)


def InstanceCheck(before, after, instarg):
  """Decorator to check instance status before and after test.

  @param before: L{INST_DOWN} if instance must be stopped before test,
    L{INST_UP} if instance must be running before test, L{None} to not check.
  @param after: L{INST_DOWN} if instance must be stopped after test,
    L{INST_UP} if instance must be running after test, L{None} to not check.
  @param instarg: L{FIRST_ARG} to use first argument to test as instance (a
    dictionary), L{RETURN_VALUE} to use return value (disallows pre-checks)

  """
  def decorator(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
      _InstanceCheckInner(before, instarg, args, NotImplemented)

      result = fn(*args, **kwargs)

      _InstanceCheckInner(after, instarg, args, result)

      return result
    return wrapper
  return decorator


def GetNonexistentGroups(count):
  """Gets group names which shouldn't exist on the cluster.

  @param count: Number of groups to get
  @rtype: integer

  """
  return GetNonexistentEntityNames(count, "groups", "group")


def GetNonexistentEntityNames(count, name_config, name_prefix):
  """Gets entity names which shouldn't exist on the cluster.

  The actualy names can refer to arbitrary entities (for example
  groups, networks).

  @param count: Number of names to get
  @rtype: integer
  @param name_config: name of the leaf in the config containing
    this entity's configuration, including a 'inexistent-'
    element
  @rtype: string
  @param name_prefix: prefix of the entity's names, used to compose
    the default values; for example for groups, the prefix is
    'group' and the generated names are then group1, group2, ...
  @rtype: string

  """
  entities = qa_config.get(name_config, {})

  default = [name_prefix + str(i) for i in range(count)]
  assert count <= len(default)

  name_config_inexistent = "inexistent-" + name_config
  candidates = entities.get(name_config_inexistent, default)[:count]

  if len(candidates) < count:
    raise Exception("At least %s non-existent %s are needed" %
                    (count, name_config))

  return candidates


def MakeNodePath(node, path):
  """Builds an absolute path for a virtual node.

  @type node: string or L{qa_config._QaNode}
  @param node: Node
  @type path: string
  @param path: Path without node-specific prefix

  """
  (_, basedir) = qa_config.GetVclusterSettings()

  if isinstance(node, str):
    name = node
  else:
    name = node.primary

  if basedir:
    assert path.startswith("/")
    return "%s%s" % (vcluster.MakeNodeRoot(basedir, name), path)
  else:
    return path


def _GetParameterOptions(specs):
  """Helper to build policy options."""
  values = ["%s=%s" % (par, val)
            for (par, val) in specs.items()]
  return ",".join(values)


def TestSetISpecs(new_specs=None, diff_specs=None, get_policy_fn=None,
                  build_cmd_fn=None, fail=False, old_values=None):
  """Change instance specs for an object.

  At most one of new_specs or diff_specs can be specified.

  @type new_specs: dict
  @param new_specs: new complete specs, in the same format returned by
      L{ParseIPolicy}.
  @type diff_specs: dict
  @param diff_specs: partial specs, it can be an incomplete specifications, but
      if min/max specs are specified, their number must match the number of the
      existing specs
  @type get_policy_fn: function
  @param get_policy_fn: function that returns the current policy as in
      L{ParseIPolicy}
  @type build_cmd_fn: function
  @param build_cmd_fn: function that return the full command line from the
      options alone
  @type fail: bool
  @param fail: if the change is expected to fail
  @type old_values: tuple
  @param old_values: (old_policy, old_specs), as returned by
     L{ParseIPolicy}
  @return: same as L{ParseIPolicy}

  """
  assert get_policy_fn is not None
  assert build_cmd_fn is not None
  assert new_specs is None or diff_specs is None

  if old_values:
    (old_policy, old_specs) = old_values
  else:
    (old_policy, old_specs) = get_policy_fn()

  if diff_specs:
    new_specs = copy.deepcopy(old_specs)
    if constants.ISPECS_MINMAX in diff_specs:
      AssertEqual(len(new_specs[constants.ISPECS_MINMAX]),
                  len(diff_specs[constants.ISPECS_MINMAX]))
      for (new_minmax, diff_minmax) in zip(new_specs[constants.ISPECS_MINMAX],
                                           diff_specs[constants.ISPECS_MINMAX]):
        for (key, parvals) in diff_minmax.items():
          for (par, val) in parvals.items():
            new_minmax[key][par] = val
    for (par, val) in diff_specs.get(constants.ISPECS_STD, {}).items():
      new_specs[constants.ISPECS_STD][par] = val

  if new_specs:
    cmd = []
    if (diff_specs is None or constants.ISPECS_MINMAX in diff_specs):
      minmax_opt_items = []
      for minmax in new_specs[constants.ISPECS_MINMAX]:
        minmax_opts = []
        for key in ["min", "max"]:
          keyopt = _GetParameterOptions(minmax[key])
          minmax_opts.append("%s:%s" % (key, keyopt))
        minmax_opt_items.append("/".join(minmax_opts))
      cmd.extend([
        "--ipolicy-bounds-specs",
        "//".join(minmax_opt_items)
        ])
    if diff_specs is None:
      std_source = new_specs
    else:
      std_source = diff_specs
    std_opt = _GetParameterOptions(std_source.get("std", {}))
    if std_opt:
      cmd.extend(["--ipolicy-std-specs", std_opt])
    AssertCommand(build_cmd_fn(cmd), fail=fail)

    # Check the new state
    (eff_policy, eff_specs) = get_policy_fn()
    AssertEqual(eff_policy, old_policy)
    if fail:
      AssertEqual(eff_specs, old_specs)
    else:
      AssertEqual(eff_specs, new_specs)

  else:
    (eff_policy, eff_specs) = (old_policy, old_specs)

  return (eff_policy, eff_specs)


def ParseIPolicy(policy):
  """Parse and split instance an instance policy.

  @type policy: dict
  @param policy: policy, as returned by L{GetObjectInfo}
  @rtype: tuple
  @return: (policy, specs), where:
      - policy is a dictionary of the policy values, instance specs excluded
      - specs is a dictionary containing only the specs, using the internal
        format (see L{constants.IPOLICY_DEFAULTS} for an example)

  """
  ret_specs = {}
  ret_policy = {}
  for (key, val) in policy.items():
    if key == "bounds specs":
      ret_specs[constants.ISPECS_MINMAX] = []
      for minmax in val:
        ret_minmax = {}
        for key in minmax:
          keyparts = key.split("/", 1)
          assert len(keyparts) > 1
          ret_minmax[keyparts[0]] = minmax[key]
        ret_specs[constants.ISPECS_MINMAX].append(ret_minmax)
    elif key == constants.ISPECS_STD:
      ret_specs[key] = val
    else:
      ret_policy[key] = val
  return (ret_policy, ret_specs)


def UsesIPv6Connection(host, port):
  """Returns True if the connection to a given host/port could go through IPv6.

  """
  return any(t[0] == socket.AF_INET6 for t in socket.getaddrinfo(host, port))


def TimedeltaToTotalSeconds(td):
  """Returns the total seconds in a C{datetime.timedelta} object.

  This performs the same task as the C{datetime.timedelta.total_seconds()}
  method which is present in Python 2.7 onwards.

  @type td: datetime.timedelta
  @param td: timedelta object to convert
  @rtype float
  @return: total seconds in the timedelta object

  """
  return ((td.microseconds + (td.seconds + td.days * 24.0 * 3600.0) * 10 ** 6) /
          10 ** 6)
