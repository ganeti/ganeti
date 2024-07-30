#
#

# Copyright (C) 2013 Google Inc.
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


"""Support for mocking the opcode processor"""


import re

from ganeti import constants
from ganeti import mcpu


class LogRecordingCallback(mcpu.OpExecCbBase):
  """Helper class for log output recording.

  """
  def __init__(self, processor):
    super(LogRecordingCallback, self).__init__()

    self.processor = processor

  # TODO: Cleanup calling conventions, make them explicit
  def Feedback(self, *args):
    assert len(args) < 3

    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      (log_type, log_msg) = args

    # TODO: Remove this once calling conventions are explicit.
    # Feedback can be called with anything, we interpret ELogMessageList as
    # messages that have to be individually added to the log list, but pushed
    # in a single update. Other types are only transparently passed forward.
    if log_type == constants.ELOG_MESSAGE_LIST:
      log_msg_list = [(constants.ELOG_MESSAGE, msg) for msg in log_msg]
    else:
      log_msg_list = [(log_type, log_msg)]

    self.processor.log_entries.extend(log_msg_list)

  def SubmitManyJobs(self, jobs):
    results = []
    for idx, _ in enumerate(jobs):
      results.append((True, idx))
    return results


class ProcessorMock(mcpu.Processor):
  """Mocked opcode processor for tests.

  This class actually performs much more than a mock, as it drives the
  execution of LU's. But it also provides access to the log output of the LU
  the result of the execution.

  See L{ExecOpCodeAndRecordOutput} for the main method of this class.

  """

  def __init__(self, context, wconfd):
    super(ProcessorMock, self).__init__(context, 1, True)
    self.log_entries = []
    self._lu_test_func = None
    self.wconfd = wconfd

  def ExecOpCodeAndRecordOutput(self, op):
    """Executes the given opcode and records the output for further inspection.

    @param op: the opcode to execute.
    @return: see L{mcpu.Processor.ExecOpCode}

    """
    return self.ExecOpCode(op, LogRecordingCallback(self))

  def _ExecLU(self, lu):
    # pylint: disable=W0212
    if not self._lu_test_func:
      return super(ProcessorMock, self)._ExecLU(lu)
    else:
      # required by a lot LU's, and usually passed in Exec
      lu._feedback_fn = self.Log
      return self._lu_test_func(lu)

  def _CheckLUResult(self, op, result):
    # pylint: disable=W0212
    if not self._lu_test_func:
      return super(ProcessorMock, self)._CheckLUResult(op, result)
    else:
      pass

  def RunWithLockedLU(self, op, func):
    """Takes the given opcode, creates a LU and runs func with it.

    @param op: the opcode to get the LU for.
    @param func: the function to run with the created and locked LU.
    @return: the result of func.

    """
    self._lu_test_func = func
    try:
      return self.ExecOpCodeAndRecordOutput(op)
    finally:
      self._lu_test_func = None

  def GetLogEntries(self):
    """Return the list of recorded log entries.

    @rtype: list of (string, string) tuples
    @return: the list of recorded log entries

    """
    return self.log_entries

  def GetLogMessages(self):
    """Return the list of recorded log messages.

    @rtype: list of string
    @return: the list of recorded log messages

    """
    return [msg for _, msg in self.log_entries]

  def GetLogEntriesString(self):
    """Return a string with all log entries separated by a newline.

    """
    return "\n".join("%s: %s" % (log_type, msg)
                     for log_type, msg in self.GetLogEntries())

  def GetLogMessagesString(self):
    """Return a string with all log messages separated by a newline.

    """
    return "\n".join("%s" % msg for _, msg in self.GetLogEntries())

  def assertLogContainsEntry(self, expected_type, expected_msg):
    """Asserts that the log contains the exact given entry.

    @type expected_type: string
    @param expected_type: the expected type
    @type expected_msg: string
    @param expected_msg: the expected message

    """
    for log_type, msg in self.log_entries:
      if log_type == expected_type and msg == expected_msg:
        return

    raise AssertionError(
      "Could not find '%s' (type '%s') in LU log messages. Log is:\n%s" %
      (expected_msg, expected_type, self.GetLogEntriesString()))

  def assertLogContainsMessage(self, expected_msg):
    """Asserts that the log contains the exact given message.

    @type expected_msg: string
    @param expected_msg: the expected message

    """
    for msg in self.GetLogMessages():
      if msg == expected_msg:
        return

    raise AssertionError(
      "Could not find '%s' in LU log messages. Log is:\n%s" %
      (expected_msg, self.GetLogMessagesString()))

  def assertLogContainsRegex(self, expected_regex):
    """Asserts that the log contains a message which matches the regex.

    @type expected_regex: string
    @param expected_regex: regular expression to match messages with.

    """
    for msg in self.GetLogMessages():
      if re.search(expected_regex, msg) is not None:
        return

    raise AssertionError(
      "Could not find '%s' in LU log messages. Log is:\n%s" %
      (expected_regex, self.GetLogMessagesString())
    )

  def assertLogContainsInLine(self, expected):
    """Asserts that the log contains a message which contains a string.

    @type expected: string
    @param expected: string to search in messages.

    """
    self.assertLogContainsRegex(re.escape(expected))

  def assertLogDoesNotContainRegex(self, expected_regex):
    """Asserts that the log does not contain a message which matches the regex.

    @type expected_regex: string
    @param expected_regex: regular expression to match messages with.

    """
    for msg in self.GetLogMessages():
      if re.search(expected_regex, msg) is not None:
        raise AssertionError(
          "Found '%s' in LU log messages. Log is:\n%s" %
          (expected_regex, self.GetLogMessagesString())
        )

  def assertLogIsEmpty(self):
    """Asserts that the log does not contain any message.

    """
    if len(self.GetLogMessages()) > 0:
      raise AssertionError("Log is not empty. Log is:\n%s" %
                           self.GetLogMessagesString())

  def ClearLogMessages(self):
    """Clears all recorded log messages.

    This is useful if you use L{GetLockedLU} and want to test multiple calls
    on it.

    """
    self.log_entries = []
