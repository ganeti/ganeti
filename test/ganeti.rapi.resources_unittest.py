#!/usr/bin/python
#

# Copyright (C) 2007, 2008 Google Inc.
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


"""Script for unittesting the rapi.resources module"""


import os
import unittest

from ganeti.rapi import resources


class MapperTests(unittest.TestCase):

  def setUp(self):
    self.con = resources.CONNECTOR
    self.map = resources.Mapper(self.con)
    
  def testMapper(self):
    """Testing for Mapper."""
    
    self.failUnless(self.map.getController('/tags') == 
                    ('R_tags',
                     ['/tags'],
                     {}))

    self.failUnless(self.map.getController('/tag') == None)
    
    self.failUnless(self.map.getController('/instances/www.test.com') == 
                    ('R_instances_name',
                     ['www.test.com'],
                     {}))
    
    self.failUnless(self.map.getController(
        '/instances/www.test.com/tags?f=5&f=6&alt=html') == 
                    ('R_instances_name_tags',
                     ['www.test.com'],
                     {'alt':['html'], 'f':['5', '6']}))


class R_RootTests(unittest.TestCase):
  """Testing for R_root class."""
  
  def setUp(self):
    self.root = resources.R_root(None, None, None)
    self.root.result = []
  
  def testGet(self):
    self.root._get()
    self.failUnless(self.root.result == 
                    [{'name': 'instances', 'uri': '/instances'},
                     {'name': 'info', 'uri': '/info'},
                     {'name': 'os', 'uri': '/os'},
                     {'name': 'status', 'uri': '/status'},
                     {'name': 'tags', 'uri': '/tags'},
                     {'name': 'nodes', 'uri': '/nodes'}])
    

if __name__ == '__main__':
  unittest.main()
