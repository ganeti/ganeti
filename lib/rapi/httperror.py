#!/usr/bin/python
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


"""HTTP errors.

"""


class HTTPException(Exception):
  code = None
  message = None

  def __init__(self, message=None):
    if message is not None:
      self.message = message


class HTTPBadRequest(HTTPException):
  code = 400


class HTTPNotFound(HTTPException):
  code = 404


class HTTPInternalError(HTTPException):
  code = 500


class HTTPServiceUnavailable(HTTPException):
  code = 503
