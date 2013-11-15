#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Module holding different constants."""

# pylint: disable=W0401,W0614
#
# The modules 'ganeti._constants' and 'ganeti._vcsversion' are meant
# to be re-exported but pylint complains because the imported names
# are not actually used in this module.

import re
import socket

from ganeti._constants import *
from ganeti._vcsversion import *
from ganeti import compat
from ganeti import pathutils

ALLOCATABLE_KEY = "allocatable"
FAILED_KEY = "failed"

DAEMONS_LOGFILES = \
    dict((daemon, pathutils.GetLogFilename(DAEMONS_LOGBASE[daemon]))
         for daemon in DAEMONS_LOGBASE)

DAEMONS_EXTRA_LOGFILES = \
  dict((daemon, dict((extra,
       pathutils.GetLogFilename(DAEMONS_EXTRA_LOGBASE[daemon][extra]))
       for extra in DAEMONS_EXTRA_LOGBASE[daemon]))
         for daemon in DAEMONS_EXTRA_LOGBASE)

# When the Xen toolstack used is "xl", live migration requires the source host
# to connect to the target host via ssh (xl runs this command). We need to pass
# the command xl runs some extra info so that it can use Ganeti's key
# verification and not fail. Note that this string is incomplete: it must be
# filled with the cluster name before being used.
XL_SSH_CMD = ("ssh -l %s -oGlobalKnownHostsFile=%s"
              " -oUserKnownHostsFile=/dev/null"
              " -oCheckHostIp=no -oStrictHostKeyChecking=yes"
              " -oHostKeyAlias=%%s") % (SSH_LOGIN_USER,
                                        pathutils.SSH_KNOWN_HOSTS_FILE)

IE_MAGIC_RE = re.compile(r"^[-_.a-zA-Z0-9]{5,100}$")

# External script validation mask
EXT_PLUGIN_MASK = re.compile("^[a-zA-Z0-9_-]+$")

JOB_ID_TEMPLATE = r"\d+"
JOB_FILE_RE = re.compile(r"^job-(%s)$" % JOB_ID_TEMPLATE)

# HVC_DEFAULTS contains one value 'HV_VNC_PASSWORD_FILE' which is not
# a constant because it depends on an environment variable that is
# used for VClusters.  Therefore, it cannot be automatically generated
# by Haskell at compilation time (given that this environment variable
# might be different at runtime).
HVC_DEFAULTS[HT_XEN_HVM][HV_VNC_PASSWORD_FILE] = pathutils.VNC_PASSWORD_FILE

# Do not re-export imported modules
del re, socket, pathutils, compat
