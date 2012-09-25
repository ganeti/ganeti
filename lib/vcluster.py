#
#

# Copyright (C) 2012 Google Inc.
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


"""Module containing utilities for virtual clusters.

Most functions manipulate file system paths and are no-ops when the environment
variables C{GANETI_ROOTDIR} and C{GANETI_HOSTNAME} are not set. See the
functions' docstrings for details.

"""

import os

from ganeti import compat


_VIRT_PATH_PREFIX = "/###-VIRTUAL-PATH-###,"
_ROOTDIR_ENVNAME = "GANETI_ROOTDIR"
_HOSTNAME_ENVNAME = "GANETI_HOSTNAME"


def _GetRootDirectory(envname):
  """Retrieves root directory from an environment variable.

  @type envname: string
  @param envname: Environment variable name
  @rtype: string
  @return: Root directory (can be empty)

  """
  path = os.getenv(envname)

  if path:
    if not os.path.isabs(path):
      raise RuntimeError("Root directory in '%s' must be absolute: %s" %
                         (envname, path))
    return os.path.normpath(path)

  return ""


def _GetHostname(envname):
  """Retrieves virtual hostname from an environment variable.

  @type envname: string
  @param envname: Environment variable name
  @rtype: string
  @return: Host name (can be empty)

  """
  return os.getenv(envname, default="")


def _CheckHostname(hostname):
  """Very basic check for hostnames.

  @type hostname: string
  @param hostname: Hostname

  """
  if os.path.basename(hostname) != hostname:
    raise RuntimeError("Hostname '%s' can not be used for a file system"
                       " path" % hostname)


def _PreparePaths(rootdir, hostname):
  """Checks if the root directory and hostname are acceptable.

  The (node-specific) root directory must have the hostname as its last
  component. The parent directory then becomes the cluster-wide root directory.
  This is necessary as some components must be able to predict the root path on
  a remote node (e.g. copying files via scp).

  @type rootdir: string
  @param rootdir: Root directory (from environment)
  @type hostname: string
  @param hostname: Hostname (from environment)
  @rtype: tuple; (string, string, string or None)
  @return: Tuple containing cluster-global root directory, node root directory
    and virtual hostname

  """
  if bool(rootdir) ^ bool(hostname):
    raise RuntimeError("Both root directory and hostname must be specified"
                       " using the environment variables %s and %s" %
                       (_ROOTDIR_ENVNAME, _HOSTNAME_ENVNAME))

  if rootdir:
    assert rootdir == os.path.normpath(rootdir)

    _CheckHostname(hostname)

    if os.path.basename(rootdir) != hostname:
      raise RuntimeError("Last component of root directory ('%s') must match"
                         " hostname ('%s')" % (rootdir, hostname))

    return (os.path.dirname(rootdir), rootdir, hostname)
  else:
    return ("", "", None)


(_VIRT_BASEDIR, _VIRT_NODEROOT, _VIRT_HOSTNAME) = \
  _PreparePaths(_GetRootDirectory(_ROOTDIR_ENVNAME),
                _GetHostname(_HOSTNAME_ENVNAME))


assert (compat.all([_VIRT_BASEDIR, _VIRT_NODEROOT, _VIRT_HOSTNAME]) or
        not compat.any([_VIRT_BASEDIR, _VIRT_NODEROOT, _VIRT_HOSTNAME]))


def GetVirtualHostname():
  """Returns the virtual hostname.

  @rtype: string or L{None}

  """
  return _VIRT_HOSTNAME


def _MakeNodeRoot(base, node_name):
  """Appends a node name to the base directory.

  """
  _CheckHostname(node_name)
  return os.path.normpath("%s/%s" % (base, node_name))


def ExchangeNodeRoot(node_name, filename,
                     _basedir=_VIRT_BASEDIR, _noderoot=_VIRT_NODEROOT):
  """Replaces the node-specific root directory in a path.

  Replaces it with the root directory for another node. Assuming
  C{/tmp/vcluster/node1} is the root directory for C{node1}, the result will be
  C{/tmp/vcluster/node3} for C{node3} (as long as a root directory is specified
  in the environment).

  """
  if _basedir:
    pure = _RemoveNodePrefix(filename, _noderoot=_noderoot)
    result = "%s/%s" % (_MakeNodeRoot(_basedir, node_name), pure)
  else:
    result = filename

  return os.path.normpath(result)


def EnvironmentForHost(hostname, _basedir=_VIRT_BASEDIR):
  """Returns the environment variables for a host.

  """
  if _basedir:
    return {
      _ROOTDIR_ENVNAME: _MakeNodeRoot(_basedir, hostname),
      _HOSTNAME_ENVNAME: hostname,
      }
  else:
    return {}


def AddNodePrefix(path, _noderoot=_VIRT_NODEROOT):
  """Adds a node-specific prefix to a path in a virtual cluster.

  Returned path includes user-specified root directory if specified in
  environment. As an example, the path C{/var/lib/ganeti} becomes
  C{/tmp/vcluster/node1/var/lib/ganeti} if C{/tmp/vcluster/node1} is the root
  directory specified in the environment.

  """
  assert os.path.isabs(path)

  if _noderoot:
    result = "%s/%s" % (_noderoot, path)
  else:
    result = path

  assert os.path.isabs(result)

  return os.path.normpath(result)


def _RemoveNodePrefix(path, _noderoot=_VIRT_NODEROOT):
  """Removes the node-specific prefix from a path.

  This is the opposite of L{AddNodePrefix} and removes a node-local prefix
  path.

  """
  assert os.path.isabs(path)

  norm_path = os.path.normpath(path)

  if _noderoot:
    # Make sure path is actually below node root
    norm_root = os.path.normpath(_noderoot)
    root_with_sep = "%s%s" % (norm_root, os.sep)
    prefix = os.path.commonprefix([root_with_sep, norm_path])

    if prefix == root_with_sep:
      result = norm_path[len(norm_root):]
    else:
      raise RuntimeError("Path '%s' is not below node root '%s'" %
                         (path, _noderoot))
  else:
    result = norm_path

  assert os.path.isabs(result)

  return result


def MakeVirtualPath(path, _noderoot=_VIRT_NODEROOT):
  """Virtualizes a path.

  A path is "virtualized" by stripping it of its node-specific directory and
  prepending a prefix (L{_VIRT_PATH_PREFIX}). Use L{LocalizeVirtualPath} to
  undo the process. Virtual paths are meant to be transported via RPC.

  """
  assert os.path.isabs(path)

  if _noderoot:
    return _VIRT_PATH_PREFIX + _RemoveNodePrefix(path, _noderoot=_noderoot)
  else:
    return path


def LocalizeVirtualPath(path, _noderoot=_VIRT_NODEROOT):
  """Localizes a virtual path.

  A "virtualized" path consists of a prefix (L{LocalizeVirtualPath}) and a
  local path. This function adds the node-specific directory to the local path.
  Virtual paths are meant to be transported via RPC.

  """
  assert os.path.isabs(path)

  if _noderoot:
    if path.startswith(_VIRT_PATH_PREFIX):
      return AddNodePrefix(path[len(_VIRT_PATH_PREFIX):], _noderoot=_noderoot)
    else:
      raise RuntimeError("Path '%s' is not a virtual path" % path)
  else:
    return path
