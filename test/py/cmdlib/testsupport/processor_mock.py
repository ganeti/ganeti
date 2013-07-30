#
#

# Copyright (C) 2013 Google Inc.
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


"""Support for mocking the opcode processor"""


import re

from ganeti import constants
from ganeti import mcpu


class LogRecordingCallback(mcpu.OpExecCbBase):
  """Helper class for log output recording.

  """
  def __init__(self, processor):
    self.processor = processor

  def Feedback(self, *args):
    assert len(args) < 3

    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      (log_type, log_msg) = args

    self.processor.log_entries.append((log_type, log_msg))

  def SubmitManyJobs(self, jobs):
    return mcpu.OpExecCbBase.SubmitManyJobs(self, jobs)


class ProcessorMock(mcpu.Processor):
  """Mocked opcode processor for tests.

  This class actually performs much more than a mock, as it drives the
  execution of LU's. But it also provides access to the log output of the LU
  the result of the execution.

  See L{ExecOpCodeAndRecordOutput} for the main method of this class.

  """

  def __init__(self, context):
    super(ProcessorMock, self).__init__(context, 0, True)
    self.log_entries = []

  def ExecOpCodeAndRecordOutput(self, op):
    """Executes the given opcode and records the output for further inspection.

    @param op: the opcode to execute.
    @return: see L{mcpu.Processor.ExecOpCode}

    """
    return self.ExecOpCode(op, LogRecordingCallback(self))

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

  def assertLogIsEmpty(self):
    """Asserts that the log does not contain any message.

    """
    if len(self.GetLogMessages()) > 0:
      raise AssertionError("Log is not empty. Log is:\n%s" %
                           self.GetLogMessagesString())
