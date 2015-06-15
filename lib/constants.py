#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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
