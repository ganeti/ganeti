#
#

# Copyright (C) 2015 Google Inc.
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


"""QA tests for the universal job hooks.

"""

import time

from ganeti import constants
from ganeti import pathutils
from qa_config import GetMasterNode
from qa_job_utils import ExecuteJobProducingCommand
from qa_utils import AssertEqual, GetCommandOutput, IsFileExists

PRE_PATH = "%s/global-pre.d" % pathutils.HOOKS_BASE_DIR
POST_PATH = "%s/global-post.d" % pathutils.HOOKS_BASE_DIR
H_DIR = "/var/log/ganeti/qa_global_hooks"


def _GetHookFilePath(job_id, phase, status=None):
  """Returns the path to the qa hooks temporary files.

  """
  h_fname = H_DIR + "/%d_OP_TEST_DELAY_%s" % (job_id, phase)
  if phase == "pre":
    return h_fname
  return h_fname + "_" + status


def TestHooksInitialize():
  """Creates global hooks on the master node

  """
  master = GetMasterNode().primary
  GetCommandOutput(master, "mkdir -p %s" % pathutils.HOOKS_BASE_DIR)
  GetCommandOutput(master, "mkdir -p %s" % PRE_PATH)
  GetCommandOutput(master, "mkdir -p %s" % POST_PATH)
  GetCommandOutput(master, "mkdir -p %s" % H_DIR)
  h_name = "/qa_test_hook"
  create_hook_common = """
FOUT=%s
echo '#!/bin/sh' > $FOUT
echo 'touch %s/$GANETI_JOB_ID"_"$GANETI_OP_CODE%s' >> $FOUT
chmod +x $FOUT
"""
  create_pre = create_hook_common % (PRE_PATH + h_name, H_DIR, '"_pre"')
  create_post = create_hook_common % (POST_PATH + h_name, H_DIR,
                                      '"_post_"$GANETI_POST_STATUS')
  GetCommandOutput(master, create_pre)
  GetCommandOutput(master, create_post)


def TestHookSucceeded():
  """Checks whether the global hooks have been executed (status succes).

  - Global pre hook should has been executed.
  - Global post hook should with status *success* should has been executed.
  - Global post hooks with failed statuses shouldn't have been executed.
  """
  master = GetMasterNode().primary
  job_id = ExecuteJobProducingCommand("gnt-debug delay --submit 1")
  time.sleep(3)
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "pre")), True,
              "Global pre hook hasn't been executed.")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_SUCCESS)), True,
              "Global post hook hasn't been executed with status *success*")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_ERROR)), False,
              "Global post hook has been executed with status *error*")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_DISAPPEARED)), False,
              "Global post hook has been executed with status *disappeared*")


def TestHookFailed():
  """Checks whether the global hooks have been executed (status error).

  - Global post hook should with status *error* should has been executed.
  - Global post hook with other statuses shouldn't have been executed.
  """
  master = GetMasterNode().primary
  job_id = ExecuteJobProducingCommand("gnt-debug delay --submit 0")
  time.sleep(1)
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_SUCCESS)), False,
              "Global post hook has been executed with status *success*")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_ERROR)), True,
              "Global post hook hasn't been executed with status *error*")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_DISAPPEARED)), False,
              "Global post hook has been executed with status *disappeared*")


def TestHookDisappeared():
  """Checks whether the global hooks have been executed (status disappeared).

  - Global pre hook should has been executed.
  - Global post hook should with status *disappeared* should has been executed.
  - Global post hook with other statuses shouldn't have been executed.
  """
  master = GetMasterNode().primary
  job_id = ExecuteJobProducingCommand("gnt-debug delay --submit 10")
  time.sleep(1)
  GetCommandOutput(master, "gnt-job cancel --kill --yes-do-it %d" % job_id)
  time.sleep(10)
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "pre")), True,
              "Global pre hook hasn't been executed.")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_SUCCESS)), False,
              "Global post hook has been executed with status *success*")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_ERROR)), False,
              "Global post hook has been executed with status *error*")
  AssertEqual(IsFileExists(master, _GetHookFilePath(job_id, "post",
                           constants.POST_HOOKS_STATUS_DISAPPEARED)), True,
              "Global post hook hasn't been executed with status *disappeared*")


def TestHooksCleanup():
  """Remove the directories created by the tests

  """
  master = GetMasterNode().primary
  GetCommandOutput(master, "rm %s/*" % PRE_PATH)
  GetCommandOutput(master, "rm %s/*" % POST_PATH)
  GetCommandOutput(master, "rm -rf %s" % H_DIR)


def RunGlobalHooksTests():
  """Runs tests for global hooks considering different job execution cases.

  """
  TestHooksInitialize()
  TestHookSucceeded()
  TestHookFailed()
  TestHookDisappeared()
  TestHooksCleanup()
