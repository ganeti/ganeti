#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Remote API version 2 baserlib.library.

"""

import re

import ganeti.opcodes

from ganeti import constants
from ganeti import luxi

from ganeti.rapi import baserlib 

from ganeti.rapi.rlib1 import I_FIELDS, N_FIELDS


class R_2_jobs(baserlib.R_Generic):
  """/2/jobs resource.

  """
  DOC_URI = "/2/jobs"

  def GET(self):
    """Returns a dictionary of jobs.

    Returns:
      A dictionary with jobs id and uri.
    
    """
    fields = ["id"]
    # Convert the list of lists to the list of ids
    result = [job_id for [job_id] in luxi.Client().QueryJobs(None, fields)]
    return baserlib.BuildUriList(result, "/2/jobs/%s", uri_fields=("id", "uri"))


class R_2_jobs_id(baserlib.R_Generic):
  """/2/jobs/[job_id] resource.

  """
  DOC_URI = "/2/jobs/[job_id]"

  def GET(self):
    """Returns a job status.

    Returns: 
      A dictionary with job parameters.

    The result includes:
      id - job ID as a number
      status - current job status as a string
      ops - involved OpCodes as a list of dictionaries for each opcodes in 
        the job
      opstatus - OpCodes status as a list
      opresult - OpCodes results as a list of lists
    
    """
    fields = ["id", "ops", "status", "opstatus", "opresult"]
    job_id = self.items[0]
    result = luxi.Client().QueryJobs([job_id,], fields)[0]
    return baserlib.MapFields(fields, result)


class R_2_nodes(baserlib.R_Generic):
  """/2/nodes resource.

  """
  DOC_URI = "/2/nodes"
 
  def GET(self):
    """Returns a list of all nodes.
    
    Returns:
      A dictionary with 'name' and 'uri' keys for each of them.

    Example: [
        {
          "id": "node1.example.com",
          "uri": "\/instances\/node1.example.com"
        },
        {
          "id": "node2.example.com",
          "uri": "\/instances\/node2.example.com"
        }]

    If the optional 'bulk' argument is provided and set to 'true' 
    value (i.e '?bulk=1'), the output contains detailed
    information about nodes as a list.

    Example: [
        {
          "pinst_cnt": 1,
          "mfree": 31280,
          "mtotal": 32763,
          "name": "www.example.com",
          "tags": [],
          "mnode": 512,
          "dtotal": 5246208,
          "sinst_cnt": 2,
          "dfree": 5171712
        },
        ...
    ]

    """
    op = ganeti.opcodes.OpQueryNodes(output_fields=["name"], names=[])
    nodeslist = baserlib.ExtractField(ganeti.cli.SubmitOpCode(op), 0)
    
    if 'bulk' in self.queryargs:
      op = ganeti.opcodes.OpQueryNodes(output_fields=N_FIELDS,
                                       names=nodeslist)
      result = ganeti.cli.SubmitOpCode(op)
      return baserlib.MapBulkFields(result, N_FIELDS)

    return baserlib.BuildUriList(nodeslist, "/nodes/%s", uri_fields=("id", "uri"))
