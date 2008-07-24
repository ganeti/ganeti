#
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

"""RESTfull HTTPS Server module.

"""

from ganeti import constants
from ganeti import http
from ganeti import errors
from ganeti import rpc
from ganeti.rapi import connector
from ganeti.rapi import httperror


class RESTRequestHandler(http.HTTPRequestHandler):
  """REST Request Handler Class.

  """
  def setup(self):
    super(RESTRequestHandler, self).setup()
    self._resmap = connector.Mapper()
  
  def HandleRequest(self):
    """ Handels a request.

    """
    (HandlerClass, items, args) = self._resmap.getController(self.path)
    handler = HandlerClass(self, items, args)

    command = self.command.upper()
    try:
      fn = getattr(handler, command)
    except AttributeError, err:
      raise httperror.HTTPBadRequest()

    try:
      result = fn()

    except errors.OpPrereqError, err:
      # TODO: "Not found" is not always the correct error. Ganeti's core must
      # differentiate between different error types.
      raise httperror.HTTPNotFound(message=str(err))
    
    return result


def start(options):
  log_fd = open(constants.LOG_RAPIACCESS, 'a')
  try:
    apache_log = http.ApacheLogfile(log_fd)
    httpd = http.HTTPServer(("", options.port), RESTRequestHandler,
                            httplog=apache_log)
    try:
      httpd.serve_forever()
    finally:
      httpd.server_close()

  finally:
    log_fd.close()
